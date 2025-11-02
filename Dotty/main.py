#!/usr/bin/env python3
"""
Dotty main loop

- 28x28 → 4 digits (top = hours, bottom = minutes/seconds)
- /tmp/dotty_show_seconds → bottom shows seconds
- /tmp/dotty_top_of_hour → force invert + redraw
- /tmp/dotty_snake_delay → live minute speed
- /tmp/dotty_sec_snake_delay → live seconds speed
- /tmp/dotty_force_minute → test the minute animation right now
- minute/second transitions are now DIFF-AWARE (minimum pixels flipped)
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
# DIGIT → SNAKE RUNS (adjacency-driven)
# ---------------------------------------------------------------------
def make_digit_runs(mask):
    """
    Build runs from a 14x14 mask, but order them so each new run tries to
    start from something we already drew. Keeps 0/4 from drawing both rails
    in parallel and makes 3 draw from the spine outward.
    """
    DIG = DIGIT_SIZE
    tmp_runs = []
    consumed = [[False] * DIG for _ in range(DIG)]

    # 1) horizontals first (top → bottom)
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

    # 2) verticals for leftovers (left → right)
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

    # helper: does point touch anything we've already drawn?
    def touches_drawn(pt, drawn):
        x, y = pt
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in drawn:
                return True
        return False

    # start with earliest run on screen
    start_idx = min(
        range(len(tmp_runs)),
        key=lambda i: (tmp_runs[i][0][1], tmp_runs[i][0][0])
    )
    ordered = [tmp_runs.pop(start_idx)]
    drawn = set(ordered[0])

    # greedily add runs that touch what we've drawn
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
                # if it connects at the end, reverse so we draw from the connection
                if (not first_touches) and last_touches:
                    picked_run = list(reversed(picked_run))
                break

        if picked_idx is None:
            # nothing touched — just take the next one
            picked_run = tmp_runs.pop(0)
        else:
            tmp_runs.pop(picked_idx)

        ordered.append(picked_run)
        drawn.update(picked_run)

    return ordered


# ---------------------------------------------------------------------
# DIFF-AWARE SNAKE TRANSITION  👈 NEW SMART VERSION
# ---------------------------------------------------------------------
def snake_digit_transition(dx, dy, old_mask, new_mask, inverted, delay):
    """
    Smart, minimum-change snake:
      - walk a connected path built from (old OR new)
      - at each pixel:
          old=1, new=0 → erase
          old=0, new=1 → draw
          else → skip
    So we only flip the pixels that *actually* changed.
    """
    bg = 0 if not inverted else 1
    fg = 1 if not inverted else 0
    DIG = DIGIT_SIZE

    # union: places we might need to touch
    union_mask = [
        [
            1 if (old_mask[y][x] == 1 or new_mask[y][x] == 1) else 0
            for x in range(DIG)
        ]
        for y in range(DIG)
    ]

    runs = make_digit_runs(union_mask)

    for run in runs:
        for (lx, ly) in run:
            old_val = old_mask[ly][lx]
            new_val = new_mask[ly][lx]

            # no change needed
            if old_val == new_val:
                continue

            # change needed
            if new_val == 1:
                color = fg
            else:
                color = bg

            panels.draw(dx + lx, dy + ly, color)
            refresh()
            time.sleep(delay)


# ---------------------------------------------------------------------
# ANIMATIONS
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
# DRAWING CONVENIENCE
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

    # top
    d1 = h // 10
    d2 = h % 10
    panels.frame(matrix.returnDigit(d1), 0, 0)
    panels.frame(matrix.returnDigit(d2), 14, 0)

    # bottom
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

        # live tuning
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY_DEFAULT)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY_DEFAULT)

        # =========================================================
        # SECONDS MODE
        # =========================================================
        if show_seconds:
            if not prev_show_seconds:
                # first frame entering seconds mode
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
                    snake_digit_transition(
                        0, 14,
                        matrix.returnDigit(old_tens),
                        matrix.returnDigit(new_tens),
                        DISPLAY_INVERTED,
                        delay=second_delay,
                    )

                # seconds ones
                if new_ones != old_ones:
                    snake_digit_transition(
                        14, 14,
                        matrix.returnDigit(old_ones),
                        matrix.returnDigit(new_ones),
                        DISPLAY_INVERTED,
                        delay=second_delay,
                    )

                last_sec = s

            # allow invert even in seconds mode
            if os.path.exists(TRIGGER_INVERT_FILE):
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                os.remove(TRIGGER_INVERT_FILE)

            time.sleep(0.05)
            continue

        # leaving seconds mode → restore minutes
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
            snake_digit_transition(
                0, 14,
                matrix.returnDigit(tens),
                matrix.returnDigit(tens),
                DISPLAY_INVERTED,
                delay=minute_delay,
            )
            snake_digit_transition(
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
                snake_digit_transition(
                    0, 14,
                    matrix.returnDigit(old_tens),
                    matrix.returnDigit(new_tens),
                    DISPLAY_INVERTED,
                    delay=minute_delay,
                )

            # minute ones
            if new_ones != old_ones:
                snake_digit_transition(
                    14, 14,
                    matrix.returnDigit(old_ones),
                    matrix.returnDigit(new_ones),
                    DISPLAY_INVERTED,
                    delay=minute_delay,
                )

            last_min = m

            # hour might have changed too
            if h != last_hour:
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

        # =========================================================
        # SSH INVERT TRIGGER
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
