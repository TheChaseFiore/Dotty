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
#import GUI


def main():
    print("Hello World!")
    print(serialCom.serial_ports())
    rs232 = serialCom.initiate_Serial()
    panels = matrix.matrix(4)
    print(panels.panel[0].address)
    serialCom.refresh(panels, rs232, 0)

if __name__ == "__main__":
    main()