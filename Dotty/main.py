#!/usr/bin/env python3
"""
main.py — Dotty with stroke-based digit transitions (two-point strokes)

Features:
- 14x14 digit strokes authored as two-tuples per stroke (list of points)
- stroke-based transitions: erase whole strokes then draw whole strokes
- simulated seconds debug mode (/tmp/dotty_show_seconds) — advances sec_sim step-by-step
- top-of-hour random invert and hour polarity toggle (/tmp/dotty_top_of_hour)
- live per-pixel speed tuning via files:
    /tmp/dotty_snake_delay
    /tmp/dotty_sec_snake_delay
- test trigger /tmp/dotty_force_minute to run minute animation now
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
# Digit stroke definitions (14x14 coordinate grid 0..13)
# Each digit: list of strokes (stroke = list of points)
# Authorable — your strokes retained.
# ---------------------------
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
# sequential_strokes defines an ordered sequence of strokes used to
# transition *into* the target digit (stroke-by-stroke).
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
# Helper: flip authored bottom-left Y -> hardware top-left Y
# ---------------------------
def flip_stroke_y(stroke, size=DIGIT_SIZE):
    """Flip stroke's Y coordinates so bottom-left origin becomes top-left."""
    return [(x, (size - 1) - y) for (x, y) in stroke]

def flip_all_strokes(strokes_map, size=DIGIT_SIZE):
    flipped = {}
    for d, s_list in strokes_map.items():
        flipped[d] = [flip_stroke_y(s, size) for s in s_list]
    return flipped

# create flipped copy (use this everywhere)
digit_strokes_flipped = flip_all_strokes(digit_strokes, DIGIT_SIZE)
sequential_strokes_flipped = flip_all_strokes(sequential_strokes, DIGIT_SIZE)

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
    return [int(now.strftime("%H")), int(now.strftime("%M")), int(now.strftime("%S"))]


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
# Stroke toolkit (bresenham raster + players)
# ---------------------------
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
    w, h = bounds
    pts = []
    seen = set()
    # rasterize each segment preserving stroke order and avoiding repeats
    for a, b in zip(stroke, stroke[1:]):
        seg = bresenham_line(a[0], a[1], b[0], b[1])
        for p in seg:
            if p not in seen and 0 <= p[0] < w and 0 <= p[1] < h:
                pts.append(p)
                seen.add(p)
    # thickness expansion (keeps approximate order)
    if thickness <= 1:
        return pts
    ordered = []
    added = set()
    r = thickness // 2
    for (cx, cy) in pts:
        for dy in range(-r, r+1):
            for dx in range(-r, r+1):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in added:
                    ordered.append((nx, ny))
                    added.add((nx, ny))
    return ordered

def play_stroke(panels_obj, stroke_pixels, color, refresh_fn=None,
                per_pixel_delay=0.01, instant_threshold=INSTANT_THRESHOLD_DEFAULT):
    if not stroke_pixels:
        return
    if len(stroke_pixels) <= instant_threshold:
        for (x, y) in stroke_pixels:
            panels_obj.draw(x, y, color)
        if refresh_fn:
            refresh_fn()
        return
    for (x, y) in stroke_pixels:
        panels_obj.draw(x, y, color)
        if refresh_fn:
            refresh_fn()
        time.sleep(per_pixel_delay)

def offset_strokes(strokes, dx=0, dy=0):
    return [[(x + dx, y + dy) for (x, y) in s] for s in strokes]

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

    if erase_first and old_strokes:
        ordered_old = list(reversed(old_strokes))
        ordered_old.sort(key=_stroke_key)
        for stroke in ordered_old:
            pixels = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=bounds)
            play_stroke(panels_obj, pixels, bg, refresh_fn,
                        per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

    if new_strokes:
        ordered_new = list(new_strokes)
        ordered_new.sort(key=_stroke_key)
        for stroke in ordered_new:
            pixels = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=bounds)
            play_stroke(panels_obj, pixels, fg, refresh_fn,
                        per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

# ---------------------------
# Paint canonical digit instantly using strokes (replaces matrix.returnDigit)
# ---------------------------
def paint_digit_instant(panels_obj, strokes, dx=0, dy=0, inverted=False,
                        thickness=STROKE_THICKNESS_DEFAULT):
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    # clear digit box area first
    for yy in range(DIGIT_SIZE):
        for xx in range(DIGIT_SIZE):
            panels_obj.draw(dx + xx, dy + yy, bg)

    # draw strokes (strokes should be pre-flipped for top-left origin)
    for stroke in strokes:
        pxs = stroke_to_ordered_pixels(stroke, thickness=thickness, bounds=(WIDTH, HEIGHT))
        for (x, y) in pxs:
            panels_obj.draw(x, y, fg)

    refresh()

# ---------------------------
# Sequential transition (uses sequential_strokes_flipped)
# ---------------------------
def sequential_transition(panels_obj, from_digit, to_digit, dx, dy,
                          refresh_fn,
                          per_pixel_delay=0.01,
                          thickness=1,
                          instant_threshold=3,
                          bounds=(WIDTH, HEIGHT),
                          inverted=False):
    """
    Sequential stroke transition from `from_digit` -> `to_digit`, placed at offset (dx,dy).
    Uses sequential_strokes_flipped to decide the order.
    """
    if from_digit == to_digit:
        return

    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    seq = sequential_strokes_flipped.get(to_digit, digit_strokes_flipped.get(to_digit, []))

    def _offset(stroke, ox, oy):
        return [(x + ox, y + oy) for (x, y) in stroke]

    for stroke in seq:
        off_stroke = _offset(stroke, dx, dy)
        pixels = stroke_to_ordered_pixels(off_stroke, thickness=thickness, bounds=bounds)

        # ERASE (background)
        play_stroke(panels_obj, pixels, bg, refresh_fn,
                    per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

        # DRAW (foreground)
        play_stroke(panels_obj, pixels, fg, refresh_fn,
                    per_pixel_delay=per_pixel_delay, instant_threshold=instant_threshold)

    # Final snap to canonical digit to avoid small rasterization differences
    paint_digit_instant(panels_obj, [s for s in digit_strokes_flipped[to_digit]], dx=dx, dy=dy, inverted=inverted)

# ---------------------------
# Replace matrix-based draw functions with stroke-based canonical draws
# ---------------------------
def draw_hours_only(h, inverted):
    d1 = h // 10
    d2 = h % 10
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=14, dy=0, inverted=inverted)

def draw_hours_and_bottom(h, bottom_val, inverted):
    # top row (hours)
    d1 = h // 10
    d2 = h % 10
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=14, dy=0, inverted=inverted)
    # bottom (minutes or seconds)
    b1 = bottom_val // 10
    b2 = bottom_val % 10
    paint_digit_instant(panels, digit_strokes_flipped[b1], dx=0, dy=14, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[b2], dx=14, dy=14, inverted=inverted)

# ---------------------------
# Random invert animation
# ---------------------------
def random_invert_animation(panels_obj, refresh_fn,
                            delay=0.01, width=WIDTH, height=HEIGHT):
    current = capture_screen(panels_obj, width, height)
    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)
    for (x, y) in coords:
        panels_obj.draw(x, y, int(target[y, x]))
        if refresh_fn:
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
                sequential_transition(panels, old_tens, new_tens, dx=0, dy=14,
                                      refresh_fn=refresh,
                                      per_pixel_delay=second_delay,
                                      thickness=thickness,
                                      instant_threshold=instant_threshold,
                                      bounds=(WIDTH, HEIGHT),
                                      inverted=DISPLAY_INVERTED)

            # ones (bottom-right)
            if new_ones != old_ones:
                sequential_transition(panels, old_ones, new_ones, dx=14, dy=14,
                                      refresh_fn=refresh,
                                      per_pixel_delay=second_delay,
                                      thickness=thickness,
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
            # do a quick non-changing transition to exercise animation
            sequential_transition(panels, tens, tens, dx=0, dy=14,
                                  refresh_fn=refresh,
                                  per_pixel_delay=minute_delay,
                                  thickness=thickness,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)
            sequential_transition(panels, ones, ones, dx=14, dy=14,
                                  refresh_fn=refresh,
                                  per_pixel_delay=minute_delay,
                                  thickness=thickness,
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

            # bottom-left (tens)
            sequential_transition(panels, old_tens, new_tens, dx=0, dy=14,
                                  refresh_fn=refresh,
                                  per_pixel_delay=minute_delay,
                                  thickness=thickness,
                                  instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT),
                                  inverted=DISPLAY_INVERTED)

            # bottom-right (ones)
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
