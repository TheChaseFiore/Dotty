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
#import video
from datetime import datetime
import time
#import gui
from multiprocessing import Process, Array
#import cv2
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

        panels.time(h, m)

        # once per minute
        if lm != m:
            if m == 0:
                print("[dotty] top-of-hour animation")
                random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
            refresh()
            lm = m

        # TEST TRIGGER
        if os.path.exists(TRIGGER_FILE):
            print("[dotty] trigger file seen -> running animation")
            random_invert_animation(panels, refresh, delay=0.01, width=WIDTH, height=HEIGHT)
            os.remove(TRIGGER_FILE)
            print("[dotty] trigger file removed")

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

if __name__ == "__main__":

    

    p = Process(target=fps)
    #p.start()

    p2 = Process(target=main)
    #p2.start()
    main()
