#!/bin/python3

sync_bytes = b"\x00\x03\x04\x01\x23\x02\x3b"

with open("driving.bin", "rb") as sourcefile:
    bytesource = sourcefile.read()

firstsync = bytesource.find(sync_bytes) + 7
length = len(bytesource)
bytesource = bytesource[firstsync:-((length - firstsync) % 41)]

print(f"Loaded {length} bytes. First packet at {firstsync}, full length after trimming {len(bytesource)}.")

index = 1
bit_status = bytesource[0x1d] & 0x40

while (index * 41) < len(bytesource):
    
    print("\nHunting for bit change...")
    while bit_status == bytesource[0x1d + (index * 41)] & 0x40:
        index += 1
        if (index * 41) >= len(bytesource):
            bit_status = -1
            break

    if bit_status == -1:
        print("End of file reached.")
        exit(0)

    index2 = index - 10
    index += 1

    for j in range(34):
        datastr = f"{j:02x}:"
        for i in range(index2, index2 + 22):
            datastr += f" {bytesource[i * 41 + j]:02x}"
        print(datastr)

# EOF
