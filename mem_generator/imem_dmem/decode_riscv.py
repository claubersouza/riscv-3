"""
Filename: decodeRiscv.py

Author: Isaac Gubelin
Date: May 13, 2024

Description: This file contains the functions for decoding a 32-bit RISC-V instruction.
	This validates the input string and then decodes it into RISC-V assembly with a
	mnemonic, register numbers, and immediate if applicable.

"""

import re  # Regex for validating input
from riscv_tables import instr_types_from_opcode, instructions_rv32

"""Masks for retrieving desired bits from 32-bit number"""
OPCODE_MASK = 0x0000007F
RS1_MASK = 0x000F8000
RS2_MASK = 0x01F00000
RD_MASK = 0x00000F80
FN3_MASK = 0x00007000
FN7_MASK = 0xFE000000


def is_binary_instruction(s):
    """
    Check valid binary format of a string.
    Accepts binary with or without '0b', rejects anything that isn't 32 bits long.
    """
    return bool(re.match(r"^(0[bB])?[01]{32}$", s))  # String match with Regex


def is_hex_instruction(s):
    """
    Check if a string is a hexadecimal literal.
    Accepts binary with or without '0x' and rejects non-32-bit numbers.
    """
    return bool(re.match(r"^(0[xX])?[0-9a-fA-F]{8}$", s))


def get_instruction_type(opcode):
    """Retrieve the instruction type letter for the given opcode."""
    return instr_types_from_opcode[opcode]


def get_mnemonic(tup):
    """Retrieves the mnemonic for an instruction opcode and funct codes in a tuple."""
    return instructions_rv32[tup]


def get_immediate(instruction):
    """Returns the immediate value of the instruction as an integer"""

    opcode = instruction & OPCODE_MASK  # Get opcode
    inst_type = instr_types_from_opcode[opcode]  # Get instruction type

    # Make a string of pure binary, no prefix. This will make it easier to bit-slice
    bin_str = format(instruction, "032b")

    # Immediate value is calculated based on instruction type
    if inst_type in {"I", "I_load", "I_jump", "I_environment"}:
        return instruction >> 20  # I: Immediate is upper 12 bits

    elif inst_type == "S":
        imm = bin_str[0:7] + bin_str[20:25]  # S: Immediate is bits 31-25, 11-7
        return int(imm, 2)

    elif inst_type == "B":  # ...and so on, folowing green card.
        imm = bin_str[0] + bin_str[24] + bin_str[1:7] + bin_str[20:24] + "0"
        return int(imm, 2)

    elif inst_type == "U":
        return instruction >> 12

    elif inst_type == "J":
        imm = bin_str[0] + bin_str[12:20] + bin_str[11] + bin_str[1:11] + "0"
        return int(imm, 2)

    else:
        return None


def get_base_2_int(instr):
    """Convert string to binary integer"""
    return int(instr, 2)


def get_hex_int(instr):
    return int(instr, 16)


def decode_instruction(instr):
    """
    Main decoding function. Accepts a single instruction string and decodes
    it into its assembly form with the mnemonic.
    """

    if is_binary_instruction(instr):
        instr = get_base_2_int(instr)
    elif is_hex_instruction(instr):
        instr = get_hex_int(instr)
    else:
        print("Invalid format. Use 32-bit binary or hex.")
        return

    f_type = "?"

    # Make an assembly equivalent string of the 32-bit instruction
    try:
        opcode = instr & OPCODE_MASK  # Get opcode
        f_type = get_instruction_type(opcode)  # Get instruction format type
        rs1 = "x" + str((instr & RS1_MASK) >> 15)  # Get rs1 and all critical pieces
        rs2 = "x" + str((instr & RS2_MASK) >> 20)
        rd = "x" + str((instr & RD_MASK) >> 7)
        fn7 = (instr & FN7_MASK) >> 25
        fn3 = (instr & FN3_MASK) >> 12
        imm = get_immediate(instr)

        if f_type == "R":
            name = get_mnemonic((opcode, fn3, fn7))  # Get instruction name
            return (f"Assembly: {name} {rd}, {rs1}, {rs2}")  # Print assembly

        elif f_type == "I":
            if fn3 == 0x1 or fn3 == 0x5:  # These funct3 codes mean funct7 is needed
                name = get_mnemonic((opcode, fn3, fn7))
                return(f"Assembly: {name} {rd}, {rs1}, {imm}")
            else:
                name = get_mnemonic((opcode, fn3))
                return (f"Assembly: {name} {rd}, {rs1}, {imm}")

        elif f_type == "I_load" or f_type == "I_jump":
            name = get_mnemonic((opcode, fn3))
            return (f"Assembly: {name} {rd}, {imm}({rs1})")

        elif (
            f_type == "I_environment"
        ):  # rs1, rs2, and rd are zero for environment calls
            if rs1 != "x0" or rd != "x0":
                print("Invalid environment instruction, registers must be zero.")
            else:
                name = get_mnemonic((opcode, fn3, imm))
                return(f"Assembly: {name}")

        elif f_type == "S":
            name = get_mnemonic((opcode, fn3))
            return(f"Assembly: {name} {rs2}, {imm}({rs1})")

        elif f_type == "B":
            name = get_mnemonic((opcode, fn3))
            return(f"Assembly: {name} {rs1}, {rs2}, {imm}")

        elif f_type == "J" or f_type == "U":
            name = get_mnemonic(opcode)
            return(f"Assembly: {name} {rd}, {imm}")

        return(f"Format: {f_type[0]}-type")  # return instruction format type

    except KeyError:
        print(f"Error: 00000000")
