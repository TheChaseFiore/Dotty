#!/usr/bin/env python3
"""
Dotty main loop (advanced diff transitions)

- 28x28 → 4 digits:
    (0, 0)  -> hour tens
    (14, 0) -> hour ones
    (0, 14) -> minute/second tens
    (14,14) -> minute/second ones

- Normal = bottom shows minutes
- /tmp/dotty_show_seconds = bottom shows seconds
- /tmp/dotty_top_of_hour = force invert + redraw
- /tmp/dotty_snake_delay = live minute speed
- /tmp/dotty_sec_snake_delay = live second speed
- /tmp/dotty_force_minute = test minute animation now

NEW:
- digit transitions only touch pixels that actually change
- erase phase and draw phase are separate
- each phase walks *connected components* → “one motion per shape”
"""

import os
import time
import random
from datetime import datetime

import numpy as np

import serial_port
import matrix

# ---------------------------------------------------------------------
# FILE TRIGGERS
# ---------------------------------------------------------------------
TRIGGER_INVERT_FILE = "/tmp/dotty_top_of_hour"
SHOW_SECONDS_FILE = "/tmp/dotty_show_seconds"
FORCE_MINUTE_FILE = "/tmp/dotty_force_minute"

SNAKE_DELAY_FILE = "/tmp/dotty_snake_delay"
SEC_SNAKE_DELAY_FILE = "/tmp/dotty_sec_snake_delay"

# ---------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------
WIDTH = 28
HEIGHT = 28
DIGIT_SIZE = 14

SNAKE_DELAY_DEFAULT = 0.06      # minute animation speed
SEC_SNAKE_DELAY_DEFAULT = 0.02  # seconds animation speed

# ---------------------------------------------------------------------
# HARDWARE
# ---------------------------------------------------------------------
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# top-of-hour toggle
DISPLAY_INVERTED = False


# ---------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# CONNECTED COMPONENTS FOR 14x14 MASKS
# ---------------------------------------------------------------------
def mask_connected_components(mask):
    """
    mask: 14x14 list-of-lists (0/1)
    return: list of components, each component is list[(x,y)]
    """
    visited = [[False] * DIGIT_SIZE for _ in range(DIGIT_SIZE)]
    comps = []

    for y in range(DIGIT_SIZE):
        for x in range(DIGIT_SIZE):
            if mask[y][x] == 1 and not visited[y][x]:
                # BFS/DFS
                stack = [(x, y)]
                visited[y][x] = True
                comp = [(x, y)]
                while stack:
                    cx, cy = stack.pop()
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < DIGIT_SIZE and 0 <= ny < DIGIT_SIZE:
                            if mask[ny][nx] == 1 and not visited[ny][nx]:
                                visited[ny][nx] = True
                                stack.append((nx, ny))
                                comp.append((nx, ny))
                comps.append(comp)

    return comps


def order_component_pixels(comp):
    """
    Make a reasonable, non-jumpy order for a single component.
    Easiest: sort top-to-bottom, then left-to-right.
    Since components are small, this looks like "one stroke".
    """
    return sorted(comp, key=lambda p: (p[1], p[0]))


# ---------------------------------------------------------------------
# ADVANCED DIFF-AWARE TRANSITION
# ---------------------------------------------------------------------
def advanced_digit_transition(dx, dy, old_mask, new_mask, inverted, delay):
    """
    Do a minimum-change transition from old_mask → new_mask.

    1. ERASE PHASE:
        build erase_mask = old=1 and new=0
        find connected components
        for each component: walk it in order, erase

    2. DRAW PHASE:
        build draw_mask = old=0 and new=1
        find connected components
        for each component: walk it in order, draw

    This gives the behavior you described:
    - 9→0  →  1 erase blob (right column + middle bar), then 1–2 draw blobs
    - 2→3  →  1 erase blob (left mid), 1 draw blob (right mid)
    - 4→5  →  1 erase blob (right rail), 2 draw blobs (top bar, bottom bar)
    """
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    # 1) build erase_mask and draw_mask
    erase_mask = [[0] * DIGIT_SIZE for _ in range(DIGIT_SIZE)]
    draw_mask = [[0] * DIGIT_SIZE for _ in range(DIGIT_SIZE)]

    for y in range(DIGIT_SIZE):
        for x in range(DIGIT_SIZE):
            o = old_mask[y][x]
            n = new_mask[y][x]
            if o == 1 and n == 0:
                erase_mask[y][x] = 1
            elif o == 0 and n == 1:
                draw_mask[y][x] = 1

    # 2) ERASE PHASE: one stroke per connected comp
    erase_comps = mask_connected_components(erase_mask)
    for comp in erase_comps:
        for (lx, ly) in order_component_pixels(comp):
            panels.draw(dx + lx, dy + ly, bg)
            refresh()
            time.sleep(delay)

    # 3) DRAW PHASE: one stroke per connected comp
    draw_comps = mask_connected_components(draw_mask)
    for comp in draw_comps:
        for (lx, ly) in order_component_pixels(comp):
            panels.draw(dx + lx, dy + ly, fg)
            refresh()
            time.sleep(delay)


# ---------------------------------------------------------------------
# OTHER ANIMATIONS
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# DRAWING
# ---------------------------------------------------------------------
def draw_hours_only(h, inverted):
    d1 = h // 10
    d2 = h % 10
    panels.frame(matrix.returnDigit(d1), 0, 0)
    panels.frame(matrix.returnDigit(d2), 14, 0)
    if inverted:
        for y in range(14):
            for x in range(28):
                val = panels.get(x, y)
                panels.draw(x, y, 1 - val)
    refresh()


def draw_hours_and_bottom(h, bottom_val, inverted):
    panels.clear()

    # hours (top)
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


# ---------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------
def main():
    global DISPLAY_INVERTED

    last_min = -1
    last_hour = -1
    last_sec = -1
    prev_show_seconds = False

    # initial draw
    h, m, s = get_time()
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)

    while True:
        h, m, s = get_time()
        show_seconds = os.path.exists(SHOW_SECONDS_FILE)

        # live SSH tuning
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)

        # =========================================================
        # SECONDS MODE (bottom shows seconds)
        # =========================================================
        if show_seconds:
            if not prev_show_seconds:
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                last_sec = s
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            if s != last_sec:
                old_s = last_sec
                old_tens = old_s // 10
                old_ones = old_s % 10
                new_tens = s // 10
                new_ones = s % 10

                # seconds tens
                if new_tens != old_tens:
                    advanced_digit_transition(
                        0, 14,
                        matrix.returnDigit(old_tens),
                        matrix.returnDigit(new_tens),
                        DISPLAY_INVERTED,
                        delay=second_delay,
                    )

                # seconds ones
                if new_ones != old_ones:
                    advanced_digit_transition(
                        14, 14,
                        matrix.returnDigit(old_ones),
                        matrix.returnDigit(new_ones),
                        DISPLAY_INVERTED,
                        delay=second_delay,
                    )

                last_sec = s

            # allow invert in seconds mode
            if os.path.exists(TRIGGER_INVERT_FILE):
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                os.remove(TRIGGER_INVERT_FILE)

            time.sleep(0.05)
            continue

        # leaving seconds mode → back to minutes
        if prev_show_seconds:
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            prev_show_seconds = False
            last_sec = -1

        # =========================================================
        # FORCE-MINUTE TEST (for SSH)
        # =========================================================
        if os.path.exists(FORCE_MINUTE_FILE):
            tens = m // 10
            ones = m % 10
            advanced_digit_transition(
                0, 14,
                matrix.returnDigit(tens),
                matrix.returnDigit(tens),
                DISPLAY_INVERTED,
                delay=minute_delay,
            )
            advanced_digit_transition(
                14, 14,
                matrix.returnDigit(ones),
                matrix.returnDigit(ones),
                DISPLAY_INVERTED,
                delay=minute_delay,
            )
            os.remove(FORCE_MINUTE_FILE)

        # =========================================================
        # NORMAL MINUTE MODE
        # =========================================================
        if m != last_min:
            old_m = last_min if last_min >= 0 else m
            old_tens = old_m // 10
            old_ones = old_m % 10
            new_tens = m // 10
            new_ones = m % 10

            # top-of-hour
            if m == 0:
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED

            # minute tens
            if new_tens != old_tens:
                advanced_digit_transition(
                    0, 14,
                    matrix.returnDigit(old_tens),
                    matrix.returnDigit(new_tens),
                    DISPLAY_INVERTED,
                    delay=minute_delay,
                )

            # minute ones
            if new_ones != old_ones:
                advanced_digit_transition(
                    14, 14,
                    matrix.returnDigit(old_ones),
                    matrix.returnDigit(new_ones),
                    DISPLAY_INVERTED,
                    delay=minute_delay,
                )

            last_min = m

            # hour may have changed too
            if h != last_hour:
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

        # =========================================================
        # SSH INVERT TRIGGER (normal mode)
        # =========================================================
        if os.path.exists(TRIGGER_INVERT_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            os.remove(TRIGGER_INVERT_FILE)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
