#!/usr/bin/env python3
"""
main.py — Dotty (cleaned + MQTT command queue + sequential stroke transitions)

Features:
- stroke-based digits & sequential transitions
- MQTT control: publish status, subscribe to dotty/command, accept "blank" and "refresh"
- env-driven MQTT config: DOTTY_MQTT_HOST, DOTTY_MQTT_PORT, DOTTY_MQTT_USER, DOTTY_MQTT_PASS
"""

import os
import time
import random
import logging
import queue
import threading
from datetime import datetime
from typing import List, Tuple, Iterable, Iterable as IterableType

import numpy as np
import paho.mqtt.client as mqtt

# local hardware modules (must exist in repo)
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

INSTANT_THRESHOLD_DEFAULT = 0
STROKE_THICKNESS_DEFAULT = 1

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dotty")

# ---------------------------
# MQTT config (from env)
# ---------------------------
MQTT_BROKER = os.getenv("DOTTY_MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("DOTTY_MQTT_PORT", "1883"))
MQTT_USER = os.getenv("DOTTY_MQTT_USER", "")
MQTT_PASS = os.getenv("DOTTY_MQTT_PASS", "")

# command queue used by MQTT on_message to hand commands to the main loop
command_queue: "queue.Queue[str]" = queue.Queue()

# ---------------------------
# Digit stroke definitions (14x14 coordinate grid 0..13)
# (kept equivalent to your authored strokes)
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
def flip_stroke_y(stroke: IterableType[Tuple[int,int]], size: int = DIGIT_SIZE):
    """Flip authored bottom-left Y -> top-left hardware Y"""
    return [(x, (size - 1) - y) for (x, y) in stroke]

def flip_all(strokes_map):
    return {d: [flip_stroke_y(s) for s in s_list] for d, s_list in strokes_map.items()}

digit_strokes_flipped = flip_all(digit_strokes)
sequential_strokes_flipped = flip_all(sequential_strokes)

for d in range(10):
    if d not in sequential_strokes_flipped:
        log.warning("Warning: no sequential strokes for %d", d)

# hardware init
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
    """Rasterize a stroke (series of points) -> ordered pixel list."""
    w, h = bounds
    pts = []
    seen = set()
    for a, b in zip(stroke, stroke[1:]):
        for p in bresenham_line(a[0], a[1], b[0], b[1]):
            if p not in seen and 0 <= p[0] < w and 0 <= p[1] < h:
                pts.append(p)
                seen.add(p)
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

def play_pixels_invert(pan, pixels: IterableType[Tuple[int,int]], refresh_fn=None, per_pixel_delay:float=0.01):
    """Draw pixels by inverting current state."""
    for x, y in pixels:
        current = pan.get(x, y)
        pan.draw(x, y, 1 - current)
        if refresh_fn:
            refresh_fn()
        time.sleep(per_pixel_delay)

def offset_stroke(stroke: IterableType[Tuple[int,int]], dx:int=0, dy:int=0):
    return [(x + dx, y + dy) for (x, y) in stroke]

# ---------------------------
# Canonical paint utility
# ---------------------------
def paint_digit_instant(pan, strokes: List[List[Tuple[int,int]]], dx=0, dy=0, inverted=False,
                        thickness=STROKE_THICKNESS_DEFAULT, refresh_fn=None):
    """Clear digit box and draw canonical strokes instantly."""
    bg = 1 if not inverted else 0
    fg = 0 if not inverted else 1

    for yy in range(DIGIT_SIZE):
        for xx in range(DIGIT_SIZE):
            pan.draw(dx + xx, dy + yy, bg)

    for s in strokes:
        off = offset_stroke(s, dx, dy)
        pxs = stroke_to_ordered_pixels(off, thickness=thickness, bounds=(WIDTH, HEIGHT))
        for tx, ty in pxs:
            if 0 <= tx < WIDTH and 0 <= ty < HEIGHT:
                pan.draw(tx, ty, fg)

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
    if from_digit == to_digit and not animate_if_same:
        return

    seq = sequential_strokes_flipped.get(to_digit, digit_strokes_flipped.get(to_digit, []))
    for stroke in seq:
        off = offset_stroke(stroke, dx, dy)
        pixels = stroke_to_ordered_pixels(off, thickness=thickness, bounds=bounds)
        # sequential strokes should invert the visual state (we want reveal/morph)
        play_pixels_invert(pan, pixels, refresh_fn=refresh_fn, per_pixel_delay=per_pixel_delay)
    # final snap to canonical digit for pixel-perfect result
    time.sleep(per_pixel_delay)
    paint_digit_instant(pan, digit_strokes_flipped[to_digit], dx=dx, dy=dy, inverted=inverted, thickness=thickness, refresh_fn=refresh_fn)

# ---------------------------
# Display helpers
# ---------------------------
def draw_hours_only(h:int, inverted:bool):
    d1, d2 = divmod(h, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted, refresh_fn=refresh)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted, refresh_fn=refresh)

def draw_hours_and_bottom(h:int, bottom_val:int, inverted:bool):
    d1, d2 = divmod(h, 10)
    b1, b2 = divmod(bottom_val, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[b1], dx=0, dy=DIGIT_SIZE, inverted=inverted)
    paint_digit_instant(panels, digit_strokes_flipped[b2], dx=DIGIT_SIZE, dy=DIGIT_SIZE, inverted=inverted)
    refresh()

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
    bg = 1 if not inverted else 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pan.draw(x, y, bg)
    if refresh_fn:
        refresh_fn()

# ---------------------------
# Random hour reveal helpers
# ---------------------------
def render_digits_to_buffer(hour:int, bottom_val:int=None, inverted:bool=False):
    buf = np.zeros((HEIGHT, WIDTH), dtype=int)
    bg = 1 if not inverted else 0
    fg = 0 if not inverted else 1
    buf[:, :] = bg

    def draw_digit_to_buf(digit, dx, dy):
        strokes = digit_strokes_flipped.get(digit, [])
        for s in strokes:
            off = offset_stroke(s, dx, dy)
            pxs = stroke_to_ordered_pixels(off, thickness=STROKE_THICKNESS_DEFAULT, bounds=(WIDTH, HEIGHT))
            for x, y in pxs:
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    buf[y, x] = fg

    d1, d2 = divmod(hour, 10)
    draw_digit_to_buf(d1, 0, 0)
    draw_digit_to_buf(d2, DIGIT_SIZE, 0)
    if bottom_val is not None:
        b1, b2 = divmod(bottom_val, 10)
        draw_digit_to_buf(b1, 0, DIGIT_SIZE)
        draw_digit_to_buf(b2, DIGIT_SIZE, DIGIT_SIZE)
    return buf

def random_reveal_buffer(pan, refresh_fn, target_buf, delay=0.01):
    h, w = target_buf.shape
    coords = [(x, y) for y in range(h) for x in range(w)]
    random.shuffle(coords)
    for x, y in coords:
        pan.draw(x, y, int(target_buf[y, x]))
        if refresh_fn:
            refresh_fn()
        time.sleep(delay)

# ---------------------------
# MQTT callbacks & startup
# ---------------------------
def mqtt_on_connect(client, userdata, flags, rc, properties=None):
    log.info("MQTT connected rc=%s flags=%s", rc, flags)
    if rc == 0:
        client.publish("dotty/status", "online", qos=1, retain=True)
        client.subscribe("dotty/command")
    else:
        log.warning("MQTT connect failed rc=%s", rc)

def mqtt_on_message(client, userdata, msg):
    payload = msg.payload.decode(errors="ignore").strip()
    log.info("MQTT RX %s -> %s", msg.topic, payload)
    if payload:
        command_queue.put(payload)

def mqtt_on_disconnect(client, userdata, rc):
    log.warning("MQTT disconnected rc=%s", rc)

# create mqtt client (single instance)
mqtt_client = mqtt.Client(client_id=f"dotty-{os.uname().nodename}-{random.getrandbits(32):08x}", protocol=mqtt.MQTTv311)
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

mqtt_client.on_connect = mqtt_on_connect
mqtt_client.on_message = mqtt_on_message
mqtt_client.on_disconnect = mqtt_on_disconnect

def start_mqtt_background():
    backoff = 1.0
    while True:
        try:
            log.info("Attempting mqtt connect to %s:%s", MQTT_BROKER, MQTT_PORT)
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            mqtt_client.loop_start()
            log.info("MQTT loop started")
            return
        except Exception as e:
            log.exception("MQTT start failed: %s — retrying in %s sec", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

# start MQTT in background thread so main loop isn't blocked
threading.Thread(target=start_mqtt_background, daemon=True).start()

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
            try:
                cmd = command_queue.get_nowait()
            except queue.Empty:
                break
            cmd = cmd.lower().strip()
            if cmd == "blank":
                log.info("MQTT command: blank -> clearing display")
                clear_display(panels, inverted=DISPLAY_INVERTED, refresh_fn=refresh)
            elif cmd == "refresh":
                log.info("MQTT command: refresh -> redrawing time")
                h, m, s = get_time()
                draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            else:
                log.info("MQTT command: unknown -> %s", cmd)

        # ----------------------------
        # SECONDS DEBUG MODE (simulated step-through)
        # ----------------------------
        if show_seconds:
            if not prev_show_seconds:
                sec_sim = 0
                draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            while os.path.exists(SHOW_SECONDS_FILE):
                old_s = sec_sim
                sec_sim = (sec_sim + 1) % 60
                new_s = sec_sim

                old_tens, old_ones = divmod(old_s, 10)
                new_tens, new_ones = divmod(new_s, 10)

                if new_tens != old_tens:
                    sequential_transition(panels, old_tens, new_tens, dx=0, dy=DIGIT_SIZE,
                                          refresh_fn=refresh, per_pixel_delay=second_delay,
                                          thickness=thickness, instant_threshold=instant_threshold,
                                          bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

                if new_ones != old_ones:
                    sequential_transition(panels, old_ones, new_ones, dx=DIGIT_SIZE, dy=DIGIT_SIZE,
                                          refresh_fn=refresh, per_pixel_delay=second_delay,
                                          thickness=thickness, instant_threshold=instant_threshold,
                                          bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

                # allow invert trigger while in seconds mode
                if os.path.exists(TRIGGER_INVERT_FILE):
                    random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
                    DISPLAY_INVERTED = not DISPLAY_INVERTED
                    draw_hours_and_bottom(h, sec_sim, DISPLAY_INVERTED)
                    try:
                        os.remove(TRIGGER_INVERT_FILE)
                    except Exception:
                        pass

                time.sleep(1.0)

            prev_show_seconds = False
            h, m, _ = get_time()
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            continue

        # ----------------------------
        # NORMAL minute mode transitions
        # ----------------------------
        if m != last_min:
            old_m = last_min if last_min >= 0 else m
            old_tens, old_ones = divmod(old_m, 10)
            new_tens, new_ones = divmod(m, 10)

            # top-of-hour: random reveal showing next hour
            if m == 0:
                # next hour is already reflected by get_time()
                reveal_hour = h
                new_inverted = not DISPLAY_INVERTED
                target = render_digits_to_buffer(reveal_hour, bottom_val=0, inverted=new_inverted)
                random_reveal_buffer(panels, refresh, target, delay=0.005)

                DISPLAY_INVERTED = new_inverted
                draw_hours_only(reveal_hour, DISPLAY_INVERTED)
                paint_digit_instant(panels, digit_strokes_flipped[0], dx=0, dy=DIGIT_SIZE, inverted=DISPLAY_INVERTED)
                paint_digit_instant(panels, digit_strokes_flipped[0], dx=DIGIT_SIZE, dy=DIGIT_SIZE, inverted=DISPLAY_INVERTED)
                last_hour = reveal_hour

                # re-read to avoid race with long reveal
                h, m, _ = get_time()
                old_m = last_min if last_min >= 0 else m
                old_tens, old_ones = divmod(old_m, 10)
                new_tens, new_ones = divmod(m, 10)

            # bottom-left (tens)
            sequential_transition(panels, old_tens, new_tens, dx=0, dy=DIGIT_SIZE,
                                  refresh_fn=refresh, per_pixel_delay=minute_delay,
                                  thickness=thickness, instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

            # bottom-right (ones)
            sequential_transition(panels, old_ones, new_ones, dx=DIGIT_SIZE, dy=DIGIT_SIZE,
                                  refresh_fn=refresh, per_pixel_delay=minute_delay,
                                  thickness=thickness, instant_threshold=instant_threshold,
                                  bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

            last_min = m

            if h != last_hour:
                # keep last_hour in sync to avoid duplicate reveals
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

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
    try:
        main()
    except KeyboardInterrupt:
        log.info("Dotty stopped by user")
    finally:
        try:
            mqtt_client.publish("dotty/status", "offline", qos=1, retain=True)
            mqtt_client.loop_stop()
        except Exception:
            pass
