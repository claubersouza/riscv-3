def read_inst(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        lines = [line.rstrip() for line in lines]
    return lines

def decoder(inst):
    bw =32
    # R-type
    opcode = inst[bw-7:]
    rd = inst[bw-12:bw-7]
    funct3 = inst[bw-15:bw-12]
    rs1    = inst[bw-20:bw-15]
    rs2    = inst[bw-25:bw-20]
    funct7 = inst[bw-32:bw-25]
    
    # I-type
    imm_I = inst[bw-32:bw-20]
    # S-type
    imm_S = inst[bw-32:bw-25] + inst[bw-12:bw-7]
    # B-type
    imm_B = inst[bw-32] + inst[bw-8] + inst[bw-31:bw-25] + inst[bw-12:bw-8]
    # U-type
    imm_U = inst[bw-32:bw-12]
    # J-type
    imm_J = inst[bw-32] + inst[bw-20:bw-12] + inst[bw-20] + inst[bw-31:bw-21]

    if opcode == '0110111':
        inst_n = "LUI"
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, imm:{imm_U}")
    elif opcode == '0010111':
        inst_n = "AUIPC"
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, imm:{imm_U}")
    elif opcode == "1101111":
        inst_n = "JAL"
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, imm:{imm_J}")
    elif opcode == "1100111":
        inst_n = "JALR"
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, imm:{imm_I}")
    elif opcode == "1100011":
        if funct3 == '000':
            inst_n = 'BEQ '
        if funct3 == '001':
            inst_n = 'BNE '
        if funct3 == '100':
            inst_n = 'BLT '
        if funct3 == '101':
            inst_n = 'BGE '
        if funct3 == '110':
            inst_n = 'BLTU '
        if funct3 == '111':
            inst_n = 'BGEU '
        print(f"inst_n: {inst_n}, opcode: {opcode}, funct3:{funct3}, rs1:{rs1}, rs2:{rs2}, imm:{imm_B}")
    elif opcode == "0000011":
        if funct3 == '000':
            inst_n = 'LB '
        if funct3 == '001':
            inst_n = 'LH '
        if funct3 == '010':
            inst_n = 'LW '
        if funct3 == '100':
            inst_n = 'LBU '
        if funct3 == '101':
            inst_n = 'LHU '
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, imm:{imm_I}")
    elif opcode == "0100011":
        if funct3 == '000':
            inst_n = 'SB '
        if funct3 == '001':
            inst_n = 'SH '
        if funct3 == '010':
            inst_n = 'SW '
        print(f"inst_n: {inst_n}, opcode: {opcode}, funct3:{funct3}, rs1:{rs1}, rs2:{rs2}, imm:{imm_S}")
    elif opcode == "0010011":
        if funct3 == '000':
            inst_n = 'ADDI '
        if funct3 == '010':
            inst_n = 'SLTI '
        if funct3 == '011':
            inst_n = 'SLTIU '
        if funct3 == '100':
            inst_n = 'XORI '
        if funct3 == '110':
            inst_n = 'ORI '
        if funct3 == '111':
            inst_n = 'ANDI '
        if funct3 == '001':
            inst_n = 'SLLI '
        if funct3 == '101':
            if funct7 == '0000000':
                inst_n = 'SRLI '
            else:
                inst_n = 'SRAI'
            print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, func7:{funct7}")
        else:
            print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, imm:{imm_I}")
    elif opcode == "0110011":
        if funct3 == '000':
            if funct7 == '0000000':
                inst_n = 'ADD'
            else:
                inst_n = 'SUB'
        if funct3 == '001':
            inst_n = 'SLL'
        if funct3 == '010':
            inst_n = 'SLT'
        if funct3 == '011':
            inst_n = 'SLTU'
        if funct3 == '100':
            inst_n = 'XOR'
        if funct3 == '101':
            if funct7 == '0000000':
                inst_n = 'SRL'
            else:
                inst_n ='SRA'
        if funct3 == '110':
            inst_n = 'OR'
        if funct3 == '111':
            inst_n = 'AND'
        print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, rs2:{rs2}, func7:{funct7}")
            
    elif opcode == '0001111':
        if funct3 == '000':
            inst_n = 'FENCE'
        if funct3 == '001':
            inst_n = 'FENCE.I'
        print(f"inst_n: {inst_n}, opcode: {opcode}, funct3:{funct3}")
        
    elif opcode == '1110011':
        if funct3 == '001':
            inst_n = 'CSRRW'
        if funct3 == '010':
            inst_n = 'CSRRS'
        if funct3 == '011':
            inst_n = 'CSRRC'
        if funct3 == '101':
            inst_n = 'CSRRWI'
        if funct3 == '110':
            inst_n = 'CSRRSI'
        if funct3 == '111':
            inst_n = 'CSRRCI'
        if funct3 == '000':
            if imm_I == '000000000000': 
                inst_n = 'ECALL'
            else:
                inst_n = 'EBREAK'
            print(f"inst_n: {inst_n}, opcode: {opcode}, imm:{imm_I}")
        else:
            print(f"inst_n: {inst_n}, opcode: {opcode}, rd:{rd}, funct3:{funct3}, rs1:{rs1}, csr:{imm_I}")
    else:
        print("ERROR")
        

def main():
    path = "./imem.hex"
    codes = read_inst(path)
    for code in codes:
        code = code[0:8]
        decimal_code = int(code, 16)
        binary_code = bin(decimal_code)[2:]
        thirty_two_width_code = binary_code.zfill(32)
        print(f"inst: {thirty_two_width_code}")
        decoder(thirty_two_width_code)
        
        
if __name__ == '__main__':
    main()
    