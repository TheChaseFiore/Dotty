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
import global_var
#import gui


def main():
    global_var.init()
    print("Hello World!")
    print(serial_port.serial_ports())
    while True:
        serial_port.refresh(2)
    serial_port.refresh(2)

if __name__ == "__main__":
    main()