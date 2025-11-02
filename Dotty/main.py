#!/usr/bin/env python3

import os
import time
import random
from datetime import datetime
from multiprocessing import Process

import numpy as np

import serial_port
import matrix

TRIGGER_FILE = "/tmp/dotty_top_of_hour"
WIDTH = 28
HEIGHT = 28

# hardware
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# this is the new hour-to-hour toggle
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
            # your matrix now has a working .get(x, y)
            buf[y, x] = panels_obj.get(x, y)
    return buf


def draw_buffer(panels_obj, buf, refresh_fn=None):
    h, w = buf.shape
    for y in range(h):
        for x in range(w):
            panels_obj.draw(x, y, int(buf[y, x]))
    if refresh_fn:
        refresh_fn()

def build_time_frame_raw(panels_obj, h, m, width=WIDTH, height=HEIGHT):
    """
    Draw the time, capture it, and return the buffer.
    This does NOT restore the old screen — it's the 'raw' version.
    """
    panels_obj.clear()
    panels_obj.time(h, m)
    refresh(False)
    buf = capture_screen(panels_obj, width, height)
    return buf
    
def transition_to_time_pixelwise(panels_obj, refresh_fn, h, m,
                                 inverted: bool,
                                 width=WIDTH, height=HEIGHT,
                                 per_pixel_delay=0.01,
                                 shuffle=True):
    """
    Transition from whatever is currently on screen to the time (h:m)
    one pixel at a time.
    If `inverted` is True, we invert the target frame before applying.
    """
    # 1) what we have right now
    current = capture_screen(panels_obj, width, height)

    # 2) what the time should look like (normal)
    target = build_time_frame_raw(panels_obj, h, m, width, height)

    # if we're in inverted mode for this hour, invert the target
    if inverted:
        target = 1 - target

    # 3) figure out which pixels need to change
    diffs = []
    for y in range(height):
        for x in range(width):
            if current[y, x] != target[y, x]:
                diffs.append((x, y))

    # optionally randomize order
    if shuffle:
        random.shuffle(diffs)

    # 4) walk them
    for (x, y) in diffs:
        panels_obj.draw(x, y, int(target[y, x]))
        refresh_fn()
        if per_pixel_delay > 0:
            time.sleep(per_pixel_delay)

def random_invert_animation(panels_obj, refresh_fn, delay=0.01,
                            width=WIDTH, height=HEIGHT):
    current = capture_screen(panels_obj, width, height)
    target = 1 - current  # invert everything

    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)

    for (x, y) in coords:
        panels_obj.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)


def draw_time_in_mode(h, m, inverted: bool):
    """
    Draws the time, but if inverted==True, we draw the inverted time buffer
    so the whole hour stays in that “polarity.”
    """
    # first, draw normal time into the panel buffer
    panels.clear()
    panels.time(h, m)

    if not inverted:
        # normal mode, we're done
        return

    # inverted mode: capture what we just drew, invert it, and write it back
    buf = capture_screen(panels, WIDTH, HEIGHT)
    inv = 1 - buf
    draw_buffer(panels, inv, None)


def fps():
    while True:
        get_time()
        refresh(True)
        time.sleep(1 / 60)


def main():
    global DISPLAY_INVERTED

    last_min = -1
    while True:
        h, m, s = get_time()

        # always draw clock in current mode
        draw_time_in_mode(h, m, DISPLAY_INVERTED)
        refresh()

        # run once per minute
        if m != last_min:
            if m == 0:
                # 1) fun animation
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                # 2) flip display mode so the next draws stay inverted
                DISPLAY_INVERTED = not DISPLAY_INVERTED

            last_min = m

        if os.path.exists(TRIGGER_FILE):
            random_invert_animation(...)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            transition_to_time_pixelwise(
                panels,
                refresh,
                h,
                m,
                inverted=DISPLAY_INVERTED,
                per_pixel_delay=0.005,
            )
            os.remove(TRIGGER_FILE)


        time.sleep(0.1)


if __name__ == "__main__":
    # p = Process(target=fps)
    # p.start()
    main()
