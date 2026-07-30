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
            grupo_atual.append(linha)
            chave_atual = chave
        else:
            if len(grupo_atual) >= minimo_grupo:
                grupos_validos.append(grupo_atual)

            grupo_atual = [linha]
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