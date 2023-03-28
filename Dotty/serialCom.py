#!/usr/bin/env python3

import serial



class initiateSerial(object):
    rs232 = serial.Serial('/dev/ttyUSB0')  # open serial port
    print(rs232.name)         # check which port was really used
    rs232.write(b'hello')     # write a string
    rs232.close()             # close port
    pass




