#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CUSTOM LW2X - compactação real sem NOP - V6 incremental real.

Objetivo
--------
Transformar pares consecutivos:

    lw rd1, imm1(rs1a)
    lw rd2, imm2(rs1b)

em UMA instrução CUSTOM de 32 bits.

Arquitetura RTL criada
----------------------
1. IF/ID:
   - reconhece a palavra CUSTOM;
   - NÃO executa leitura de memória;
   - captura base1/base2, imm1/imm2 e rd1/rd2 em registradores EX.

2. EX:
   - calcula os dois endereços;
   - usa DUAS portas combinacionais exclusivas da DMEM;
   - no próximo posedge captura os dois dados em registradores WB.

3. WB:
   - grava rd1 e rd2 no banco de registradores;
   - fornece forwarding para a instrução imediatamente seguinte.

Não usa:
- replay;
- pending;
- drain;
- FSM;
- stall específico da CUSTOM;
- palavra NOP reservada.

O segundo LW é realmente removido do HEX. BRANCH/JAL são relocados.

Uso
---
python3 customizar_lw2x_novo_do_zero.py BASE DESTINO \
    --hex-entrada imem.hex \
    --hex-saida imem_custom.hex \
    --originais fec42703 fd842783 \
    --sobrescrever

Para vários pares:
    --originais LW1 LW2 LW3 LW4 ...

Opcional:
    --ocorrencias 1 2 ...
    --aplicar-no-base
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


MARK = "LW2X_COMPACT_V4"
EXISTING_MARKS = ("LW2X_ZERO_V1", "LW2X_COMPACT_V4")
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
# RV32I decode / encode
# ============================================================================

def decode_lw(h: str) -> dict:
    h = h.lower().replace("0x", "")
    if not HEX8.fullmatch(h):
        die(f"hex inválido: {h}")

    w = int(h, 16)
    opcode = w & 0x7f
    funct3 = (w >> 12) & 7

    if opcode != 0x03 or funct3 != 0b010:
        die(f"{h} não é LW RV32I.")

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

    mask = (
        (1 << 31) |
        (1 << 7) |
        (0x3f << 25) |
        (0xf << 8)
    )
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

    mask = (
        (1 << 31) |
        (0xff << 12) |
        (1 << 20) |
        (0x3ff << 21)
    )
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
    """
    Usa opcode CUSTOM-0 0x0B.
    A palavra inteira é apenas um ID para lookup no RTL.
    Não tentamos codificar todos os operandos dentro dos 32 bits.
    """
    used = {x.lower() for x in words}
    used |= {
        x.lower()
        for x in re.findall(r"32'h([0-9a-fA-F]{8})", rtl_text)
    }

    # opcode 0x0b; bits superiores funcionam apenas como ID.
    for tag in range(1 + ordinal, 1 << 20):
        w = ((tag & 0xfffff) << 12) | (0b111 << 7) | 0x0b
        hx = h32(w)
        if hx not in used:
            return hx

    die("não foi possível escolher palavra CUSTOM livre.")


def map_pc_after_deletions(pc: int, deleted_pcs: list[int]) -> int:
    return pc - 4 * sum(1 for d in deleted_pcs if d < pc)


def compact_all(words: list[str], pair_specs: list[dict]) -> tuple[list[str], list[dict]]:
    """
    pair_specs inicialmente contém índices no HEX ORIGINAL.
    Remove sempre o segundo LW de cada par e reloca BRANCH/JAL globalmente.
    """
    deleted_pcs = sorted((p["index"] + 1) * 4 for p in pair_specs)
    deleted_set = set(deleted_pcs)

    custom_by_pc = {
        p["index"] * 4: p["custom"]
        for p in pair_specs
    }

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
# Text helpers
# ============================================================================

def find_matching_begin_end(s: str, begin_pos: int) -> int:
    """
    begin_pos aponta para o início da palavra 'begin'.
    Retorna posição imediatamente após o 'end' correspondente.
    """
    token_re = re.compile(r"\bbegin\b|\bend\b")
    depth = 0

    for m in token_re.finditer(s, begin_pos):
        tok = m.group(0)
        if tok == "begin":
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

    # abs_end aponta após 'end'; inserir antes do end externo.
    end_start = s.rfind("end", abs_begin, abs_end)
    if end_start < 0:
        die("IF_ID.v: fim do always do register file não localizado.")

    return s[:end_start] + block + "\n" + s[end_start:]


def prepend_rhs_to_continuous_assign(
    s: str,
    signal: str,
    prefix_rhs: str,
) -> str:
    """
    Reescreve:
      assign SIGNAL = RHS;
    como:
      assign SIGNAL = PREFIX RHS;
    preservando o RHS original integralmente.
    """
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


def ternary_table(mappings: list[dict], field_fn, default: str, key="instruction") -> str:
    lines = []
    for mp in mappings:
        lines.append(
            f"({key} == 32'h{mp['custom']}) ? {field_fn(mp)} :"
        )
    lines.append(default)
    return "\n        ".join(lines)


# ============================================================================
# Safety
# ============================================================================

def validate_pair_safety(
    words: list[str],
    idx: int,
    first: dict,
    second: dict,
    targets: set[int],
):
    second_pc = (idx + 1) * 4

    if second_pc in targets:
        die(
            f"não é seguro remover o segundo LW em PC=0x{second_pc:08x}: "
            "ele é alvo de BRANCH/JAL."
        )

    # A segunda LW não pode usar como BASE o resultado da primeira,
    # pois as duas leituras ocorrerão em paralelo.
    if first["rd"] != 0 and second["rs1"] == first["rd"]:
        die(
            "par LW possui dependência interna: a segunda LW usa rd1 como rs1. "
            "Esse par não pode ser executado como dual-read paralelo."
        )

    # STORE imediatamente anterior NÃO bloqueia a fusão.
    # A CUSTOM continua entrando no pipeline na ordem arquitetural normal.
    # Mantemos apenas as verificações que tornam o paralelismo semanticamente
    # impossível (dependência interna) ou quebrariam o fluxo de controle.


# ============================================================================
# memory.v
# ============================================================================

def patch_memory(path: Path):
    s = read(path)

    if any(m in s for m in EXISTING_MARKS):
        print(f"{path.name}: infraestrutura LW2X já existe; reutilizando.")
        return

    # Porta: inserimos antes do fechamento da lista de ports.
    # Procuramos o último input read2_address, presente no módulo base.
    pm = re.search(
        r"(input\s+\[\s*31\s*:\s*2\s*\]\s+read2_address\s*)"
        r"(?P<tail>,?\s*\n\s*\)\s*;)",
        s,
        re.MULTILINE,
    )

    if not pm:
        die("memory.v: porta read2_address / fechamento do módulo não localizado.")

    original = pm.group(1)
    repl = original.rstrip() + f""",
    // {MARK}_PORTS
    input       [31:2] lw2x_read1_address,
    input       [31:2] lw2x_read2_address,
    output wire [31:0] lw2x_read1_data,
    output wire [31:0] lw2x_read2_data
);
"""
    s = s[:pm.start()] + repl + s[pm.end():]

    # Precisamos de ADDR e memory[]. Inserimos após declaração do array.
    array_pat = re.compile(
        r"(reg\s+\[\s*31\s*:\s*0\s*\]\s+memory\s*\[\s*\(SIZE/4\)-1\s*:\s*0\s*\]\s*;)"
    )
    am = array_pat.search(s)
    if not am:
        die("memory.v: array memory[] não localizado.")

    block = f"""
    // {MARK}_ASYNC_DUAL_READ
    wire [ADDR-1:0] lw2x_read1_addr;
    wire [ADDR-1:0] lw2x_read2_addr;

    assign lw2x_read1_addr = lw2x_read1_address[ADDR+1:2];
    assign lw2x_read2_addr = lw2x_read2_address[ADDR+1:2];

    // Leituras combinacionais exclusivas da CUSTOM.
    assign lw2x_read1_data = memory[lw2x_read1_addr];
    assign lw2x_read2_data = memory[lw2x_read2_addr];
"""
    s = s[:am.end()] + block + s[am.end():]

    write(path, s)
    print("memory.v: duas portas combinacionais LW2X instaladas.")


# ============================================================================
# pipeline.v
# ============================================================================

def patch_pipeline(path: Path, mappings: list[dict]):
    s = read(path)

    if any(m in s for m in EXISTING_MARKS):
        print(f"{path.name}: infraestrutura LW2X já existe; ampliando tabela de CUSTOMs.")

        def get_assign(name: str):
            m = re.search(
                rf"(assign\s+{re.escape(name)}\s*=\s*)(.*?)(;)",
                s,
                re.DOTALL,
            )
            if not m:
                die(f"pipeline.v: assign {name} não localizado na infraestrutura existente.")
            return m

        def prepend_match(text: str, custom: str):
            # Evita duplicação se a CUSTOM já estiver cadastrada.
            literal = f"32'h{custom}"
            if literal in text:
                return text
            return f"(instruction == {literal}) ||\n        ({text.strip()})"

        def prepend_ternary(text: str, custom: str, value: str):
            literal = f"32'h{custom}"
            if literal in text:
                return text
            return (
                f"(instruction == {literal}) ? {value} :\n"
                f"        {text.strip()}"
            )

        updates = {
            "lw2x_fetch_match": ("match", None),
            "lw2x_fetch_rs1a": ("ternary", lambda mp: f"5'd{mp['first']['rs1']}"),
            "lw2x_fetch_rs1b": ("ternary", lambda mp: f"5'd{mp['second']['rs1']}"),
            "lw2x_fetch_rd1":  ("ternary", lambda mp: f"5'd{mp['first']['rd']}"),
            "lw2x_fetch_rd2":  ("ternary", lambda mp: f"5'd{mp['second']['rd']}"),
            "lw2x_fetch_imm1": ("ternary", lambda mp: v_s32(mp["first"]["imm"])),
            "lw2x_fetch_imm2": ("ternary", lambda mp: v_s32(mp["second"]["imm"])),
        }

        # Atualiza uma atribuição por vez sobre a versão corrente do texto.
        for name, (kind, value_fn) in updates.items():
            m = get_assign(name)
            expr = m.group(2)

            for mp in mappings:
                if kind == "match":
                    expr = prepend_match(expr, mp["custom"])
                else:
                    expr = prepend_ternary(expr, mp["custom"], value_fn(mp))

            s = s[:m.start(2)] + expr + s[m.end(2):]

        # Confirma que todos os novos opcodes entraram na tabela.
        for mp in mappings:
            literal = f"32'h{mp['custom']}"
            if literal not in s:
                die(f"pipeline.v: falha ao adicionar {literal} à tabela LW2X.")

        write(path, s)
        print(f"pipeline.v: {len(mappings)} novo(s) par(es) LW2X adicionado(s) à tabela.")
        return

    # Novas entradas da DMEM.
    anchor_re = re.compile(
        r"(input\s+\[\s*31\s*:\s*0\s*\]\s+dmem_read2_data_temp\s*,?)"
    )
    m = anchor_re.search(s)
    if not m:
        die("pipeline.v: dmem_read2_data_temp não localizado.")

    old = m.group(1).rstrip().rstrip(",")
    new = old + f""",
    // {MARK}_DMEM_INPUTS
    input           [31:0] dmem_lw2x_read1_data_temp,
    input           [31:0] dmem_lw2x_read2_data_temp,"""

    s = s[:m.start()] + new + s[m.end():]

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

    block = f"""
    // ========================================================================
    // {MARK}
    // IF/ID -> EX -> WB; duas leituras combinacionais na DMEM.
    // ========================================================================

    wire        lw2x_fetch_match;
    wire [4:0]  lw2x_fetch_rs1a;
    wire [4:0]  lw2x_fetch_rs1b;
    wire [4:0]  lw2x_fetch_rd1;
    wire [4:0]  lw2x_fetch_rd2;
    wire signed [31:0] lw2x_fetch_imm1;
    wire signed [31:0] lw2x_fetch_imm2;
    wire [31:0] lw2x_fetch_base1;
    wire [31:0] lw2x_fetch_base2;

    // Registradores IF/ID -> EX exclusivos da CUSTOM.
    reg         lw2x_ex_valid;
    reg [4:0]   lw2x_ex_rd1;
    reg [4:0]   lw2x_ex_rd2;
    reg signed [31:0] lw2x_ex_imm1;
    reg signed [31:0] lw2x_ex_imm2;
    reg [31:0]  lw2x_ex_base1;
    reg [31:0]  lw2x_ex_base2;

    wire [31:0] lw2x_ex_addr1;
    wire [31:0] lw2x_ex_addr2;
    wire [31:0] lw2x_ex_data1;
    wire [31:0] lw2x_ex_data2;

    // Registradores EX -> WB.
    reg         wb_lw2x;
    reg [4:0]   wb_lw2x_rd1;
    reg [4:0]   wb_lw2x_rd2;
    reg [31:0]  wb_lw2x_data1;
    reg [31:0]  wb_lw2x_data2;

    assign lw2x_fetch_match =
        {match_expr};

    assign lw2x_fetch_rs1a =
        {rs1a};

    assign lw2x_fetch_rs1b =
        {rs1b};

    assign lw2x_fetch_rd1 =
        {rd1};

    assign lw2x_fetch_rd2 =
        {rd2};

    assign lw2x_fetch_imm1 =
        {imm1};

    assign lw2x_fetch_imm2 =
        {imm2};

    // Base atual com forwarding do WB normal e do WB LW2X.
    // rd2 tem prioridade quando rd1 == rd2 porque a segunda LW é posterior.
    assign lw2x_fetch_base1 =
        (lw2x_fetch_rs1a == 5'd0) ? 32'd0 :
        (wb_lw2x &&
         wb_lw2x_rd2 != 5'd0 &&
         wb_lw2x_rd2 == lw2x_fetch_rs1a) ?
            wb_lw2x_data2 :
        (wb_lw2x &&
         wb_lw2x_rd1 != 5'd0 &&
         wb_lw2x_rd1 == lw2x_fetch_rs1a) ?
            wb_lw2x_data1 :
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == lw2x_fetch_rs1a) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[lw2x_fetch_rs1a];

    assign lw2x_fetch_base2 =
        (lw2x_fetch_rs1b == 5'd0) ? 32'd0 :
        (wb_lw2x &&
         wb_lw2x_rd2 != 5'd0 &&
         wb_lw2x_rd2 == lw2x_fetch_rs1b) ?
            wb_lw2x_data2 :
        (wb_lw2x &&
         wb_lw2x_rd1 != 5'd0 &&
         wb_lw2x_rd1 == lw2x_fetch_rs1b) ?
            wb_lw2x_data1 :
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == lw2x_fetch_rs1b) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[lw2x_fetch_rs1b];

    assign lw2x_ex_addr1 = lw2x_ex_base1 + lw2x_ex_imm1;
    assign lw2x_ex_addr2 = lw2x_ex_base2 + lw2x_ex_imm2;

    // LW2X_ZERO_V3_STORE_FORWARD
    // Reproduz o bypass write->read existente nas portas normais da memory.v.
    wire [31:0] lw2x_store_mask1 = {{
        {{8{{dmem_write_byte[3]}}}},
        {{8{{dmem_write_byte[2]}}}},
        {{8{{dmem_write_byte[1]}}}},
        {{8{{dmem_write_byte[0]}}}}
    }};

    wire [31:0] lw2x_store2_mask = {{
        {{8{{dmem_write2_byte[3]}}}},
        {{8{{dmem_write2_byte[2]}}}},
        {{8{{dmem_write2_byte[1]}}}},
        {{8{{dmem_write2_byte[0]}}}}
    }};

    wire lw2x_store_hit1_a =
        dmem_write_ready &&
        (dmem_write_address[31:2] == lw2x_ex_addr1[31:2]);

    wire lw2x_store_hit1_b =
        dmem_write_ready &&
        (dmem_write_address[31:2] == lw2x_ex_addr2[31:2]);

    wire lw2x_store_hit2_a =
        dmem_write2_ready &&
        (dmem_write2_address[31:2] == lw2x_ex_addr1[31:2]);

    wire lw2x_store_hit2_b =
        dmem_write2_ready &&
        (dmem_write2_address[31:2] == lw2x_ex_addr2[31:2]);

    wire [31:0] lw2x_after_store1_a =
        lw2x_store_hit1_a ?
            ((dmem_lw2x_read1_data_temp & ~lw2x_store_mask1) |
             (dmem_write_data            &  lw2x_store_mask1)) :
            dmem_lw2x_read1_data_temp;

    wire [31:0] lw2x_after_store1_b =
        lw2x_store_hit1_b ?
            ((dmem_lw2x_read2_data_temp & ~lw2x_store_mask1) |
             (dmem_write_data            &  lw2x_store_mask1)) :
            dmem_lw2x_read2_data_temp;

    assign lw2x_ex_data1 =
        lw2x_store_hit2_a ?
            ((lw2x_after_store1_a & ~lw2x_store2_mask) |
             (dmem_write2_data     &  lw2x_store2_mask)) :
            lw2x_after_store1_a;

    assign lw2x_ex_data2 =
        lw2x_store_hit2_b ?
            ((lw2x_after_store1_b & ~lw2x_store2_mask) |
             (dmem_write2_data     &  lw2x_store2_mask)) :
            lw2x_after_store1_b;

"""

    s = s.replace(section, block + section, 1)

    write(path, s)
    print("pipeline.v: sinais LW2X IF/ID -> EX -> WB instalados.")


# ============================================================================
# IF_ID.v
# ============================================================================

def patch_ifid(path: Path):
    s = read(path)

    if any(m in s for m in EXISTING_MARKS):
        print(f"{path.name}: infraestrutura LW2X já existe; reutilizando.")
        return

    # 1) CUSTOM não é illegal.
    illegal_anchor = "pipe.illegal_inst                  = 1'b0;"
    if illegal_anchor not in s:
        # fallback: acha início do always combinacional de immediate.
        case_pos = s.find("case(pipe.instruction[`OPCODE])")
        if case_pos < 0:
            die("IF_ID.v: decoder opcode não localizado.")
        # inserimos override DEPOIS do endcase.
        endcase = s.find("endcase", case_pos)
        if endcase < 0:
            die("IF_ID.v: endcase do decoder não localizado.")
        insert_pos = endcase + len("endcase")
        s = (
            s[:insert_pos]
            + f"""
// {MARK}_LEGAL
if (pipe.lw2x_fetch_match)
begin
    pipe.immediate    = 32'd0;
    pipe.illegal_inst = 1'b0;
end
"""
            + s[insert_pos:]
        )
    else:
        # Ainda precisamos override ao final do case, não no início.
        case_pos = s.find("case(pipe.instruction[`OPCODE])")
        endcase = s.find("endcase", case_pos)
        if case_pos < 0 or endcase < 0:
            die("IF_ID.v: case/endcase do decoder não localizado.")
        insert_pos = endcase + len("endcase")
        s = (
            s[:insert_pos]
            + f"""
// {MARK}_LEGAL
if (pipe.lw2x_fetch_match)
begin
    pipe.immediate    = 32'd0;
    pipe.illegal_inst = 1'b0;
end
"""
            + s[insert_pos:]
        )

    # 2) Reset dos registradores EX.
    reset_candidates = list(
        re.finditer(r"pipe\.mem_to_reg\s*<=\s*1'b0\s*;", s)
    )
    if not reset_candidates:
        die("IF_ID.v: reset de mem_to_reg não localizado.")

    # Primeiro reset antes do bloco normal de decode.
    rm = reset_candidates[0]
    reset_block = f"""
    // {MARK}_RESET_EX
    pipe.lw2x_ex_valid <= 1'b0;
    pipe.lw2x_ex_rd1   <= 5'd0;
    pipe.lw2x_ex_rd2   <= 5'd0;
    pipe.lw2x_ex_imm1  <= 32'sd0;
    pipe.lw2x_ex_imm2  <= 32'sd0;
    pipe.lw2x_ex_base1 <= 32'd0;
    pipe.lw2x_ex_base2 <= 32'd0;
"""
    s = s[:rm.end()] + reset_block + s[rm.end():]

    # 3) Captura IF/ID -> EX.
    # Localizamos a ocorrência REAL de execute_immediate <= pipe.immediate;
    exec_pat = re.compile(
        r"pipe\.execute_immediate\s*<=\s*pipe\.immediate\s*;"
    )
    em = exec_pat.search(s)
    if not em:
        die("IF_ID.v: decode 'execute_immediate <= pipe.immediate' não localizado.")

    capture = f"""
    // {MARK}_CAPTURE_EX
    pipe.lw2x_ex_valid <= pipe.lw2x_fetch_match;
    if (pipe.lw2x_fetch_match)
    begin
        pipe.lw2x_ex_rd1   <= pipe.lw2x_fetch_rd1;
        pipe.lw2x_ex_rd2   <= pipe.lw2x_fetch_rd2;
        pipe.lw2x_ex_imm1  <= pipe.lw2x_fetch_imm1;
        pipe.lw2x_ex_imm2  <= pipe.lw2x_fetch_imm2;
        pipe.lw2x_ex_base1 <= pipe.lw2x_fetch_base1;
        pipe.lw2x_ex_base2 <= pipe.lw2x_fetch_base2;
    end
"""
    s = s[:em.start()] + capture + s[em.start():]

    # 3b) Neutraliza explicitamente o caminho normal quando a palavra exata
    # é uma LW2X.
    mem_assigns = list(
        re.finditer(
            r"pipe\.mem_to_reg\s*<=\s*[^;]+;",
            s,
            re.MULTILINE,
        )
    )
    if not mem_assigns:
        die("IF_ID.v: atribuição normal de mem_to_reg não localizada.")

    # Escolhe a atribuição sequencial mais próxima do decode/capture.
    exec_pos2 = s.find("pipe.execute_immediate", s.find(MARK + "_CAPTURE_EX"))
    candidates = [x for x in mem_assigns if x.start() > exec_pos2]
    mm = candidates[0] if candidates else mem_assigns[-1]

    neutral = f"""
    // {MARK}_NEUTRALIZE_NORMAL_PATH
    if (pipe.lw2x_fetch_match)
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

    # 4) Forwarding WB LW2X para consumidor seguinte.
    prefix1 = f"""    // {MARK}_FWD_R1
    (pipe.wb_lw2x &&
     pipe.wb_lw2x_rd2 != 5'd0 &&
     pipe.wb_lw2x_rd2 == pipe.src1_select) ?
        pipe.wb_lw2x_data2 :
    (pipe.wb_lw2x &&
     pipe.wb_lw2x_rd1 != 5'd0 &&
     pipe.wb_lw2x_rd1 == pipe.src1_select) ?
        pipe.wb_lw2x_data1 :"""

    prefix2 = f"""    // {MARK}_FWD_R2
    (pipe.wb_lw2x &&
     pipe.wb_lw2x_rd2 != 5'd0 &&
     pipe.wb_lw2x_rd2 == pipe.src2_select) ?
        pipe.wb_lw2x_data2 :
    (pipe.wb_lw2x &&
     pipe.wb_lw2x_rd1 != 5'd0 &&
     pipe.wb_lw2x_rd1 == pipe.src2_select) ?
        pipe.wb_lw2x_data1 :"""

    s = prepend_rhs_to_continuous_assign(s, "pipe.reg_rdata1", prefix1)
    s = prepend_rhs_to_continuous_assign(s, "pipe.reg_rdata2", prefix2)

    # 5) Dual-commit no mesmo always do banco, independente do chain normal.
    commit = f"""
// {MARK}_DUAL_COMMIT
if (reset && pipe.wb_lw2x)
begin
    if (pipe.wb_lw2x_rd1 != 5'd0)
        pipe.regs[pipe.wb_lw2x_rd1] <= pipe.wb_lw2x_data1;

    // Segunda LW tem prioridade arquitetural se rd1 == rd2.
    if (pipe.wb_lw2x_rd2 != 5'd0)
        pipe.regs[pipe.wb_lw2x_rd2] <= pipe.wb_lw2x_data2;

    $display(
        "[LW2X_WB] rd1=x%0d d1=%h rd2=x%0d d2=%h",
        pipe.wb_lw2x_rd1,
        pipe.wb_lw2x_data1,
        pipe.wb_lw2x_rd2,
        pipe.wb_lw2x_data2
    );
end
"""
    s = insert_before_end_of_register_file_always(s, commit)

    write(path, s)
    print("IF_ID.v: legalização, captura EX, forwarding e dual-commit instalados.")


# ============================================================================
# execute.v
# ============================================================================

def patch_execute(path: Path):
    s = read(path)

    if any(m in s for m in EXISTING_MARKS):
        print(f"{path.name}: infraestrutura LW2X já existe; reutilizando.")
        return

    pos = s.rfind("endmodule")
    if pos < 0:
        die("execute.v: endmodule não localizado.")

    block = f"""
// ============================================================================
// {MARK}_EX_TO_WB
// Únicos registradores EX -> WB da CUSTOM LW2X.
// ============================================================================
always @(posedge clk or negedge reset)
begin
    if (!reset)
    begin
        pipe.wb_lw2x       <= 1'b0;
        pipe.wb_lw2x_rd1   <= 5'd0;
        pipe.wb_lw2x_rd2   <= 5'd0;
        pipe.wb_lw2x_data1 <= 32'd0;
        pipe.wb_lw2x_data2 <= 32'd0;
    end
    else if (!pipe.stall_read)
    begin
        pipe.wb_lw2x <= pipe.lw2x_ex_valid;

        if (pipe.lw2x_ex_valid)
        begin
            pipe.wb_lw2x_rd1   <= pipe.lw2x_ex_rd1;
            pipe.wb_lw2x_rd2   <= pipe.lw2x_ex_rd2;
            pipe.wb_lw2x_data1 <= pipe.lw2x_ex_data1;
            pipe.wb_lw2x_data2 <= pipe.lw2x_ex_data2;

            $display(
                "[LW2X_EX] a1=%h raw1=%h d1=%h rd1=x%0d a2=%h raw2=%h d2=%h rd2=x%0d wr1=%b/%h wr2=%b/%h",
                pipe.lw2x_ex_addr1,
                pipe.dmem_lw2x_read1_data_temp,
                pipe.lw2x_ex_data1,
                pipe.lw2x_ex_rd1,
                pipe.lw2x_ex_addr2,
                pipe.dmem_lw2x_read2_data_temp,
                pipe.lw2x_ex_data2,
                pipe.lw2x_ex_rd2,
                pipe.dmem_write_ready,
                pipe.dmem_write_address,
                pipe.dmem_write2_ready,
                pipe.dmem_write2_address
            );
        end
    end
    else
    begin
        // Não repete commit durante stall global.
        pipe.wb_lw2x <= 1'b0;
    end
end

"""
    s = s[:pos] + block + s[pos:]

    write(path, s)
    print("execute.v: registro EX -> WB LW2X instalado.")


# ============================================================================
# tb_pipeline.v
# ============================================================================

def add_named_ports_to_instance(
    s: str,
    module_name: str,
    instance_hint: str,
    anchor_port: str,
    new_ports: str,
    occurrence: int = 1,
) -> str:
    """
    Procura .anchor_port(...) dentro de uma instancia e adiciona portas
    imediatamente depois. occurrence é 1-based.
    """
    hits = list(re.finditer(
        rf"\.{re.escape(anchor_port)}\s*\([^;]+?\)",
        s,
        re.DOTALL,
    ))

    if len(hits) < occurrence:
        die(
            f"tb_pipeline.v: porta .{anchor_port}(...) ocorrência "
            f"{occurrence} não localizada."
        )

    m = hits[occurrence - 1]
    text = m.group(0)

    # Garante vírgula depois da porta existente.
    replacement = text.rstrip()
    if not replacement.endswith(","):
        replacement += ","

    replacement += "\n" + new_ports
    return s[:m.start()] + replacement + s[m.end():]


def patch_tb(path: Path):
    s = read(path)

    if any(m in s for m in EXISTING_MARKS):
        print(f"{path.name}: infraestrutura LW2X já existe; reutilizando.")
        return

    # ---------------------------------------------------------------------
    # Wires de retorno da DMEM.
    # ---------------------------------------------------------------------
    decl_anchor = re.search(
        r"(wire\s+\[\s*31\s*:\s*0\s*\]\s+dmem_read2_data_temp\s*;)",
        s,
    )
    if not decl_anchor:
        decl_anchor = re.search(
            r"(wire\s+\[\s*31\s*:\s*0\s*\]\s+dmem_read2_data\s*;)",
            s,
        )
    if not decl_anchor:
        die("tb_pipeline.v: wire de dmem read2 não localizado.")

    wires = f"""
    // {MARK}_WIRES
    wire [31:0] dmem_lw2x_read1_data_temp;
    wire [31:0] dmem_lw2x_read2_data_temp;
"""
    s = s[:decl_anchor.end()] + wires + s[decl_anchor.end():]

    # ---------------------------------------------------------------------
    # Instância pipe.
    # ---------------------------------------------------------------------
    pipe_inst = re.search(
        r"\bpipe\s+pipe\s*\(",
        s,
        re.MULTILINE,
    )
    if not pipe_inst:
        die("tb_pipeline.v: instância 'pipe pipe(' não localizada.")

    pipe_end = s.find(");", pipe_inst.end())
    if pipe_end < 0:
        die("tb_pipeline.v: fim da instância pipe não localizado.")

    pipe_block = s[pipe_inst.start():pipe_end + 2]

    anchor = None
    for name in ("dmem_read2_data_temp", "dmem_read_data_temp"):
        mm = re.search(rf"\.{name}\s*\([^)]*\)", pipe_block)
        if mm:
            anchor = mm
            break

    if not anchor:
        die("tb_pipeline.v: conexão de leitura DMEM na instância pipe não localizada.")

    abs_start = pipe_inst.start() + anchor.start()
    abs_end = pipe_inst.start() + anchor.end()

    current = s[abs_start:abs_end].rstrip()
    if not current.endswith(","):
        current += ","

    pins = f"""
    // {MARK}_PIPE
    .dmem_lw2x_read1_data_temp(dmem_lw2x_read1_data_temp),
    .dmem_lw2x_read2_data_temp(dmem_lw2x_read2_data_temp)"""

    s = s[:abs_start] + current + pins + s[abs_end:]

    # ---------------------------------------------------------------------
    # Localiza uma instância memory PELO NOME, não pela ordem.
    # Isso corrige o bug anterior em que a segunda memory foi considerada
    # DMEM, mas no seu testbench a primeira é dmem e a segunda é inst_mem.
    # ---------------------------------------------------------------------
    def find_memory_instance(text: str, instance_name: str):
        pat = re.compile(
            rf"\bmemory\s*#\s*\(.*?\)\s*{re.escape(instance_name)}\s*\(",
            re.DOTALL,
        )
        m = pat.search(text)
        if not m:
            die(f"tb_pipeline.v: instância memory '{instance_name}' não localizada.")

        # início dos ports = último '(' do match
        ports_start = m.end() - 1

        # Procura ');' que fecha a instância.
        ports_end = text.find(");", ports_start)
        if ports_end < 0:
            die(f"tb_pipeline.v: fim da instância '{instance_name}' não localizado.")

        return m.start(), ports_start, ports_end + 2

    # ---------------------------------------------------------------------
    # DMEM: conecta as portas LW2X aos endereços do EX.
    # ---------------------------------------------------------------------
    _, dmem_ports_start, dmem_end = find_memory_instance(s, "dmem")
    dmem_block = s[dmem_ports_start:dmem_end]

    dm_anchor = re.search(
        r"\.read2_address\s*\([^)]*\)",
        dmem_block,
    )
    if not dm_anchor:
        die("tb_pipeline.v: .read2_address da DMEM não localizado.")

    abs_start = dmem_ports_start + dm_anchor.start()
    abs_end = dmem_ports_start + dm_anchor.end()

    current = s[abs_start:abs_end].rstrip()
    if not current.endswith(","):
        current += ","

    dpins = f"""
        // {MARK}_DMEM
        .lw2x_read1_address(pipe.lw2x_ex_addr1[31:2]),
        .lw2x_read2_address(pipe.lw2x_ex_addr2[31:2]),
        .lw2x_read1_data(dmem_lw2x_read1_data_temp),
        .lw2x_read2_data(dmem_lw2x_read2_data_temp)"""

    s = s[:abs_start] + current + dpins + s[abs_end:]

    # ---------------------------------------------------------------------
    # IMEM: novas portas existem no módulo memory, então precisam estar
    # conectadas, mas ficam amarradas em zero e seus dados são ignorados.
    # ---------------------------------------------------------------------
    _, imem_ports_start, imem_end = find_memory_instance(s, "inst_mem")
    imem_block = s[imem_ports_start:imem_end]

    im_anchor = re.search(
        r"\.read2_address\s*\([^)]*\)",
        imem_block,
    )
    if not im_anchor:
        die("tb_pipeline.v: .read2_address da IMEM não localizado.")

    abs_start = imem_ports_start + im_anchor.start()
    abs_end = imem_ports_start + im_anchor.end()

    current = s[abs_start:abs_end].rstrip()
    if not current.endswith(","):
        current += ","

    ipins = f"""
        // {MARK}_IMEM_UNUSED
        .lw2x_read1_address(30'd0),
        .lw2x_read2_address(30'd0),
        .lw2x_read1_data(),
        .lw2x_read2_data()"""

    s = s[:abs_start] + current + ipins + s[abs_end:]

    # Validação local: as portas de dados LW2X devem aparecer DENTRO
    # da instância dmem, nunca somente em inst_mem.
    _, dps, de = find_memory_instance(s, "dmem")
    final_dmem_block = s[dps:de]
    if "dmem_lw2x_read1_data_temp" not in final_dmem_block:
        die("tb_pipeline.v: LW2X read1 não ficou conectada à DMEM.")
    if "dmem_lw2x_read2_data_temp" not in final_dmem_block:
        die("tb_pipeline.v: LW2X read2 não ficou conectada à DMEM.")

    write(path, s)
    print("tb_pipeline.v: LW2X conectada explicitamente à instância dmem.")


# ============================================================================
# Validation
# ============================================================================

def validate_rtl(dest: Path, mappings: list[dict]):
    p = read(dest / "pipeline.v")
    i = read(dest / "IF_ID.v")
    e = read(dest / "execute.v")
    m = read(dest / "memory.v")
    t = read(dest / "tb_pipeline.v")

    checks = {
        "memory dual async":
            f"{MARK}_ASYNC_DUAL_READ" in m,
        "pipeline inputs":
            "dmem_lw2x_read1_data_temp" in p
            and "dmem_lw2x_read2_data_temp" in p,
        "IF/ID capture":
            f"{MARK}_CAPTURE_EX" in i,
        "EX->WB":
            f"{MARK}_EX_TO_WB" in e,
        "dual commit":
            f"{MARK}_DUAL_COMMIT" in i,
        "forward R1/R2":
            f"{MARK}_FWD_R1" in i
            and f"{MARK}_FWD_R2" in i,
        "TB DMEM":
            f"{MARK}_DMEM" in t,
        "sem replay":
            "lw2x_replay" not in (p + i + e),
        "sem FSM":
            "lw2x_state" not in (p + i + e),
        "sem pending":
            "lw2x_pending" not in (p + i + e),
    }

    for mp in mappings:
        checks[f"custom {mp['custom']}"] = f"32'h{mp['custom']}" in p

    bad = [name for name, ok in checks.items() if not ok]
    if bad:
        die("validação RTL falhou: " + ", ".join(bad))

    print("Validação RTL LW2X: OK")


def apply_to_base(base: Path, dest: Path, hex_out: Path):
    for name in (
        "pipeline.v",
        "IF_ID.v",
        "execute.v",
        "memory.v",
        "tb_pipeline.v",
    ):
        src = dest / name
        dst = base / name

        backup = base / f"{name}.pre_{MARK.lower()}"
        if dst.exists() and not backup.exists():
            shutil.copy2(dst, backup)

        shutil.copy2(src, dst)
        print(f"aplicado: {src} -> {dst}")

    target_hex = base / hex_out.name
    if target_hex.exists():
        bak = base / f"{target_hex.name}.pre_{MARK.lower()}"
        if not bak.exists():
            shutil.copy2(target_hex, bak)

    shutil.copy2(hex_out, target_hex)
    print(f"aplicado: {hex_out} -> {target_hex}")


# ============================================================================
# Main
# ============================================================================

def main():
    print("V6 incremental real: reutiliza RTL LW2X e amplia a tabela existente.")

    ap = argparse.ArgumentParser(
        description=(
            "CUSTOM LW2X nova: LW+LW -> 1 CUSTOM, "
            "IF/ID -> EX dual-read -> WB dual-commit."
        )
    )

    ap.add_argument("base", type=Path)
    ap.add_argument("destino", type=Path)

    ap.add_argument(
        "--originais",
        nargs="+",
        required=True,
        help="Pares: LW1 LW2 LW3 LW4 ...",
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
        die("--originais precisa conter quantidade PAR de palavras LW.")

    pair_count = len(args.originais) // 2

    if args.ocorrencias is None:
        occurrences = [1] * pair_count
    else:
        if len(args.ocorrencias) != pair_count:
            die("--ocorrencias deve ter um número por par.")
        occurrences = args.ocorrencias

    if not args.base.is_dir():
        die(f"diretório base inexistente: {args.base}")

    required = (
        "pipeline.v",
        "IF_ID.v",
        "execute.v",
        "memory.v",
        "tb_pipeline.v",
    )

    for name in required:
        if not (args.base / name).exists():
            die(f"base sem arquivo obrigatório: {name}")

    # V6 incremental real:
    # a base pode já conter a infraestrutura LW2X. Nesse caso ela será
    # reutilizada e a tabela de decode em pipeline.v será ampliada.
    base_all = "\n".join(read(args.base / x) for x in required)
    base_has_lw2x = any(m in base_all for m in EXISTING_MARKS)
    if base_has_lw2x:
        print("Base já contém LW2X: modo incremental ativado.")

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

        first = decode_lw(h1)
        second = decode_lw(h2)

        idx = find_occurrence(words, h1, h2, occurrences[pair_no])

        if idx in used_indices or idx + 1 in used_indices:
            die("pares selecionados se sobrepõem.")

        validate_pair_safety(words, idx, first, second, targets)

        custom = choose_custom_word(words, rtl_text, pair_no)
        rtl_text += f" 32'h{custom}"

        mappings.append({
            "pair": pair_no + 1,
            "index": idx,
            "old_pc": idx * 4,
            "first": first,
            "second": second,
            "custom": custom,
        })

        used_indices.add(idx)
        used_indices.add(idx + 1)

    # Compacta globalmente em uma única passada.
    new_words, reloc = compact_all(words, mappings)

    # V4: fusão real. Cada par selecionado deve reduzir exatamente 1 palavra.
    expected_len = len(words) - len(mappings)
    if len(new_words) != expected_len:
        die(
            f"V4: compactação inconsistente: esperado {expected_len} palavras, "
            f"obtido {len(new_words)}."
        )

    # Garante que o segundo LW não virou NOP; ele precisa ter sido removido.
    if len(new_words) >= len(words):
        die("V4: nenhuma palavra foi removida; fusão real não ocorreu.")

    args.hex_saida.parent.mkdir(parents=True, exist_ok=True)
    args.hex_saida.write_text(
        "\n".join(new_words) + "\n",
        encoding="utf-8",
    )

    # RTL.
    patch_memory(args.destino / "memory.v")
    patch_pipeline(args.destino / "pipeline.v", mappings)
    patch_ifid(args.destino / "IF_ID.v")
    patch_execute(args.destino / "execute.v")
    patch_tb(args.destino / "tb_pipeline.v")

    # Copia HEX também para destino com o nome solicitado.
    dest_hex = args.destino / args.hex_saida.name
    if args.hex_saida.resolve() != dest_hex.resolve():
        shutil.copy2(args.hex_saida, dest_hex)

    validate_rtl(args.destino, mappings)

    print()
    print("=" * 72)
    print("CUSTOM LW2X - COMPACTADO SEM NOP - V6 INCREMENTAL REAL")
    print("=" * 72)

    for mp in mappings:
        a = mp["first"]
        b = mp["second"]

        new_pc = map_pc_after_deletions(
            mp["old_pc"],
            sorted((x["index"] + 1) * 4 for x in mappings),
        )

        print(
            f"Par {mp['pair']}: "
            f"PC antigo=0x{mp['old_pc']:08x} "
            f"PC novo=0x{new_pc:08x}"
        )
        print(
            f"  {a['hex']} -> lw x{a['rd']},{a['imm']}(x{a['rs1']})"
        )
        print(
            f"  {b['hex']} -> lw x{b['rd']},{b['imm']}(x{b['rs1']})"
        )
        print(f"  CUSTOM = {mp['custom']}")

    print()
    print(f"Palavras antes : {len(words)}")
    print(f"Palavras depois: {len(new_words)}")
    print(f"Removidas      : {len(words) - len(new_words)} (1 por par LW2X)")
    print(f"Relocações     : {len(reloc)}")
    print("Replay         : NÃO")
    print("Pending/drain  : NÃO")
    print("FSM LW2X       : NÃO")
    print("Stall LW2X     : NÃO")
    print("Memória        : 2 leituras combinacionais no EX")
    print("Commit         : dual-WB")
    print("=" * 72)

    if args.aplicar_no_base:
        apply_to_base(args.base, args.destino, args.hex_saida)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())