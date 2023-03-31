#!/usr/bin/env python3

import matrix
import serial
import os, pty #delete

def initiate_serial():
    master, slave = pty.openpty()
    s_name = os.ttyname(slave)
    rs232 = serial.Serial(s_name,57600)

    #rs232 = serial.Serial('COM2',57600)  # open serial port
    print(rs232.name)         # check which port was really used
    return rs232

def init():
  global rs232
  rs232 = initiate_serial()
  global panels
  panels = matrix.matrix(4)