#!/usr/bin/env python3
"""
main.py — Dotty with stroke-based digit transitions (two-point strokes)

Features:
- 14x14 digit strokes authored as two-tuples per stroke (list of points)
- stroke-based transitions: erase whole old strokes then draw whole new strokes
- simulated seconds debug mode (/tmp/dotty_show_seconds) — advances sec_sim step-by-step
- top-of-hour random invert and hour polarity toggle (/tmp/dotty_top_of_hour)
- live per-pixel speed tuning via files:
    /tmp/dotty_snake_delay
    /tmp/dotty_sec_snake_delay
- test trigger /tmp/dotty_force_minute to run minute animation now
- strokes included for digits 0..9 (authorable)
"""

import os
import time
import random
from datetime import datetime

import numpy as np

import serial_port
import matrix

# ---------------------------
# Config / files / constants
# ---------------------------
TRIGGER_INVERT_FILE = "/tmp/dotty_top_of_hour"
SHOW_SECONDS_FILE = "/tmp/dotty_show_seconds"
FORCE_MINUTE_FILE = "/tmp/dotty_force_minute"

SNAKE_DELAY_FILE = "/tmp/dotty_snake_delay"
SEC_SNAKE_DELAY_FILE = "/tmp/dotty_sec_snake_delay"

WIDTH = 28
HEIGHT = 28
DIGIT_SIZE = 14

SNAKE_DELAY_DEFAULT = 0.06
SEC_SNAKE_DELAY_DEFAULT = 0.02

# if a stroke has <= this many pixels, draw it instantly (avoid orphan flicker)
INSTANT_THRESHOLD_DEFAULT = 3

# stroke rasterization thickness (1 works well on 14x14)
STROKE_THICKNESS_DEFAULT = 1

# ---------------------------
# Hardware
# ---------------------------
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# display polarity toggled at top-of-hour
DISPLAY_INVERTED = False

# ---------------------------
# Utilities
# ---------------------------
def refresh(flaggs=True):
    serial_port.refresh(panels, rs232, flaggs)


def get_time():
    now = datetime.now()
    return [
        int(now.strftime("%H")),
        int(now.strftime("%M")),
        int(now.strftime("%S")),
    ]


def capture_screen(panels_obj, width=WIDTH, height=HEIGHT):
    buf = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            buf[y, x] = panels_obj.get(x, y)
    return buf


def draw_buffer(panels_obj, buf, refresh_fn=None):
    h, w = buf.shape
    for y in range(h):
        for x in range(w):
            panels_obj.draw(x, y, int(buf[y, x]))
    if refresh_fn:
        refresh_fn()


def read_delay(path, fallback):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                val = f.read().strip()
            return float(val)
    except Exception:
        pass
    return fallback

# ---------------------------
# Strokes helper (embedded)
# ---------------------------
# Bresenham integer line
def bresenham_line(x0, y0, x1, y1):
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    out = []
    while True:
        out.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return out

def stroke_to_ordered_pixels(stroke, thickness=STROKE_THICKNESS_DEFAULT, bounds=(WIDTH, HEIGHT)):
    """
    Convert stroke (polyline of points) to ordered pixel list.
    stroke: list of (x,y) points (2-tuples minimum)
    thickness: integer
    bounds: (width, height)
    """
    w, h = bounds
    pts = []
    seen = set()
    # walk segments
    for a, b in zip(stroke, stroke[1:]):
        seg = bresenham_line(a[0], a[1], b[0], b[1])
        for p in seg:
            if p not in seen and 0 <= p[0] < w and 0 <= p[1] < h:
                pts.append(p)
                seen.add(p)
    # thickness expansion while roughly preserving order
    if thickness <= 1:
        return pts
    ordered = []
    added = set()
    r = thickness // 2
    for (cx, cy) in pts:
        for dy in range(-r, r+1):
            for dx in range(-r, r+1):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h:
                    if (nx, ny) not in added:
                        ordered.append((nx, ny))
                        added.add((nx, ny))
    return ordered

def play_stroke(panels_obj, stroke_pixels, color, refresh_fn,
                per_pixel_delay=0.01, instant_threshold=INSTANT_THRESHOLD_DEFAULT):
    if not stroke_pixels:
        return
    if len(stroke_pixels) <= instant_threshold:
        for (x,y) in stroke_pixels:
            panels_obj.draw(x, y, color)
        refresh_fn()
        return
    for (x,y) in stroke_pixels:
        panels_obj.draw(x, y, color)
        refresh_fn()
        time.sleep(per_pixel_delay)

def offset_strokes(strokes, dx=0, dy=0):
    return [[(x+dx, y+dy) for (x,y) in s] for s in strokes]

def transition_by_strokes(panels_obj, old_strokes, new_strokes,
                          refresh_fn,
                          thickness=STROKE_THICKNESS_DEFAULT,
                          per_pixel_delay=0.01,
                          instant_threshold=INSTANT_THRESHOLD_DEFAULT,
                          bounds=(WIDTH, HEIGHT),
                          inverted=False,
                          erase_first=True):
    """
    Erase old_strokes (reverse order), then draw new_strokes. Each stroke is a list of points.
    """
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    def _stroke_key(s):
        return -len(stroke_to_ordered_pixels(s, thickness=thickness, bounds=bounds))

    if erase_first:
        ordered_old = list(reversed(old_strokes or []))
        ordered_old.sort(key=_stroke_key)
        for stroke in ordered_old:
            pixels = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=bounds)
            play_stroke(panels_obj, pixels, bg, refresh_fn,
                        per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

    ordered_new = list(new_strokes or [])
    ordered_new.sort(key=_stroke_key)
    for stroke in ordered_new:
        pixels = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=bounds)
        play_stroke(panels_obj, pixels, fg, refresh_fn,
                    per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

def sequential_transition(panels_obj, from_digit, to_digit, dx, dy,
                          refresh_fn,
                          per_pixel_delay=0.01,
                          thickness=1,
                          instant_threshold=3,
                          bounds=(WIDTH, HEIGHT),
                          inverted=False):
    """
    Sequential stroke transition from `from_digit` -> `to_digit`, placed at offset (dx,dy).
    Uses your `sequential_strokes` mapping for the target digit to drive stroke order.
    - panels_obj: your matrix instance
    - from_digit, to_digit: ints 0..9
    - dx,dy: pixel offsets to place strokes (e.g., 0,14 or 14,14)
    - refresh_fn: function to call to push changes to hardware (usually refresh)
    - per_pixel_delay: delay between each pixel when animating strokes
    - thickness: stroke rasterization thickness
    - instant_threshold: strokes with <= this many pixels are drawn instantly
    - bounds: (width,height) for rasterization clamping
    - inverted: whether display polarity is inverted (swap bg/fg)
    """
    # no-op if nothing to change
    if from_digit == to_digit:
        return

    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    # sequence for the target digit (fallback to digit_strokes if not provided)
    seq = sequential_strokes.get(to_digit, digit_strokes.get(to_digit, []))

    # Helper to offset a single stroke by dx,dy
    def _offset(stroke, ox, oy):
        return [(x + ox, y + oy) for (x, y) in stroke]

    # Optional: erase any pixels that belong to the from_digit but are not covered by
    # the first few strokes — this is cautious but often unnecessary because the seq
    # typically includes removal strokes. Uncomment if you see leftover pixels.
    # old_mask = capture_screen(panels_obj, bounds[0], bounds[1])  # not used by default

    # Run the sequence: erase-then-draw for each stroke in order
    for stroke in seq:
        off_stroke = _offset(stroke, dx, dy)
        pixels = stroke_to_ordered_pixels(off_stroke, thickness=thickness, bounds=bounds)

        # ERASE this stroke area (write background along stroke)
        play_stroke(panels_obj, pixels, bg, refresh_fn,
                    per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

        # DRAW this stroke area (write foreground along stroke)
        play_stroke(panels_obj, pixels, fg, refresh_fn,
                    per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

    # Final pass: ensure we exactly match the canonical new digit in that box.
    # (This avoids any tiny rasterization differences.)
    # draw canonical new digit pixels in case any incidental pixels remain.
    # Build the new digit frame and blit it into place:
    # Clear the digit box area first to bg then draw canonical glyph pixels.
    # NOTE: this final "snap" is optional 
    
    # clear digit box
    for y in range(14):
        for x in range(14):
            panels_obj.draw(dx + x, dy + y, bg)
    '''# draw canonical new digit (using matrix.returnDigit)
    panels_obj.frame(matrix.returnDigit(to_digit), dx, dy)
    if inverted:
        # invert that box
        for y in range(14):
            for x in range(14):
                panels_obj.draw(dx + x, dy + y, 1 - panels_obj.get(dx + x, dy + y))
    refresh_fn()'''

# ---------------------------
# Coordinate flip helpers
# ---------------------------
def flip_stroke_y(stroke, size=DIGIT_SIZE):
    """
    Flip stroke's Y coordinates so authored bottom-left (y up) becomes
    top-left origin (y down) used by display code.
    size: dimension of digit (14)
    """
    # new_y = (size - 1) - old_y
    return [(x, (size - 1) - y) for (x, y) in stroke]

def flip_all_strokes(strokes_map, size=DIGIT_SIZE):
    """Return a new dict with every stroke flipped in Y."""
    flipped = {}
    for d, s_list in strokes_map.items():
        flipped[d] = [flip_stroke_y(s, size) for s in s_list]
    return flipped

# create a flipped copy you can use everywhere
digit_strokes_flipped = flip_all_strokes(digit_strokes, DIGIT_SIZE)

# ---------------------------
# Instant painter using strokes (replaces matrix.returnDigit usage)
# ---------------------------
def paint_digit_instant(panels_obj, strokes, dx=0, dy=0, inverted=False,
                        thickness=STROKE_THICKNESS_DEFAULT):
    """
    Paint the canonical digit defined by `strokes` into panels at offset (dx,dy).
    This writes all stroke pixels instantly (no per-pixel animation) for canonical display.
    honors `inverted` by flipping color after drawing.
    """
    # 1) clear the digit box to background (so leftover pixels vanish)
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    for yy in range(DIGIT_SIZE):
        for xx in range(DIGIT_SIZE):
            panels_obj.draw(dx + xx, dy + yy, bg)

    # 2) draw strokes (rasterize with thickness) — draw foreground color directly
    for stroke in strokes:
        pxs = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=(WIDTH, HEIGHT))
        # stroke pixels are already offset with dx/dy? ensure we offset here
        for (x, y) in pxs:
            panels_obj.draw(x, y, fg)

    # 3) if inverted true, we already used fg/bg swapped above; nothing else to do
    refresh()

# ---------------------------
# Replace matrix-based draw functions with stroke-based canonical draws
# ---------------------------
def draw_hours_only(h, inverted):
    d1 = h // 10
    d2 = h % 10
    # top-left (hours tens)
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[d1]], dx=0, dy=0, inverted=inverted)
    # top-right (hours ones)
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[d2]], dx=14, dy=0, inverted=inverted)

def draw_hours_and_bottom(h, bottom_val, inverted):
    # paint hours (top row)
    d1 = h // 10
    d2 = h % 10
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[d1]], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[d2]], dx=14, dy=0, inverted=inverted)

    # paint bottom (minutes or seconds)
    b1 = bottom_val // 10
    b2 = bottom_val % 10
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[b1]], dx=0, dy=14, inverted=inverted)
    paint_digit_instant(panels, [s for s in digit_strokes_flipped[b2]], dx=14, dy=14, inverted=inverted)


# ---------------------------
# Digit stroke definitions (14x14 coordinate grid 0..13)
# Authorable. Tweak endpoints to taste.
# Each digit: list of strokes (stroke = list of points)
# ---------------------------
# digit_strokes (derived from your 14x14 bitmaps)
digit_strokes = {
    0: [
        [(2,11),(11,11)],  
        [(11,11),(11,2)], 
        [(11,2),(2,2)],  
        [(2,2),(2,11)],   
    ],
    1: [
        [(6,11),(7,11)],  
        [(7,11),(7,2)],  
    ],
    2: [
        [(2,11),(11,11)],  
        [(11,11),(11,7)], 
        [(11,7),(2,7)],  
        [(2,2),(11,2)],  
    ],
    3: [
        [(2,11),(11,11)],   
        [(11,11),(11,2)],  
        [(11,2),(2,2)], 
        [(11,7),(4,7)],   
    ],
    4: [
        [(2,11),(2,7)],    
        [(2,7),(11,7)], 
        [(11,11),(11,2)],  
    ],
    5: [
        [(11,11),(2,11)],  
        [(2,11),(2,7)],   
        [(2,7),(11,7)],    
        [(11,7),(11,2)], 
        [(11,2),(2,2)],  
    ],
    6: [
        [(11,11),(2,11)],    
        [(2,11),(2,2)],   
        [(2,2),(11,2)],  
        [(11,2),(11,7)], 
        [(11,7),(2,7)],  
    ],
    7: [
        [(2,11),(11,11)],   
        [(11,2),(11,2)],  
    ],
    8: [
        [(2,11),(11,11)],   
        [(11,11),(11,2)],  
        [(11,2),(2,2)],  
        [(2,2),(2,11)],   
        [(2,7),(11,7)],  
    ],
    9: [
        [(2,11),(11,11)],    
        [(11,11),(11,2)],  
        [(2,11),(2,7)],  
        [(2,7),(11,7)],     
    ],
}

# ---------------------------
# sequential_strokes defines what strokes are needed to
# transisition between numbers smoothely as long as it is
# done sequentially
# ---------------------------
sequential_strokes = {
    1: [
        [(2,11),(5,11)],  
        [(8,11),(11,11)],  
        [(11,11),(11,2)],   
        [(11,2),(2,2)],  
        [(2,2),(2,11)],  
    ],
    2: [
        [(6,11),(7,11)],   
        [(7,11),(7,2)],   
        [(2,11),(11,11)], 
        [(11,11),(11,7)],  
        [(11,7),(2,7)],    
        [(2,2),(11,2)],
    ],
    3: [
        [(2,2),(2,7)],  
        [(2,7),(4,7)],  
        [(11,7),(11,11)],   
    ],
    4: [
        [(11,11),(2,11)],    
        [(2,11),(2,7)],  
        [(2,7),(4,7)],  
        [(11,2),(2,2)],    
    ],
    5: [
        [(2,2),(11,2)],    
        [(11,7),(11,11)],  
        [(11,11),(2,11)],   
    ],
    6: [
        [(2,7),(2,2)],    
    ],
    7: [
        [(2,11),(2,2)],   
        [(2,2),(11,2)],   
        [(11,7),(11,11)],  
        [(11,7),(2,7)], 
    ],
    8: [
        [(2,11),(2,2)],    
        [(2,2),(11,2)], 
        [(2,7),(11,7)],
    ],
    9: [
        [(2,7),(2,2)],    
        [(2,2),(11,2)],  
    ],
    0: [
        [(11,7),(2,7)],   
        [(2,7),(2,2)], 
        [(2,2),(11,2)],   
    ],
}


# ---------------------------
# Drawing helpers that reuse matrix API
# ---------------------------
def draw_hours_only(h, inverted):
    d1 = h // 10
    d2 = h % 10
    panels.frame(matrix.returnDigit(d1), 0, 0)
    panels.frame(matrix.returnDigit(d2), 14, 0)
    if inverted:
        for y in range(14):
            for x in range(28):
                panels.draw(x, y, 1 - panels.get(x, y))
    refresh()

def draw_hours_and_bottom(h, bottom_val, inverted):
    panels.clear()
    # hours
    d1 = h // 10
    d2 = h % 10
    panels.frame(matrix.returnDigit(d1), 0, 0)
    panels.frame(matrix.returnDigit(d2), 14, 0)
    # bottom (minutes or seconds)
    b1 = bottom_val // 10
    b2 = bottom_val % 10
    panels.frame(matrix.returnDigit(b1), 0, 14)
    panels.frame(matrix.returnDigit(b2), 14, 14)
    if inverted:
        buf = capture_screen(panels)
        draw_buffer(panels, 1 - buf)
    else:
        refresh()

# ---------------------------
# Random invert animation (unchanged)
# ---------------------------
def random_invert_animation(panels_obj, refresh_fn,
                            delay=0.01, width=WIDTH, height=HEIGHT):
    current = capture_screen(panels_obj, width, height)
    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)
    for (x, y) in coords:
        panels_obj.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)

# ---------------------------
# Main loop
# ---------------------------
def main():
    global DISPLAY_INVERTED

    last_min = -1
    last_hour = -1
    last_sec = -1
    prev_show_seconds = False

    # simulated seconds counter
    sec_sim = 0

    # initial draw
    h, m, s = get_time()
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)

    while True:
        # top row (hours) follows real wall-clock
        h, m, _ = get_time()
        show_seconds = os.path.exists(SHOW_SECONDS_FILE)

        # live delays
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)
        instant_threshold = INSTANT_THRESHOLD_DEFAULT
        thickness = STROKE_THICKNESS_DEFAULT

        # ----------------------------
        # SECONDS DEBUG MODE: simulated seconds stepping
        # ----------------------------
        if show_seconds:
            if not prev_show_seconds:
                sec_sim = 0
                draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            old_s = sec_sim
            sec_sim = (sec_sim + 1) % 60
            new_s = sec_sim

            old_tens = old_s // 10
            old_ones = old_s % 10
            new_tens = new_s // 10
            new_ones = new_s % 10

            # tens (bottom-left)
            if new_tens != old_tens:
                old_strokes = offset_strokes(digit_strokes_flipped[old_tens], 0, 14)
                new_strokes = offset_strokes(digit_strokes_flipped[new_tens], 0, 14)
                transition_by_strokes(panels, old_strokes, new_strokes,
                                      refresh_fn=refresh,
                                      thickness=thickness,
                                      per_pixel_delay=second_delay,
                                      instant_threshold=instant_threshold,
                                      bounds=(WIDTH, HEIGHT),
                                      inverted=DISPLAY_INVERTED)

            # ones (bottom-right)
            if new_ones != old_ones:
                old_strokes = offset_strokes(digit_strokes_flipped[old_ones], 14, 14)
                new_strokes = offset_strokes(digit_strokes_flipped[new_ones], 14, 14)
                transition_by_strokes(panels, old_strokes, new_strokes,
                                      refresh_fn=refresh,
                                      thickness=thickness,
                                      per_pixel_delay=second_delay,
                                      instant_threshold=instant_threshold,
                                      bounds=(WIDTH, HEIGHT),
                                      inverted=DISPLAY_INVERTED)

            last_sec = sec_sim
            
            # allow invert trigger while in seconds mode
            if os.path.exists(TRIGGER_INVERT_FILE):
                random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                os.remove(TRIGGER_INVERT_FILE)

            time.sleep(0.05)
            continue

        # leaving seconds mode: restore minutes display
        if prev_show_seconds:
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            prev_show_seconds = False

        # ----------------------------
        # FORCE-MINUTE test
        # ----------------------------
        if os.path.exists(FORCE_MINUTE_FILE):
            tens = m // 10
            ones = m % 10
            transition_by_strokes(panels,
                                  offset_strokes(digit_strokes_flipped[tens], 0, 14),
                                  offset_strokes(digit_strokes_flipped[tens], 0, 14),
                                  refresh_fn=refresh,
                                  thickness=thickness,
                                  per_pixel_delay=minute_delay,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)
            transition_by_strokes(panels,
                                  offset_strokes(digit_strokes_flipped[ones], 14, 14),
                                  offset_strokes(digit_strokes_flipped[ones], 14, 14),
                                  refresh_fn=refresh,
                                  thickness=thickness,
                                  per_pixel_delay=minute_delay,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)
            os.remove(FORCE_MINUTE_FILE)

        # ----------------------------
        # NORMAL minute mode
        # ----------------------------
        if m != last_min:
            old_m = last_min if last_min >= 0 else m
            old_tens = old_m // 10
            old_ones = old_m % 10
            new_tens = m // 10
            new_ones = m % 10

            # top-of-hour: random invert and flip polarity
            if m == 0:
                random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED

            # bottom-left (tens) example:
            sequential_transition(panels, old_tens, new_tens, dx=0, dy=14,
                                  refresh_fn=refresh,
                                  per_pixel_delay=minute_delay,
                                  thickness=thickness,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)

            # bottom-right (ones) example:
            sequential_transition(panels, old_ones, new_ones, dx=14, dy=14,
                                  refresh_fn=refresh,
                                  per_pixel_delay=minute_delay,
                                  thickness=thickness,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)


            last_min = m

            # if hour changed, redraw top half immediately
            if h != last_hour:
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

        # ----------------------------
        # SSH invert trigger (normal mode)
        # ----------------------------
        if os.path.exists(TRIGGER_INVERT_FILE):
            random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            os.remove(TRIGGER_INVERT_FILE)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
