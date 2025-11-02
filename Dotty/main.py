#!/usr/bin/env python3

import os
import time
import random
from datetime import datetime

import numpy as np

import serial_port
import matrix

TRIGGER_FILE = "/tmp/dotty_top_of_hour"
WIDTH = 28
HEIGHT = 28
DIGIT_SIZE = 14
SNAKE_DELAY = 0.01   # 👈 speed knob for erase/draw

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


# ------------------------------------------------------------
# digit helpers
# ------------------------------------------------------------
def make_digit_runs(mask):
    """
    mask: 14x14 list-of-lists (0/1)
    return: list of runs, each run is a list of (x,y), longest first
    strategy:
      1. take horizontal lines first, marking pixels as consumed
      2. then vertical lines for any leftovers
      3. sort by length desc
    """
    consumed = [[False] * DIGIT_SIZE for _ in range(DIGIT_SIZE)]
    runs = []

    # 1) horizontal runs
    for y in range(DIGIT_SIZE):
        x = 0
        while x < DIGIT_SIZE:
            if mask[y][x] == 1 and not consumed[y][x]:
                start = x
                pixels = []
                while x < DIGIT_SIZE and mask[y][x] == 1 and not consumed[y][x]:
                    consumed[y][x] = True
                    pixels.append((x, y))
                    x += 1
                runs.append(pixels)
            else:
                x += 1

    # 2) vertical runs for leftovers
    for x in range(DIGIT_SIZE):
        y = 0
        while y < DIGIT_SIZE:
            if mask[y][x] == 1 and not consumed[y][x]:
                start = y
                pixels = []
                while y < DIGIT_SIZE and mask[y][x] == 1 and not consumed[y][x]:
                    consumed[y][x] = True
                    pixels.append((x, y))
                    y += 1
                runs.append(pixels)
            else:
                y += 1

    # 3) longest first
    runs.sort(key=len, reverse=True)
    return runs


def erase_digit_snake(dx, dy, old_mask, inverted, delay=SNAKE_DELAY):
    """
    dx,dy: top-left of the digit on the 28x28
    old_mask: 14x14 0/1 (digit we want to ERASE)
    inverted: if True, background is 0 and digit is 1->0 reversed
    """
    bg = 1 if not inverted else 0
    runs = make_digit_runs(old_mask)
    for run in runs:
        for (lx, ly) in run:
            panels.draw(dx + lx, dy + ly, bg)
            refresh()
            time.sleep(delay)


def draw_digit_snake(dx, dy, new_mask, inverted, delay=SNAKE_DELAY):
    """
    Draw digit one stroke at a time
    """
    fg = 0 if inverted else 1
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


# ------------------------------------------------------------
# main loop
# ------------------------------------------------------------
def main():
    global DISPLAY_INVERTED

    last_min = -1
    last_hour = -1

    # draw initial time
    h, m, s = get_time()
    panels.clear()
    panels.time(h, m)
    if DISPLAY_INVERTED:
        buf = capture_screen(panels)
        draw_buffer(panels, 1 - buf)
    refresh()

    while True:
        h, m, s = get_time()

        if m != last_min:
            # detect which minute digits changed
            old_m = last_min if last_min >= 0 else m
            old_tens = old_m // 10
            old_ones = old_m % 10

            new_tens = m // 10
            new_ones = m % 10

            # top of hour: do the invert and flip mode FIRST
            if m == 0:
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED

            # now animate minute digits that changed
            # bottom-left digit (minute tens) at (0,14)
            if new_tens != old_tens:
                old_mask = matrix.returnDigit(old_tens)
                new_mask = matrix.returnDigit(new_tens)
                # erase old
                erase_digit_snake(0, 14, old_mask, DISPLAY_INVERTED, delay=SNAKE_DELAY)
                # draw new
                draw_digit_snake(0, 14, new_mask, DISPLAY_INVERTED, delay=SNAKE_DELAY)

            # bottom-right digit (minute ones) at (14,14)
            if new_ones != old_ones:
                old_mask = matrix.returnDigit(old_ones)
                new_mask = matrix.returnDigit(new_ones)
                erase_digit_snake(14, 14, old_mask, DISPLAY_INVERTED, delay=SNAKE_DELAY)
                draw_digit_snake(14, 14, new_mask, DISPLAY_INVERTED, delay=SNAKE_DELAY)

            # update minute marker
            last_min = m

            # after animating, make sure the hours are right too
            # (hour might have changed at 59->00)
            if h != last_hour:
                # redraw hours in current polarity, but INSTANT (not animated)
                panels.clear()
                panels.time(h, m)
                if DISPLAY_INVERTED:
                    buf = capture_screen(panels)
                    draw_buffer(panels, 1 - buf)
                else:
                    refresh()
                last_hour = h

        # SSH trigger: flip polarity now
        if os.path.exists(TRIGGER_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            # redraw current time in new polarity
            panels.clear()
            panels.time(h, m)
            if DISPLAY_INVERTED:
                buf = capture_screen(panels)
                draw_buffer(panels, 1 - buf)
            else:
                refresh()
            os.remove(TRIGGER_FILE)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
