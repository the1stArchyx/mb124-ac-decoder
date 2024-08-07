#!/bin/python3

# decoder.py - datastream decoder for Mercedes-Benz 124 A/C (SA 580) diagnostics

#    Copyright (C) 2023-2024  Lauri "Archyx" Lindholm

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

# ------------------------------------------------------------------------------

# TODO:

#   - Group user inputs together:
#     1) reheat/EC/recirculation mode statuses
#     2) temperature dial positions

#   - Group temperature inputs in air flow sequence:
#     1) exterior/air intake temperature
#     2) evaporator temperature
#     3) mixing chamber temperatures
#     4) interior temperature

#   - Group actuators controlled by, or controlling inputs near the
#     values. Includes the "switch-on countdown" and "self-cal" status.

import argparse
import curses
import io
import serial
import time


parser = argparse.ArgumentParser(description="program to decode Mercedes-Benz BR 124 basic air conditioning data stream")
parser.add_argument("-f", "--file", help="name of file read as data stream (when omitted, data is read from a serial line)", default="")
parser.add_argument("-i", "--interval", help="time interval in milliseconds between bytes when reading from a file, default: 32", type=int, default=32)
parser.add_argument("-p", "--port", help="serial port to read data from, default: /dev/ttyUSB0", default="/dev/ttyUSB0")
parser.add_argument("-b", "--baudrate", help="serial data rate in bits per second, default: 4800", type=int, default=4800)
args = parser.parse_args()

# sync bytes, defined as nested tuples -> any combination of known bytes can match
sync_bytes = ((b"\x00"),
              (b"\x03"),
              (b"\x04"),
              (b"\x01"),
              (b"\x23"),
              (b"\x02"),
              (b"\x3b", b"\x3c"))

# known sync byte strings:
# sync_bytes = (b"\x00", b"\x03", b"\x04", b"\x01", b"\x23", b"\x02", b"\x3b")
# sync_bytes = (b"\x00", b"\x03", b"\x04", b"\x01", b"\x23", b"\x02", b"\x3c")

statuses = dict(circmode=0, fastcool=False, middleventbypass=False, selfcal=False, tempmode=False, waterpump=False)

# List of cached bytes, each byte of a packet is copied to this list
# for caching. This enables experimental comparation of different
# values, eg. the difference of Adjustment Target and Temperature Dial
# to compare with Exterior Temperature Bias.
byte_cache = [b"\x00"] * 0x22

ticker_line = 1
ticker_col = 22

xLeftLabel = 0
xRightLabel = 52

### labels

# This may need further rebision. The concept is that the tuple called
# 'labels' is to be indexed with the ticker counter to get appropriate
# coordinated, labels, and everything for the data byte in question.

# The first element in every top-level tuple is a bit-mask integer. It
# is used to describe the existense of a label and other required
# information. This is to be expanded as needed.

# bit 0 = label — If this bit is set, the first nested tuple has a
#         label to be printed. This is used to set a single label for
#         value pairs where the other member of the pair has the label
#         for the line.

# bit 1 = bitmask — If this bit is set, the next nested tuple contains
#         tuples for labels for each bit.

# The label tuple has the following elements:

# 0) int - line coordinate

# 1) int - column coordinate for the label

# 2) str - label text

# 3) int - column coordinate for the value, relative to the label's
#          column coordinate, can be negative to print value to the
#          left of the label

labels = ((0b01, ( 1, xLeftLabel,  "Temp dial  . . . . :", 21)), # 0x00 - temperature setting dial, left
          (0b01, ( 9, xLeftLabel,  "Adjustment target  :", 21)), # 0x01 - temperature target, left
          (0b00, ( 1, xLeftLabel,  ""                    , 34)), # 0x02 - temperature setting dial, right
          (0b00, ( 9, xLeftLabel,  ""                    , 34)), # 0x03 - temperature target, right
          (0b01, (23, xRightLabel, "Self-cal. timer  . :", 21)), # 0x04 - self-calibration timer a.k.a. switch-on countdown, ~10 minutes
          (0b01, (18, xLeftLabel,  "Mixing chamber temp:", 22)), # 0x05 - mixing chamber temperature, left
          (0b00, (18, xLeftLabel,  ""                    , 35)), # 0x06 - mixing chamber temperature, right
          (0b01, ( 6, xLeftLabel,  "Interior air temp  :", 21)), # 0x07 - interior temperature, raw
          (0b01, (15, xRightLabel, "Exterior air temp  :", 21)), # 0x08 - exterior temperature (cabin air intake)
          (0b01, (11, xLeftLabel,  "Control (temp diff):", 21)), # 0x09 - temperature control, left
          (0b00, (11, xLeftLabel,  ""                    , 34)), # 0x0a - temperature control, right
          (0b01, (12, xLeftLabel,  "Ext. temp. bias  . :", 21)), # 0x0b - exterior/interior temperature control bias
          (0b01, (14, xLeftLabel,  "Heater drive . . . :", 21)), # 0x0c - heater drive, left
          (0b00, (14, xLeftLabel,  ""                    , 34)), # 0x0d - heater drive, right
          (0b01, (16, xLeftLabel,  "^^ slow (feedback) :", 21)), # 0x0e - reference for temperature sensor (feedback), left
          (0b00, (16, xLeftLabel,  ""                    , 34)), # 0x0f - reference for temperature sensor (feedback), right
          (0b01, (15, xLeftLabel,  "^^ fast  . . . . . :", 21)), # 0x10 - reference for valve drive, left
          (0b00, (15, xLeftLabel,  ""                    , 34)), # 0x11 - reference for valve drive, right
          (0b01, (20, xLeftLabel,  "Valve feedback ctrl:", 21)), # 0x12 - valve feedback control, left
          (0b00, (20, xLeftLabel,  ""                    , 34)), # 0x13 - valve feedback control, right
          (0b01, (21, xLeftLabel,  "Valve duty cycle . :", 21)), # 0x14 - valve drive duty cycle, left
          (0b00, (21, xLeftLabel,  ""                    , 34)), # 0x15 - valve drive duty cycle, right
          (0b01, (18, xRightLabel, "Engine coolant . . :", 21)), # 0x16 - engine coolant temperature
          (0b01, (16, xRightLabel, "Evaporator temp  . :", 21)), # 0x17 - evaporator temperature
          (0b01, (20, xRightLabel, "Overheat protection:", 21)), # 0x18 - overheat protection status
          (0b01, ( 7, xLeftLabel,  "Int.temp. (delayed):", 21)), # 0x19 - interior temperature, dampened
          (0b11, (( 2, xRightLabel, "Recirculation  . . :", 21), # 0x1a/0 - user input: manual forced recirculation
                  ( 1, xRightLabel, "Economy mode . . . :", 21), # 0x1a/1 - user input: economy = manual A/C off
                  ( 0, xRightLabel, "Reheat mode  . . . :", 21), # 0x1a/2 - user input: reheat = manual A/C on
                  ( 2, xLeftLabel,  ""                    , 21), # 0x1a/3 - user temperature adjustment, left
                  ( 3, xRightLabel, "Mode change, user  :", 21), # 0x1a/4 - this is occasionally briefly set when changing modes
                  ( 2, xLeftLabel,  ""                    , 34), # 0x1a/5 - user temperature adjustment, right
                  ( 5, xRightLabel, "Intense cooling  . :", 21), # 0x1a/6 - intense cooling mode
                  (25, xLeftLabel,  "0x1a / 7 . . . . . :", 21), # 0x1a/7
                  )
           ),
          (0b01, ( 8, xRightLabel, "Recirculation timer:       min.", 21)), # 0x1b - recirculation timer
          (0b11, ((12, xRightLabel, "Center vents heat  :", 21), # 0x1c/0 - center vents temp control: 0 = heating bypassed; 1 = heated
                  (19, xRightLabel, "Radiator blower II :", 21), # 0x1c/1 - radiator blower, second stage
                  ( 0, xRightLabel, ""                    , 21), # 0x1c/2 - 100% recirculation
                  ( 9, xRightLabel, "Recirculation mode :", 21), # 0x1c/3 -  80% recirculation
                  (13, xRightLabel, "A/C Compressor . . :", 21), # 0x1c/4 - A/C compressor request
                  (26, xLeftLabel,  "0x1c / 5 . . . . . :", 21), # 0x1c/5
                  (27, xLeftLabel,  "0x1c / 6 . . . . . :", 21), # 0x1c/6
                  (22, xLeftLabel,  "Water pump . . . . :", 31), # 0x1c/7 - water recirculation pump
                  )
           ),
          (0b11, (( 0, xLeftLabel,  ""                    , 21), # 0x1d/0 - max cooling, left
                  ( 0, xLeftLabel,  ""                    , 21), # 0x1d/1 - defrost, left
                  ( 0, xLeftLabel,  ""                    , 34), # 0x1d/2 - max cooling, right
                  ( 0, xLeftLabel,  ""                    , 34), # 0x1d/3 - defrost, right
                  (14, xRightLabel, "Exterior air . . . :", 21), # 0x1d/4 - exterior air (non-)freeze
                  (11, xRightLabel, "Temp control mode  :", 21), # 0x1d/5 - control mode: 0 = heating; 1 = cooling
                  (22, xRightLabel, "Self-calibration . :", 21), # 0x1d/6 - self-calibration
                  ( 6, xRightLabel, "^^ recirculation . :", 21), # 0x1d/7 - intense cooling mode auto-recirculation
                  )
           ),
          (0b01, ( 3, xLeftLabel,  "^^ dampened  . . . :", 21)), # 0x1e - temperature dial, left - dampened value
          (0b01, ( 4, xLeftLabel,  "adjustment timer . :", 21)), # 0x1f - temperature dial, left - adjustment timer
          (0b01, ( 3, xLeftLabel,  ""                    , 34)), # 0x20 - temperature dial, right - dampened value
          (0b01, ( 4, xLeftLabel,  ""                    , 34)), # 0x21 - temperature dial, right - adjustment timer
          )


def logtime():
    return time.strftime("%H:%M:%S : ")


def makePercent(byte) -> float:
    """This function returns a float between 0 and 100 from a byte
       value between 0x00 and 0xff.
    """
    return 100 * int.from_bytes(byte, byteorder="big") / 255


def getCol(ticker, bit=0):
    """This function returns the column number for a value from the
       label structure.
    """
    if labels[ticker][0] & 2:
        return labels[ticker][1][bit][1] + labels[ticker][1][bit][3]
    else:
        return labels[ticker][1][1] + labels[ticker][1][3]


def getLine(ticker, bit=0):
    """This function returns the line number for a value from the label
       structure.
    """
    if labels[ticker][0] & 2:
        return labels[ticker][1][bit][0]
    else:
        return labels[ticker][1][0]


def updateAdjTargetDeltas(outwin):
    leftDelta = int.from_bytes(byte_cache[1], byteorder="big", signed=True) - int.from_bytes(byte_cache[0], byteorder="big", signed=True)
    rightDelta = int.from_bytes(byte_cache[3], byteorder="big", signed=True) - int.from_bytes(byte_cache[2], byteorder="big", signed=True)
    outwin.addstr(getLine(1) + 1, getCol(1),
                  f"{leftDelta:+4d} {(leftDelta / 5):+5.1f}°  {rightDelta:+4d} {(rightDelta / 5):+5.1f}°", curses.color_pair(5))


def updateExtTempBiasDelta(outwin):
    extTempBiasDelta = int.from_bytes(byte_cache[0x08], byteorder="big", signed=True) - int.from_bytes(byte_cache[0xb], byteorder="big", signed=True)
    outwin.addstr(getLine(0xb) + 1, getCol(0xb), f"{extTempBiasDelta:4d} / {(50 - extTempBiasDelta):+4d}", curses.color_pair(5))


def printByte(outwin, msg_pad, byte, ticker):
    match ticker:
        case 0x00 | 0x02:  # temperature setting dial, left and right
            rawi = int.from_bytes(byte, byteorder="big", signed=True)
            if rawi < -33:
                colour = curses.color_pair(1)
            elif rawi > -1:
                colour = curses.color_pair(2)
            else:
                colour = curses.A_REVERSE
            actualf = (rawi + 126) / 5
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:4d} ")
            outwin.addstr(f"{actualf:5.1f}° ", colour)

        case 0x01 | 0x03:  # temperature adjustment target, left and right
            actualf = (int.from_bytes(byte, byteorder="big", signed=True) + 126) / 5
            outwin.addstr(getLine(ticker), getCol(ticker), f"{int.from_bytes(byte, byteorder='big', signed=True):4d} ")
            outwin.addstr(f"{actualf:5.1f}°")
#            updateAdjTargetDeltas(outwin)

        case 0x04: # self-calibration timer a.k.a. switch-on countdown
            rawi = int.from_bytes(byte, byteorder="big")
            seconds = (rawi % 12) * 5
            minutes = rawi // 12
            colour = 0
            if rawi:
                colour = curses.color_pair(3)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:4d} ", colour)
            if rawi:
                outwin.addstr(f"  {minutes:2d} min. {seconds:2d} s")
            else:
                outwin.addstr("               ")

        case 0x05 | 0x06:  # mixing chamber temperature, left and right
            rawi = int.from_bytes(byte, byteorder="big")
            tempf = (rawi + 48) / 4
            colour = 0
            if not rawi:
                colour = curses.color_pair(1)
            elif rawi > 242:
                colour = curses.color_pair(2)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:3d} ")
            outwin.addstr(f"{tempf:6.2f}° ", colour)

        case 0x07 | 0x19: # interior temperature, raw and dampened/delayed
            rawi = int.from_bytes(byte, byteorder="big", signed=True)
            tempf = (rawi + 126) / 5
            colour = 0
            if (rawi < -127) or (rawi > 125):
                colour = curses.color_pair(3)
            elif (rawi < -56):
                colour = curses.color_pair(1)
            elif (rawi > 24):
                colour = curses.color_pair(2)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:4d} = ")
            outwin.addstr(f"{tempf:5.1f} °C ", colour)

        case 0x08: # exterior temperature
            rawi = int.from_bytes(byte, byteorder="big", signed=True)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{(rawi / 2):6.1f} °C  ({rawi:4d})")

        case 0x09 | 0x0a:  # temperature control, left and right
            signed = int.from_bytes(byte, byteorder="big", signed=True)
            if (signed < -50):
                colour = curses.color_pair(2)
            elif (signed > 23):
                colour = curses.color_pair(1)
            elif (signed < -7):
                colour = curses.color_pair(7) + curses.A_BOLD
            elif (signed > 3):
                colour = curses.color_pair(6) + curses.A_BOLD
            else:
                colour = 0
            outwin.addstr(getLine(ticker),  getCol(ticker), f"{signed:+4d} ", colour)
            outwin.addstr(f"{(signed / 5):+5.1f}°")

        case 0x0b: # exterior temperature bias
            rawi = int.from_bytes(byte, byteorder="big", signed=True)
            if (rawi < -15):
                colour = curses.color_pair(2)
            elif (rawi > -14):
                colour = curses.color_pair(1)
            else:
                colour = curses.color_pair(4)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:+4d} = ")
            outwin.addstr(f"{(-1 * (((rawi + 1) // 2) + 7) / 5):+5.1f} °C ", colour)
            outwin.addstr(f"{(rawi / 5):+5.1f} °C")
#            updateExtTempBiasDelta(outwin)

        case 0x0c | 0x0d:  # heater drive, left and right
            if (byte[0] < 80):
                colour = curses.color_pair(1)
            elif (byte[0] > 80):
                colour = curses.color_pair(2)
            else:
                colour = curses.color_pair(4)
            outwin.addstr(getLine(ticker),  getCol(ticker), f" {byte[0]:3d} ", colour)
            outwin.addstr(f"{(byte[0] - 80):4d}")

        case 0x0e | 0x0f:  # mixing chamber temperature reference, left and right
            outwin.addstr(getLine(ticker), getCol(ticker), f" {byte[0]:3d} {(byte[0] / 4 + 10):6.2f}°")

        case 0x10 | 0x11:  # valve drive reference, left and right
            outwin.addstr(getLine(ticker), getCol(ticker), f" {byte[0]:3d} {(byte[0] - 80):4d}")

        case 0x12 | 0x13:  # valve control bias (feedback), left and right
            signed = int.from_bytes(byte, byteorder="big", signed=True)
            if (signed < 0):
                colour = curses.color_pair(2)
            elif (signed > 0):
                colour = curses.color_pair(1)
            else:
                colour = curses.color_pair(4)
            outwin.addstr(getLine(ticker), getCol(ticker) + 2, f"{signed:+5d} ", colour)

        case 0x14 | 0x15:  # valve drive duty cycle, left and right
            colour = 0
            if byte == b"\x00":
                colour = curses.color_pair(1)
            elif byte == b"\xff":
                colour = curses.color_pair(2)
            outwin.addstr(getLine(ticker),  getCol(ticker), f"{int.from_bytes(byte, byteorder='big'):4d} {makePercent(byte):5.1f}% ", colour)

        case 0x16: # coolant temperature
            rawi = int.from_bytes(byte, byteorder="big", signed=False)
            colour = 0
            if rawi < 6:
                colour = curses.color_pair(1)
            elif rawi > 107:
                colour = curses.color_pair(2)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:4d} ", colour)
            outwin.addstr(f"  °C")

        case 0x17: # evaporator temperature
            rawi = int.from_bytes(byte, byteorder="big", signed=True)
            tempf = rawi / 2
            colour = 0
            if not tempf:
                colour = curses.color_pair(1)
            elif rawi > 125:
                colour = curses.color_pair(2)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{tempf:6.1f} ", colour)
            outwin.addstr(f"°C  ({rawi:4d})")

        case 0x18: # overheat protection status
            st = int.from_bytes(byte, byteorder="big")
            colour = 0
            st_count = 0x3f & st
            if st:
                colour = curses.color_pair(3)
                if st_count > 19:
                    colour = curses.color_pair(2)
            if st & 0x80:
                st_mode = "Stage 2"
            elif st & 0x40:
                st_mode = "Stage 1"
            else:
                st_mode = "off    "
            outwin.addstr(getLine(ticker), getCol(ticker), f"{st_count:4d} ", colour)
            outwin.addstr(f" ({st_mode})")

        case 0x1a:  # user input
            bits = int.from_bytes(byte, byteorder="big")
            if (bits & 0x01):   # bit 0 - recirculation (user)
                outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), "  on ", curses.color_pair(3))
            else:
                outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), " off ")

            if (bits & 0x02):   # bit 1 - economy mode (user)
                outwin.addstr(getLine(ticker, 1), getCol(ticker, 1), "  on ", curses.color_pair(4))
            else:
                outwin.addstr(getLine(ticker, 1), getCol(ticker, 1), " off ")

            if (bits & 0x04):   # bit 2 - reheat mode (user)
                outwin.addstr(getLine(ticker, 2), getCol(ticker, 2), "  on ", curses.color_pair(1))
            else:
                outwin.addstr(getLine(ticker, 2), getCol(ticker, 2), " off ")

            if (bits & 0x08):   # bit 3
                status = "Adjusting"
            else:
                status = "         "
            outwin.addstr(getLine(ticker, 3), getCol(ticker, 3), status)

            if (bits & 0x10):   # bit 4 - mode change, user
                colour = curses.color_pair(3)
                status = "  on "
            else:
                colour = 0
                status = " off "
            outwin.addstr(getLine(ticker, 4), getCol(ticker, 4), status, colour)

            if (bits & 0x20):   # bit 5
                status = "Adjusting"
            else:
                status = "         "
            outwin.addstr(getLine(ticker, 5), getCol(ticker, 5), status)

            if (bits & 0x40):   # bit 6 - intense cooling
                outwin.addstr(getLine(ticker, 6), getCol(ticker, 6), " off ")
                if statuses["fastcool"]:
                    statuses["fastcool"] = False
                    msg_pad.addstr(logtime() + "Intense cooling mode off.\n")
            else:
                outwin.addstr(getLine(ticker, 6), getCol(ticker, 6), "  on ", curses.color_pair(1))
                if not statuses["fastcool"]:
                    statuses["fastcool"] = True
                    msg_pad.addstr(logtime() + "Intense cooling mode on.\n")

            if (bits & 0x80):   # bit 7
                status = "1 /  set"
            else:
                status = "0 / unset"
            outwin.addstr(getLine(ticker, 7), getCol(ticker, 7), status)

        case 0x1b: # recirculation timer
            rawi = int.from_bytes(byte, byteorder="big")
            colour = 0
            if rawi:
                colour = curses.color_pair(4)
            outwin.addstr(getLine(ticker), getCol(ticker), f"{rawi:4d} ", colour)

        case 0x1c:  # actuator control
            bits = int.from_bytes(byte, byteorder="big")
            if (bits & 0x01):   # bit 0
                colour = 0
                status = "controlled"
                if statuses["middleventbypass"]:
                    statuses["middleventbypass"] = False
                    msg_pad.addstr(logtime() + "Center vents temperature-controlled.\n")
            else:
                colour = curses.color_pair(1)
                status = " bypassed "
                if not statuses["middleventbypass"]:
                    statuses["middleventbypass"] = True
                    msg_pad.addstr(logtime() + "Center vents heating bypassed.\n")
            outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), status, colour)

            if (bits & 0x02):   # bit 1 - radiator blower stage II
                outwin.addstr(getLine(ticker, 1), getCol(ticker, 1), "  on ", curses.color_pair(2))
            else:
                outwin.addstr(getLine(ticker, 1), getCol(ticker, 1), " off ")

            if (bits & 0x04):   # bit 2 - recirculation, full
                outwin.addstr(getLine(ticker, 3), getCol(ticker, 3), " 100% ", curses.color_pair(3))
                if statuses["circmode"] != 2:
                    statuses["circmode"] = 2
                    msg_pad.addstr(logtime() + "Air recirculation 100%.\n")
            elif (bits & 0x08): # bit 3 - recirculation, partial
                outwin.addstr(getLine(ticker, 3), getCol(ticker, 3), "  80% ", curses.color_pair(3))
                if statuses["circmode"] != 1:
                    statuses["circmode"] = 1
                    msg_pad.addstr(logtime() + "Air recirculation 80%.\n")
            else:
                outwin.addstr(getLine(ticker, 3), getCol(ticker, 3), " off  ")
                if statuses["circmode"]:
                    statuses["circmode"] = 0
                    msg_pad.addstr(logtime() + "Air recirculation off.\n")

            if (bits & 0x10):   # bit 4 - compressor enable
                outwin.addstr(getLine(ticker, 4), getCol(ticker, 4), "  on ", curses.color_pair(1))
            else:
                outwin.addstr(getLine(ticker, 4), getCol(ticker, 4), " off ")

            if (bits & 0x20):   # bit 5
                status = "1 /   set"
            else:
                status = "0 / unset"
            outwin.addstr(getLine(ticker, 5), getCol(ticker, 5), status)

            if (bits & 0x40):   # bit 6
                status = "1 /   set"
            else:
                status = "0 / unset"
            outwin.addstr(getLine(ticker, 6), getCol(ticker, 6), status)

            if (bits & 0x80):   # bit 7 - water pump
                outwin.addstr(getLine(ticker, 7), getCol(ticker, 7), " on ", curses.color_pair(2))
                if not statuses["waterpump"]:
                    statuses["waterpump"] = True
                    msg_pad.addstr(logtime() + "Water circulation pump on.\n")
            else:
                outwin.addstr(getLine(ticker, 7), getCol(ticker, 7), "off ")
                if statuses["waterpump"]:
                    statuses["waterpump"] = False
                    msg_pad.addstr(logtime() + "Water circulation pump off.\n")

        case 0x1d:  # temperature control
            bits = int.from_bytes(byte, byteorder="big")
            if (bits & 0x01):   # bit 0
                outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), " Max cold ", curses.color_pair(1))
            elif (bits & 0x02): # bit 1
                outwin.addstr(getLine(ticker, 1), getCol(ticker, 1), " Defrost  ", curses.color_pair(2))
            elif (bits & 0x03): # bits 0 and 1 should never be set at the same time!
                outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), "( ?????? )")
            else:
                outwin.addstr(getLine(ticker, 0), getCol(ticker, 0), "Controlled")

            if (bits & 0x04):   # bit 2
                outwin.addstr(getLine(ticker, 2), getCol(ticker, 2), " Max cold ", curses.color_pair(1))
            elif (bits & 0x08): # bit 3
                outwin.addstr(getLine(ticker, 3), getCol(ticker, 3), " Defrost  ", curses.color_pair(2))
            elif (bits & 0x0c): # bits 2 and 3 should never be set at the same time!
                outwin.addstr(getLine(ticker, 2), getCol(ticker, 2), "( ?????? )")
            else:
                outwin.addstr(getLine(ticker, 2), getCol(ticker, 2), "Controlled")

            if (bits & 0x10):   # bit 4
                status = "non-freezing"
            else:
                status = "freezing    "
            outwin.addstr(getLine(ticker, 4), getCol(ticker, 4), status)

            if (bits & 0x20):   # bit 5 - temperature control mode
                colour = curses.color_pair(1)
                status = " cooling "
                if not statuses["tempmode"]:
                    statuses["tempmode"] = True
                    msg_pad.addstr(logtime() + "Temperature control mode: cooling.\n")
            else:
                colour = curses.color_pair(2)
                status = " heating "
                if statuses["tempmode"]:
                    statuses["tempmode"] = False
                    msg_pad.addstr(logtime() + "Temperature control mode: heating.\n")
            outwin.addstr(getLine(ticker, 5), getCol(ticker, 5), status, colour)

            if (bits & 0x40):   # bit 6 - self-calibration
                outwin.addstr(getLine(ticker, 6), getCol(ticker, 6), "  on ", curses.color_pair(3))
                if not statuses["selfcal"]:
                    statuses["selfcal"] = True
                    msg_pad.addstr(logtime() + "Self-calibration on.\n")
            else:
                outwin.addstr(getLine(ticker, 6), getCol(ticker, 6), " off ")
                if statuses["selfcal"]:
                    statuses["selfcal"] = False
                    msg_pad.addstr(logtime() + "Self-calibration off.\n")


            if (bits & 0x80):   # bit 7 - intense cooling recirculation
                status = " enabled"
            else:
                status = " off    "
            outwin.addstr(getLine(ticker, 7), getCol(ticker, 7), status)

        case 0x1e | 0x20:  # temperature dial value, dampened, left and right
            actualf = (int.from_bytes(byte, byteorder="big", signed=True) + 126) / 5
            outwin.addstr(getLine(ticker), getCol(ticker), f"{int.from_bytes(byte, byteorder='big', signed=True):4d} ")
            outwin.addstr(f"{actualf:5.1f}°")

        case 0x1f | 0x21:  # adjustment interval, left and right
            if byte[0]:
                colour = curses.color_pair(3)
                timerstring = f"{int.from_bytes(byte, byteorder='big'):4d} s. "
            else:
                colour = 0
                timerstring = " (off)  "
            outwin.addstr(getLine(ticker), getCol(ticker), timerstring, colour)


def readByte (bytesrc, stdscr):
    if (args.file != ""):
        stdscr.addstr(1, 68, f"pos: {bytesrc.tell():8d}")
        time.sleep(args.interval / 1000)
    byte = bytesrc.read(1)
    if (byte == b""):
        if args.file != "":
            stdscr.addstr(1, 2, "EOF. r to restart.")
            stdscr.refresh()
            while True:
                inputKey = stdscr.getch()
                if inputKey == ord('r'):
                    bytesrc.seek(0)
                    return bytesrc.read(1)
                if inputKey == ord('q'):
                    curses.ungetch('q')
                    return b"\x00"
                if inputKey == ord('h'): # seek back by 60 packets
                    bytesrc.seek(-2460, io.SEEK_CUR)
                    return bytesrc.read(1)
        else:
            stdscr.addstr(1, 2, "Waiting for data...")
            stdscr.refresh()
            while (byte == b""):
                byte = bytesrc.read(1)
                if ((byte == b"") and (stdscr.getch() == ord("q"))):
                    curses.ungetch("q")
                    byte = b"\x00"
    return byte


def printLabels (outwin, labels):
    for label in labels:
        if label[0] & 1:
            if label[0] & 2:  # bit mask labels
                for i in range(0, 8):
                    (line, col, lab, dummy) = label[1][i]
                    if lab != "":
                        outwin.addstr(line, col, lab)
            else:
                (line, col, lab, dummy) = label[1]
                outwin.addstr(line, col, lab)


def updTicker (ticker, window):
    if (ticker > 0x21):
        tickch = 's'
    elif (ticker % 5):
        tickch = '.'
    else:
        tickch = ':'

    if not ticker:
        window.chgat(ticker_line, ticker_col + 0x28, 1, 0)
    window.addstr(ticker_line, ticker_col + ticker, tickch, curses.color_pair(4))
    window.chgat(ticker_line, ticker_col + ticker - 1, 1, 0)


def openSource ():
    if (args.file == ""):
        return serial.Serial(args.port, args.baudrate, timeout=0.1)
    return open(args.file, "rb")


def mainLoop (stdscr):
    sync = 0
    outwin = stdscr.subwin(curses.LINES - 4, curses.COLS - 4, 3, 2)
    msgwin = outwin.subpad(9, 80, 33, 2)
    printLabels(outwin, labels)
    outwin.addstr(25, xRightLabel, "Sync bytes")
    outwin.scrollok(True)
    msgwin.scrollok(True)

    with openSource() as bytesource:
        while (stdscr.getch() != ord("q")):
            if sync < 3:
                stdscr.addstr(1, 2, "Resyncing...      ")
                stdscr.refresh()
                while sync < len(sync_bytes):
                    byte = readByte(bytesource, stdscr)
                    if (stdscr.getch() == ord("q")):  #  This is here only to not get stuck in this loop!
                        return                        #  Maybe it should be rethought at some point..?
                    if byte in sync_bytes[sync]:
                        sync += 1
                    else:
                        if byte in sync_bytes[0]:
                            sync = 1
                        else:
                            sync = 0
                stdscr.addstr(1, 2, f"Synchronised: {sync}   ")
                sync_hits  = [0, 0, 0, 0, 0, 0, 0]
                ticker = 0
            elif ticker > 0x21:  # data is read, check stream sync
                sync = 0
                while ticker < 0x29:
                    byte = readByte(bytesource, stdscr)
                    tick = ticker - 0x22
                    if byte in sync_bytes[tick]:
                        outwin.addstr(26, xRightLabel - 3 + (3 * (ticker - 0x21)), f"{byte.hex()}")
                        outwin.addstr(27, xRightLabel - 4 + (3 * (ticker - 0x21)), f"{int.from_bytes(byte, byteorder='big'):3d}")
                        sync += 1
                    else:  # print non-matching sync bytes in reverse and a copy two lines below to catch them!
                        outwin.addstr(26, xRightLabel - 3 + (3 * (ticker - 0x21)), f"{byte.hex()}", curses.A_REVERSE)
                        outwin.addstr(28, xRightLabel - 3 + (3 * (ticker - 0x21)), f"{byte.hex()}")
                    updTicker(ticker, stdscr)
                    stdscr.refresh()
                    ticker += 1
                stdscr.addstr(1, 2, f"Synchronised: {sync}   ")
                outwin.refresh()
                stdscr.refresh()
                ticker = 0

            byte = readByte(bytesource, stdscr)
            byte_cache[ticker] = byte

            printByte(outwin, msgwin, byte, ticker)
            updTicker(ticker, stdscr)
            ticker += 1
            outwin.refresh()
            msgwin.refresh()

            if args.file != "":
                inputKey = stdscr.getch()
                if inputKey == ord('q'):
                    curses.ungetch('q')
                else:
                    seekBy = 0
                    if inputKey == ord('h'): # seek back by 60 packets
                        seekBy = -2460
                    elif inputKey == ord('j'): # seek back by 10 packets
                        seekBy = -410
                    elif inputKey == ord('k'): # seek forward by 10 packets
                        seekBy = 410
                    elif inputKey == ord('l'): # seek forward by 60 packets
                        seekBy = 2460

                    if seekBy:
                        curPos = bytesource.tell()
                        if (curPos + seekBy) < 0:
                            seekBy = -curPos
                        bytesource.seek(seekBy, io.SEEK_CUR)


def main (stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(5, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(7, curses.COLOR_RED, curses.COLOR_BLACK)

    stdscr.clear()
    stdscr.border()
    stdscr.addstr(0, 3, " Mercedes-Benz BR 124 A/C data stream decoder - press q to quit ")
    stdscr.nodelay(True)
    curses.curs_set(0)
    mainLoop(stdscr)

curses.wrapper(main)

# EOF
