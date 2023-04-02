#!/usr/bin/env python3

global blp #byte look up
blu = [0,6,5,4,3,2,1]

class panel:
    def __init__(self,address):
        self.updateFlag = True
        if address >= 1:
            address += 1
        self.address = address.to_bytes(1,byteorder='big',signed=False)
        self.rows = bytearray(28)
    def len(self):
        return len(self.rows)

class matrix:
    def __init__(self,panelCt=4):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses
    def len(self):
        return len(self.panel)

    def invert(self):
        for panel in self.panel:
            for byte in panel.rows:
                byte = ~byte & 255 #invert all bits
                byte = set_bit_off(byte,7)
                panel.updateFlag = True

    def clear(self,color=1):
        pass

    def draw(self,x,y,color=1):
        y -= 1
        panelNum = x//8
        byteNum = blu[x%7]
        if color == 1:
            self.panel[panelNum].rows[y] = set_bit_on(self.panel[panelNum].rows[y],byteNum)
        else:
            self.panel[panelNum].rows[y] = set_bit_off(self.panel[panelNum].rows[y],byteNum)
        self.panel[panelNum].updateFlag = True

def set_bit_on(value, bit_index):
    return value | (1 << bit_index)

def set_bit_off(value, bit_index):
    return value & ~(1 << bit_index)
