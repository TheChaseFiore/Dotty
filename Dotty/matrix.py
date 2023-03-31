#!/usr/bin/env python3

import global_var

class panel:
    def __init__(self,address):
        self.address = bytearray(address.to_bytes(1))
        array = bytearray()
        for ct in range(28):
            array.append(0)
        self.rows = array

class matrix:
    def __init__(self,panelCt):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses

