#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5
__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"

import serialCom
import matrix
import GUI


def main():
    print("Hello World!")
    print(serialCom.serial_ports())
    serialCom.initiate_Serial()

if __name__ == "__main__":
    main()