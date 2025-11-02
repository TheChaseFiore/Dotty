#!/usr/bin/env python3
"""
Dotty main loop

Features:
- 28x28 layout → 4 digits:
    (0, 0)  -> hour tens
    (14, 0) -> hour ones
    (0, 14) -> minute/second tens
    (14,14) -> minute/second ones
- normal mode: bottom shows minutes
- test mode (touch /tmp/dotty_show_seconds): bottom shows seconds
- top-of-hour: random invert + toggle display polarity
- snake-style transitions for digits
- live SSH tuning of animation speeds
"""

import os
import time
import random
from datetime import datetime

import numpy as np

import serial_port
import matrix

# ---------------------------------------------------------------------
# PATH TRIGGERS
# ---------------------------------------------------------------------
TRIGGER_INVERT_FILE = "/tmp/dotty_top_of_hour"
SHOW_SECONDS_FILE = "/tmp/dotty_show_seconds"
FORCE_MINUTE_FILE = "/tmp/dotty_force_minute"

# live-tunable delays
SNAKE_DELAY_FILE = "/tmp/dotty_snake_delay"
SEC_SNAKE_DELAY_FILE = "/tmp/dotty_sec_snake_delay"

# ---------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------
WIDTH = 28
HEIGHT = 28
DIGIT_SIZE = 14

# baked-in defaults (can be overridden by files above)
SNAKE_DELAY_DEFAULT = 0.06      # minute animation speed
SEC_SNAKE_DELAY_DEFAULT = 0.02  # seconds animation speed

# ---------------------------------------------------------------------
# HARDWARE INIT
# ---------------------------------------------------------------------
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# this flips each time we reach minute == 0
DISPLAY_INVERTED = False


# ---------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------
def refresh(flaggs=True):
    """Push buffer to hardware."""
    serial_port.refresh(panels, rs232, flaggs)


def get_time():
    """Return (H, M, S) as ints."""
    now = datetime.now()
    return [
        int(now.strftime("%H")),
        int(now.strftime("%M")),
        int(now.strftime("%S")),
    ]


def capture_screen(panels_obj, width=WIDTH, height=HEIGHT):
    """Read current panel state into a numpy array (height x width)."""
    buf = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            buf[y, x] = panels_obj.get(x, y)
    return buf


def draw_buffer(panels_obj, buf, refresh_fn=None):
    """Write a numpy buffer back to the panel."""
    h, w = buf.shape
    for y in range(h):
        for x in range(w):
            panels_obj.draw(x, y, int(buf[y, x]))
    if refresh_fn:
        refresh_fn()


def read_delay(path, fallback):
    """Allow live SSH tuning: echo 0.2 > /tmp/dotty_snake_delay."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                val = f.read().strip()
            return float(val)
    except Exception:
        pass
    return fallback


# ---------------------------------------------------------------------
# DIGIT → RUNS (adjacency-driven so it looks hand-drawn)
# ---------------------------------------------------------------------
def make_digit_runs(mask):
    """
    Build runs (strokes) from a 14x14 digit, and then order them so that
    each new run tries to start from something we already drew.

    This prevents the two vertical rails of digits like 0 and 4 from
    appearing “in parallel”, and makes 3 draw from the right spine outward.
    """
    DIG = DIGIT_SIZE
    tmp_runs = []
    consumed = [[False] * DIG for _ in range(DIG)]

    # 1) collect horizontals, top → bottom
    for y in range(DIG):
        x = 0
        while x < DIG:
            if mask[y][x] == 1 and not consumed[y][x]:
                run = []
                while x < DIG and mask[y][x] == 1 and not consumed[y][x]:
                    consumed[y][x] = True
                    run.append((x, y))
                    x += 1
                tmp_runs.append(run)
            else:
                x += 1

    # 2) collect verticals, left → right (for leftover pixels)
    for x in range(DIG):
        y = 0
        while y < DIG:
            if mask[y][x] == 1 and not consumed[y][x]:
                run = []
                while y < DIG and mask[y][x] == 1 and not consumed[y][x]:
                    consumed[y][x] = True
                    run.append((x, y))
                    y += 1
                tmp_runs.append(run)
            else:
                y += 1

    if not tmp_runs:
        return []

    # helper: does this pixel touch anything we drew?
    def touches_drawn(pt, drawn):
        x, y = pt
        # self + 4-neighbors
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in drawn:
                return True
        return False

    # pick the earliest (top-most, then left-most) run as our starting run
    start_idx = min(
        range(len(tmp_runs)),
        key=lambda i: (tmp_runs[i][0][1], tmp_runs[i][0][0])
    )
    ordered = [tmp_runs.pop(start_idx)]
    drawn = set(ordered[0])

    # repeatedly pick the run that touches what we have
    while tmp_runs:
        picked_idx = None
        picked_run = None

        for i, run in enumerate(tmp_runs):
            first = run[0]
            last = run[-1]
            first_touches = touches_drawn(first, drawn)
            last_touches = touches_drawn(last, drawn)

            if first_touches or last_touches:
                picked_idx = i
                picked_run = run
                # if it connects at the *end*, reverse so we draw from the connection point
                if (not first_touches) and last_touches:
                    picked_run = list(reversed(picked_run))
                break

        if picked_idx is None:
            # nothing touched: just pop one to avoid infinite loop
            picked_run = tmp_runs.pop(0)
        else:
            tmp_runs.pop(picked_idx)

        ordered.append(picked_run)
        drawn.update(picked_run)

    return ordered


def erase_digit_snake(dx, dy, old_mask, inverted, delay):
    """Erase one digit (14x14) at (dx,dy) in a snakey, connected order."""
    bg = 0 if not inverted else 1
    runs = make_digit_runs(old_mask)
    for run in runs:
        for (lx, ly) in run:
            if old_mask[ly][lx] == 1:
                panels.draw(dx + lx, dy + ly, bg)
                refresh()
                time.sleep(delay)


def draw_digit_snake(dx, dy, new_mask, inverted, delay):
    """Draw one digit (14x14) at (dx,dy) in a snakey, connected order."""
    fg = 1 if not inverted else 0
    runs = make_digit_runs(new_mask)
    for run in runs:
        for (lx, ly) in run:
            if new_mask[ly][lx] == 1:
                panels.draw(dx + lx, dy + ly, fg)
                refresh()
                time.sleep(delay)


# ---------------------------------------------------------------------
# ANIMATIONS
# ---------------------------------------------------------------------
def random_invert_animation(panels_obj, refresh_fn,
                            delay=0.01, width=WIDTH, height=HEIGHT):
    """Invert every pixel in a random order."""
    current = capture_screen(panels_obj, width, height)
    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)
    for (x, y) in coords:
        panels_obj.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)


# ---------------------------------------------------------------------
# DRAWING CONVENIENCE
# ---------------------------------------------------------------------
def draw_hours_only(h, inverted):
    """Redraw just the top two digits (HH)."""
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
    """Draw 4 digits: HH on top, bottom_val on bottom."""
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

    # initial draw: HH:MM
    h, m, s = get_time()
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)

    while True:
        h, m, s = get_time()

        # allow live SSH speed tweaks
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)

        show_seconds = os.path.exists(SHOW_SECONDS_FILE)

        # ---------------------------------------------------------
        # SECONDS MODE: bottom shows seconds instead of minutes
        # ---------------------------------------------------------
        if show_seconds:
            if not prev_show_seconds:
                # first frame in seconds mode
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                last_sec = s
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            # seconds ticked → animate just the bottom digit(s)
            if s != last_sec:
                old_s = last_sec
                old_tens = old_s // 10
                old_ones = old_s % 10
                new_tens = s // 10
                new_ones = s % 10

                # seconds tens
                if new_tens != old_tens:
                    erase_digit_snake(0, 14, matrix.returnDigit(old_tens),
                                      DISPLAY_INVERTED, delay=second_delay)
                    draw_digit_snake(0, 14, matrix.returnDigit(new_tens),
                                     DISPLAY_INVERTED, delay=second_delay)

                # seconds ones
                if new_ones != old_ones:
                    erase_digit_snake(14, 14, matrix.returnDigit(old_ones),
                                      DISPLAY_INVERTED, delay=second_delay)
                    draw_digit_snake(14, 14, matrix.returnDigit(new_ones),
                                     DISPLAY_INVERTED, delay=second_delay)

                last_sec = s

            # still in seconds mode, but let SSH invert work
            if os.path.exists(TRIGGER_INVERT_FILE):
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                os.remove(TRIGGER_INVERT_FILE)

            time.sleep(0.05)
            continue

        # ---------------------------------------------------------
        # we were in seconds mode but not anymore → restore minutes
        # ---------------------------------------------------------
        if prev_show_seconds:
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            prev_show_seconds = False
            last_sec = -1  # reset

        # ---------------------------------------------------------
        # FORCE-MINUTE trigger: test snake without waiting a minute
        # ---------------------------------------------------------
        if os.path.exists(FORCE_MINUTE_FILE):
            tens = m // 10
            ones = m % 10
            erase_digit_snake(0, 14, matrix.returnDigit(tens),
                              DISPLAY_INVERTED, delay=minute_delay)
            draw_digit_snake(0, 14, matrix.returnDigit(tens),
                             DISPLAY_INVERTED, delay=minute_delay)

            erase_digit_snake(14, 14, matrix.returnDigit(ones),
                              DISPLAY_INVERTED, delay=minute_delay)
            draw_digit_snake(14, 14, matrix.returnDigit(ones),
                             DISPLAY_INVERTED, delay=minute_delay)

            os.remove(FORCE_MINUTE_FILE)

        # ---------------------------------------------------------
        # NORMAL MINUTE MODE
        # ---------------------------------------------------------
        if m != last_min:
            old_m = last_min if last_min >= 0 else m
            old_tens = old_m // 10
            old_ones = old_m % 10
            new_tens = m // 10
            new_ones = m % 10

            # top-of-hour: random invert + toggle mode
            if m == 0:
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED

            # minute tens (0,14)
            if new_tens != old_tens:
                erase_digit_snake(0, 14, matrix.returnDigit(old_tens),
                                  DISPLAY_INVERTED, delay=minute_delay)
                draw_digit_snake(0, 14, matrix.returnDigit(new_tens),
                                 DISPLAY_INVERTED, delay=minute_delay)

            # minute ones (14,14)
            if new_ones != old_ones:
                erase_digit_snake(14, 14, matrix.returnDigit(old_ones),
                                  DISPLAY_INVERTED, delay=minute_delay)
                draw_digit_snake(14, 14, matrix.returnDigit(new_ones),
                                 DISPLAY_INVERTED, delay=minute_delay)

            last_min = m

            # hour might have changed too → redraw top only
            if h != last_hour:
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

        # ---------------------------------------------------------
        # SSH INVERT TRIGGER (works in normal minute mode)
        # ---------------------------------------------------------
        if os.path.exists(TRIGGER_INVERT_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            os.remove(TRIGGER_INVERT_FILE)

        time.sleep(0.1)


# ---------------------------------------------------------------------
if __name__ == "__main__":
    main()
