#!/usr/bin/env python3

import sys
from pathlib import Path


MINIMO_GRUPO = 2


def extrair_hex(linha: str) -> str | None:
    """Extrai a instrução hexadecimal localizada antes de //Assembly."""
    parte_hex = linha.split("//", 1)[0].strip()
    parte_hex = parte_hex.removeprefix("0x").removeprefix("0X")

    if not parte_hex:
        return None

    try:
        valor = int(parte_hex, 16)
    except ValueError:
        return None

    return f"{valor & 0xFFFFFFFF:08x}"



def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def decodificar_assembly(hex_instrucao: str) -> str:
    """Decodifica instruções RV32I comuns para texto Assembly."""
    v = int(hex_instrucao, 16)
    opcode = v & 0x7F
    rd = (v >> 7) & 0x1F
    funct3 = (v >> 12) & 0x7
    rs1 = (v >> 15) & 0x1F
    rs2 = (v >> 20) & 0x1F
    funct7 = (v >> 25) & 0x7F

    imm_i = sign_extend((v >> 20) & 0xFFF, 12)
    imm_s = sign_extend(((v >> 25) << 5) | ((v >> 7) & 0x1F), 12)
    imm_b = sign_extend((((v >> 31) & 1) << 12) | (((v >> 7) & 1) << 11) | (((v >> 25) & 0x3F) << 5) | (((v >> 8) & 0xF) << 1), 13)
    imm_u = v & 0xFFFFF000
    imm_j = sign_extend((((v >> 31) & 1) << 20) | (((v >> 12) & 0xFF) << 12) | (((v >> 20) & 1) << 11) | (((v >> 21) & 0x3FF) << 1), 21)

    if opcode == 0x03:  # LOAD
        nomes = {0: 'lb', 1: 'lh', 2: 'lw', 4: 'lbu', 5: 'lhu'}
        if funct3 in nomes:
            return f"{nomes[funct3]} x{rd}, {imm_i}(x{rs1})"
    elif opcode == 0x23:  # STORE
        nomes = {0: 'sb', 1: 'sh', 2: 'sw'}
        if funct3 in nomes:
            return f"{nomes[funct3]} x{rs2}, {imm_s}(x{rs1})"
    elif opcode == 0x13:  # OP-IMM
        nomes = {0: 'addi', 2: 'slti', 3: 'sltiu', 4: 'xori', 6: 'ori', 7: 'andi'}
        if funct3 in nomes:
            return f"{nomes[funct3]} x{rd}, x{rs1}, {imm_i}"
        shamt = (v >> 20) & 0x1F
        if funct3 == 1:
            return f"slli x{rd}, x{rs1}, {shamt}"
        if funct3 == 5:
            nome = 'srai' if funct7 == 0x20 else 'srli'
            return f"{nome} x{rd}, x{rs1}, {shamt}"
    elif opcode == 0x33:  # OP
        nomes = {(0,0x00):'add',(0,0x20):'sub',(1,0x00):'sll',(2,0x00):'slt',(3,0x00):'sltu',(4,0x00):'xor',(5,0x00):'srl',(5,0x20):'sra',(6,0x00):'or',(7,0x00):'and'}
        nome = nomes.get((funct3, funct7))
        if nome:
            return f"{nome} x{rd}, x{rs1}, x{rs2}"
    elif opcode == 0x63:  # BRANCH
        nomes = {0:'beq',1:'bne',4:'blt',5:'bge',6:'bltu',7:'bgeu'}
        if funct3 in nomes:
            return f"{nomes[funct3]} x{rs1}, x{rs2}, {imm_b}"
    elif opcode == 0x37:
        return f"lui x{rd}, 0x{imm_u >> 12:x}"
    elif opcode == 0x17:
        return f"auipc x{rd}, 0x{imm_u >> 12:x}"
    elif opcode == 0x6F:
        return f"jal x{rd}, {imm_j}"
    elif opcode == 0x67 and funct3 == 0:
        return f"jalr x{rd}, {imm_i}(x{rs1})"

    return 'desconhecida'


def formatar_linha(linha: str) -> str | None:
    hex_instrucao = extrair_hex(linha)
    if hex_instrucao is None:
        return None
    return f"{hex_instrucao}//Assembly: {decodificar_assembly(hex_instrucao)}"

def extrair_campos(hex_instrucao: str) -> tuple[int, int]:
    """
    Retorna opcode e funct3 da instrução RISC-V.

    opcode: bits [6:0]
    funct3: bits [14:12]
    """
    valor = int(hex_instrucao, 16)
    opcode = valor & 0x7F
    funct3 = (valor >> 12) & 0x07
    return opcode, funct3


def agrupar_instrucoes(
    linhas: list[str],
    minimo_grupo: int = MINIMO_GRUPO,
) -> list[list[str]]:
    """
    Agrupa somente instruções consecutivas que possuem:
      - o mesmo opcode;
      - o mesmo funct3.

    Grupos menores que minimo_grupo são descartados.
    """
    grupos_validos: list[list[str]] = []
    grupo_atual: list[str] = []
    chave_atual: tuple[int, int] | None = None

    for linha_original in linhas:
        linha = linha_original.strip()

        if not linha:
            continue

        hex_instrucao = extrair_hex(linha)

        if hex_instrucao is None:
            continue

        # Ignora palavras vazias usadas como preenchimento da memória.
        if hex_instrucao == "00000000":
            continue

        chave = extrair_campos(hex_instrucao)

        if chave_atual is None or chave == chave_atual:
            grupo_atual.append(formatar_linha(linha))
            chave_atual = chave
        else:
            if len(grupo_atual) >= minimo_grupo:
                grupos_validos.append(grupo_atual)

            grupo_atual = [formatar_linha(linha)]
            chave_atual = chave

    if len(grupo_atual) >= minimo_grupo:
        grupos_validos.append(grupo_atual)

    return grupos_validos


def salvar_grupos(grupos: list[list[str]], arquivo_saida: Path) -> None:
    """Salva os grupos separados por uma linha em branco."""
    with arquivo_saida.open("w", encoding="utf-8") as arquivo:
        for indice, grupo in enumerate(grupos):
            if indice > 0:
                arquivo.write("\n")

            for linha in grupo:
                arquivo.write(linha + "\n")


def main() -> None:
    arquivo_entrada = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("imem.hex")
    )

    arquivo_saida = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path("grupos_opcode_funct3.txt")
    )

    if not arquivo_entrada.exists():
        print(f"Erro: arquivo não encontrado: {arquivo_entrada}")
        sys.exit(1)

    linhas = arquivo_entrada.read_text(encoding="utf-8").splitlines()

    grupos = agrupar_instrucoes(
        linhas,
        minimo_grupo=MINIMO_GRUPO,
    )

    if not grupos:
        print(
            f"Nenhum grupo consecutivo com pelo menos "
            f"{MINIMO_GRUPO} instruções foi encontrado."
        )
        return

    salvar_grupos(grupos, arquivo_saida)

    for indice, grupo in enumerate(grupos, start=1):
        hex_primeira = extrair_hex(grupo[0])
        opcode, funct3 = extrair_campos(hex_primeira)

        print(
            f"Grupo {indice} - "
            f"opcode 0x{opcode:02x}, funct3 0b{funct3:03b}"
        )

        for linha in grupo:
            print(linha)

        print()

    print(f"Resultado salvo em: {arquivo_saida}")


if __name__ == "__main__":
    main()