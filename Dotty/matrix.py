#!/usr/bin/env python3
import global_var

class panel:
    def __init__(self,address):
        self.address = bytearray()
        if address >= 1:
            address += 1
        self.address.append(address)
        array = bytearray()
        for ct in range(28):
            array.append(0)
        self.rows = array

class matrix:
    def __init__(self,panelCt=4):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses
