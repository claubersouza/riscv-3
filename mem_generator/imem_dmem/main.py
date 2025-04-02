"""
Filename: main.py

Author: Isaac Gubelin
Date: May 13, 2024

Description: This program uses the argparse library to collect a RISC-V instruction
	from the user. The instruction should be given in binary or in hexadecimal. The
	instruction will be decoded into a line of assembly.

"""

from argparse import ArgumentParser
from decode_riscv import decode_instruction

def read_inst(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        lines = [line.rstrip() for line in lines]
    return lines

def main():

    asm = []

    path = "imem.hex"
    count = 0 
    count2 = 0
    codes = read_inst(path)
    print(codes)
    for code in codes:
        code = code[0:8]
        count = count + 1
        asm.append(str(code) + "//"+ str(decode_instruction(code) ))

    count2 += 0
    with open(path, "w") as file:
        for line in codes:
            
            file.write(asm[count2]+ "\n")
            count2 += 1
        

if __name__ == "__main__":
    main()
