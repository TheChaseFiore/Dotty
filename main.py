#!/usr/bin/env python3
"""
Dotty main - fixed, single-file version with robust MQTT/command queue handling.

Drop this into /home/chase/Dotty/main.py and restart the service.
"""

import os
import time
import random
from datetime import datetime
from typing import List, Tuple, Iterable
import threading
import queue
import logging

import numpy as np

import serial_port
import matrix

# optional: paho mqtt
try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

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
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("dotty")

# ---------------------------
# Command queue (MQTT -> main)
# ---------------------------
command_queue = queue.Queue()

# ---------------------------
# MQTT config from env
# ---------------------------
MQTT_BROKER = os.getenv("DOTTY_MQTT_BROKER", os.getenv("DOTTY_MQTT_HOST", "localhost"))
MQTT_PORT = int(os.getenv("DOTTY_MQTT_PORT", os.getenv("DOTTY_MQTT_PORT", 1883)))
MQTT_USER = os.getenv("DOTTY_MQTT_USER", "")
MQTT_PASS = os.getenv("DOTTY_MQTT_PASS", "")

# ---------------------------
# MQTT callbacks
# ---------------------------
def _mqtt_on_connect(client, userdata, flags, rc, properties=None):
    log.info("MQTT connected rc=%s flags=%s", rc, flags)
    if rc == 0:
        client.publish("dotty/status", "online", qos=1, retain=True)
        client.subscribe("dotty/command")
    else:
        log.warning("MQTT connect returned rc=%s", rc)

def _mqtt_on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode(errors="ignore").strip()
    except Exception:
        payload = "<binary>"
    log.info("MQTT RX %s -> %s", msg.topic, payload)
    # only enqueue short commands; keep callbacks tiny
    if payload:
        try:
            command_queue.put_nowait(payload)
        except queue.Full:
            log.warning("Command queue full; dropping MQTT command")

def _mqtt_on_disconnect(client, userdata, rc):
    log.warning("MQTT disconnected rc=%s", rc)

def publish_state(state: str):
    """Publish dotty/state retained so HA can wait_for_trigger on display state."""
    if mqtt_client is None:
        return
    try:
        mqtt_client.publish("dotty/state", state, qos=1, retain=True)
        log.info("Published dotty/state=%s", state)
    except Exception:
        log.exception("publish_state(%s) failed", state)

# ---------------------------
# MQTT client management (single instance)
# ---------------------------
mqtt_client = None
def build_mqtt_client():
    global mqtt_client
    if mqtt is None:
        log.warning("paho.mqtt not available; MQTT will be disabled")
        return None
    # use client id that is reasonably unique
    client_id = f"dotty-{os.uname().nodename}-{random.getrandbits(32):08x}"
    # Use MQTTv311 (most common) - paho default
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    # LWT: broker publishes offline if dotty drops the connection ungracefully
    client.will_set("dotty/status", "offline", qos=1, retain=True)
    client.on_connect = _mqtt_on_connect
    client.on_message = _mqtt_on_message
    client.on_disconnect = _mqtt_on_disconnect
    return client

def start_mqtt_background():
    """Start MQTT non-blocking with retries (runs in its own thread)."""
    global mqtt_client
    mqtt_client = build_mqtt_client()
    if mqtt_client is None:
        return
    backoff = 1.0
    while True:
        try:
            log.info("Attempting MQTT connect to %s:%s", MQTT_BROKER, MQTT_PORT)
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            mqtt_client.loop_start()   # non-blocking
            log.info("MQTT loop started")
            return
        except Exception as e:
            log.exception("MQTT start failed: %s - retrying in %.1fs", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

# Start MQTT thread as a daemon so it can't block exit
if mqtt is not None:
    t = threading.Thread(target=start_mqtt_background, name="mqtt-start", daemon=True)
    t.start()
else:
    log.info("MQTT support disabled (paho not installed)")

# ---------------------------
# Utilities / hardware wrappers
# ---------------------------
class ShadowMatrix:
    def __init__(self, real_panels, width, height):
        self.real = real_panels
        self.w = width
        self.h = height
        # Keep state in memory for O(1) reads
        self.buffer = np.zeros((height, width), dtype=int)

    def draw(self, x, y, val):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.buffer[y, x] = int(val)
            self.real.draw(x, y, int(val))

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.buffer[y, x]
        return 0
        
def refresh(flaggs=True):
    try:
        # FIX: If we are using ShadowMatrix, unwrap it to get the real hardware object
        target = panels.real if hasattr(panels, "real") else panels
        serial_port.refresh(target, rs232, flaggs)
    except Exception:
        log.exception("refresh() failed")

def get_time():
    now = datetime.now()
    return now.hour, now.minute, now.second

def capture_screen(pan, width=WIDTH, height=HEIGHT):
    buf = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            try:
                buf[y, x] = int(pan.get(x, y))
            except Exception:
                buf[y, x] = 0
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

def play_pixels_invert(pan, pixels: Iterable[Tuple[int,int]], refresh_fn=None, per_pixel_delay:float=0.01):
    for x, y in pixels:
        try:
            current = pan.get(x, y)
            pan.draw(x, y, 1 - current)
        except Exception:
            pass
        if refresh_fn:
            refresh_fn()
        time.sleep(per_pixel_delay)

def offset_stroke(stroke: Iterable[Tuple[int,int]], dx:int=0, dy:int=0):
    return [(x + dx, y + dy) for (x, y) in stroke]

# ---------------------------
# Digit stroke data (kept as you provided)
# ---------------------------
# (I preserved your stroke maps - truncated here for brevity in comments)
digit_strokes = {
    0: [[(2,11),(11,11)], [(11,11),(11,2)], [(11,2),(2,2)], [(2,2),(2,11)]],
    1: [[(6,11),(7,11)], [(7,11),(7,2)]],
    2: [[(2,11),(11,11)], [(11,11),(11,7)], [(11,7),(2,7)], [(2,7),(2,2)], [(2,2),(11,2)]],
    3: [[(2,11),(11,11)], [(11,11),(11,2)], [(11,2),(2,2)], [(11,7),(4,7)]],
    4: [[(2,11),(2,7)], [(2,7),(11,7)], [(11,11),(11,2)]],
    5: [[(11,11),(2,11)], [(2,11),(2,7)], [(2,7),(11,7)], [(11,7),(11,2)], [(11,2),(2,2)]],
    6: [[(11,11),(2,11)], [(2,11),(2,2)], [(2,2),(11,2)], [(11,2),(11,7)], [(11,7),(2,7)]],
    7: [[(2,11),(11,11)], [(11,11),(11,2)]],
    8: [[(2,11),(11,11)], [(11,11),(11,2)], [(11,2),(2,2)], [(2,2),(2,11)], [(2,7),(11,7)]],
    9: [[(2,11),(11,11)], [(11,11),(11,2)], [(2,11),(2,7)], [(2,7),(11,7)]],
}

sequential_strokes = {
    1: [[(2,11),(11,11)], [(11,10),(11,2)], [(10,2),(2,2)], [(2,3),(2,10)], [(6,11),(7,11)], [(7,10),(7,2)]],
    2: [[(7,10),(7,2)], [(2,11),(5,11)], [(8,11),(11,11)], [(11,10),(11,7)], [(10,7),(2,7)], [(2,6),(2,2)], [(3,2),(11,2)]],
    3: [[(2,3),(2,7)], [(3,7),(3,7)], [(11,3),(11,6)]],
    4: [[(10,11),(2,11)], [(2,11),(2,7)], [(3,7),(3,7)], [(10,2),(2,2)]],
    5: [[(2,2),(10,2)], [(11,8),(11,10)], [(10,11),(3,11)]],
    6: [[(2,6),(2,3)]],
    7: [[(2,10),(2,2)], [(3,2),(11,2)], [(11,3),(11,7)], [(10,7),(3,7)], [(11,10),(11,2)]],
    8: [[(2,10),(2,2)], [(3,2),(10,2)], [(10,7),(3,7)]],
    9: [[(2,6),(2,2)], [(3,2),(10,2)]],
    0: [[(10,7),(3,7)], [(2,6),(2,2)], [(3,2),(10,2)]],
}

def flip_stroke_y(stroke: Iterable[Tuple[int,int]], size: int = DIGIT_SIZE):
    return [(x, (size - 1) - y) for (x, y) in stroke]

def flip_all(strokes_map):
    return {d: [flip_stroke_y(s) for s in s_list] for d, s_list in strokes_map.items()}

digit_strokes_flipped = flip_all(digit_strokes)
sequential_strokes_flipped = flip_all(sequential_strokes)

# ---------------------------
# Hardware init
# ---------------------------
# existing hardware init
try:
    panels = matrix.matrix(4)
    rs232 = serial_port.initiate_serial()
except:
    log.exception("Hardware init failed - running in degraded mode")
    panels = None
    rs232 = None

# WRAP IT HERE:
if panels:
    panels = ShadowMatrix(panels, WIDTH, HEIGHT)
    

DISPLAY_INVERTED = False

# ---------------------------
# Paint utilities (instant + sequential)
# ---------------------------
def paint_digit_instant(pan, strokes: List[List[Tuple[int,int]]], dx=0, dy=0, inverted=False,
                        thickness=STROKE_THICKNESS_DEFAULT, refresh_fn=None):
    if pan is None:
        return
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

def sequential_transition(pan, from_digit:int, to_digit:int, dx:int, dy:int,
                          refresh_fn=refresh,
                          per_pixel_delay:float=0.01,
                          thickness:int=STROKE_THICKNESS_DEFAULT,
                          instant_threshold:int=INSTANT_THRESHOLD_DEFAULT,
                          bounds=(WIDTH, HEIGHT),
                          inverted:bool=False,
                          animate_if_same:bool=False):
    if pan is None:
        return
    if from_digit == to_digit and not animate_if_same:
        return
    seq = sequential_strokes_flipped.get(to_digit, digit_strokes_flipped.get(to_digit, []))
    for stroke in seq:
        off = offset_stroke(stroke, dx, dy)
        pixels = stroke_to_ordered_pixels(off, thickness=thickness, bounds=bounds)
        play_pixels_invert(pan, pixels, refresh_fn=refresh_fn, per_pixel_delay=per_pixel_delay)
    # final snap to canonical digit
    time.sleep(per_pixel_delay)
    paint_digit_instant(pan, digit_strokes_flipped[to_digit], dx=dx, dy=dy, inverted=inverted, thickness=thickness, refresh_fn=refresh_fn)

def draw_hours_only(h:int, inverted:bool):
    if panels is None:
        return
    d1, d2 = divmod(h, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted, refresh_fn=refresh)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted, refresh_fn=refresh)

def draw_hours_and_bottom(h:int, bottom_val:int, inverted:bool):
    if panels is None:
        return
    d1, d2 = divmod(h, 10)
    b1, b2 = divmod(bottom_val, 10)
    paint_digit_instant(panels, digit_strokes_flipped[d1], dx=0, dy=0, inverted=inverted, refresh_fn=refresh)
    paint_digit_instant(panels, digit_strokes_flipped[d2], dx=DIGIT_SIZE, dy=0, inverted=inverted, refresh_fn=refresh)
    paint_digit_instant(panels, digit_strokes_flipped[b1], dx=0, dy=DIGIT_SIZE, inverted=inverted, refresh_fn=refresh)
    paint_digit_instant(panels, digit_strokes_flipped[b2], dx=DIGIT_SIZE, dy=DIGIT_SIZE, inverted=inverted, refresh_fn=refresh)

def clear_display(pan, inverted=False, refresh_fn=refresh):
    if pan is None:
        return
    bg = 1 if not inverted else 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pan.draw(x, y, bg)
    if refresh_fn:
        refresh_fn()

# ---------------------------
# Random reveal utilities
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
# Netflix splash logo
# ---------------------------
# Geometry of the Netflix 'N' on the 28x28 grid (white/lit on a black field).
NETFLIX_TOP = 3
NETFLIX_BOTTOM = 24          # vertical extent of the legs (inclusive)
NETFLIX_BAR_W = 3
NETFLIX_LEFT_X0 = 6          # left leg starts here
NETFLIX_RIGHT_X0 = WIDTH - NETFLIX_BAR_W - NETFLIX_LEFT_X0  # symmetric right leg -> 19

def netflix_logo_buffer():
    """Final 28x28 frame of the Netflix 'N': lit (white) strokes on a dark field."""
    buf = np.zeros((HEIGHT, WIDTH), dtype=int)
    top, bottom, bar_w = NETFLIX_TOP, NETFLIX_BOTTOM, NETFLIX_BAR_W
    lx, rx = NETFLIX_LEFT_X0, NETFLIX_RIGHT_X0
    buf[top:bottom + 1, lx:lx + bar_w] = 1
    buf[top:bottom + 1, rx:rx + bar_w] = 1
    span = bottom - top
    for i, y in enumerate(range(top, bottom + 1)):
        x0 = int(round(lx + (rx - lx) * (i / span)))
        buf[y, x0:x0 + bar_w] = 1
    return buf

def display_netflix_logo(pan, refresh_fn=refresh, step_delay: float = 0.03):
    """Animate the Netflix 'N' onto the display like the title-sequence ident:
    starting from black, light sweeps up the left leg, down the diagonal, then up
    the right leg. White (lit) strokes on a black (dark) field."""
    if pan is None:
        return
    top, bottom, bar_w = NETFLIX_TOP, NETFLIX_BOTTOM, NETFLIX_BAR_W
    lx, rx = NETFLIX_LEFT_X0, NETFLIX_RIGHT_X0
    span = bottom - top

    # Start from a clean black field.
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pan.draw(x, y, 0)
    if refresh_fn:
        refresh_fn()

    def light_row(y, x0):
        for x in range(x0, x0 + bar_w):
            pan.draw(x, y, 1)
        if refresh_fn:
            refresh_fn()
        time.sleep(step_delay)

    # 1) left leg rises (bottom -> top)
    for y in range(bottom, top - 1, -1):
        light_row(y, lx)
    # 2) diagonal sweeps (top -> bottom)
    for i, y in enumerate(range(top, bottom + 1)):
        x0 = int(round(lx + (rx - lx) * (i / span)))
        light_row(y, x0)
    # 3) right leg rises (bottom -> top)
    for y in range(bottom, top - 1, -1):
        light_row(y, rx)

# Baked clip produced by tools/make_netflix_clip.py (white-on-black 1-bit frames).
NETFLIX_CLIP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "netflix.npz")

def load_clip(path):
    """Load a baked 1-bit clip. Returns (frames(n,H,W) uint8, fps) or None."""
    if not os.path.exists(path):
        return None
    try:
        data = np.load(path)
        shape = tuple(int(v) for v in data["shape"])
        n = int(np.prod(shape))
        frames = np.unpackbits(data["frames"])[:n].reshape(shape).astype(np.uint8)
        fps = float(data["fps"]) if "fps" in data.files else 12.0
        return frames, fps
    except Exception:
        log.exception("Failed to load clip %s", path)
        return None

def play_clip(pan, frames, fps, refresh_fn=refresh):
    """Play baked frames, pushing only changed pixels so the slow flip-dot bus
    redraws just the panels that actually changed between frames."""
    if pan is None or len(frames) == 0:
        return
    delay = 1.0 / fps if fps > 0 else 0.08
    prev = None
    for fr in frames:
        fh, fw = fr.shape
        if prev is None:
            for y in range(min(fh, HEIGHT)):
                for x in range(min(fw, WIDTH)):
                    pan.draw(x, y, int(fr[y, x]))
        else:
            ys, xs = np.where(fr != prev)
            for y, x in zip(ys, xs):
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    pan.draw(int(x), int(y), int(fr[y, x]))
        if refresh_fn:
            refresh_fn()
        prev = fr
        time.sleep(delay)

# ---------------------------
# Main loop
# ---------------------------
def main():
    global DISPLAY_INVERTED
    
    # Initialize state with current time to prevent 
    # animations from triggering immediately on boot/restart.
    h, m, s = get_time()
    last_min = m
    last_hour = h
    
    prev_show_seconds = False
    sec_sim = 0

    # Initial draw (Instant)
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
    publish_state("time")

    log.info("Entering main loop")
    while True:
        try:
            h, m, _ = get_time()
            show_seconds = os.path.exists(SHOW_SECONDS_FILE)

            minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
            second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)
            instant_threshold = INSTANT_THRESHOLD_DEFAULT
            thickness = STROKE_THICKNESS_DEFAULT

            # --- handle commands from MQTT (non-blocking) ---
            while not command_queue.empty():
                try:
                    cmd = command_queue.get_nowait()
                except queue.Empty:
                    break
                if not cmd:
                    continue
                cmd_norm = cmd.strip().lower()
                log.info("Processing command from queue: %s", cmd_norm)
                if cmd_norm == "blank":
                    clear_display(panels, inverted=DISPLAY_INVERTED, refresh_fn=refresh)
                    publish_state("blank")
                elif cmd_norm == "refresh":
                    hh, mm, ss = get_time()
                    draw_hours_and_bottom(hh, mm, DISPLAY_INVERTED)
                    publish_state("time")
                elif cmd_norm == "netflix":
                    clip = load_clip(NETFLIX_CLIP_PATH)
                    if clip is not None:
                        frames, fps = clip
                        play_clip(panels, frames, fps, refresh_fn=refresh)
                    else:
                        log.info("No baked clip at %s; using drawn animation", NETFLIX_CLIP_PATH)
                        display_netflix_logo(panels, refresh_fn=refresh)
                    publish_state("netflix")
                else:
                    log.info("Unknown command: %s", cmd)

            # seconds simulated step-through mode
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
                    time.sleep(1.0)
                prev_show_seconds = False
                h, m, _ = get_time()
                draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
                continue

            # ==========================================
            # PRIORITY 1: Top of Hour Transition
            # ==========================================
            if h != last_hour:
                log.info("Top of Hour Triggered: %02d:00", h)
                
                # 1. Prepare the Invert State
                new_inverted = not DISPLAY_INVERTED
                
                # 2. Render the "After" image (New Hour + "00" minutes)
                # Note: We use 'h' because get_time() has already rolled over
                target = render_digits_to_buffer(h, bottom_val=0, inverted=new_inverted)
                
                # 3. Perform the Sparkle/Reveal Animation
                random_reveal_buffer(panels, refresh, target, delay=0.005)
                
                # 4. Commit State
                DISPLAY_INVERTED = new_inverted
                last_hour = h
                last_min = m  # Sync minutes so we don't trigger the snake animation below
                
                # 5. Safety Redraw (snaps to perfect lines in case reveal left artifacts)
                draw_hours_and_bottom(h, 0, DISPLAY_INVERTED)
                
                continue # SKIP the rest of the loop to prevent conflicts

            # ==========================================
            # PRIORITY 2: Standard Minute Transition
            # ==========================================
            if m != last_min:
                log.info("Minute Transition: %02d -> %02d", last_min, m)
                
                old_m = last_min
                old_tens, old_ones = divmod(old_m, 10)
                new_tens, new_ones = divmod(m, 10)

                # Tens digit (only if changed)
                if old_tens != new_tens:
                    sequential_transition(panels, old_tens, new_tens, dx=0, dy=DIGIT_SIZE,
                                          refresh_fn=refresh, per_pixel_delay=minute_delay,
                                          thickness=thickness, instant_threshold=instant_threshold,
                                          bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

                # Ones digit (always changes on minute change)
                sequential_transition(panels, old_ones, new_ones, dx=DIGIT_SIZE, dy=DIGIT_SIZE,
                                      refresh_fn=refresh, per_pixel_delay=minute_delay,
                                      thickness=thickness, instant_threshold=instant_threshold,
                                      bounds=(WIDTH, HEIGHT), inverted=DISPLAY_INVERTED)

                last_min = m
                
                # Check if hours drifted (unlikely, but keeps display strict)
                if h != last_hour:
                    draw_hours_only(h, DISPLAY_INVERTED)
                    last_hour = h

            # SSH invert trigger (manual file)
            if os.path.exists(TRIGGER_INVERT_FILE):
                # ... existing manual trigger logic ...
                current = capture_screen(panels)
                target = 1 - current
                coords = [(x, y) for y in range(HEIGHT) for x in range(WIDTH)]
                random.shuffle(coords)
                for x, y in coords:
                    panels.draw(x, y, int(target[y, x]))
                    refresh()
                    time.sleep(0.01)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
                try:
                    os.remove(TRIGGER_INVERT_FILE)
                except Exception:
                    pass

            time.sleep(0.1)

        except Exception:
            log.exception("Unhandled exception in main loop; sleeping briefly and continuing")
            time.sleep(1.0)

if __name__ == "__main__":
    main()
