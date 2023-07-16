#!/bin/python3
import argparse

parser = argparse.ArgumentParser(description="program to hunt minimum and maximum data values from MB 124 A/C data stream captures",
                                 epilog="Modify the program to change its function.")
parser.add_argument("filename", help="name of file read")
args = parser.parse_args()

sync_bytes = b"\x00\x03\x04\x01\x23\x02\x3b"

with open(args.filename, "rb") as sourcefile:
    bytesource = sourcefile.read()

firstsync = bytesource.find(sync_bytes) + 7
length = len(bytesource)
bytesource = bytesource[firstsync:-((length - firstsync) % 41)]

print(f"Loaded {length} bytes. First packet at {firstsync}, full length after trimming {len(bytesource)}.")

index = 0

AdjDampLMin = 255
AdjDampLMax = 0
AdjDampRMin = 255
AdjDampRMax = 0
ExtBiasMin = +127
ExtBiasMax = -128

print("\nHunting...\n")

while (index * 41) < len(bytesource):
    offset = index * 41 + 0xb
    ExtBias = int.from_bytes(bytesource[offset:offset + 1], signed=True)
    if ExtBias > ExtBiasMax:
        ExtBiasMax = ExtBias
    if ExtBias < ExtBiasMin:
        ExtBiasMin = ExtBias

    offset = index * 41 + 0x1f
    AdjDampL = int.from_bytes(bytesource[offset:offset + 1], signed=False)
    if AdjDampL:
        if AdjDampL > AdjDampLMax:
            AdjDampLMax = AdjDampL
        if AdjDampL < AdjDampLMin:
            AdjDampLMin = AdjDampL

    offset = index * 41 + 0x21
    AdjDampR = int.from_bytes(bytesource[offset:offset + 1], signed=False)
    if AdjDampR:
        if AdjDampR > AdjDampRMax:
            AdjDampRMax = AdjDampR
        if AdjDampR < AdjDampRMin:
            AdjDampRMin = AdjDampR

    index += 1

print(f"External temp bias min/max: {ExtBiasMin:4d} / {ExtBiasMax:4d}")

if AdjDampLMax:
    print(f"Left adjustment damping min/max: {AdjDampLMin:3d} / {AdjDampLMax:3d}")

if AdjDampRMax:
    print(f"Right adjustment damping min/max: {AdjDampRMin:3d} / {AdjDampRMax:3d}")

# EOF
