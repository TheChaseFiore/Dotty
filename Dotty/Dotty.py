#!/usr/bin/env python3
__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"

import serialCom

ser = serial.Serial('/dev/ttyUSB0')  # open serial port
print(ser.name)         # check which port was really used
ser.write(b'hello')     # write a string
ser.close()             # close port

def main():
    print("Hello World!")

if __name__ == "__main__":
    main()