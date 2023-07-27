#!/bin/python3

import argparse
import serial
import time

parser = argparse.ArgumentParser(description="log serial data on disk while printing it to console in hexadecimal")
parser.add_argument("-f", "--file", help="name of file to store logged data into (if omitted, data is only echoed to console)", default="")
parser.add_argument("-l", "--recordlen", help="length in bytes of each printed line to console (doesn't affect data stored into file), default: 41", type=int, default=41)
parser.add_argument("-t", "--timeout", help="time in seconds to wait after data stream stops before ending datalogging, default: 30", type=float, default=30)
parser.add_argument("-p", "--port", help="serial port to log data from, default: /dev/ttyUSB0", default="/dev/ttyUSB0")
parser.add_argument("-b", "--baudrate", help="data rate in bits per second, default: 4800", type=int, default=4800)
args = parser.parse_args()

with serial.Serial(args.port, args.baudrate, timeout=2.0) as port:
    print(f"Reading from {args.port} @ {args.baudrate} bps.")
    if (args.file != ""):
        with open(args.file, "wb") as outFile:
            print(f"Writing to {args.file}.")
            bytecounter = 0
            timestamp = time.time()
            while (time.time() <= timestamp + args.timeout):
                dataBuffer = port.read(args.recordlen)
                if dataBuffer:
                    print(f"{bytecounter:8x}: " + dataBuffer.hex(" ", -2))
                    bytecounter += outFile.write(dataBuffer)
                    timestamp = time.time()
    else:
        bytecounter = 0
        timestamp = time.time()
        while (time.time() <= timestamp + args.timeout):
            dataBuffer = port.read(args.recordlen)
            if dataBuffer:
                print(f"{bytecounter:8x}: " + dataBuffer.hex(" ", -2))
                bytecounter += len(dataBuffer)
                timestamp = time.time()
