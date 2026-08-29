#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CUSTOM ADDI2X - somente ADDI, compactação real, sem NOP.

Transforma:

    addi rd1, rs1a, imm1
    addi rd2, rs1b, imm2

em UMA instrução CUSTOM de 32 bits.

Também suporta dependência interna:

    addi x14, x14, 1
    addi x15, x14, 2

Nesse caso o segundo resultado usa internamente o resultado do primeiro,
preservando a semântica sequencial.

Não altera:
- memory.v
- tb_pipeline.v
- lógica LW2X já existente

Altera apenas:
- pipeline.v
- IF_ID.v
- execute.v
- HEX de instruções

A segunda ADDI é removida fisicamente do HEX. BRANCH/JAL são relocados.

Uso:

python3 customizar_addi2x_sem_nop.py BASE DESTINO \
    --hex-entrada imem_custom.hex \
    --hex-saida imem_custom_addi.hex \
    --originais ADDI1 ADDI2 \
    --sobrescrever

Para vários pares na mesma execução (também continua suportado):

    --originais ADDI1 ADDI2 ADDI3 ADDI4 ...

Opcional:
    --ocorrencias 1 1 ...
    --aplicar-no-base

Também aceita novas execuções sobre uma base que já contém ADDI2X_V1.
Nesse caso entra automaticamente em modo incremental.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


MARK = "ADDI2X_V1"
HEX8 = re.compile(r"^[0-9a-fA-F]{8}$")


def die(msg: str):
    raise SystemExit(f"ERRO: {msg}")


def read(path: Path) -> str:
    if not path.exists():
        die(f"arquivo não encontrado: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def h32(v: int) -> str:
    return f"{v & 0xffffffff:08x}"


def sext(v: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (v & (sign - 1)) - (v & sign)


def v_s32(v: int) -> str:
    if v < 0:
        return f"-32'sd{abs(v)}"
    return f"32'sd{v}"


# ============================================================================
# Decode RV32I
# ============================================================================

def decode_addi(h: str) -> dict:
    h = h.lower().replace("0x", "")
    if not HEX8.fullmatch(h):
        die(f"hex inválido: {h}")

    w = int(h, 16)
    opcode = w & 0x7f
    funct3 = (w >> 12) & 7

    if opcode != 0x13 or funct3 != 0b000:
        die(f"{h} não é ADDI RV32I.")

    return {
        "hex": h,
        "rd": (w >> 7) & 31,
        "rs1": (w >> 15) & 31,
        "imm": sext((w >> 20) & 0xfff, 12),
    }


def decode_branch(w: int) -> int:
    imm = 0
    imm |= ((w >> 31) & 1) << 12
    imm |= ((w >> 7) & 1) << 11
    imm |= ((w >> 25) & 0x3f) << 5
    imm |= ((w >> 8) & 0xf) << 1
    return sext(imm, 13)


def encode_branch_keep_fields(w: int, imm: int) -> int:
    if imm & 1:
        die(f"BRANCH desalinhado: {imm}")
    if not (-4096 <= imm <= 4094):
        die(f"BRANCH fora do alcance após relocação: {imm}")

    u = imm & 0x1fff
    mask = (1 << 31) | (1 << 7) | (0x3f << 25) | (0xf << 8)
    w &= ~mask & 0xffffffff
    w |= ((u >> 12) & 1) << 31
    w |= ((u >> 11) & 1) << 7
    w |= ((u >> 5) & 0x3f) << 25
    w |= ((u >> 1) & 0xf) << 8
    return w


def decode_jal(w: int) -> int:
    imm = 0
    imm |= ((w >> 31) & 1) << 20
    imm |= ((w >> 12) & 0xff) << 12
    imm |= ((w >> 20) & 1) << 11
    imm |= ((w >> 21) & 0x3ff) << 1
    return sext(imm, 21)


def encode_jal_keep_fields(w: int, imm: int) -> int:
    if imm & 1:
        die(f"JAL desalinhado: {imm}")
    if not (-(1 << 20) <= imm <= (1 << 20) - 2):
        die(f"JAL fora do alcance após relocação: {imm}")

    u = imm & 0x1fffff
    mask = (1 << 31) | (0xff << 12) | (1 << 20) | (0x3ff << 21)
    w &= ~mask & 0xffffffff
    w |= ((u >> 20) & 1) << 31
    w |= ((u >> 12) & 0xff) << 12
    w |= ((u >> 11) & 1) << 20
    w |= ((u >> 1) & 0x3ff) << 21
    return w


# ============================================================================
# HEX
# ============================================================================

def parse_hex(path: Path) -> list[str]:
    words = []
    for raw in read(path).splitlines():
        token = raw.split("//", 1)[0].strip().lower()
        if token.startswith("0x"):
            token = token[2:]
        if HEX8.fullmatch(token):
            words.append(token)

    if not words:
        die(f"nenhuma palavra de 32 bits encontrada em {path}")
    return words


def find_occurrence(words: list[str], h1: str, h2: str, occurrence: int) -> int:
    hits = []
    for i in range(len(words) - 1):
        if words[i] == h1 and words[i + 1] == h2:
            hits.append(i)

    if not hits:
        die(f"par {h1} {h2} não encontrado consecutivamente.")

    if occurrence < 1 or occurrence > len(hits):
        die(
            f"ocorrência {occurrence} inválida para {h1} {h2}; "
            f"existem {len(hits)} ocorrência(s)."
        )

    return hits[occurrence - 1]


def control_targets(words: list[str]) -> set[int]:
    targets = set()
    for idx, hx in enumerate(words):
        w = int(hx, 16)
        op = w & 0x7f
        pc = idx * 4
        if op == 0x63:
            targets.add(pc + decode_branch(w))
        elif op == 0x6f:
            targets.add(pc + decode_jal(w))
    return targets


def choose_custom_word(words: list[str], rtl_text: str, ordinal: int) -> str:
    # CUSTOM-1 = opcode 0x2B. Mantemos separado da LW2X (CUSTOM-0/0x0B).
    used = {x.lower() for x in words}
    used |= {
        x.lower()
        for x in re.findall(r"32'h([0-9a-fA-F]{8})", rtl_text)
    }

    for tag in range(1 + ordinal, 1 << 20):
        w = ((tag & 0xfffff) << 12) | (0b110 << 7) | 0x2b
        hx = h32(w)
        if hx not in used:
            return hx

    die("não foi possível escolher palavra CUSTOM livre para ADDI2X.")


def map_pc_after_deletions(pc: int, deleted_pcs: list[int]) -> int:
    return pc - 4 * sum(1 for d in deleted_pcs if d < pc)


def compact_all(words: list[str], pair_specs: list[dict]) -> tuple[list[str], list[dict]]:
    deleted_pcs = sorted((p["index"] + 1) * 4 for p in pair_specs)
    deleted_set = set(deleted_pcs)
    custom_by_pc = {p["index"] * 4: p["custom"] for p in pair_specs}

    out = []
    reloc = []

    for old_i, hx in enumerate(words):
        old_pc = old_i * 4

        if old_pc in deleted_set:
            continue

        if old_pc in custom_by_pc:
            out.append(custom_by_pc[old_pc])
            continue

        w = int(hx, 16)
        op = w & 0x7f
        new_pc = map_pc_after_deletions(old_pc, deleted_pcs)
        new_w = w

        if op == 0x63:
            old_target = old_pc + decode_branch(w)
            new_target = map_pc_after_deletions(old_target, deleted_pcs)
            new_w = encode_branch_keep_fields(w, new_target - new_pc)

        elif op == 0x6f:
            old_target = old_pc + decode_jal(w)
            new_target = map_pc_after_deletions(old_target, deleted_pcs)
            new_w = encode_jal_keep_fields(w, new_target - new_pc)

        if new_w != w:
            reloc.append({
                "old_pc": old_pc,
                "new_pc": new_pc,
                "old": h32(w),
                "new": h32(new_w),
            })

        out.append(h32(new_w))

    return out, reloc


# ============================================================================
# Helpers para RTL
# ============================================================================

def find_matching_begin_end(s: str, begin_pos: int) -> int:
    token_re = re.compile(r"\bbegin\b|\bend\b")
    depth = 0

    for m in token_re.finditer(s, begin_pos):
        if m.group(0) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()

    die("begin/end desbalanceado ao modificar RTL.")


def insert_before_end_of_register_file_always(s: str, block: str) -> str:
    regpos = s.find("integer i;")
    if regpos < 0:
        die("IF_ID.v: 'integer i;' do banco de registradores não localizado.")

    am = re.search(
        r"always\s*@\s*\(\s*posedge\s+clk\s+or\s+negedge\s+reset\s*\)\s*begin",
        s[regpos:],
        re.MULTILINE,
    )
    if not am:
        die("IF_ID.v: always do banco de registradores não localizado.")

    abs_begin = regpos + am.end() - len("begin")
    abs_end = find_matching_begin_end(s, abs_begin)
    end_start = s.rfind("end", abs_begin, abs_end)

    if end_start < 0:
        die("IF_ID.v: fim do always do register file não localizado.")

    return s[:end_start] + block + "\n" + s[end_start:]


def prepend_rhs_to_continuous_assign(s: str, signal: str, prefix_rhs: str) -> str:
    pat = re.compile(
        rf"assign\s+{re.escape(signal)}"
        rf"(?:\s*\[\s*31\s*:\s*0\s*\])?"
        rf"\s*=",
        re.MULTILINE,
    )

    m = pat.search(s)
    if not m:
        die(f"atribuição contínua não encontrada: {signal}")

    semi = s.find(";", m.end())
    if semi < 0:
        die(f"';' não encontrado em {signal}")

    full = s[m.start():semi + 1]
    eq = full.find("=")
    lhs = full[:eq + 1].rstrip()
    rhs = full[eq + 1:-1].strip()

    repl = f"{lhs}\n{prefix_rhs}\n    {rhs};"
    return s[:m.start()] + repl + s[semi + 1:]


def ternary_table(mappings: list[dict], field_fn, default: str) -> str:
    lines = []
    for mp in mappings:
        lines.append(
            f"(instruction == 32'h{mp['custom']}) ? {field_fn(mp)} :"
        )
    lines.append(default)
    return "\n        ".join(lines)


def validate_pair_safety(words: list[str], idx: int, targets: set[int]):
    second_pc = (idx + 1) * 4
    if second_pc in targets:
        die(
            f"não é seguro remover a segunda ADDI em PC=0x{second_pc:08x}: "
            "ela é alvo de BRANCH/JAL."
        )


# ============================================================================
# pipeline.v
# ============================================================================

def patch_pipeline(path: Path, mappings: list[dict]):
    s = read(path)

    if MARK in s:
        die("pipeline.v já contém ADDI2X_V1. Use todos os pares ADDI na mesma execução.")

    section = "    // PC"
    if section not in s:
        die("pipeline.v: seção // PC não localizada.")

    match_expr = " ||\n        ".join(
        f"(instruction == 32'h{mp['custom']})"
        for mp in mappings
    )

    rs1a = ternary_table(mappings, lambda x: f"5'd{x['first']['rs1']}", "5'd0")
    rs1b = ternary_table(mappings, lambda x: f"5'd{x['second']['rs1']}", "5'd0")
    rd1 = ternary_table(mappings, lambda x: f"5'd{x['first']['rd']}", "5'd0")
    rd2 = ternary_table(mappings, lambda x: f"5'd{x['second']['rd']}", "5'd0")
    imm1 = ternary_table(mappings, lambda x: v_s32(x["first"]["imm"]), "32'sd0")
    imm2 = ternary_table(mappings, lambda x: v_s32(x["second"]["imm"]), "32'sd0")
    dep = ternary_table(
        mappings,
        lambda x: "1'b1" if (
            x["first"]["rd"] != 0 and
            x["second"]["rs1"] == x["first"]["rd"]
        ) else "1'b0",
        "1'b0",
    )

    # Forwarding opcional de LW2X, caso a base já possua a CUSTOM LW.
    has_lw2x = "wb_lw2x" in s
    lw2x_b1 = ""
    lw2x_b2 = ""
    if has_lw2x:
        lw2x_b1 = """
        (wb_lw2x &&
         wb_lw2x_rd2 != 5'd0 &&
         wb_lw2x_rd2 == addi2x_fetch_rs1a) ? wb_lw2x_data2 :
        (wb_lw2x &&
         wb_lw2x_rd1 != 5'd0 &&
         wb_lw2x_rd1 == addi2x_fetch_rs1a) ? wb_lw2x_data1 :"""
        lw2x_b2 = """
        (wb_lw2x &&
         wb_lw2x_rd2 != 5'd0 &&
         wb_lw2x_rd2 == addi2x_fetch_rs1b) ? wb_lw2x_data2 :
        (wb_lw2x &&
         wb_lw2x_rd1 != 5'd0 &&
         wb_lw2x_rd1 == addi2x_fetch_rs1b) ? wb_lw2x_data1 :"""

    block = f"""
    // ========================================================================
    // {MARK}
    // ADDI + ADDI -> 1 CUSTOM; sem memória e sem NOP.
    // ========================================================================

    wire        addi2x_fetch_match;
    wire [4:0]  addi2x_fetch_rs1a;
    wire [4:0]  addi2x_fetch_rs1b;
    wire [4:0]  addi2x_fetch_rd1;
    wire [4:0]  addi2x_fetch_rd2;
    wire signed [31:0] addi2x_fetch_imm1;
    wire signed [31:0] addi2x_fetch_imm2;
    wire        addi2x_fetch_dep;
    wire [31:0] addi2x_fetch_base1;
    wire [31:0] addi2x_fetch_base2;

    reg         addi2x_ex_valid;
    reg [4:0]   addi2x_ex_rd1;
    reg [4:0]   addi2x_ex_rd2;
    reg signed [31:0] addi2x_ex_imm1;
    reg signed [31:0] addi2x_ex_imm2;
    reg [31:0]  addi2x_ex_base1;
    reg [31:0]  addi2x_ex_base2;
    reg         addi2x_ex_dep;

    wire [31:0] addi2x_ex_result1;
    wire [31:0] addi2x_ex_result2;

    reg         wb_addi2x;
    reg [4:0]   wb_addi2x_rd1;
    reg [4:0]   wb_addi2x_rd2;
    reg [31:0]  wb_addi2x_data1;
    reg [31:0]  wb_addi2x_data2;

    assign addi2x_fetch_match =
        {match_expr};

    assign addi2x_fetch_rs1a =
        {rs1a};

    assign addi2x_fetch_rs1b =
        {rs1b};

    assign addi2x_fetch_rd1 =
        {rd1};

    assign addi2x_fetch_rd2 =
        {rd2};

    assign addi2x_fetch_imm1 =
        {imm1};

    assign addi2x_fetch_imm2 =
        {imm2};

    assign addi2x_fetch_dep =
        {dep};

    assign addi2x_fetch_base1 =
        (addi2x_fetch_rs1a == 5'd0) ? 32'd0 :
        (wb_addi2x &&
         wb_addi2x_rd2 != 5'd0 &&
         wb_addi2x_rd2 == addi2x_fetch_rs1a) ? wb_addi2x_data2 :
        (wb_addi2x &&
         wb_addi2x_rd1 != 5'd0 &&
         wb_addi2x_rd1 == addi2x_fetch_rs1a) ? wb_addi2x_data1 :
        {lw2x_b1}
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == addi2x_fetch_rs1a) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[addi2x_fetch_rs1a];

    assign addi2x_fetch_base2 =
        (addi2x_fetch_rs1b == 5'd0) ? 32'd0 :
        (wb_addi2x &&
         wb_addi2x_rd2 != 5'd0 &&
         wb_addi2x_rd2 == addi2x_fetch_rs1b) ? wb_addi2x_data2 :
        (wb_addi2x &&
         wb_addi2x_rd1 != 5'd0 &&
         wb_addi2x_rd1 == addi2x_fetch_rs1b) ? wb_addi2x_data1 :
        {lw2x_b2}
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == addi2x_fetch_rs1b) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[addi2x_fetch_rs1b];

    assign addi2x_ex_result1 =
        addi2x_ex_base1 + addi2x_ex_imm1;

    // Se ADDI2 depende de rd1, usa o resultado intermediário diretamente.
    assign addi2x_ex_result2 =
        addi2x_ex_dep ?
            (addi2x_ex_result1 + addi2x_ex_imm2) :
            (addi2x_ex_base2 + addi2x_ex_imm2);

"""
    s = s.replace(section, block + "\n" + section, 1)
    write(path, s)
    print("pipeline.v: datapath ADDI2X instalado.")



def _append_before_assignment_default(s: str, signal: str, new_lines: list[str]) -> str:
    """Adiciona novos termos a um assign ADDI2X já existente, antes do valor default."""
    pat = re.compile(rf"assign\s+{re.escape(signal)}\s*=", re.MULTILINE)
    m = pat.search(s)
    if not m:
        die(f"pipeline.v incremental: assign {signal} não localizado.")
    semi = s.find(";", m.end())
    if semi < 0:
        die(f"pipeline.v incremental: fim de {signal} não localizado.")
    body = s[m.end():semi]
    # Todas as tabelas geradas originalmente terminam em um default simples.
    lines = body.rstrip().splitlines()
    if not lines:
        die(f"pipeline.v incremental: corpo vazio em {signal}.")
    # Última linha não vazia é o default (5'd0, 32'sd0, 1'b0 etc.).
    last_i = len(lines) - 1
    while last_i >= 0 and not lines[last_i].strip():
        last_i -= 1
    default_line = lines[last_i]
    indent = re.match(r"\s*", default_line).group(0)
    insertion = "\n".join(indent + x for x in new_lines)
    new_body = "\n".join(lines[:last_i])
    if new_body:
        new_body += "\n"
    new_body += insertion + "\n" + default_line
    return s[:m.end()] + new_body + s[semi:]


def patch_pipeline_incremental(path: Path, mappings: list[dict]):
    """Reutiliza ADDI2X_V1 já instalado e acrescenta somente novos mapeamentos."""
    s = read(path)
    if MARK not in s:
        die("pipeline.v incremental: ADDI2X_V1 não encontrado.")

    # 1) Match das novas CUSTOMs.
    pat = re.compile(r"assign\s+addi2x_fetch_match\s*=", re.MULTILINE)
    m = pat.search(s)
    if not m:
        die("pipeline.v incremental: addi2x_fetch_match não localizado.")
    semi = s.find(";", m.end())
    if semi < 0:
        die("pipeline.v incremental: fim de addi2x_fetch_match não localizado.")
    body = s[m.end():semi].rstrip()
    extras = "".join(f" ||\n        (instruction == 32'h{mp['custom']})" for mp in mappings)
    s = s[:m.end()] + body + extras + s[semi:]

    # 2) Acrescenta linhas nas tabelas, antes dos defaults existentes.
    specs = [
        ("addi2x_fetch_rs1a", lambda x: f"(instruction == 32'h{x['custom']}) ? 5'd{x['first']['rs1']} :"),
        ("addi2x_fetch_rs1b", lambda x: f"(instruction == 32'h{x['custom']}) ? 5'd{x['second']['rs1']} :"),
        ("addi2x_fetch_rd1",  lambda x: f"(instruction == 32'h{x['custom']}) ? 5'd{x['first']['rd']} :"),
        ("addi2x_fetch_rd2",  lambda x: f"(instruction == 32'h{x['custom']}) ? 5'd{x['second']['rd']} :"),
        ("addi2x_fetch_imm1", lambda x: f"(instruction == 32'h{x['custom']}) ? {v_s32(x['first']['imm'])} :"),
        ("addi2x_fetch_imm2", lambda x: f"(instruction == 32'h{x['custom']}) ? {v_s32(x['second']['imm'])} :"),
        ("addi2x_fetch_dep",  lambda x: f"(instruction == 32'h{x['custom']}) ? " + ("1'b1" if (x['first']['rd'] != 0 and x['second']['rs1'] == x['first']['rd']) else "1'b0") + " :"),
    ]
    for signal, fn in specs:
        s = _append_before_assignment_default(s, signal, [fn(mp) for mp in mappings])

    write(path, s)
    print(f"pipeline.v: {len(mappings)} novo(s) mapeamento(s) ADDI2X acrescentado(s) ao RTL existente.")

# ============================================================================
# IF_ID.v
# ============================================================================

def patch_ifid(path: Path):
    s = read(path)

    if MARK in s:
        die("IF_ID.v já contém ADDI2X_V1.")

    case_pos = s.find("case(pipe.instruction[`OPCODE])")
    if case_pos < 0:
        die("IF_ID.v: decoder opcode não localizado.")

    endcase = s.find("endcase", case_pos)
    if endcase < 0:
        die("IF_ID.v: endcase do decoder não localizado.")

    insert_pos = endcase + len("endcase")
    legal = f"""
// {MARK}_LEGAL
if (pipe.addi2x_fetch_match)
begin
    pipe.immediate    = 32'd0;
    pipe.illegal_inst = 1'b0;
end
"""
    s = s[:insert_pos] + legal + s[insert_pos:]

    reset_candidates = list(
        re.finditer(r"pipe\.mem_to_reg\s*<=\s*1'b0\s*;", s)
    )
    if not reset_candidates:
        die("IF_ID.v: reset de mem_to_reg não localizado.")

    rm = reset_candidates[0]
    reset_block = f"""
    // {MARK}_RESET_EX
    pipe.addi2x_ex_valid <= 1'b0;
    pipe.addi2x_ex_rd1   <= 5'd0;
    pipe.addi2x_ex_rd2   <= 5'd0;
    pipe.addi2x_ex_imm1  <= 32'sd0;
    pipe.addi2x_ex_imm2  <= 32'sd0;
    pipe.addi2x_ex_base1 <= 32'd0;
    pipe.addi2x_ex_base2 <= 32'd0;
    pipe.addi2x_ex_dep   <= 1'b0;
"""
    s = s[:rm.end()] + reset_block + s[rm.end():]

    em = re.search(
        r"pipe\.execute_immediate\s*<=\s*pipe\.immediate\s*;",
        s,
    )
    if not em:
        die("IF_ID.v: execute_immediate <= pipe.immediate não localizado.")

    capture = f"""
    // {MARK}_CAPTURE_EX
    pipe.addi2x_ex_valid <= pipe.addi2x_fetch_match;
    if (pipe.addi2x_fetch_match)
    begin
        pipe.addi2x_ex_rd1   <= pipe.addi2x_fetch_rd1;
        pipe.addi2x_ex_rd2   <= pipe.addi2x_fetch_rd2;
        pipe.addi2x_ex_imm1  <= pipe.addi2x_fetch_imm1;
        pipe.addi2x_ex_imm2  <= pipe.addi2x_fetch_imm2;
        pipe.addi2x_ex_base1 <= pipe.addi2x_fetch_base1;
        pipe.addi2x_ex_base2 <= pipe.addi2x_fetch_base2;
        pipe.addi2x_ex_dep   <= pipe.addi2x_fetch_dep;
    end
"""
    s = s[:em.start()] + capture + s[em.start():]

    mem_assigns = list(
        re.finditer(r"pipe\.mem_to_reg\s*<=\s*[^;]+;", s, re.MULTILINE)
    )
    exec_pos = s.find("pipe.execute_immediate", s.find(MARK + "_CAPTURE_EX"))
    candidates = [x for x in mem_assigns if x.start() > exec_pos]
    if not candidates:
        die("IF_ID.v: mem_to_reg normal não localizado após decode.")
    mm = candidates[0]

    neutral = f"""
    // {MARK}_NEUTRALIZE_NORMAL_PATH
    if (pipe.addi2x_fetch_match)
    begin
        pipe.execute_immediate <= 32'd0;
        pipe.immediate_sel     <= 1'b0;
        pipe.alu               <= 1'b0;
        pipe.lui               <= 1'b0;
        pipe.jal               <= 1'b0;
        pipe.jalr              <= 1'b0;
        pipe.branch            <= 1'b0;
        pipe.mem_write         <= 1'b0;
        pipe.mem_to_reg        <= 1'b0;
        pipe.dest_reg_sel      <= 5'd0;
    end
"""
    s = s[:mm.end()] + neutral + s[mm.end():]

    prefix1 = f"""    // {MARK}_FWD_R1
    (pipe.wb_addi2x &&
     pipe.wb_addi2x_rd2 != 5'd0 &&
     pipe.wb_addi2x_rd2 == pipe.src1_select) ?
        pipe.wb_addi2x_data2 :
    (pipe.wb_addi2x &&
     pipe.wb_addi2x_rd1 != 5'd0 &&
     pipe.wb_addi2x_rd1 == pipe.src1_select) ?
        pipe.wb_addi2x_data1 :"""

    prefix2 = f"""    // {MARK}_FWD_R2
    (pipe.wb_addi2x &&
     pipe.wb_addi2x_rd2 != 5'd0 &&
     pipe.wb_addi2x_rd2 == pipe.src2_select) ?
        pipe.wb_addi2x_data2 :
    (pipe.wb_addi2x &&
     pipe.wb_addi2x_rd1 != 5'd0 &&
     pipe.wb_addi2x_rd1 == pipe.src2_select) ?
        pipe.wb_addi2x_data1 :"""

    s = prepend_rhs_to_continuous_assign(s, "pipe.reg_rdata1", prefix1)
    s = prepend_rhs_to_continuous_assign(s, "pipe.reg_rdata2", prefix2)

    commit = f"""
// {MARK}_DUAL_COMMIT
if (reset && pipe.wb_addi2x)
begin
    if (pipe.wb_addi2x_rd1 != 5'd0)
        pipe.regs[pipe.wb_addi2x_rd1] <= pipe.wb_addi2x_data1;

    // ADDI2 é arquiteturalmente posterior; ganha se rd1 == rd2.
    if (pipe.wb_addi2x_rd2 != 5'd0)
        pipe.regs[pipe.wb_addi2x_rd2] <= pipe.wb_addi2x_data2;

    $display(
        "[ADDI2X_WB] rd1=x%0d d1=%h rd2=x%0d d2=%h",
        pipe.wb_addi2x_rd1,
        pipe.wb_addi2x_data1,
        pipe.wb_addi2x_rd2,
        pipe.wb_addi2x_data2
    );
end
"""
    s = insert_before_end_of_register_file_always(s, commit)

    write(path, s)
    print("IF_ID.v: decode/captura/forwarding/dual-commit ADDI2X instalados.")


# ============================================================================
# execute.v
# ============================================================================

def patch_execute(path: Path):
    s = read(path)

    if MARK in s:
        die("execute.v já contém ADDI2X_V1.")

    pos = s.rfind("endmodule")
    if pos < 0:
        die("execute.v: endmodule não localizado.")

    block = f"""
// ============================================================================
// {MARK}_EX_TO_WB
// ============================================================================
always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.wb_addi2x       <= 1'b0;
        pipe.wb_addi2x_rd1   <= 5'd0;
        pipe.wb_addi2x_rd2   <= 5'd0;
        pipe.wb_addi2x_data1 <= 32'd0;
        pipe.wb_addi2x_data2 <= 32'd0;
    end
    else if (!pipe.stall_read)
    begin
        pipe.wb_addi2x <= pipe.addi2x_ex_valid;

        if (pipe.addi2x_ex_valid)
        begin
            pipe.wb_addi2x_rd1   <= pipe.addi2x_ex_rd1;
            pipe.wb_addi2x_rd2   <= pipe.addi2x_ex_rd2;
            pipe.wb_addi2x_data1 <= pipe.addi2x_ex_result1;
            pipe.wb_addi2x_data2 <= pipe.addi2x_ex_result2;

            $display(
                "[ADDI2X_EX] b1=%h imm1=%0d r1=%h rd1=x%0d b2=%h imm2=%0d dep=%b r2=%h rd2=x%0d",
                pipe.addi2x_ex_base1,
                pipe.addi2x_ex_imm1,
                pipe.addi2x_ex_result1,
                pipe.addi2x_ex_rd1,
                pipe.addi2x_ex_base2,
                pipe.addi2x_ex_imm2,
                pipe.addi2x_ex_dep,
                pipe.addi2x_ex_result2,
                pipe.addi2x_ex_rd2
            );
        end
    end
    else
    begin
        pipe.wb_addi2x <= 1'b0;
    end
end

"""
    s = s[:pos] + block + s[pos:]
    write(path, s)
    print("execute.v: EX->WB ADDI2X instalado.")


# ============================================================================
# Validação / aplicação
# ============================================================================

def validate_rtl(dest: Path, mappings: list[dict]):
    p = read(dest / "pipeline.v")
    i = read(dest / "IF_ID.v")
    e = read(dest / "execute.v")

    for name, txt in (
        ("pipeline.v", p),
        ("IF_ID.v", i),
        ("execute.v", e),
    ):
        if MARK not in txt:
            die(f"validação: marcador {MARK} ausente em {name}")

    for mp in mappings:
        literal = f"32'h{mp['custom']}"
        if literal not in p:
            die(f"validação: CUSTOM {literal} ausente em pipeline.v")

    forbidden = ("addi2x_pending", "addi2x_replay", "addi2x_state")
    all_text = p + i + e
    for x in forbidden:
        if x in all_text:
            die(f"validação: mecanismo proibido encontrado: {x}")

    print("Validação RTL: OK.")


def apply_to_base(base: Path, dest: Path, hex_out: Path):
    for name in ("pipeline.v", "IF_ID.v", "execute.v"):
        src = dest / name
        dst = base / name
        backup = base / f"{name}.pre_addi2x"
        if not backup.exists():
            shutil.copy2(dst, backup)
        shutil.copy2(src, dst)
        print(f"aplicado: {src} -> {dst}")

    target_hex = base / hex_out.name
    if target_hex.exists():
        backup_hex = base / f"{target_hex.name}.pre_addi2x"
        if not backup_hex.exists():
            shutil.copy2(target_hex, backup_hex)

    shutil.copy2(hex_out, target_hex)
    print(f"aplicado: {hex_out} -> {target_hex}")


# ============================================================================
# Main
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="CUSTOM ADDI2X: ADDI+ADDI -> 1 CUSTOM, sem NOP."
    )

    ap.add_argument("base", type=Path)
    ap.add_argument("destino", type=Path)

    ap.add_argument(
        "--originais",
        nargs="+",
        required=True,
        help="Pares: ADDI1 ADDI2 ADDI3 ADDI4 ...",
    )

    ap.add_argument(
        "--ocorrencias",
        nargs="+",
        type=int,
        help="Ocorrência 1-based de cada par.",
    )

    ap.add_argument("--hex-entrada", type=Path, required=True)
    ap.add_argument("--hex-saida", type=Path, required=True)
    ap.add_argument("--sobrescrever", action="store_true")
    ap.add_argument("--aplicar-no-base", action="store_true")

    args = ap.parse_args()

    if len(args.originais) < 2 or len(args.originais) % 2:
        die("--originais precisa conter quantidade PAR de palavras ADDI.")

    pair_count = len(args.originais) // 2

    if args.ocorrencias is None:
        occurrences = [1] * pair_count
    else:
        if len(args.ocorrencias) != pair_count:
            die("--ocorrencias deve ter um número por par.")
        occurrences = args.ocorrencias

    if not args.base.is_dir():
        die(f"diretório base inexistente: {args.base}")

    required = ("pipeline.v", "IF_ID.v", "execute.v")
    for name in required:
        if not (args.base / name).exists():
            die(f"base sem arquivo obrigatório: {name}")

    base_all = "\n".join(read(args.base / x) for x in required)
    incremental = MARK in base_all
    if incremental:
        print("ADDI2X_V1 já existe na base: modo incremental ativado.")
        print("O RTL existente será reutilizado; somente os novos pares serão adicionados.")

    if args.destino.exists():
        if not args.sobrescrever:
            die("destino já existe; use --sobrescrever.")
        shutil.rmtree(args.destino)

    shutil.copytree(args.base, args.destino)

    words = parse_hex(args.hex_entrada)
    targets = control_targets(words)
    rtl_text = base_all

    mappings = []
    used_indices = set()

    for pair_no in range(pair_count):
        h1 = args.originais[2 * pair_no].lower().replace("0x", "")
        h2 = args.originais[2 * pair_no + 1].lower().replace("0x", "")

        first = decode_addi(h1)
        second = decode_addi(h2)

        idx = find_occurrence(words, h1, h2, occurrences[pair_no])

        if idx in used_indices or idx + 1 in used_indices:
            die("pares selecionados se sobrepõem.")

        validate_pair_safety(words, idx, targets)

        custom = choose_custom_word(words, rtl_text, pair_no)
        rtl_text += f" 32'h{custom}"

        mappings.append({
            "pair": pair_no + 1,
            "index": idx,
            "old_pc": idx * 4,
            "first": first,
            "second": second,
            "custom": custom,
            "dependency": (
                first["rd"] != 0 and
                second["rs1"] == first["rd"]
            ),
        })

        used_indices.add(idx)
        used_indices.add(idx + 1)

    new_words, reloc = compact_all(words, mappings)

    expected_len = len(words) - len(mappings)
    if len(new_words) != expected_len:
        die(
            f"compactação inconsistente: esperado {expected_len} palavras, "
            f"obtido {len(new_words)}."
        )

    args.hex_saida.parent.mkdir(parents=True, exist_ok=True)
    args.hex_saida.write_text("\n".join(new_words) + "\n", encoding="utf-8")

    if incremental:
        patch_pipeline_incremental(args.destino / "pipeline.v", mappings)
        print("IF_ID.v: ADDI2X existente reutilizado.")
        print("execute.v: ADDI2X existente reutilizado.")
    else:
        patch_pipeline(args.destino / "pipeline.v", mappings)
        patch_ifid(args.destino / "IF_ID.v")
        patch_execute(args.destino / "execute.v")

    dest_hex = args.destino / args.hex_saida.name
    if args.hex_saida.resolve() != dest_hex.resolve():
        shutil.copy2(args.hex_saida, dest_hex)

    validate_rtl(args.destino, mappings)

    print()
    print("=" * 72)
    print("CUSTOM ADDI2X - SEM NOP")
    print("=" * 72)
    print(f"Pares          : {len(mappings)}")
    print(f"Palavras antes : {len(words)}")
    print(f"Palavras depois: {len(new_words)}")
    print(f"Removidas      : {len(words) - len(new_words)} (1 por par)")
    print(f"Relocações     : {len(reloc)}")

    for mp in mappings:
        f = mp["first"]
        g = mp["second"]
        print()
        print(
            f"Par {mp['pair']}: PC antigo 0x{mp['old_pc']:08x} "
            f"-> CUSTOM {mp['custom']}"
        )
        print(
            f"  ADDI1: x{f['rd']} = x{f['rs1']} + {f['imm']}"
        )
        print(
            f"  ADDI2: x{g['rd']} = x{g['rs1']} + {g['imm']}"
        )
        print(
            "  dependência interna: "
            + ("SIM" if mp["dependency"] else "NÃO")
        )

    print()
    print("Nenhum NOP foi inserido.")
    print("memory.v e tb_pipeline.v não foram alterados.")

    if args.aplicar_no_base:
        apply_to_base(args.base, args.destino, args.hex_saida)


if __name__ == "__main__":
    main()