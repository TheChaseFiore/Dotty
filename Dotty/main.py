#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5

__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"


import serial_port, matrix
from datetime import datetime
import time
from multiprocessing import Process, Array
import numpy as np
import random
import os

TRIGGER_FILE = "/tmp/dotty_top_of_hour"
WIDTH = 28
HEIGHT = 28

global rs232, panels
panels = matrix.matrix(4)#make matrix with X panels
rs232 = serial_port.initiate_serial() #initiate serial com2
def getTime():
    now = datetime.now()
    return [int(now.strftime('%H')), int(now.strftime('%M')), int(now.strftime('%S'))]

def refresh(flaggs=True):
    serial_port.refresh(panels, rs232, flaggs)

def main():
    lm = 0

    while True:
        clock = getTime()
        h = clock[0]
        m = clock[1]

        # always show current time (steady state)
        panels.time(h, m)

        # once per minute logic
        if lm != m:
            if m == 0:
                # 1) random invert
                random_invert_animation(
                    panels,
                    refresh,
                    delay=0.01,
                    width=WIDTH,
                    height=HEIGHT,
                )
                # 2) matrix waterfall / rain
                matrix_rain_animation(
                    panels,
                    refresh,
                    width=WIDTH,
                    height=HEIGHT,
                    frames=70,
                    spawn_chance=0.28,
                    trail=4,
                    frame_delay=0.04,
                )
                # 3) go back to time
                show_time(panels, refresh, h, m)

            refresh()
            lm = m

        # 🔔 SSH test trigger
        if os.path.exists(TRIGGER_FILE):
            # same sequence, but manual
            random_invert_animation(panels, refresh, delay=0.01,
                                    width=WIDTH, height=HEIGHT)
            matrix_rain_animation(panels, refresh,
                                  width=WIDTH, height=HEIGHT,
                                  frames=70, spawn_chance=0.28,
                                  trail=4, frame_delay=0.04)
            show_time(panels, refresh, h, m)
            os.remove(TRIGGER_FILE)

        time.sleep(0.1)


def refresh(flaggs=True):
    serial_port.refresh(panels,rs232,flaggs)

def getTime():
    clock = datetime.now()
    clock = [int(clock.strftime('%H')),int(clock.strftime('%M')),int(clock.strftime('%S'))]
    #print(clock[0],":",clock[1],":",clock[2])
    return clock

def fps():
    while True:
        getTime()
        refresh(True)
        time.sleep(1/60) #0.016 == 1/60


def random_invert_animation(panels, refresh_fn, delay=0.01, width=28, height=28):
    # if your matrix has a .get(x, y), use it; otherwise fake it
    current = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            # if you have panels.get:
            # current[y, x] = panels.get(x, y)
            # fallback:
            current[y, x] = 0

    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)

    for (x, y) in coords:
        panels.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)

def matrix_rain_animation(panels, refresh_fn, width=28, height=28, frames=60,
                          spawn_chance=0.25, trail=4, frame_delay=0.05):
    """
    Simple matrix-style rain:
    - some columns spawn a drop at the top
    - every frame, drops move down
    - trail makes a fading tail
    """
    # each drop: {"x": int, "y": int}
    drops = []

    for _ in range(frames):
        # maybe spawn new drops
        for col in range(width):
            if random.random() < spawn_chance:
                drops.append({"x": col, "y": 0})

        # clear screen for this frame
        panels.clear()

        # update & draw drops
        new_drops = []
        for d in drops:
            x = d["x"]
            y = d["y"]

            # head of the drop
            panels.draw(x, y, 1)

            # draw trailing bits behind it
            for t in range(1, trail + 1):
                ty = y - t
                if 0 <= ty < height:
                    panels.draw(x, ty, 1)

            # move it down
            y += 1
            if y < height:
                d["y"] = y
                new_drops.append(d)
            # else: drop is off-screen, don't keep

        drops = new_drops

        refresh_fn()
        time.sleep(frame_delay)
        
def show_time(panels, refresh_fn, h, m):
    panels.clear()
    panels.time(h, m)
    refresh_fn()


if __name__ == "__main__":

    

    p = Process(target=fps)
    #p.start()

    p2 = Process(target=main)
    #p2.start()
    main()
