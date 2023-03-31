#!/usr/bin/env python3

import sys
import glob
import serial
import global_var

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


def refresh(panel=255):
    output = bytearray()
    output.append(128) #header
    output.append(131) #command
    if panel != 255:
        output.extend(panels.panel[panel].address) #address
    else:
        output.append(255) #send data to all (blanking)
    output.extend(panels.panel[panel].rows) #data
    output.append(143) #end
    print(output)
    rs232.write(output)