#!/usr/bin/env python3

import txt_to_px

global blp #byte look up
blu = [6,5,4,3,2,1,0]
alu = [0,2,3,5]

class panel:
    def __init__(self,in_address):
        self.updateFlag = True
        address = alu[in_address]
        self.address = address.to_bytes(1,byteorder='big',signed=False)
        self.rows = bytearray(28)
    def len(self):
        return len(self.rows)

class matrix:
    def __init__(self,panelCt=4):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses
        return None
    def len(self):
        return len(self.panel)

    def invert(self):
        for panel in self.panel:
            for ct in range(28):
                panel.rows[ct] = ~panel.rows[ct] & 255 #invert all bits
                panel.rows[ct] = set_bit_off(panel.rows[ct],7)
                panel.updateFlag = True

    def clear(self,color=1):
        for panel in self.panel:
            panel.rows = bytearray(28)
            panel.updateFlag = True

    def draw(self,x,y,color=1):
        panelNum = x//7
        byteNum = blu[x % 7] #byte look up
        if color == 1:
            self.panel[panelNum].rows[y] = set_bit_on(self.panel[panelNum].rows[y],byteNum)
        else:
            self.panel[panelNum].rows[y] = set_bit_off(self.panel[panelNum].rows[y],byteNum)
        self.panel[panelNum].updateFlag = True

    def drawTxt(self,txt,size=14):
        array = txt_to_px.char_to_pixels(txt, path = 'arialbd.ttf', fontsize = size)
        for y in range(len(array)):
            for x in range(len(array[y])):
                self.draw(x,y,array[y][x])

def set_bit_on(value, bit_index):
    return value | (1 << bit_index)

def set_bit_off(value, bit_index):
    return value & ~(1 << bit_index)


