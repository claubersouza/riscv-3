import re
import sys

# Hex customizado para instruções otimizadas
CUSTOM_HEX = "DEADBEEF"

def parse_instruction(line):
    """Analisa uma linha no formato 'hex // Assembly: instrução'"""
    parts = line.strip().split("//")
    if len(parts) < 2:
        return "", ""
    hex_part = parts[0].strip()
    asm_part = parts[1].replace("Assembly:", "").strip()
    return hex_part, asm_part

def generate_custom_instructions(lines):
    """Gera instruções customizadas com otimizações"""
    custom_code = []
    instructions = [parse_instruction(line) for line in lines]

    i = 0
    while i < len(instructions):
        hex_code, asm = instructions[i]

        try:
            # Otimização 1: Transforma addi com x0 em li
            addi_match = re.match(r"addi\s+(x\d+),\s*(x0|xzero),\s*(-?\d+)", asm)
            if addi_match and len(addi_match.groups()) == 3:
                rd, _, imm = addi_match.groups()
                custom_code.append((CUSTOM_HEX, f"li {rd}, {imm}"))
                i += 1
                continue

            # Otimização 2: Transforma addi com imediato 0 em mv
            addi_zero_match = re.match(r"addi\s+(x\d+),\s*(x\d+),\s*0", asm)
            if addi_zero_match and len(addi_zero_match.groups()) == 3:
                rd, rs, _ = addi_zero_match.groups()
                custom_code.append((CUSTOM_HEX, f"mv {rd}, {rs}"))
                i += 1
                continue

            # Otimização 3: Detecta load/store redundantes
            if i + 1 < len(instructions):
                _, next_asm = instructions[i + 1]
                load_match = re.match(r"lw\s+(x\d+),\s*(\d+)\((x\d+)\)", asm)
                store_match = re.match(r"sw\s+(x\d+),\s*(\d+)\((x\d+)\)", next_asm)
                
                if (load_match and len(load_match.groups()) == 3 and
                    store_match and len(store_match.groups()) == 3):
                    reg_ld, offset_ld, base_ld = load_match.groups()
                    reg_st, offset_st, base_st = store_match.groups()
                    
                    if (offset_ld == offset_st) and (base_ld == base_st) and (reg_ld == reg_st):
                        # Remove a sequência redundante
                        i += 2
                        continue

            # Otimização 4: NOPs podem ser eliminados
            if asm in ["nop", "addi x0, x0, 0"]:
                i += 1
                continue

        except Exception as e:
            print(f"Erro ao processar linha {i+1}: {asm} - {str(e)}", file=sys.stderr)

        # Se não houver otimização, mantém a instrução original
        custom_code.append((hex_code, asm))
        i += 1

    return custom_code

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 gerador_custom.py <arquivo_entrada> [<arquivo_saída>]")
        return

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        with open(input_file, "r") as f:
            lines = f.readlines()

        custom_instructions = generate_custom_instructions(lines)

        # Saída para arquivo ou console
        output = []
        for hex_code, asm in custom_instructions:
            output_line = f"{hex_code} // Assembly: {asm}"
            output.append(output_line)

        if output_file:
            with open(output_file, "w") as f:
                f.write("\n".join(output))
        else:
            print("\n".join(output))

    except FileNotFoundError:
        print(f"Erro: Arquivo '{input_file}' não encontrado.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro inesperado: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
