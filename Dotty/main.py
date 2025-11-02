#!/usr/bin/env python3

import os
import time
import random
from datetime import datetime

import numpy as np

import serial_port
import matrix

TRIGGER_FILE = "/tmp/dotty_top_of_hour"
SHOW_SECONDS_FILE = "/tmp/dotty_show_seconds"

WIDTH = 28
HEIGHT = 28
DIGIT_SIZE = 14
SNAKE_DELAY = 0.06        # default minute speed
SEC_SNAKE_DELAY = 0.02    # default second speed

SNAKE_DELAY_FILE = "/tmp/dotty_snake_delay"
SEC_SNAKE_DELAY_FILE = "/tmp/dotty_sec_snake_delay"

# hardware
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# toggled at top of hour
DISPLAY_INVERTED = False


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

# ------------------------------------------------------------
# digit helpers
# ------------------------------------------------------------
def make_digit_runs(mask):
    """
    Build runs, then order them so each new run tries to start from
    something we've already drawn.

    Rules:
      1. collect horizontals, then verticals (to keep shapes nice)
      2. pick a starting run = top-most, then left-most
      3. for each next run:
         - prefer a run that TOUCHES what we already drew
         - if it touches with its *last* point, reverse it
         - if nothing touches (rare), just take the next one
    This makes digits like 0, 4, 3 look hand-drawn (no parallel rails).
    """
    DIG = DIGIT_SIZE  # 14
    # 1) collect all runs (same as before)
    tmp_runs = []
    consumed = [[False] * DIG for _ in range(DIG)]

    # horizontals first
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

    # verticals for leftovers
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

    # little helper: does a point touch anything we've drawn?
    def touches_drawn(pt, drawn):
        x, y = pt
        # 4-neighbor + itself
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in drawn:
                return True
        return False

    # 2) pick starting run = earliest on screen (top-most, then left-most)
    start_idx = min(
        range(len(tmp_runs)),
        key=lambda i: (tmp_runs[i][0][1], tmp_runs[i][0][0])
    )
    ordered = [tmp_runs.pop(start_idx)]
    drawn = set(ordered[0])

    # 3) keep picking the next run that touches what we already drew
    while tmp_runs:
        picked_idx = None
        picked_run = None

        for i, run in enumerate(tmp_runs):
            first = run[0]
            last = run[-1]
            first_touches = touches_drawn(first, drawn)
            last_touches = touches_drawn(last, drawn)

            if first_touches or last_touches:
                # take this one
                picked_idx = i
                picked_run = run
                # if it connects at the *end*, reverse it so we draw from the connection
                if (not first_touches) and last_touches:
                    picked_run = list(reversed(picked_run))
                break

        if picked_idx is None:
            # no run touched — just pop one to avoid infinite loop
            picked_run = tmp_runs.pop(0)
        else:
            tmp_runs.pop(picked_idx)

        ordered.append(picked_run)
        drawn.update(picked_run)

    return ordered


def erase_digit_snake(dx, dy, old_mask, inverted, delay):
    bg = 0 if not inverted else 1
    runs = make_digit_runs(old_mask)
    for run in runs:
        for (lx, ly) in run:
            if old_mask[ly][lx] == 1:
                panels.draw(dx + lx, dy + ly, bg)
                refresh()
                time.sleep(delay)


def draw_digit_snake(dx, dy, new_mask, inverted, delay):
    fg = 1 if not inverted else 0
    runs = make_digit_runs(new_mask)
    for run in runs:
        for (lx, ly) in run:
            if new_mask[ly][lx] == 1:
                panels.draw(dx + lx, dy + ly, fg)
                refresh()
                time.sleep(delay)


# ------------------------------------------------------------
# animations
# ------------------------------------------------------------
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

    # hours
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


# ------------------------------------------------------------
# main loop
# ------------------------------------------------------------
def main():
    global DISPLAY_INVERTED

    last_min = -1
    last_hour = -1
    last_sec = -1
    prev_show_seconds = False

    # initial paint (hours + minutes)
    h, m, s = get_time()
    draw_hours_and_bottom(h, m, DISPLAY_INVERTED)

    while True:
        h, m, s = get_time()
        show_seconds = os.path.exists(SHOW_SECONDS_FILE)

        # allow live tuning over SSH
        minute_delay = read_delay(SNAKE_DELAY_FILE, SNAKE_DELAY)
        second_delay = read_delay(SEC_SNAKE_DELAY_FILE, SEC_SNAKE_DELAY)

        # 🧪 SECONDS MODE: bottom shows seconds instead of minutes
        if show_seconds:
            # first time we enter seconds mode, just paint it
            if not prev_show_seconds:
                draw_hours_and_bottom(h, s, DISPLAY_INVERTED)
                last_sec = s
                prev_show_seconds = True
                time.sleep(0.05)
                continue

            # seconds ticked → animate ONLY the changed bottom digit(s)
            if s != last_sec:
                old_s = last_sec
                old_tens = old_s // 10
                old_ones = old_s % 10
                new_tens = s // 10
                new_ones = s % 10

                # seconds tens (0,14)
                if new_tens != old_tens:
                    erase_digit_snake(0, 14, matrix.returnDigit(old_tens),
                                      DISPLAY_INVERTED, delay=second_delay)
                    draw_digit_snake(0, 14, matrix.returnDigit(new_tens),
                                     DISPLAY_INVERTED, delay=second_delay)

                # seconds ones (14,14)
                if new_ones != old_ones:
                    erase_digit_snake(14, 14, matrix.returnDigit(old_ones),
                                      DISPLAY_INVERTED, delay=second_delay)
                    draw_digit_snake(14, 14, matrix.returnDigit(new_ones),
                                     DISPLAY_INVERTED, delay=second_delay)

                last_sec = s

            time.sleep(0.05)
            continue

        else:
            # we were in seconds mode, now back to minutes
            if prev_show_seconds:
                draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
                prev_show_seconds = False
                last_sec = -1  # reset

        # -----------------------------
        # NORMAL MINUTE MODE
        # -----------------------------
        if m != last_min:
            old_m = last_min if last_min >= 0 else m
            old_tens = old_m // 10
            old_ones = old_m % 10
            new_tens = m // 10
            new_ones = m % 10

            # top of hour: invert whole display and flip mode
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
                                  DISPLAY_INVERTED, ddelay=minute_delay)
                draw_digit_snake(14, 14, matrix.returnDigit(new_ones),
                                 DISPLAY_INVERTED, delay=minute_delay)

            last_min = m

            # hour might have changed at 59→00 → refresh TOP ONLY
            if h != last_hour:
                draw_hours_only(h, DISPLAY_INVERTED)
                last_hour = h

        # SSH trigger: flip polarity now
        if os.path.exists(TRIGGER_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            # redraw current time in new polarity (minutes on bottom)
            draw_hours_and_bottom(h, m, DISPLAY_INVERTED)
            os.remove(TRIGGER_FILE)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
