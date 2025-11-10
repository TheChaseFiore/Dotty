#!/usr/bin/env python3

import sys
import glob
import serial
import binascii

def serial_ports():
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

def initiate_serial():
    rs232 = serial.Serial('/dev/ttyS0',57600)  # open serial port
    print(rs232.name)         # check which port was really used
    return rs232

def refresh(panels,rs232,flagged=True):
    for panel in panels.panel:
        if panel.updateFlag or flagged == False:
            output = bytearray([128,131])
            output.extend(panel.address) #address
            output.extend(panel.rows) #data
            output.append(143) #end
            rs232.write(output)
            panel.updateFlag=False
