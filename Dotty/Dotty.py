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


import serialCom
import matrix
import Global
#import GUI


def main():
    print("Hello World!")
    print(serialCom.serial_ports())
    print(panels.panel[0].address)
    while True:
        serialCom.refresh(2)
    serialCom.refresh(2)

if __name__ == "__main__":
    main()