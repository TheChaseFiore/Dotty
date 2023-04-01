#!/usr/bin/env python3
import matrix
import serialCom

def init():
  global rs232, panels
  rs232 = serialCom.initiate_Serial() #initiate serial com2
  panels = matrix.matrix(4) #make matrix with X panels