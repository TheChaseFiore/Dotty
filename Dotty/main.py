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
        h, m, s = clock

        # show time in normal running mode
        panels.time(h, m)

        if lm != m:
            if m == 0:
                # 1) do your random invert first (the "starting chaos")
                random_invert_animation(panels, refresh,
                                        delay=0.01,
                                        width=WIDTH, height=HEIGHT)

                # 2) build what the time SHOULD look like
                target = build_time_frame(panels, refresh, h, m,
                                          width=WIDTH, height=HEIGHT)

                # 3) matrix-style reveal FROM the current noisy screen TO the time
                matrix_rain_reveal(panels, refresh, target,
                                   width=WIDTH, height=HEIGHT,
                                   frames=140,
                                   spawn_chance=0.25,
                                   frame_delay=0.04)

            refresh()
            lm = m

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

def matrix_rain_reveal(panels, refresh_fn, target_frame,
                       width=WIDTH, height=HEIGHT,
                       frames=120, spawn_chance=0.25,
                       frame_delay=0.04):
    """
    Matrix/rain style animation that gradually turns the current screen
    into target_frame.
    """
    # start from whatever is on screen right now
    current_frame = capture_screen(panels, width, height)

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

        # we'll rebuild current_frame this step
        # start by copying current_frame so we can modify it
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
            # else: drop is off-screen → drop it

        drops = new_drops
        current_frame = new_frame

        # draw current_frame to the hardware
        draw_buffer(panels, current_frame, refresh_fn)

        time.sleep(frame_delay)

    # make sure we end exactly on target
    draw_buffer(panels, target_frame, refresh_fn)

        
def show_time(panels, refresh_fn, h, m):
    panels.clear()
    panels.time(h, m)
    refresh_fn()

def capture_screen(panels, width=WIDTH, height=HEIGHT):
    buf = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            buf[y, x] = panels.get(x, y)
    return buf
    
def draw_buffer(panels, buf, refresh_fn=None):
    h, w = buf.shape
    for y in range(h):
        for x in range(w):
            panels.draw(x, y, int(buf[y, x]))
    if refresh_fn:
        refresh_fn()
        
def build_time_frame(panels, refresh_fn, h, m, width=WIDTH, height=HEIGHT):
    # 1. save current screen
    current = capture_screen(panels, width, height)

    # 2. draw time
    panels.clear()
    panels.time(h, m)
    refresh_fn()

    # 3. capture time frame
    target = capture_screen(panels, width, height)

    # 4. restore what was on screen
    draw_buffer(panels, current, refresh_fn)

    return target



if __name__ == "__main__":

    

    p = Process(target=fps)
    #p.start()

    p2 = Process(target=main)
    #p2.start()
    main()
