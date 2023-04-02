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
#import gui



def main():
    global rs232, panels
    rs232 = serial_port.initiate_serial() #initiate serial com2
    panels = matrix.matrix(4) #make matrix with X panels



    panels.draw(1,5)
    refresh()
    panels.draw(19,28)
    refresh()
    print("refresh")
    panels.invert()
    refresh()

def refresh(flaggs=True):
    serial_port.refresh(panels,flaggs)

if __name__ == "__main__":
    main()