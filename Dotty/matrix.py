#!/usr/bin/env python3

class panel:
    def __init__(self,address):
        self.address = bytearray()
        if address >= 1:
            address += 1
        self.address.append(address)
        array = bytearray()
        for ct in range(28):
            array.extend(bx00)
        self.rows = array

class matrix:
    def __init__(self,panelCt):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses
