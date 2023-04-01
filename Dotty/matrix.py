#!/usr/bin/env python3
import globals

class panel:
    def __init__(self,address):
        self.address = bytearray()
        self.updateFlag = True
        if address >= 1:
            address += 1
        self.address.append(address)
        array = bytearray()
        for ct in range(28):
            array.append(0)
        self.rows = array
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
            for byte in range(28):
                panel.rows[byte] = ~panel.rows[byte] & 255 #invert all bits
                panel.rows[byte] = set_bit_off(panel.rows[byte],7)
                panel.updateFlag = True

    def clear(self,color=1):
        pass

    def draw(self,x,y,color=1):
        panelNum = int((x-1)/7)
        byteNum = 6-((x-1)%7)
        print(byteNum)
        if color == 1:
            self.panel[panelNum].rows[y-1] = set_bit_on(self.panel[panelNum].rows[y-1],byteNum)
        else:
            self.panel[panelNum].rows[y-1] = set_bit_off(self.panel[panelNum].rows[y-1],byteNum)
        self.panel[panelNum].updateFlag = True

def set_bit_on(value, bit_index):
    print(value | (1 << bit_index))
    return value | (1 << bit_index)

def set_bit_off(value, bit_index):
    return value & ~(1 << bit_index)
