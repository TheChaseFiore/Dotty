#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5

__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"


import serial_port
import matrix
import time, os
#import gui
from multiprocessing import Process



def main():

    panels.draw(1,5)
    refresh()
    panels.draw(19,28)
    refresh()
    print("refresh")
    panels.invert()
    refresh()

def refresh(flaggs=True):
    serial_port.refresh(panels,flaggs)

def getTime():
    clock = time.localtime()
    print(clock.tm_hour,":",clock.tm_min,":",clock.tm_sec," - ",clock.tm_zone)

def fps():
    while True:
        getTime()
        refresh(True)
        time.sleep(1/60) #0.016 == 1/60

if __name__ == "__main__":
    global rs232, panels, clock
    os.environ['TZ'] = 'America/New_York' # set new timezone
    time.tzset()
    clock = time.localtime()
    rs232 = serial_port.initiate_serial() #initiate serial com2
    panels = matrix.matrix(4) #make matrix with X panels

    p = Process(target=fps)
    p.start()

    p2 = Process(target=main)
    p2.start()