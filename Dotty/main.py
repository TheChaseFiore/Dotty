#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5

__author__ = "Chase Fiore"
__copyright__ = "Copyright 2025, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"

import os
import time
import random
from datetime import datetime
from multiprocessing import Process, Array

import numpy as np

import serial_port
import matrix

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TRIGGER_FILE = "/tmp/dotty_top_of_hour"
WIDTH = 28
HEIGHT = 28

# ---------------------------------------------------------------------------
# INIT DISPLAY
# ---------------------------------------------------------------------------
panels = matrix.matrix(4)              # make matrix with X panels
rs232 = serial_port.initiate_serial()  # initiate serial com2


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------
def refresh(flaggs: bool = True):
    """Send current panel buffer out the serial port."""
    serial_port.refresh(panels, rs232, flaggs)


def get_time():
    now = datetime.now()
    return [
        int(now.strftime("%H")),
        int(now.strftime("%M")),
        int(now.strftime("%S")),
    ]


def get_pixel(panels_obj, x, y):
    """Try to read a pixel from the matrix; fall back to 0 if not supported."""
    if hasattr(panels_obj, "get"):
        return panels_obj.get(x, y)
    # fallback: if matrix doesn't expose read, assume 0
    return 0


# ---------------------------------------------------------------------------
# SCREEN SNAPSHOT / DRAW HELPERS
# ---------------------------------------------------------------------------
def capture_screen(panels_obj, width=WIDTH, height=HEIGHT):
    buf = np.zeros((height, width), dtype=int)
    for yy in range(height):
        for xx in range(width):
            buf[yy, xx] = get_pixel(panels_obj, xx, yy)
    return buf


def draw_buffer(panels_obj, buf, refresh_fn=None):
    h, w = buf.shape
    for yy in range(h):
        for xx in range(w):
            panels_obj.draw(xx, yy, int(buf[yy, xx]))
    if refresh_fn:
        refresh_fn()


def build_time_frame(panels_obj, refresh_fn, h, m, width=WIDTH, height=HEIGHT):
    """
    Build what the time *should* look like, without permanently changing the display.
    """
    # 1. save current screen
    current = capture_screen(panels_obj, width, height)

    # 2. draw time
    panels_obj.clear()
    panels_obj.time(h, m)
    refresh_fn()

    # 3. capture as target
    target = capture_screen(panels_obj, width, height)

    # 4. restore original
    draw_buffer(panels_obj, current, refresh_fn)

    return target


# ---------------------------------------------------------------------------
# ANIMATIONS
# ---------------------------------------------------------------------------
def random_invert_animation(panels_obj, refresh_fn, delay=0.01,
                            width=WIDTH, height=HEIGHT):
    """
    Randomly flip pixels until the whole screen is inverted from its current state.
    """
    # capture current screen
    current = capture_screen(panels_obj, width, height)
    target = 1 - current  # invert

    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)

    for (x, y) in coords:
        panels_obj.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)


def matrix_rain_reveal(panels_obj, refresh_fn, target_frame,
                       width=WIDTH, height=HEIGHT,
                       frames=120, spawn_chance=0.25,
                       frame_delay=0.04):
    """
    Matrix/rain style animation that gradually turns the current screen
    into target_frame.
    """
    # start from whatever is on screen right now
    current_frame = capture_screen(panels_obj, width, height)

    # falling drops: list of {"x": int, "y": int}
    drops = []

    for _ in range(frames):
        # if we already match the target, we can stop early
        if np.array_equal(current_frame, target_frame):
            break

        # maybe spawn new drops at top
        for col in range(width):
            if random.random() < spawn_chance:
                drops.append({"x": col, "y": 0})

        # copy current frame to mutate
        new_frame = np.array(current_frame, copy=True)

        new_drops = []
        for d in drops:
            x = d["x"]
            y = d["y"]

            # when the drop passes over (x,y), "reveal" target there
            new_frame[y, x] = target_frame[y, x]

            # move drop down
            y += 1
            if y < height:
                d["y"] = y
                new_drops.append(d)
            # else: drop is off-screen

        drops = new_drops
        current_frame = new_frame

        # draw to hardware
        draw_buffer(panels_obj, current_frame, refresh_fn)
        time.sleep(frame_delay)

    # make sure we end exactly on target
    draw_buffer(panels_obj, target_frame, refresh_fn)


def show_time(panels_obj, refresh_fn, h, m):
    panels_obj.clear()
    panels_obj.time(h, m)
    refresh_fn()


# ---------------------------------------------------------------------------
# FPS PROCESS (your original)
# ---------------------------------------------------------------------------
def fps():
    while True:
        get_time()
        refresh(True)
        time.sleep(1 / 60)  # 60 Hz refresh


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
def main():
    last_min = 0

    while True:
        h, m, s = get_time()

        # normal steady state: show current time
        panels.time(h, m)

        # run once per minute
        if m != last_min:
            if m == 0:  # top of hour
                # 1) chaos
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)

                # 2) figure out what the time screen should look like
                target = build_time_frame(panels, refresh, h, m,
                                          width=WIDTH, height=HEIGHT)

                # 3) reveal the time through matrix rain
                matrix_rain_reveal(panels, refresh, target,
                                   width=WIDTH, height=HEIGHT,
                                   frames=140,
                                   spawn_chance=0.25,
                                   frame_delay=0.04)

            refresh()
            last_min = m

        # SSH trigger: same sequence
        if os.path.exists(TRIGGER_FILE):
            random_invert_animation(panels, refresh,
                                    delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            target = build_time_frame(panels, refresh, h, m,
                                      width=WIDTH, height=HEIGHT)
            matrix_rain_reveal(panels, refresh, target,
                               width=WIDTH, height=HEIGHT,
                               frames=140,
                               spawn_chance=0.25,
                               frame_delay=0.04)
            os.remove(TRIGGER_FILE)

        time.sleep(0.1)


# ---------------------------------------------------------------------------
# ENTRY
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # if you want the fps process, uncomment these:
    # p = Process(target=fps)
    # p.start()

    # p2 = Process(target=main)
    # p2.start()

    main()
