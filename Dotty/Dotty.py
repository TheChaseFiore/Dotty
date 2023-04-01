#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5
#   numpy       1.24.2

__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"


import serial_port
import matrix
import globals
#import gui

globals.init()
rs232 = serial_port.initiate_serial() #initiate serial com2
panels = matrix.matrix(4) #make matrix with X panels

def main():
    print("Hello World!")
    print(serial_port.serial_ports())

    panels.draw(7,5)
    refresh()
    panels.draw(27,5)
    refresh()

def refresh(flaggs=True):
    serial_port.refresh(panels,flaggs)

if __name__ == "__main__":
    main()