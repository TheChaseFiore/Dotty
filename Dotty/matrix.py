#!/usr/bin/env python3

import numpy as np

class panel:
    def __init__(self,address):
        self.address = address.to_bytes(1,"big")
        self.dots = np.zeros( (28,7) ) #creat blank matrix


class matrix:
    def __init__(self,panelCt):
        self.panel = []
        for makePanel in range(panelCt):
            self.panel.append(panel(makePanel)) #create matrix of panels with assigned addresses
    pass

