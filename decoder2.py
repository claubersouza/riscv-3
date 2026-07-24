def sign_extend(value: int, bits: int) -> int:
    """
    Realiza extensão de sinal.
    """
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def register_name(register: int) -> str:
    """
    Retorna o registrador no formato x0 até x31.
    """
    return f"x{register}"


def decode_riscv(hexadecimal: str) -> str:
    """
    Decodifica uma instrução RISC-V RV32I.
    """

    hexadecimal = hexadecimal.strip().lower().replace("0x", "")

    if len(hexadecimal) != 8:
        return "instrução inválida"

    try:
        instruction = int(hexadecimal, 16)
    except ValueError:
        return "hexadecimal inválido"

    opcode = instruction & 0x7F
    rd = (instruction >> 7) & 0x1F
    funct3 = (instruction >> 12) & 0x07
    rs1 = (instruction >> 15) & 0x1F
    rs2 = (instruction >> 20) & 0x1F
    funct7 = (instruction >> 25) & 0x7F

    rd_name = register_name(rd)
    rs1_name = register_name(rs1)
    rs2_name = register_name(rs2)

    # Tipo R
    if opcode == 0x33:
        instructions_r = {
            (0x00, 0x0): "add",
            (0x20, 0x0): "sub",
            (0x00, 0x1): "sll",
            (0x00, 0x2): "slt",
            (0x00, 0x3): "sltu",
            (0x00, 0x4): "xor",
            (0x00, 0x5): "srl",
            (0x20, 0x5): "sra",
            (0x00, 0x6): "or",
            (0x00, 0x7): "and"
        }

        mnemonic = instructions_r.get((funct7, funct3))

        if mnemonic:
            return f"{mnemonic} {rd_name}, {rs1_name}, {rs2_name}"

    # Tipo I: operações imediatas
    elif opcode == 0x13:
        immediate = sign_extend(instruction >> 20, 12)

        instructions_i = {
            0x0: "addi",
            0x2: "slti",
            0x3: "sltiu",
            0x4: "xori",
            0x6: "ori",
            0x7: "andi"
        }

        if funct3 in instructions_i:
            mnemonic = instructions_i[funct3]
            return f"{mnemonic} {rd_name}, {rs1_name}, {immediate}"

        shamt = (instruction >> 20) & 0x1F

        if funct3 == 0x1 and funct7 == 0x00:
            return f"slli {rd_name}, {rs1_name}, {shamt}"

        if funct3 == 0x5:
            if funct7 == 0x00:
                return f"srli {rd_name}, {rs1_name}, {shamt}"

            if funct7 == 0x20:
                return f"srai {rd_name}, {rs1_name}, {shamt}"

    # Loads
    elif opcode == 0x03:
        immediate = sign_extend(instruction >> 20, 12)

        load_instructions = {
            0x0: "lb",
            0x1: "lh",
            0x2: "lw",
            0x4: "lbu",
            0x5: "lhu"
        }

        mnemonic = load_instructions.get(funct3)

        if mnemonic:
            return f"{mnemonic} {rd_name}, {immediate}({rs1_name})"

    # JALR
    elif opcode == 0x67:
        immediate = sign_extend(instruction >> 20, 12)

        if funct3 == 0x0:
            return f"jalr {rd_name}, {immediate}({rs1_name})"

    # Stores
    elif opcode == 0x23:
        immediate = (
            (((instruction >> 25) & 0x7F) << 5)
            | ((instruction >> 7) & 0x1F)
        )

        immediate = sign_extend(immediate, 12)

        store_instructions = {
            0x0: "sb",
            0x1: "sh",
            0x2: "sw"
        }

        mnemonic = store_instructions.get(funct3)

        if mnemonic:
            return f"{mnemonic} {rs2_name}, {immediate}({rs1_name})"

    # Branches
    elif opcode == 0x63:
        immediate = (
            (((instruction >> 31) & 0x01) << 12)
            | (((instruction >> 7) & 0x01) << 11)
            | (((instruction >> 25) & 0x3F) << 5)
            | (((instruction >> 8) & 0x0F) << 1)
        )

        immediate = sign_extend(immediate, 13)

        branch_instructions = {
            0x0: "beq",
            0x1: "bne",
            0x4: "blt",
            0x5: "bge",
            0x6: "bltu",
            0x7: "bgeu"
        }

        mnemonic = branch_instructions.get(funct3)

        if mnemonic:
            return f"{mnemonic} {rs1_name}, {rs2_name}, {immediate}"

    # LUI
    elif opcode == 0x37:
        immediate = instruction >> 12
        return f"lui {rd_name}, 0x{immediate:x}"

    # AUIPC
    elif opcode == 0x17:
        immediate = instruction >> 12
        return f"auipc {rd_name}, 0x{immediate:x}"

    # JAL
    elif opcode == 0x6F:
        immediate = (
            (((instruction >> 31) & 0x01) << 20)
            | (((instruction >> 12) & 0xFF) << 12)
            | (((instruction >> 20) & 0x01) << 11)
            | (((instruction >> 21) & 0x3FF) << 1)
        )

        immediate = sign_extend(immediate, 21)

        return f"jal {rd_name}, {immediate}"

    # FENCE
    elif opcode == 0x0F:
        if funct3 == 0x0:
            return "fence"

        if funct3 == 0x1:
            return "fence.i"

    # SYSTEM
    elif opcode == 0x73:
        immediate = instruction >> 20

        if funct3 == 0x0:
            if immediate == 0:
                return "ecall"

            if immediate == 1:
                return "ebreak"

    return f"instrução desconhecida opcode=0x{opcode:02x}"


def get_mnemonic(line: str) -> str:
    """
    Extrai o mnemônico de uma linha decodificada.

    Exemplo:
    02010413  // addi x8, x2, 32

    Retorna:
    addi
    """

    if "//" not in line:
        return ""

    assembly = line.split("//", 1)[1].strip()

    if not assembly:
        return ""

    return assembly.split()[0]


def read_and_decode_file(
    input_file: str,
    decoded_file: str
) -> list[str]:
    """
    Lê o arquivo hexadecimal e gera o arquivo decodificado.
    """

    decoded_lines = []

    with open(input_file, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            # Remove comentário já existente
            if "//" in line:
                line = line.split("//", 1)[0].strip()

            if "#" in line:
                line = line.split("#", 1)[0].strip()

            # Ignora linhas vazias
            if not line:
                continue

            hexadecimal = line.lower().replace("0x", "")

            if len(hexadecimal) != 8:
                print(
                    f"Linha {line_number} ignorada: "
                    f"'{hexadecimal}' não possui 8 dígitos."
                )
                continue

            try:
                int(hexadecimal, 16)
            except ValueError:
                print(
                    f"Linha {line_number} ignorada: "
                    f"'{hexadecimal}' não é hexadecimal."
                )
                continue

            assembly = decode_riscv(hexadecimal)
            decoded_line = f"{hexadecimal}  // {assembly}"

            decoded_lines.append(decoded_line)

    with open(decoded_file, "w", encoding="utf-8") as file:
        for line in decoded_lines:
            file.write(line + "\n")

    return decoded_lines


def save_repeated_sequences(
    decoded_lines: list[str],
    output_file: str,
    minimum_size: int = 2
) -> None:
    """
    Salva somente sequências consecutivas com o mesmo
    mnemônico e tamanho maior ou igual ao mínimo.
    """

    repeated_groups = []
    index = 0

    while index < len(decoded_lines):
        current_mnemonic = get_mnemonic(decoded_lines[index])
        group = [decoded_lines[index]]
        index += 1

        # Captura instruções consecutivas com o mesmo mnemônico
        while (
            index < len(decoded_lines)
            and get_mnemonic(decoded_lines[index]) == current_mnemonic
        ):
            group.append(decoded_lines[index])
            index += 1

        # Guarda somente grupos com pelo menos duas instruções
        if (
            current_mnemonic
            and len(group) >= minimum_size
        ):
            repeated_groups.append(group)

    with open(output_file, "w", encoding="utf-8") as file:
        for group_index, group in enumerate(repeated_groups):
            for line in group:
                file.write(line + "\n")

            # Duas linhas vazias entre os grupos
            if group_index < len(repeated_groups) - 1:
                file.write("\n\n")


def main():
    input_file = ("./modules/imem_custom.hex")

    decoded_file = "program_decoded.lst"
    grouped_file = "repeated_sequences.lst"

    try:
        decoded_lines = read_and_decode_file(
            input_file,
            decoded_file
        )

        save_repeated_sequences(
            decoded_lines,
            grouped_file,
            minimum_size=2
        )

        print()
        print(f"Arquivo decodificado: {decoded_file}")
        print(f"Arquivo com sequências repetidas: {grouped_file}")

    except FileNotFoundError:
        print(f"Arquivo não encontrado: {input_file}")

    except OSError as error:
        print(f"Erro ao acessar o arquivo: {error}")


if __name__ == "__main__":
    main()