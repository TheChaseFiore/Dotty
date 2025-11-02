#!/usr/bin/env python3
#   Package     Version
#   pyserial    3.5

__author__ = "Chase Fiore"
__copyright__ = "Copyright 2023, Chase Fiore"
__license__ = "GPL"
__version__ = "0.0"
__email__ = "chasefiore@gmail.com"
__status__ = "Production"


import serial_port, matrix
#import video
from datetime import datetime
import time
#import gui
from multiprocessing import Process, Array
#import cv2
import numpy as np
import random
import os


global rs232, panels
panels = matrix.matrix(4)#make matrix with X panels
rs232 = serial_port.initiate_serial() #initiate serial com2

def main():
    color=1
    if 1==2:
        refresh()
        for y in range(28):
            for x in range(28):
                refresh()
                panels.draw(x,y,color)
        if color == 1:
            color = 0
        else:
            color = 1

    if 1==2:
        for ct in range(500):
            x = random.randint(0,27)
            y = random.randint(0,27)
            color = random.randint(0,1)
            panels.draw(x,y,color)
        refresh()

    while 1==2:
        chat = input("Text")
        panels.clear()
        panels.drawTxt(chat , 14)
        refresh()
    lm=0
	while True:
	    clock = getTime()
	    h = clock[0]
	    m = clock[1]
	    panels.time(h, m)
	
	    # normal once-a-minute logic
	    if lm != m:
	        if m == 0:
	            random_invert_animation(panels, refresh, delay=0.01, width=28, height=28)
	        refresh()
	        lm = m
	
	    # 🔔 TEST TRIGGER: run animation if file exists
	    if os.path.exists(TRIGGER_FILE):
	        random_invert_animation(panels, refresh, delay=0.01, width=28, height=28)
	        # remove it so it only runs once
	        os.remove(TRIGGER_FILE)
	
	    time.sleep(0.1)


def refresh(flaggs=True):
    serial_port.refresh(panels,rs232,flaggs)

def getTime():
    clock = datetime.now()
    clock = [int(clock.strftime('%H')),int(clock.strftime('%M')),int(clock.strftime('%S'))]
    #print(clock[0],":",clock[1],":",clock[2])
    return clock

def fps():
    while True:
        getTime()
        refresh(True)
        time.sleep(1/60) #0.016 == 1/60

"""def runVideo():
		cap = cv2.VideoCapture('sample.mp4')
		while True:
		#while (self.cap.isOpened()):

			# Capture frame-by-frame
			ret, frame = cap.read()
			frame = cv2.resize(frame, (28, 28), fx =0, fy = 0,interpolation = cv2.INTER_CUBIC)

			# Display the resulting frame
			cv2.imshow('Frame', frame)

			# conversion of BGR to grayscale is necessary to apply this operation
			gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

			# adaptive thresholding to use different threshold
			# values on different regions of the frame.
			Thresh = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C,
												cv2.THRESH_BINARY_INV, 11, 2)
			panels.frame(Thresh)
			#self.updateFlag = True
			serial_port.refresh(panels,rs232,False)

			cv2.imshow('Thresh', Thresh)
			# define q as the exit button
			if cv2.waitKey(25) & 0xFF == ord('q'):
				break

		# release the video capture object
		self.cap.release()
		# Closes all the windows currently opened.
		cv2.destroyAllWindows()"""

def random_invert_animation(panels, refresh_fn, delay=0.01, width=28, height=28):
    # snapshot
    current = np.zeros((height, width), dtype=int)
    for y in range(height):
        for x in range(width):
            # if you added panels.get(x,y)
            current[y, x] = panels.get(x, y)

    target = 1 - current
    coords = [(x, y) for y in range(height) for x in range(width)]
    random.shuffle(coords)

    for (x, y) in coords:
        panels.draw(x, y, int(target[y, x]))
        refresh_fn()
        time.sleep(delay)

if __name__ == "__main__":

    

    p = Process(target=fps)
    #p.start()

    p2 = Process(target=main)
    #p2.start()
    main()
