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
import random
#import gui
from multiprocessing import Process, Array

global rs232, panels, clock
panels = matrix.matrix(4)#make matrix with X panels
os.environ['TZ'] = 'America/New_York' # set new timezone
#time.tzset()
clock = time.localtime()
rs232 = serial_port.initiate_serial() #initiate serial com2

def main():
    color=1
    if color==0:
        refresh()
        for y in range(28):
            for x in range(28):
                refresh()
                panels.draw(x,y,color)
        if color == 1:
            color = 0
        else:
            color = 1
    while True:
        for ct in range(500):
            x = random.randint(0,27)
            y = random.randint(0,27)
            color = random.randint(0,1)
            panels.draw(x,y,color)
        refresh()

def refresh(flaggs=True):
    serial_port.refresh(panels,rs232,flaggs)

def getTime():
    clock = time.localtime()
    #print(clock.tm_hour,":",clock.tm_min,":",clock.tm_sec," - ",clock.tm_zone)

def fps():
    while True:
        getTime()
        refresh(True)
        time.sleep(1/60) #0.016 == 1/60

if __name__ == "__main__":

    

    p = Process(target=fps)
    #p.start()

    p2 = Process(target=main)
    #p2.start()
    main()