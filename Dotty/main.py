#!/usr/bin/env python3
"""
Dotty main loop (advanced diff transitions + small-component coalescing)

- 28x28 → 4 digits (HH on top, MM or SS on bottom)
- /tmp/dotty_show_seconds → show seconds instead of minutes
- /tmp/dotty_top_of_hour → force invert
- /tmp/dotty_snake_delay → live minute speed
- /tmp/dotty_sec_snake_delay → live seconds speed
- /tmp/dotty_force_minute → force bottom animation now

Transitions:
- erase only what disappears
- draw only what appears
- do it per connected component (1 motion per shape)
- AND now: tiny/orphan components get merged into nearest bigger stroke
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

# how small is “too small” to be its own stroke?
MIN_COMPONENT_SIZE = 3

# ---------------------------------------------------------------------
# HARDWARE
# ---------------------------------------------------------------------
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

DISPLAY_INVERTED = False  # toggled at top-of-hour


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
# CONNECTED COMPONENTS (14x14)
# ---------------------------------------------------------------------
def mask_connected_components(mask):
    """
    mask: 14x14 (0/1)
    return: list[list[(x,y)]]
    """
    visited = [[False] * DIGIT_SIZE for _ in range(DIGIT_SIZE)]
    comps = []

    for y in range(DIGIT_SIZE):
        for x in range(DIGIT_SIZE):
            if mask[y][x] == 1 and not visited[y][x]:
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
    """Draw a single component in a stable, non-jumpy order."""
    return sorted(comp, key=lambda p: (p[1], p[0]))


def coalesce_small_components(comps, min_size=MIN_COMPONENT_SIZE):
    """
    If a component is too small (1–2 pixels), merge it into the nearest
    bigger component so we don't get orphan strokes.
    """
    if not comps:
        return []

    big = [c for c in comps if len(c) >= min_size]
    small = [c for c in comps if len(c) < min_size]

    # if everything is small, just make one component
    if not big:
        merged = []
        for c in comps:
            merged.extend(c)
        return [order_component_pixels(merged)]

    # merge each small into the closest big
    for s in small:
        best_idx = 0
        best_dist = 9999
        for i, b in enumerate(big):
            for (sx, sy) in s:
                for (bx, by) in b:
                    d = abs(sx - bx) + abs(sy - by)
                    if d < best_dist:
                        best_dist = d
                        best_idx = i
        big[best_idx].extend(s)

    # order each final component
    return [order_component_pixels(c) for c in big]


# ---------------------------------------------------------------------
# ADVANCED DIFF-AWARE TRANSITION (with coalescing)
# ---------------------------------------------------------------------
def advanced_digit_transition(dx, dy, old_mask, new_mask, inverted, delay):
    """
    Minimum-change transition:
      - erase phase: old=1,new=0 → connected components → coalesce small → draw
      - draw phase: old=0,new=1 → connected components → coalesce small → draw
    """
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0

    # build diff masks
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

    # ERASE PHASE
    erase_comps = mask_connected_components(erase_mask)
    erase_comps = coalesce_small_components(erase_comps, MIN_COMPONENT_SIZE)
    for comp in erase_comps:
        for (lx, ly) in comp:
            panels.draw(dx + lx, dy + ly, bg)
            refresh()
            time.sleep(delay)

    # DRAW PHASE
    draw_comps = mask_connected_components(draw_mask)
    draw_comps = coalesce_small_components(draw_comps, MIN_COMPONENT_SIZE)
    for comp in draw_comps:
        for (lx, ly) in comp:
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

        # live tunable speeds
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)

        # =========================================================
        # SECONDS MODE
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

            # allow invert in seconds
            if os.path.exists(TRIGGER_INVERT_FILE):
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                os.remove(TRIGGER_INVERT_FILE)

            time.sleep(0.05)
            continue

        # leaving seconds → restore minutes
        if prev_show_seconds:
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            prev_show_seconds = False
            last_sec = -1

        # =========================================================
        # FORCE-MINUTE TEST
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
