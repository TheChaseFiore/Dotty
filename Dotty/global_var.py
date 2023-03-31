#!/usr/bin/env python3

import serial_port
import matrix

def init():
  global rs232
  rs232 = serial_port.initiate_serial()
  global panels
  panels = matrix.matrix(4)