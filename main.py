#!/usr/bin/env python3

import os
import time
import random
from datetime import datetime
from typing import List, Tuple, Iterable

import numpy as np

import serial_port
import matrix

import threading
import queue
import paho.mqtt.client as mqtt

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

INSTANT_THRESHOLD_DEFAULT = 0
STROKE_THICKNESS_DEFAULT = 1


# ---------------------------
# MQTT control (Home Assistant)
# ---------------------------
# These can be configured via environment variables:
MQTT_BROKER = os.environ.get("DOTTY_MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("DOTTY_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("DOTTY_MQTT_USER", "")
MQTT_PASS = os.environ.get("DOTTY_MQTT_PASS", "")
MQTT_TOPIC = os.environ.get("DOTTY_MQTT_TOPIC", "dotty/command")  # listen here

# Thread-safe command queue used by main loop
command_queue = queue.Queue()

def mqtt_on_connect(client, userdata, flags, rc):
    # rc==0 is success
    if rc == 0:
        print("MQTT connected, subscribing to", MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC)
    else:
        print("MQTT connect failed rc=", rc)

def mqtt_on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode().strip().lower()
    except Exception:
        return
    # Accept either single words or JSON in the future; keep simple now
    if payload in ("blank", "refresh"):
        print("MQTT: received command:", payload)
        command_queue.put(payload)
    else:
        print("MQTT: unknown payload:", payload)

# ---------------------------
# Digit stroke definitions (14x14 coordinate grid 0..13)
# ... (kept identical to original strokes you provided)
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
        [(2,7),(2,2)],
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
        [(11,11),(11,2)],
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

sequential_strokes = {
    1: [
        [(2,11),(11,11)],
        [(11,10),(11,2)],
        [(10,2),(2,2)],
        [(2,3),(2,10)],
        [(6,11),(7,11)],
        [(7,10),(7,2)],
    ],
    2: [
        [(7,10),(7,2)],
        [(2,11),(5,11)],
        [(8,11),(11,11)],
        [(11,10),(11,7)],
        [(10,7),(2,7)],
        [(2,6),(2,2)],
        [(3,2),(11,2)],
    ],
    3: [
        [(2,3),(2,7)],
        [(3,7),(3,7)],
        [(11,3),(11,6)],
    ],
    4: [
        [(10,11),(2,11)],
        [(2,11),(2,7)],
        [(3,7),(3,7)],
        [(10,2),(2,2)],
    ],
    5: [
        [(2,2),(10,2)],
        [(11,8),(11,10)],
        [(10,11),(3,11)],
    ],
    6: [
        [(2,6),(2,3)],
    ],
    7: [
        [(2,10),(2,2)],
        [(3,2),(11,2)],
        [(11,3),(11,7)],
        [(10,7),(3,7)],
        [(11,10),(11,2)],
    ],
    8: [
        [(2,10),(2,2)],
        [(3,2),(10,2)],
        [(10,7),(3,7)],
    ],
    9: [
        [(2,6),(2,2)],
        [(3,2),(10,2)],
    ],
    0: [
        [(10,7),(3,7)],
        [(2,6),(2,2)],
        [(3,2),(10,2)],
    ],
}

# ---------------------------
# Utilities
# ---------------------------
def flip_stroke_y(stroke: Iterable[Tuple[int,int]], size: int = DIGIT_SIZE):
    """Flip authored bottom-left Y -> top-left hardware Y"""
    return [(x, (size - 1) - y) for (x, y) in stroke]

def flip_all(strokes_map):
    return {d: [flip_stroke_y(s) for s in s_list] for d, s_list in strokes_map.items()}

digit_strokes_flipped = flip_all(digit_strokes)
sequential_strokes_flipped = flip_all(sequential_strokes)

for d in range(10):
    if d not in sequential_strokes_flipped:
        print(f"Warning: no sequential strokes for {d}")

panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()
DISPLAY_INVERTED = False

def refresh(flaggs=True):
    serial_port.refresh(panels, rs232, flaggs)

def get_time():
    now = datetime.now()
    return now.hour, now.minute, now.second

def capture_screen(pan, width=WIDTH, height=HEIGHT):
    buf = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            buf[y, x] = int(pan.get(x, y))
    return buf

def draw_buffer(pan, buf, refresh_fn=None):
    h, w = buf.shape
    for y in range(h):
        for x in range(w):
            pan.draw(x, y, int(buf[y, x]))
    if refresh_fn:
        refresh_fn()

def read_delay(path, fallback):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return float(f.read().strip())
    except Exception:
        pass
    return fallback

# ---------------------------
# Bresenham + raster helpers
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

def stroke_to_ordered_pixels(stroke: List[Tuple[int,int]],
                             thickness:int = STROKE_THICKNESS_DEFAULT,
                             bounds:Tuple[int,int] = (WIDTH, HEIGHT)):
    """Rasterize a stroke (series of points) -> ordered pixel list.
    `stroke` coordinates are expected to be in the same coordinate space
    as the target drawing (i.e., already offset if needed)."""
    w, h = bounds
    pts = []
    seen = set()
    # iterate segment-by-segment preserving order
    for a, b in zip(stroke, stroke[1:]):
        for p in bresenham_line(a[0], a[1], b[0], b[1]):
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

def play_pixels(pan, pixels, color, refresh_fn=None, per_pixel_delay=0.01, instant_threshold=1):
    pixels = list(pixels)
    print(f"Playing {len(pixels)} pixels, color={color}")
    
    """Draw list of pixels to `pan`. If short, draw instantly."""
    pixels = list(pixels)
    if not pixels:
        return
    if len(pixels) <= instant_threshold:
        for x, y in pixels:
            pan.draw(x, y, color)
        if refresh_fn:
            refresh_fn()
        return
    for x, y in pixels:
        pan.draw(x, y, color)
        if refresh_fn:
            refresh_fn()
        time.sleep(per_pixel_delay)

def play_pixels_invert(pan, pixels: Iterable[Tuple[int,int]], refresh_fn=None, per_pixel_delay:float=0.01):
    """Draw pixels by inverting current state."""
    for x, y in pixels:
        current = pan.get(x, y)
        pan.draw(x, y, 1 - current)  # invert
        if refresh_fn:
            refresh_fn()
        time.sleep(per_pixel_delay)

def offset_stroke(stroke: Iterable[Tuple[int,int]], dx:int=0, dy:int=0):
    return [(x + dx, y + dy) for (x, y) in stroke]

# ---------------------------
# Canonical paint utility
# ---------------------------
def paint_digit_instant(pan, strokes: List[List[Tuple[int,int]]], dx=0, dy=0, inverted=False,
                        thickness=STROKE_THICKNESS_DEFAULT, refresh_fn=None):
    """Clear digit box and draw canonical strokes instantly."""
    bg = 1 if not inverted else 0   # keep your panel polarity mapping here
    fg = 0 if not inverted else 1

    # clear the digit box area
    for yy in range(DIGIT_SIZE):
        for xx in range(DIGIT_SIZE):
            pan.draw(dx + xx, dy + yy, bg)

    # draw each stroke (rasterize in display coords)
    for s in strokes:
        off = offset_stroke(s, dx, dy)
        pxs = stroke_to_ordered_pixels(off, thickness=thickness, bounds=(WIDTH, HEIGHT))
        for tx, ty in pxs:
            if 0 <= tx < WIDTH and 0 <= ty < HEIGHT:
                pan.draw(tx, ty, fg)

    # caller decides whether/when to refresh
    if refresh_fn:
        refresh_fn()

# ---------------------------
# Proper sequential transition:
# ---------------------------
def sequential_transition(pan, from_digit:int, to_digit:int, dx:int, dy:int,
                          refresh_fn=refresh,
                          per_pixel_delay:float=0.01,
                          thickness:int=STROKE_THICKNESS_DEFAULT,
                          instant_threshold:int=INSTANT_THRESHOLD_DEFAULT,
                          bounds=(WIDTH, HEIGHT),
                          inverted:bool=False,
                          animate_if_same:bool=False):
    """
    Draw the sequential stroke sequence for `to_digit` placed at (dx,dy).
    - Does NOT attempt to erase old strokes first; sequential_strokes are assumed
      to lay down the correct pixels to morph the display into the target digit.
    - If from==to and animate_if_same==False, this is a no-op; if animate_if_same==True,
      the sequence will be replayed.
    """
    # skip if same digit and not requested to animate
    if from_digit == to_digit and not animate_if_same:
        return

    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    # Use sequential order for the target; fallback to canonical strokes if missing
    seq = sequential_strokes_flipped.get(to_digit, digit_strokes_flipped.get(to_digit, []))

    # draw new strokes in sequence (these should lay down pixels that form `to_digit`)
    for stroke in seq:
        off = offset_stroke(stroke, dx, dy)
        pixels = stroke_to_ordered_pixels(off, thickness=thickness, bounds=bounds)
        play_pixels_invert(pan, pixels, refresh_fn=refresh_fn, per_pixel_delay=per_pixel_delay)
    
    # final snap to canonical digit for pixel-perfect result (no-op if already exact)
    time.sleep(per_pixel_delay)
    paint_digit_instant(pan, digit_strokes_flipped[to_digit], dx=dx, dy=dy, inverted=inverted, thickness=thickness)

# ---------------------------
# Display helpers
# ---------------------------
def draw_hours_only(h:int, inverted:bool):
    d1, d2 = divmod(h, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted)

def draw_hours_and_bottom(h:int, bottom_val:int, inverted:bool):
    d1, d2 = divmod(h, 10)
    b1, b2 = divmod(bottom_val, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[b1], dx=0, dy=DIGIT_SIZE, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[b2], dx=DIGIT_SIZE, dy=DIGIT_SIZE, inverted=inverted)

def random_invert_animation(pan, refresh_fn, delay=0.01, width=WIDTH, height=HEIGHT):
    current = capture_screen(pan, width, height)
    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)
    for x, y in coords:
        pan.draw(x, y, int(target[y, x]))
        if refresh_fn:
            refresh_fn()
        time.sleep(delay)

def clear_display(pan, inverted=False, refresh_fn=refresh):
    """Fill entire display with background (blank)."""
    bg = 1 if not inverted else 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pan.draw(x, y, bg)
    if refresh_fn:
        refresh_fn()

# ---------------------------
# Random hour update
# ---------------------------

# render a pair of digits into an off-screen numpy buffer
def render_digits_to_buffer(hour:int, bottom_val:int=None, inverted:bool=False):
    """
    Render top-row hours (two digits) into a (HEIGHT, WIDTH) numpy buffer.
    If bottom_val is provided it'll render bottom row digits too (not required here).
    Returned buffer uses same 0/1 polarity as draw calls expect.
    """
    buf = np.zeros((HEIGHT, WIDTH), dtype=int)
    bg = 1 if not inverted else 0
    fg = 0 if not inverted else 1

    # fill background in the whole buffer with bg
    buf[:, :] = bg

    # helper to draw canonical strokes into the buffer
    def draw_digit_to_buf(digit, dx, dy):
        strokes = digit_strokes_flipped.get(digit, [])
        for s in strokes:
            off = offset_stroke(s, dx, dy)
            pxs = stroke_to_ordered_pixels(off, thickness=STROKE_THICKNESS_DEFAULT, bounds=(WIDTH, HEIGHT))
            for x, y in pxs:
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    buf[y, x] = fg

    # top row (hours)
    d1, d2 = divmod(hour, 10)
    draw_digit_to_buf(d1, 0, 0)
    draw_digit_to_buf(d2, DIGIT_SIZE, 0)

    # optional bottom row if requested
    if bottom_val is not None:
        b1, b2 = divmod(bottom_val, 10)
        draw_digit_to_buf(b1, 0, DIGIT_SIZE)
        draw_digit_to_buf(b2, DIGIT_SIZE, DIGIT_SIZE)

    return buf

# random reveal: progressively write pixels from target buffer to device
def random_reveal_buffer(pan, refresh_fn, target_buf, delay=0.01):
    """
    Randomly reveal pixels from target_buf onto `pan`. This writes target_buf[y,x]
    directly (not invert). Waits until finished. Returns when all pixels written.
    """
    h, w = target_buf.shape
    coords = [(x, y) for y in range(h) for x in range(w)]
    random.shuffle(coords)
    for x, y in coords:
        pan.draw(x, y, int(target_buf[y, x]))
        if refresh_fn:
            refresh_fn()
        time.sleep(delay)


# Setup MQTT client (run in background thread)
mqtt_client = mqtt.Client()
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.on_connect = mqtt_on_connect
mqtt_client.on_message = mqtt_on_message

def start_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()  # runs the network loop in a background thread
    except Exception as e:
        print("MQTT start failed:", e)

# start MQTT now
start_mqtt()

# ---------------------------
# Main loop
# ---------------------------
def main():
    global DISPLAY_INVERTED

    last_min = -1
    last_hour = -1
    prev_show_seconds = False
    sec_sim = 0

    # initial draw
    h, m, s = get_time()
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)

    while True:
        h, m, _ = get_time()
        show_seconds = os.path.exists(SHOW_SECONDS_FILE)

        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)
        instant_threshold = INSTANT_THRESHOLD_DEFAULT
        thickness = STROKE_THICKNESS_DEFAULT
        # ---- handle inbound MQTT commands (if any) ----
        while not command_queue.empty():
            cmd = command_queue.get_nowait()
            if cmd == "blank":
                print("Command: blank -> clearing display")
                clear_display(panels, inverted=DISPLAY_INVERTED, refresh_fn=refresh)
            elif cmd == "refresh":
                print("Command: refresh -> redrawing time")
                # redraw current time immediately
                h, m, s = get_time()
                draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            # mark done (queue.get removed it)
        
        # ----------------------------
        # SECONDS DEBUG MODE (simulated step-through)
        # ----------------------------

        if show_seconds:
            # entering simulated-seconds mode: reset counter and draw initial state
            if not prev_show_seconds:
                sec_sim = 0
                draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            # Run simulated stepping while the file exists.
            # This inner loop checks the file every iteration so we can exit cleanly.
            while os.path.exists(SHOW_SECONDS_FILE):
                old_s = sec_sim
                sec_sim = (sec_sim + 1) % 60
                new_s = sec_sim

                old_tens, old_ones = divmod(old_s, 10)
                new_tens, new_ones = divmod(new_s, 10)

                # tens (bottom-left)
                if new_tens != old_tens:
                    sequential_transition(panels, old_tens, new_tens, dx=0, dy=DIGIT_SIZE,
                                          refresh_fn=refresh,
                                          per_pixel_delay=second_delay,
                                          thickness=thickness,
                                          instant_threshold=instant_threshold,
                                          bounds=(WIDTH, HEIGHT),
                                          inverted=DISPLAY_INVERTED,
                                          animate_if_same=False)

                # ones (bottom-right)
                if new_ones != old_ones:
                    sequential_transition(panels, old_ones, new_ones, dx=DIGIT_SIZE, dy=DIGIT_SIZE,
                                          refresh_fn=refresh,
                                          per_pixel_delay=second_delay,
                                          thickness=thickness,
                                          instant_threshold=instant_threshold,
                                          bounds=(WIDTH, HEIGHT),
                                          inverted=DISPLAY_INVERTED,
                                          animate_if_same=False)

                # record last second shown (optional)
                last_sec = sec_sim

                # allow invert trigger while in seconds mode
                if os.path.exists(TRIGGER_INVERT_FILE):
                    random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
                    DISPLAY_INVERTED = not DISPLAY_INVERTED
                    draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                    try:
                        os.remove(TRIGGER_INVERT_FILE)
                    except Exception:
                        pass

                # wait exactly 1 second between steps
                time.sleep(1.0)

            # we exited seconds mode
            prev_show_seconds = False
            # ensure minutes are re-drawn when coming back
            h, m, _ = get_time()
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            continue



        # ----------------------------
        # NORMAL minute mode transitions
        # ----------------------------
        if m == 0:
            reveal_hour = h
            new_inverted = not DISPLAY_INVERTED
            target = render_digits_to_buffer(reveal_hour, bottom_val=0, inverted=new_inverted)
            random_reveal_buffer(panels, refresh, target, delay=0.005)
            DISPLAY_INVERTED = new_inverted
            draw_hours_only(reveal_hour, DISPLAY_INVERTED)
            paint_digit_instant(panels, digit_strokes_flipped[0], dx=0, dy=DIGIT_SIZE, inverted=DISPLAY_INVERTED)
            paint_digit_instant(panels, digit_strokes_flipped[0], dx=DIGIT_SIZE, dy=DIGIT_SIZE, inverted=DISPLAY_INVERTED)
            last_hour = reveal_hour

            # re-read time to avoid racing with long reveal
            h, m, _ = get_time()
            old_m = last_min if last_min >= 0 else m
            old_tens, old_ones = divmod(old_m, 10)
            new_tens, new_ones = divmod(m, 10)
    
            sequential_transition(panels, old_tens, new_tens, dx=0, dy=DIGIT_SIZE,
                                  refresh_fn=refresh, per_pixel_delay=minute_delay,
                                  thickness=thickness, instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)
    
            sequential_transition(panels, old_ones, new_ones, dx=DIGIT_SIZE, dy=DIGIT_SIZE,
                                  refresh_fn=refresh, per_pixel_delay=minute_delay,
                                  thickness=thickness, instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)
    
            last_min = m

        # ----------------------------
        # SSH invert trigger (normal mode)
        # ----------------------------
        if os.path.exists(TRIGGER_INVERT_FILE):
            random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            try:
                os.remove(TRIGGER_INVERT_FILE)
            except Exception:
                pass

        time.sleep(0.1)


if __name__ == "__main__":
    main()
