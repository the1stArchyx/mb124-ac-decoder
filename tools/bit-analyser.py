#!/bin/python3
import argparse

parser = argparse.ArgumentParser(description="program to hunt bit changes from MB 124 A/C data stream captures",
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

index = 1
bit_status = bytesource[0x1d] & 0b00100000  # temp control mode

while (index * 41) < len(bytesource):
    
    print("\nHunting for bit change...")
    while bit_status == bytesource[0x1d + (index * 41)] & 0b00100000:
        index += 1
        if (index * 41) >= len(bytesource):
            bit_status = -1
            break

    if bit_status == -1:
        print("End of file reached.")
        exit(0)

    index2 = index - 5
    index += 1
    bit_status = bytesource[0x1d + (index * 41)] & 0b00100000

    for j in (9, 0xa, 0xb, 0x1d):
        datastr = f"{j:02x}:"
        for i in range(index2, index2 + 11):
            datastr += f" {bytesource[i * 41 + j]:02x}"
        print(datastr)

# EOF
