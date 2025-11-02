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

# hardware
panels = matrix.matrix(4)
rs232 = serial_port.initiate_serial()

# toggle every hour
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


def build_time_frame(panels_obj, h, m, inverted, width=WIDTH, height=HEIGHT):
    """Return a 28x28 numpy array of what the time SHOULD look like."""
    panels_obj.clear()
    panels_obj.time(h, m)
    refresh(False)
    tgt = capture_screen(panels_obj, width, height)
    if inverted:
        tgt = 1 - tgt
    return tgt


def transition_frame_pixelwise(panels_obj, refresh_fn,
                               current_frame, target_frame,
                               per_pixel_delay=0.005,
                               shuffle=True):
    """ONLY change the pixels that are different."""
    height, width = current_frame.shape
    diffs = []
    for y in range(height):
        for x in range(width):
            if current_frame[y, x] != target_frame[y, x]:
                diffs.append((x, y))

    if shuffle:
        random.shuffle(diffs)

    for (x, y) in diffs:
        panels_obj.draw(x, y, int(target_frame[y, x]))
        refresh_fn()
        if per_pixel_delay > 0:
            time.sleep(per_pixel_delay)


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


def main():
    global DISPLAY_INVERTED

    last_min = -1
    # draw the very first time screen
    h, m, s = get_time()
    panels.clear()
    panels.time(h, m)
    refresh()
    # capture that as our starting frame
    prev_frame = capture_screen(panels)

    while True:
        h, m, s = get_time()

        # minute just changed
        if m != last_min:
            # top of hour: do the sparkle + flip polarity
            if m == 0:
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)
                DISPLAY_INVERTED = not DISPLAY_INVERTED
                # very important: after invert, THIS is our prev frame
                prev_frame = capture_screen(panels)

            # 1) build what the NEW time should look like (in correct polarity)
            target_frame = build_time_frame(panels, h, m, DISPLAY_INVERTED,
                                            width=WIDTH, height=HEIGHT)

            # 2) put the OLD frame back on screen, so we can animate from it
            draw_buffer(panels, prev_frame, refresh)

            # 3) animate ONLY the changed pixels
            transition_frame_pixelwise(
                panels,
                refresh,
                prev_frame,
                target_frame,
                per_pixel_delay=0.002,
                shuffle=True,
            )

            # 4) remember the new frame for next minute
            prev_frame = target_frame
            last_min = m

        # SSH trigger: do the hour thing right now
        if os.path.exists(TRIGGER_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            DISPLAY_INVERTED = not DISPLAY_INVERTED
            # after a manual invert, we want time in the new polarity too
            target_frame = build_time_frame(panels, h, m, DISPLAY_INVERTED,
                                            width=WIDTH, height=HEIGHT)
            draw_buffer(panels, prev_frame, refresh)
            transition_frame_pixelwise(
                panels,
                refresh,
                prev_frame,
                target_frame,
                per_pixel_delay=0.002,
                shuffle=True,
            )
            prev_frame = target_frame
            os.remove(TRIGGER_FILE)

        # small sleep, we don’t need sub-ms loop
        time.sleep(0.1)


if __name__ == "__main__":
    main()
