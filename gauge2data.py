#!/usr/bin/env python3
#-*- coding: utf-8 -*-

## Based on https://zulko.github.io/blog/2013/09/27/read-and-write-video-frames-in-python-using-ffmpeg/
## For example, this works:      ffmpeg -ss 00:00:05 -i test.3gp -ss 1 -f image2pipe -pix_fmt rgb24 -vcodec rawvideo - 

## Import common moduli
import matplotlib, sys, os, time
import matplotlib.pyplot as plt
import numpy as np
import subprocess as sp

from skimage.transform import (hough_line, hough_line_peaks, probabilistic_hough_line)
from skimage.feature import canny
from skimage import data

import argparse
parser = argparse.ArgumentParser(description='Convert a (timelapse) video of an analog gauge to a data series', allow_abbrev=True)
parser.add_argument('-input',         type=str,  help='input file name (may be any format accepted by ffmpeg)')
parser.add_argument('-output',         type=str,  help='output file name (stdout if left empty)')
parser.add_argument('-topcrop',     type=float, default=0.0, help='crop from top (from 0 to 1)')
parser.add_argument('-bottomcrop',  type=float, default=1.0, help='crop from bottom (from 0 to 1)')
parser.add_argument('-leftcrop',    type=float, default=0.0, help='crop from left (from 0 to 1)')
parser.add_argument('-rightcrop',   type=float, default=1.0, help='crop from right (from 0 to 1)')
parser.add_argument('-fps',         type=float, default=24, help='frames per second; use 24 for real-time video, and e.g. 0.1 for timelapse with 10 second period')
parser.add_argument('-decim',       type=int, default=2, help='decimate images for faster processing, set to 0 ')
parser.add_argument('-skipframes',     type=float, default=1, help='process every n-th frame only')
parser.add_argument('-BPP',        type=int, default=3, help='bytes per pixel')
parser.add_argument('-adjustthreshold',  type=float, default=1.2, help='adjusting the Otsu threshold of white background (Hough transform works the best with flat background)')
parser.add_argument('-hardthreshold',  type=float, default=-1, help='if set positive, defines a hard brightness value of  thresholding')
parser.add_argument('-visual',     type=float, default=0, help='shows the line-detection results on each processed frame')
parser.add_argument('-calibrate',     type=float, default=5, help='if nonzero, enables interactive calibration on the selected values; otherwise angles are output')

args = parser.parse_args()

os_ext = '' if os.name == 'posix' else '.exe' # on Linux, or Windows

input_file_name = args.input # 'test.3gp' if len(sys.argv)==1 else sys.argv[1]
bpp = 3   ## still, only the first (red?) channel will be used here
#visual = True

# You can get informations on a file (frames size, number of frames per second, etc.) by calling
ffoutput = sp.check_output(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'default=noprint_wrappers=1:nokey=1', 'test.3gp'])
xres, yres = [int(s) for s in ffoutput.split()]

# You can get informations on a file (frames size, number of frames per second, etc.) by calling
command = ['ffmpeg'+os_ext, '-ss', '00:00:00', '-i', input_file_name, '-f', 'image2pipe', '-pix_fmt', 'rgb24',
           '-vcodec','rawvideo', '-loglevel', 'error', '-']
ffoutput = sp.check_output(command)
raw_stream =  np.fromstring(ffoutput, dtype='uint8') # transform the byte read into a numpy array
framesize = xres*yres*bpp
framenumber = (len(raw_stream) / framesize)
#print("Data input contains %f frames" % framenumber )

def raw_frame_to_image(nframe, preprocess=True):
    ## process three-byte array to a monochrome image
    image = raw_stream[framesize*nframe:framesize*(nframe+1)].reshape(yres,xres,bpp)[:,:,1]   

    if preprocess:
        ## crop and decimate
        image = image[int(yres*args.topcrop):int(yres*args.bottomcrop):args.decim, int(xres*args.leftcrop):int(xres*args.rightcrop):args.decim] 

        ## thresholding is necessary for Hough to work
        if args.hardthreshold < 0:
            from skimage import filters                 ## automatic background removal using the Otsu thresholding
            val = filters.threshold_otsu(image)
            mask = image < (val*args.adjustthreshold)
            image = image*0
            image[mask] = 255
        else:
            image = 256-image                               ## take a negative
            image[image<((1-args.hardthreshold)*256)] = 0    ## optional thresholding with a set value 
    return image

times, angles = [], []
print("#time(s)\tangle")
for nframe in range(0, int(framenumber), int(args.skipframes)):

    # Find the longest line in probabilistic Hough - this is the gauge pointer!
    image = raw_frame_to_image(nframe)
    lines = probabilistic_hough_line(image, threshold=10, line_length=5, line_gap=3)
    maxlength=-1
    if args.visual:
        fig, ax1 = plt.subplots(1, 1, figsize=(6,4))
        ax1.imshow(image, cmap=plt.cm.gray)

    for line in lines:      
        p0, p1 = line
        try:
            length = ((p0[0] - p1[0])**2 + (p0[1] - p1[1])**2)**.5
            if length > maxlength:
                angle = np.arctan(-(p0[0] - p1[0]) / (p0[1] - p1[1]))
                length_angle_line = [length, angle, line]
                maxlength = length
        except ZeroDivisionError:
            pass

    length, angle, (p0, p1) = length_angle_line
    if args.visual:
        ax1.plot((p0[0], p1[0]), (p0[1], p1[1]), c='r')
        plt.show()
    times.append(nframe/args.fps)
    angles.append(angle/np.pi*180)

## Calibration routine
def closest_index(keyval, arr):
    return sorted([(np.abs(val-keyval), ind) for (ind,val) in enumerate(arr)])[0][1]
calibangles, calibvalues = [], []
if args.calibrate:
    for nstep, keyangle in enumerate(np.linspace(min(angles), max(angles), int(args.calibrate))):
        nframe = closest_index(keyangle, angles)
        print('(Calibration step %d of %d: frame %d with angle %f) Hit alt-F4 to close the plot window and remember the value on the gauge' % (nstep, args.calibrate, nframe, keyangle),)

        ## Visualise the image
        image = raw_frame_to_image(nframe*args.skipframes, preprocess=False)
        fig, ax1 = plt.subplots(1, 1, figsize=(6,4))
        ax1.imshow(image, cmap=plt.cm.gray)
        plt.show()
        try:
            calibvalues.append(float(input('What was the value on the gauge shown? ')))
            calibangles.append(keyangle)
        except ValueError:
            print("None or invalid value entered; calibration point not used")

print("Calibration table of angles to values:")
for ca, cv in zip(calibangles, calibvalues): print("\t%.06g\t%g\r" % (ca, cv))
outstr = ''
if len(calibangles) == 0:
    outstr += '#time(s)\tvalue\r'
    for time, angle in zip(times, angles):
        outstr += '%.06g\t%f\r' % (time, angle)
else:
    outstr += '#time(s)\tangle(deg)\r'
    interp_values = np.interp(angles, calibangles, calibvalues)
    for time, value in zip(times, interp_values):
        outstr += '%.06g\t%g\r' % (time, value)

if args.output:
    with open(args.output, 'w') as outfile:
        outfile.write(outstr)
else:
    print(outstr)




