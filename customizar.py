#!/usr/bin/env python3
"""
customizar_lw2b_2para1.py

Objetivo:
  preservar a CUSTOM_LW2 existente 00f47053 (que já aparece em outras
  partes do programa e tem semântica própria) e criar uma SEGUNDA custom
  para um novo par de LW.

Exemplo:
  fcc42703 = lw x14,-52(x8)
  fdc42783 = lw x15,-36(x8)

vira:
  02f47053 = CUSTOM_LW2B

A segunda LW é removida fisicamente do HEX.
Não há NOP inserido para a nova CUSTOM.

A CUSTOM antiga 00f47053 continua inalterada.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


HEX8 = re.compile(r"^[0-9a-fA-F]{8}$")

OLD_CUSTOM = "00f47053"
DEFAULT_NEW_CUSTOM = None


def die(msg):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(2)


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8")


def normalize_hex(value):
    value = value.strip().lower()
    if value.startswith("0x"):
        value = value[2:]

    if not HEX8.fullmatch(value):
        die(f"HEX inválido: {value}")

    return value


def sign_extend(value, bits):
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def decode_lw(hx):
    w = int(hx, 16)

    if (w & 0x7F) != 0x03 or ((w >> 12) & 7) != 0x2:
        die(f"{hx} não é LW RV32I.")

    return {
        "hex": hx,
        "rd": (w >> 7) & 31,
        "rs1": (w >> 15) & 31,
        "imm": sign_extend((w >> 20) & 0xFFF, 12),
    }


def parse_hex(path):
    words = []

    for raw in read_text(path).splitlines():
        token = raw.split("//", 1)[0].strip().lower()

        if token.startswith("0x"):
            token = token[2:]

        if HEX8.fullmatch(token):
            words.append(token)

    return words


# ----------------------------------------------------------------------
# Branch/JAL relocation
# ----------------------------------------------------------------------

def decode_jal(w):
    rd = (w >> 7) & 31

    imm = 0
    imm |= ((w >> 31) & 1) << 20
    imm |= ((w >> 12) & 0xFF) << 12
    imm |= ((w >> 20) & 1) << 11
    imm |= ((w >> 21) & 0x3FF) << 1

    return rd, sign_extend(imm, 21)


def encode_jal(rd, imm):
    if imm & 1:
        die(f"JAL desalinhado: {imm}")

    u = imm & 0x1FFFFF

    w = 0x6F | (rd << 7)
    w |= ((u >> 20) & 1) << 31
    w |= ((u >> 1) & 0x3FF) << 21
    w |= ((u >> 11) & 1) << 20
    w |= ((u >> 12) & 0xFF) << 12

    return w


def decode_branch(w):
    funct3 = (w >> 12) & 7
    rs1 = (w >> 15) & 31
    rs2 = (w >> 20) & 31

    imm = 0
    imm |= ((w >> 31) & 1) << 12
    imm |= ((w >> 7) & 1) << 11
    imm |= ((w >> 25) & 0x3F) << 5
    imm |= ((w >> 8) & 0xF) << 1

    return funct3, rs1, rs2, sign_extend(imm, 13)


def encode_branch(funct3, rs1, rs2, imm):
    if imm & 1:
        die(f"BRANCH desalinhado: {imm}")

    u = imm & 0x1FFF

    w = 0x63 | (funct3 << 12) | (rs1 << 15) | (rs2 << 20)
    w |= ((u >> 12) & 1) << 31
    w |= ((u >> 5) & 0x3F) << 25
    w |= ((u >> 1) & 0xF) << 8
    w |= ((u >> 11) & 1) << 7

    return w


def relocate_after_remove(words, removed_index):
    removed_pc = removed_index * 4

    output = []
    relocations = []

    for old_index, hx in enumerate(words):
        if old_index == removed_index:
            continue

        w = int(hx, 16)
        opcode = w & 0x7F

        old_pc = old_index * 4
        new_pc = old_pc - (4 if old_pc > removed_pc else 0)

        new_w = w

        if opcode == 0x6F:
            rd, old_off = decode_jal(w)
            old_target = old_pc + old_off

            if old_target == removed_pc:
                die(
                    f"JAL em 0x{old_pc:08x} aponta para a palavra removida."
                )

            new_target = old_target - (
                4 if old_target > removed_pc else 0
            )

            new_w = encode_jal(
                rd,
                new_target - new_pc,
            )

            relocations.append({
                "type": "JAL",
                "old_pc": old_pc,
                "new_pc": new_pc,
                "old_target": old_target,
                "new_target": new_target,
                "old_hex": hx,
                "new_hex": f"{new_w:08x}",
            })

        elif opcode == 0x63:
            funct3, rs1, rs2, old_off = decode_branch(w)
            old_target = old_pc + old_off

            if old_target == removed_pc:
                die(
                    f"BRANCH em 0x{old_pc:08x} aponta para a palavra removida."
                )

            new_target = old_target - (
                4 if old_target > removed_pc else 0
            )

            new_w = encode_branch(
                funct3,
                rs1,
                rs2,
                new_target - new_pc,
            )

            relocations.append({
                "type": "BRANCH",
                "old_pc": old_pc,
                "new_pc": new_pc,
                "old_target": old_target,
                "new_target": new_target,
                "old_hex": hx,
                "new_hex": f"{new_w:08x}",
            })

        output.append(f"{new_w:08x}")

    return output, relocations


def compact_hex(
    input_path,
    output_path,
    first,
    second,
    new_custom,
):
    words = parse_hex(input_path)

    matches = [
        i
        for i in range(len(words) - 1)
        if words[i] == first and words[i + 1] == second
    ]

    if not matches:
        die(
            f"par {first} {second} não encontrado consecutivamente."
        )

    if len(matches) != 1:
        die(
            f"par aparece {len(matches)} vezes. "
            "Esta versão exige uma única ocorrência."
        )

    pair_index = matches[0]

    words[pair_index] = new_custom

    compacted, relocations = relocate_after_remove(
        words,
        pair_index + 1,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_text(
        output_path,
        "\n".join(compacted) + "\n",
    )

    return (
        pair_index,
        len(words),
        len(compacted),
        relocations,
    )


def offset_expr(base, imm):
    if imm < 0:
        return f"({base} - 32'd{abs(imm)})"

    if imm > 0:
        return f"({base} + 32'd{imm})"

    return base


# ----------------------------------------------------------------------
# ASIP injection
# ----------------------------------------------------------------------

def patch_pipeline(path):
    s = read_text(path)

    if "custom_lw2b" not in s:
        anchor = (
            "    wire                   custom_lw2_writeback_valid;\n"
            "    wire           [31:0]  custom_lw2_writeback_data1;\n"
            "    wire           [31:0]  custom_lw2_writeback_data2;"
        )

        if anchor not in s:
            die(
                "pipeline.v: bloco de sinais CUSTOM_LW2 não localizado."
            )

        addition = anchor + """
    // CUSTOM_LW2B: nova dupla compactada, independente da 00f47053.
    reg                    custom_lw2b;
    reg                    custom_lw2b_seen;
    reg             [1:0] custom_lw2b_state;
    reg            [31:0] custom_lw2b_base_latched;
    wire                   custom_lw2b_busy;
    wire                   custom_lw2b_read_valid;
    wire           [31:0] custom_lw2b_read_address;
    wire           [31:0] custom_lw2b_read2_address;
    wire                   custom_lw2b_writeback_valid;
    wire           [31:0] custom_lw2b_writeback_data1;
    wire           [31:0] custom_lw2b_writeback_data2;"""

        s = s.replace(
            anchor,
            addition,
            1,
        )

    # MUX porta principal: LW2B tem prioridade sobre LW2 original.
    old = (
        "assign dmem_read_ready              = "
        "custom_lw3_read_valid || custom_lw2_read_valid || mem_to_reg;"
    )

    new = (
        "assign dmem_read_ready              = "
        "custom_lw3_read_valid || custom_lw2b_read_valid || "
        "custom_lw2_read_valid || mem_to_reg;"
    )

    if old in s:
        s = s.replace(
            old,
            new,
            1,
        )

    # O endereço principal pode estar em outra expressão.
    if "custom_lw2b_read_valid ? custom_lw2b_read_address" not in s:
        s = re.sub(
            r"assign\s+dmem_read_address\s*=\s*"
            r"custom_lw3_read_valid\s*\?\s*custom_lw3_read_address\s*:\s*"
            r"custom_lw2_read_valid\s*\?\s*custom_lw2_read_address\s*:",
            "assign dmem_read_address          = "
            "custom_lw3_read_valid ? custom_lw3_read_address : "
            "custom_lw2b_read_valid ? custom_lw2b_read_address : "
            "custom_lw2_read_valid ? custom_lw2_read_address :",
            s,
            count=1,
            flags=re.DOTALL,
        )

    # Segunda porta.
    s = s.replace(
        "assign dmem_read2_ready             = custom_lw2_read_valid;",
        "assign dmem_read2_ready             = "
        "custom_lw2b_read_valid || custom_lw2_read_valid;",
        1,
    )

    s = s.replace(
        "assign dmem_read2_address           = custom_lw2_read2_address;",
        "assign dmem_read2_address           = "
        "custom_lw2b_read_valid ? custom_lw2b_read2_address : "
        "custom_lw2_read2_address;",
        1,
    )

    write_text(
        path,
        s,
    )


def patch_if_id(
    path,
    new_custom,
    a,
    b,
):
    s = read_text(path)

    # ----------------------------------------------------------
    # Reset custom_lw2b.
    # ----------------------------------------------------------
    reset_anchor = "    pipe.custom_lw2             <= 1'b0;"

    if reset_anchor not in s:
        die("IF_ID.v: reset custom_lw2 não localizado.")

    if "pipe.custom_lw2b" not in s:
        s = s.replace(
            reset_anchor,
            reset_anchor
            + "\n"
            + "    pipe.custom_lw2b            <= 1'b0;",
            1,
        )

    # ----------------------------------------------------------
    # Decode: não altera 00f47053.
    # ----------------------------------------------------------
    decode_anchor = (
        "    pipe.custom_lw2             <= "
        "(pipe.instruction == 32'h00f47053);"
    )

    if decode_anchor not in s:
        die(
            "IF_ID.v funcional não possui decode exato da 00f47053."
        )

    if (
        f"pipe.custom_lw2b            <= "
        f"(pipe.instruction == 32'h{new_custom});"
        not in s
    ):
        s = s.replace(
            decode_anchor,
            decode_anchor
            + "\n"
            + f"    pipe.custom_lw2b            <= "
            f"(pipe.instruction == 32'h{new_custom});",
            1,
        )

    # Permitir decode da nova custom mesmo no ciclo de stall.
    marker = (
        "((pipe.instruction == 32'h00f47053) || "
        "(pipe.instruction == 32'h00f470d3))"
    )

    if marker in s:
        s = s.replace(
            marker,
            "((pipe.instruction == 32'h00f47053) || "
            f"(pipe.instruction == 32'h{new_custom}) || "
            "(pipe.instruction == 32'h00f470d3))",
            1,
        )

    # ----------------------------------------------------------
    # Stall SOMENTE para a nova custom.
    # A antiga 00f47053 continua usando NOP/prefetch como antes.
    # ----------------------------------------------------------
    stall_pattern = re.compile(
        r"(pipe\.stall_read\s*<=\s*stall\s*\|\|.*?)(;)",
        flags=re.DOTALL,
    )

    m = stall_pattern.search(s)

    if not m:
        die("IF_ID.v: stall_read não encontrado.")

    stall_text = m.group(1)

    if "custom_lw2b_busy" not in stall_text:
        replacement = (
            stall_text
            + "\n"
            + f"                       || "
            f"((pipe.instruction == 32'h{new_custom}) && "
            f"!pipe.custom_lw2b_seen)\n"
            + "                       || pipe.custom_lw2b_busy"
            + ";"
        )

        s = (
            s[:m.start()]
            + replacement
            + s[m.end():]
        )

    # ----------------------------------------------------------
    # Forwarding da NOVA custom.
    # ----------------------------------------------------------
    anchor = (
        "    // V32: a instrucao seguinte (AND) pode consumir "
        "os dois resultados\n"
        "    // diretamente durante o ciclo COMMIT da CUSTOM_LW2."
    )

    if anchor in s and "CUSTOM_LW2B" not in s:
        forwarding = f"""    // CUSTOM_LW2B: forwarding dos resultados da nova dupla.
    (pipe.custom_lw2b_writeback_valid &&
     pipe.src1_select == 5'd{a['rd']}) ?
        pipe.custom_lw2b_writeback_data1 :
    (pipe.custom_lw2b_writeback_valid &&
     pipe.src1_select == 5'd{b['rd']}) ?
        pipe.custom_lw2b_writeback_data2 :

"""
        s = s.replace(
            anchor,
            forwarding + anchor,
            1,
        )

        # src2
        src2_anchor = (
            "    // V32: forwarding do segundo resultado "
            "da CUSTOM_LW2."
        )

        forwarding2 = f"""    // CUSTOM_LW2B: forwarding src2.
    (pipe.custom_lw2b_writeback_valid &&
     pipe.src2_select == 5'd{a['rd']}) ?
        pipe.custom_lw2b_writeback_data1 :
    (pipe.custom_lw2b_writeback_valid &&
     pipe.src2_select == 5'd{b['rd']}) ?
        pipe.custom_lw2b_writeback_data2 :

"""

        if src2_anchor in s:
            s = s.replace(
                src2_anchor,
                forwarding2 + src2_anchor,
                1,
            )

    # ----------------------------------------------------------
    # Register file writeback.
    # ----------------------------------------------------------
    wb_anchor = (
        "else if (pipe.custom_lw2_writeback_valid)\n"
        "begin\n"
        "    pipe.regs[14] <= "
        "pipe.custom_lw2_writeback_data1;\n"
        "    pipe.regs[15] <= "
        "pipe.custom_lw2_writeback_data2;\n"
        "end"
    )

    if wb_anchor not in s:
        die(
            "IF_ID.v: write-back da CUSTOM_LW2 antiga não localizado."
        )

    if "else if (pipe.custom_lw2b_writeback_valid)" not in s:
        new_wb = f"""else if (pipe.custom_lw2b_writeback_valid)
begin
    pipe.regs[{a['rd']}] <= pipe.custom_lw2b_writeback_data1;
    pipe.regs[{b['rd']}] <= pipe.custom_lw2b_writeback_data2;
end
{wb_anchor}"""

        s = s.replace(
            wb_anchor,
            new_wb,
            1,
        )

    write_text(
        path,
        s,
    )


def patch_wb(
    path,
    new_custom,
    a,
    b,
):
    s = read_text(path)

    # ----------------------------------------------------------
    # Se já existe uma CUSTOM_LW2B de execução anterior,
    # remove o bloco inteiro para recriá-lo com os offsets atuais.
    # Isso torna o script idempotente.
    # ----------------------------------------------------------
    old_start = s.find(
        "// -----------------------------------------------------------------------------\n"
        "// CUSTOM_LW2B ("
    )

    if old_start >= 0:
        old_end = s.find(
            "// CUSTOM_lw3",
            old_start,
        )

        if old_end < 0:
            die(
                "wb.v contém CUSTOM_LW2B antiga, mas o fim "
                "do bloco antes de CUSTOM_lw3 não foi localizado."
            )

        s = s[:old_start] + s[old_end:]

    # Insere novo bloco antes de CUSTOM_lw3.
    insertion = s.find("// CUSTOM_lw3")

    if insertion < 0:
        die("wb.v: ponto antes de CUSTOM_lw3 não encontrado.")

    block = f"""
// -----------------------------------------------------------------------------
// CUSTOM_LW2B ({new_custom}) - NOVA dupla 2 -> 1 SEM NOP
//
// NÃO altera a CUSTOM_LW2 antiga 00f47053.
//
// Original:
//   {a['hex']} = lw x{a['rd']},{a['imm']}(x{a['rs1']})
//   {b['hex']} = lw x{b['rd']},{b['imm']}(x{b['rs1']})
//
// Usa as duas portas síncronas em paralelo e stall interno.
// -----------------------------------------------------------------------------
localparam [1:0] CUSTOM_LW2B_IDLE   = 2'd0;
localparam [1:0] CUSTOM_LW2B_COMMIT = 2'd1;

wire custom_lw2b_request_now =
    (pipe.custom_lw2b_state == CUSTOM_LW2B_IDLE) &&
    pipe.custom_lw2b &&
    !pipe.custom_lw2b_seen;

assign pipe.custom_lw2b_busy =
    custom_lw2b_request_now ||
    (pipe.custom_lw2b_state == CUSTOM_LW2B_COMMIT);

assign pipe.custom_lw2b_read_valid =
    custom_lw2b_request_now;

assign pipe.custom_lw2b_read_address =
    {offset_expr('pipe.reg_rdata1', a['imm'])};

assign pipe.custom_lw2b_read2_address =
    {offset_expr('pipe.reg_rdata1', b['imm'])};

assign pipe.custom_lw2b_writeback_valid =
    (pipe.custom_lw2b_state == CUSTOM_LW2B_COMMIT);

assign pipe.custom_lw2b_writeback_data1 =
    pipe.dmem_read_data;

assign pipe.custom_lw2b_writeback_data2 =
    pipe.dmem_read2_data;

always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.custom_lw2b_state        <= CUSTOM_LW2B_IDLE;
        pipe.custom_lw2b_base_latched <= 32'd0;
        pipe.custom_lw2b_seen         <= 1'b0;
    end
    else
    begin
        case (pipe.custom_lw2b_state)

            CUSTOM_LW2B_IDLE:
            begin
                if (pipe.custom_lw2b &&
                    !pipe.custom_lw2b_seen)
                begin
                    pipe.custom_lw2b_base_latched <=
                        pipe.reg_rdata1;

                    pipe.custom_lw2b_seen <= 1'b1;
                    pipe.custom_lw2b_state <=
                        CUSTOM_LW2B_COMMIT;
                end
                else if (!pipe.custom_lw2b)
                begin
                    pipe.custom_lw2b_seen <= 1'b0;
                end
            end

            CUSTOM_LW2B_COMMIT:
            begin
                pipe.custom_lw2b_state <=
                    CUSTOM_LW2B_IDLE;
            end

            default:
                pipe.custom_lw2b_state <=
                    CUSTOM_LW2B_IDLE;
        endcase
    end
end


"""

    s = (
        s[:insertion]
        + block
        + s[insertion:]
    )

    write_text(
        path,
        s,
    )

def patch_execute(path, new_custom):
    """
    A nova custom NÃO usa PC+8.
    O programa foi compactado fisicamente:
        CUSTOM
        próxima instrução

    Portanto o fluxo normal do execute já usa PC+4.
    """
    s = read_text(path)

    # Segurança: não deve haver regra especial já existente.
    if f"32'h{new_custom}" in s:
        die(
            f"execute.v já contém {new_custom}; "
            "use arquivos base limpos/funcionais."
        )

    write_text(
        path,
        s,
    )


def validate(
    dst,
    new_custom,
    a,
    b,
):
    ifid = read_text(dst / "IF_ID.v")
    wb = read_text(dst / "wb.v")
    pipe = read_text(dst / "pipeline.v")
    exe = read_text(dst / "execute.v")

    checks = {
        "CUSTOM antiga preservada":
            "pipe.custom_lw2             <= "
            "(pipe.instruction == 32'h00f47053);"
            in ifid,

        "CUSTOM nova decodificada":
            f"pipe.custom_lw2b            <= "
            f"(pipe.instruction == 32'h{new_custom});"
            in ifid,

        "offset novo 1":
            re.search(
                r"assign\s+pipe\.custom_lw2b_read_address\s*=\s*"
                + re.escape(
                    offset_expr(
                        "pipe.reg_rdata1",
                        a["imm"],
                    )
                )
                + r"\s*;",
                wb,
            ) is not None,

        "offset novo 2":
            re.search(
                r"assign\s+pipe\.custom_lw2b_read2_address\s*=\s*"
                + re.escape(
                    offset_expr(
                        "pipe.reg_rdata1",
                        b["imm"],
                    )
                )
                + r"\s*;",
                wb,
            ) is not None,

        "writeback novo":
            "custom_lw2b_writeback_valid"
            in ifid,

        "dual-read novo":
            "custom_lw2b_read2_address"
            in pipe,

        "sem PC+8 novo":
            f"32'h{new_custom}"
            not in exe,

        "antiga ainda possui PC+8":
            "pipe.instruction == 32'h00f47053"
            in exe,
    }

    print()
    print("Validação:")
    for name, ok in checks.items():
        print(
            f"  {'OK' if ok else 'FALHA'} - {name}"
        )

    failed = [
        name
        for name, ok in checks.items()
        if not ok
    ]

    if failed:
        die(
            "validação falhou: "
            + ", ".join(failed)
        )



def choose_free_custom(
    words: list[str],
    dst: Path,
    requested: str | None = None,
) -> str:
    """
    Escolhe uma codificação livre mantendo o mesmo formato da família
    funcional 00f47053:

      opcode = 0x53
      rd     = x0
      funct3 = 111
      rs1    = x8
      rs2    = x15
      funct7 = variável

    Exemplos:
      00f47053 -> funct7=0
      02f47053 -> funct7=1
      04f47053 -> funct7=2
      06f47053 -> funct7=3
      ...

    Uma candidata só é usada se não aparecer:
      - no HEX;
      - em IF_ID.v;
      - em execute.v;
      - em wb.v;
      - em pipeline.v.
    """
    occupied = set(words)

    for name in (
        "IF_ID.v",
        "execute.v",
        "wb.v",
        "pipeline.v",
    ):
        p = dst / name
        if not p.is_file():
            continue

        src_text = read_text(p).lower()

        for m in re.finditer(
            r"32'h([0-9a-f]{8})",
            src_text,
        ):
            occupied.add(
                m.group(1)
            )

    if requested is not None:
        candidate = normalize_hex(
            requested
        )

        if candidate in occupied:
            die(
                f"CUSTOM solicitada {candidate} já está ocupada."
            )

        if (int(candidate, 16) & 0x7f) != 0x53:
            die(
                f"CUSTOM {candidate} não usa opcode 0x53."
            )

        return candidate

    # Mantém exatamente rd/funct3/rs1/rs2 da 00f47053.
    # Só funct7 muda.
    template = int(
        "00f47053",
        16,
    )

    # limpa funct7
    template &= ~(
        0x7f << 25
    )

    for funct7 in range(1, 128):
        candidate_word = (
            template
            | (funct7 << 25)
        )

        candidate = (
            f"{candidate_word:08x}"
        )

        if candidate not in occupied:
            print(
                f"CUSTOM livre encontrada: {candidate} "
                f"(funct7={funct7})"
            )
            return candidate

    die(
        "não existe codificação CUSTOM livre nesta família "
        "(funct7 1..127 esgotado)."
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "base",
        type=Path,
    )

    parser.add_argument(
        "destino",
        type=Path,
    )

    parser.add_argument(
        "--originais",
        nargs=2,
        required=True,
    )

    parser.add_argument(
        "--hex-entrada",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--hex-saida",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--custom",
        default=None,
        help=(
            "CUSTOM explícita. Se omitida, o script escolhe "
            "automaticamente uma codificação livre da família 0x53."
        ),
    )

    parser.add_argument(
        "--sobrescrever",
        action="store_true",
    )

    args = parser.parse_args()

    first = normalize_hex(
        args.originais[0]
    )

    second = normalize_hex(
        args.originais[1]
    )

    a = decode_lw(first)
    b = decode_lw(second)

    if a["rs1"] != b["rs1"]:
        die(
            f"bases diferentes: x{a['rs1']} e x{b['rs1']}"
        )

    # Escolha da nova CUSTOM é feita somente depois de copiar a pasta
    # e analisar todas as palavras já ocupadas.
    new_custom = None

    if not args.base.is_dir():
        die(
            f"pasta base inexistente: {args.base}"
        )

    if args.destino.exists():
        if not args.sobrescrever:
            die(
                f"{args.destino} já existe; use --sobrescrever."
            )

        shutil.rmtree(
            args.destino
        )

    shutil.copytree(
        args.base,
        args.destino,
    )

    # A base deve ser o conjunto funcional original.
    base_ifid = read_text(
        args.destino / "IF_ID.v"
    )

    if (
        "pipe.custom_lw2             <= "
        "(pipe.instruction == 32'h00f47053);"
        not in base_ifid
    ):
        die(
            "a pasta base não parece ser a versão funcional "
            "com CUSTOM_LW2 00f47053."
        )

    input_words = parse_hex(
        args.hex_entrada
    )

    new_custom = choose_free_custom(
        input_words,
        args.destino,
        requested=args.custom,
    )

    if new_custom == OLD_CUSTOM:
        die(
            "não reutilize 00f47053: ela já possui outra semântica."
        )

    pair_index, before, after, relocations = compact_hex(
        args.hex_entrada,
        args.hex_saida,
        first,
        second,
        new_custom,
    )

    patch_pipeline(
        args.destino / "pipeline.v"
    )

    patch_if_id(
        args.destino / "IF_ID.v",
        new_custom,
        a,
        b,
    )

    patch_wb(
        args.destino / "wb.v",
        new_custom,
        a,
        b,
    )

    patch_execute(
        args.destino / "execute.v",
        new_custom,
    )

    validate(
        args.destino,
        new_custom,
        a,
        b,
    )

    report = {
        "input_words": before,
        "output_words": after,
        "removed_words": before - after,
        "bytes_saved": (before - after) * 4,
        "old_custom_preserved": OLD_CUSTOM,
        "new_custom": new_custom,
        "pair": [
            first,
            second,
        ],
        "pair_old_pc":
            f"0x{pair_index * 4:08x}",
        "lw1": a,
        "lw2": b,
        "relocations": relocations,
        "nop_inserted": False,
        "strategy":
            "separate_custom_lw2b_hardware_stall",
    }

    write_text(
        args.destino / "relocation_report.json",
        json.dumps(
            report,
            indent=2,
        )
        + "\n",
    )

    print()
    print("========================================")
    print("CUSTOM_LW2B 2 -> 1")
    print("========================================")
    print(
        f"Antiga preservada : {OLD_CUSTOM}"
    )
    print(
        f"Nova custom       : {new_custom}"
    )
    print(
        f"LW1               : {first}"
    )
    print(
        f"LW2               : {second}"
    )
    print(
        f"PC antigo do par  : "
        f"0x{pair_index * 4:08x}"
    )
    print(
        f"HEX               : {before} -> {after}"
    )
    print("NOP novo           : NÃO")
    print("CUSTOM antiga      : INALTERADA")
    print("========================================")


if __name__ == "__main__":
    main()