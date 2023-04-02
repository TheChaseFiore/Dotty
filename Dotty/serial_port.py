#!/usr/bin/env python3

import sys
import glob
import serial
import os, pty #delete

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
    master, slave = pty.openpty()
    s_name = os.ttyname(slave)
    rs232 = serial.Serial(s_name,57600)

    #rs232 = serial.Serial('COM2',57600)  # open serial port
    print(rs232.name)         # check which port was really used
    return rs232

def refresh(panels,flagged=True):
    if flagged == True:
        for panel in panels.panel:
            if panel.updateFlag:
                output = bytearray()
                output.append(128) #header
                output.append(131) #command
                output.extend(panel.address) #address
                output.extend(panel.rows) #data
                output.append(143) #end
                print(output)
                #rs232.write(output)
                panel.updateFlag=False
    else:
        for panel in panels.panel:
            output = bytearray()
            output.append(128) #header
            output.append(131) #command
            output.extend(panel.address) #address
            output.extend(panel.rows) #data
            output.append(143) #end
            print(output)
            #rs232.write(output)
            panel.updateFlag=False