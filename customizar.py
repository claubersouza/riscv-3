#!/usr/bin/env python3
"""
CUSTOMIZADOR LW+LW, 2 -> 1, SEM NOP NO HEX.

Aceita somente pares:
  - LW + LW

Exemplo:
  --originais LW1 LW2 LW3 LW4 ...

Para cada par:
  inst1 + inst2 -> 1 CUSTOM
  inst2 é removida fisicamente do HEX
  BRANCH/JAL são relocados

Uma única FSM REPLAY2 executa as duas LW originais
pelo datapath normal.

Estados:
  IDLE -> WAIT_CLEAR -> ISSUE1 -> ISSUE2 -> WAIT_BOTH_WB -> WAIT_PIPE_CLEAR -> RESUME

Conclusão:
  LW: espera wb_mem_to_reg = 1

Sem NOP inserido no HEX.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


def die(msg):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(2)


def read(p):
    if not p.exists():
        die(f"arquivo não encontrado: {p}")
    return p.read_text(encoding="utf-8")


def write(p, s):
    p.write_text(s, encoding="utf-8")


def sext(v, bits):
    sign = 1 << (bits - 1)
    return (v ^ sign) - sign


def decode_lw(h):
    h = h.lower().replace("0x", "")

    if not re.fullmatch(r"[0-9a-f]{8}", h):
        die(f"HEX inválido: {h}")

    w = int(h, 16)
    opcode = w & 0x7f
    funct3 = (w >> 12) & 7

    if opcode != 0x03 or funct3 != 0b010:
        die(f"{h} não é LW RV32I.")

    return {
        "hex": h,
        "type": "LW",
        "rd": (w >> 7) & 31,
        "rs1": (w >> 15) & 31,
        "imm": sext((w >> 20) & 0xfff, 12),
    }



def parse_hex(p):
    out = []

    for raw in read(p).splitlines():
        line = raw.split("//", 1)[0].strip()

        if not line:
            continue

        tok = line.split()[0].lower().replace("0x", "")

        if re.fullmatch(r"[0-9a-f]{8}", tok):
            out.append(tok)

    if not out:
        die(f"HEX vazio: {p}")

    return out


# ============================================================================
# Relocação
# ============================================================================

def branch_imm(w):
    x = (
        (((w >> 31) & 1) << 12)
        | (((w >> 7) & 1) << 11)
        | (((w >> 25) & 0x3f) << 5)
        | (((w >> 8) & 0xf) << 1)
    )
    return sext(x, 13)


def encode_branch(w, imm):
    if imm & 1 or not (-4096 <= imm <= 4094):
        die(f"BRANCH fora do alcance após relocação: {imm}")

    u = imm & 0x1fff

    mask = ~(
        (1 << 31)
        | (1 << 7)
        | (0x3f << 25)
        | (0xf << 8)
    ) & 0xffffffff

    w &= mask

    w |= ((u >> 12) & 1) << 31
    w |= ((u >> 11) & 1) << 7
    w |= ((u >> 5) & 0x3f) << 25
    w |= ((u >> 1) & 0xf) << 8

    return w


def jal_imm(w):
    x = (
        (((w >> 31) & 1) << 20)
        | (((w >> 12) & 0xff) << 12)
        | (((w >> 20) & 1) << 11)
        | (((w >> 21) & 0x3ff) << 1)
    )
    return sext(x, 21)


def encode_jal(w, imm):
    if imm & 1 or not (-(1 << 20) <= imm <= (1 << 20) - 2):
        die(f"JAL fora do alcance após relocação: {imm}")

    u = imm & 0x1fffff

    mask = ~(
        (1 << 31)
        | (0xff << 12)
        | (1 << 20)
        | (0x3ff << 21)
    ) & 0xffffffff

    w &= mask

    w |= ((u >> 20) & 1) << 31
    w |= ((u >> 12) & 0xff) << 12
    w |= ((u >> 11) & 1) << 20
    w |= ((u >> 1) & 0x3ff) << 21

    return w


def remap_pc(pc, deleted_pc):
    return pc - 4 if pc > deleted_pc else pc


def compact_one(words, h1, h2, custom):
    idx = -1

    for i in range(len(words) - 1):
        if words[i] == h1 and words[i + 1] == h2:
            idx = i
            break

    if idx < 0:
        die(f"par consecutivo não encontrado: {h1} {h2}")

    deleted_pc = (idx + 1) * 4

    out = []
    reloc = 0

    for old_i, hx in enumerate(words):
        if old_i == idx:
            out.append(custom)
            continue

        if old_i == idx + 1:
            continue

        old_pc = old_i * 4
        new_pc = remap_pc(old_pc, deleted_pc)

        w = int(hx, 16)
        opcode = w & 0x7f

        if opcode == 0x63:
            old_target = old_pc + branch_imm(w)
            new_target = remap_pc(old_target, deleted_pc)

            nw = encode_branch(
                w,
                new_target - new_pc,
            )

            reloc += int(nw != w)
            hx = f"{nw:08x}"

        elif opcode == 0x6f:
            old_target = old_pc + jal_imm(w)
            new_target = remap_pc(old_target, deleted_pc)

            nw = encode_jal(
                w,
                new_target - new_pc,
            )

            reloc += int(nw != w)
            hx = f"{nw:08x}"

        out.append(hx)

    return idx, out, reloc



# ============================================================================
# Compactação GLOBAL de múltiplos pares
# ============================================================================

def collect_control_targets(words):
    """
    Retorna todos os PCs antigos que são alvo de BRANCH/JAL.
    Usado para impedir fusão quando a segunda instrução do par é um alvo
    de controle: entrar no meio de um par fundido não é semanticamente seguro.
    """
    targets = set()

    for i, hx in enumerate(words):
        pc = i * 4
        w = int(hx, 16)
        opcode = w & 0x7f

        if opcode == 0x63:
            targets.add(pc + branch_imm(w))

        elif opcode == 0x6f:
            targets.add(pc + jal_imm(w))

    return targets


def find_pair_indices(words, pairs):
    """
    Localiza pares no HEX ORIGINAL.

    Se um par ocorre mais de uma vez, a seleção automática é insegura.
    Nesse caso use --ocorrencias com um número 1-based para cada par.
    """
    used = set()
    result = []

    for pair_no, p in enumerate(pairs, 1):
        candidates = [
            i for i in find_all_pair_indices(words, p["inst1"], p["inst2"])
            if i not in used and (i+1) not in used
        ]

        if not candidates:
            die(
                f"Par {pair_no} não encontrado consecutivamente no HEX original: "
                f"{p['inst1']} {p['inst2']}"
            )

        occurrence = p.get("occurrence")

        if occurrence is None:
            if len(candidates) > 1:
                pcs = ", ".join(f"0x{i*4:08x}" for i in candidates)
                die(
                    f"Par {pair_no} é AMBÍGUO: aparece {len(candidates)} vezes "
                    f"nos PCs {pcs}. Informe --ocorrencias para escolher "
                    f"explicitamente qual ocorrência customizar."
                )
            found = candidates[0]
        else:
            if occurrence < 1 or occurrence > len(candidates):
                die(
                    f"Par {pair_no}: ocorrência {occurrence} inválida; "
                    f"há {len(candidates)} ocorrência(s) disponível(is)."
                )
            found = candidates[occurrence - 1]

        used.add(found)
        used.add(found + 1)

        q = dict(p)
        q["old_index"] = found
        q["old_pc"] = found * 4
        q["deleted_index"] = found + 1
        q["deleted_pc"] = (found + 1) * 4
        result.append(q)

    return result



def global_new_pc(old_pc, deleted_pcs):
    """
    Mapeia um PC antigo para o PC novo removendo todas as segundas
    instruções anteriores a ele.
    """
    shift = 4 * sum(1 for d in deleted_pcs if d < old_pc)
    return old_pc - shift



def find_all_pair_indices(words, inst1, inst2):
    return [
        i for i in range(len(words)-1)
        if words[i] == inst1 and words[i+1] == inst2
    ]


def verify_control_relocation(old_words, new_words, deleted_pcs):
    """
    Verifica todos os BRANCH/JAL do programa original.
    Para cada controle sobrevivente:
      target_novo deve ser exatamente map(target_antigo)
    """
    errors = []

    for old_i, hx in enumerate(old_words):
        old_pc = old_i * 4

        if old_pc in deleted_pcs:
            continue

        # Se esta posição era a primeira instrução de um par, ela virou CUSTOM
        # e não deve ser interpretada como o opcode antigo.
        new_pc = global_new_pc(old_pc, deleted_pcs)
        new_i = new_pc // 4

        if new_i < 0 or new_i >= len(new_words):
            errors.append(
                f"PC antigo 0x{old_pc:08x} mapeou fora do HEX: 0x{new_pc:08x}"
            )
            continue

        old_w = int(hx, 16)
        old_op = old_w & 0x7f

        # Só verificamos BRANCH/JAL originais.
        if old_op not in (0x63, 0x6f):
            continue

        new_w = int(new_words[new_i], 16)
        new_op = new_w & 0x7f

        if new_op != old_op:
            # Pode ter virado CUSTOM se for início de par; nesse caso não é
            # uma instrução de controle sobrevivente.
            continue

        if old_op == 0x63:
            old_target = old_pc + branch_imm(old_w)
            expected = global_new_pc(old_target, deleted_pcs)
            got = new_pc + branch_imm(new_w)
        else:
            old_target = old_pc + jal_imm(old_w)
            expected = global_new_pc(old_target, deleted_pcs)
            got = new_pc + jal_imm(new_w)

        if got != expected:
            errors.append(
                f"controle em oldPC=0x{old_pc:08x}/newPC=0x{new_pc:08x}: "
                f"target esperado=0x{expected:08x}, obtido=0x{got:08x}"
            )

    if errors:
        die(
            "relocação de controle inválida:\n  " + "\n  ".join(errors)
        )

    print("Validação de todos os BRANCH/JAL: OK")


def compact_all_global(words, mappings):
    """
    Faz TODAS as remoções em uma única passagem sobre o programa original.

    Vantagens:
      - branch/JAL são relocados uma única vez;
      - não há acumulação de erros entre várias compactações;
      - o PC de cada CUSTOM é calculado a partir do mesmo espaço original.
    """
    located = find_pair_indices(words, mappings)

    deleted_pcs = sorted(x["deleted_pc"] for x in located)
    deleted_indices = {x["deleted_index"] for x in located}
    custom_by_index = {x["old_index"]: x["custom"] for x in located}

    # Não é seguro fundir quando alguém entra diretamente na segunda
    # instrução, pois isso seria entrada no meio da operação fundida.
    targets = collect_control_targets(words)

    for x in located:
        if x["deleted_pc"] in targets:
            die(
                "Compactação insegura: a segunda instrução do par em "
                f"PC=0x{x['deleted_pc']:08x} é alvo de BRANCH/JAL. "
                "Escolha outro par."
            )

    out = []
    reloc = 0

    for old_i, hx in enumerate(words):
        old_pc = old_i * 4

        if old_i in deleted_indices:
            continue

        if old_i in custom_by_index:
            hx = custom_by_index[old_i]

        else:
            w = int(hx, 16)
            opcode = w & 0x7f
            new_pc = global_new_pc(old_pc, deleted_pcs)

            if opcode == 0x63:
                old_target = old_pc + branch_imm(w)
                new_target = global_new_pc(old_target, deleted_pcs)
                nw = encode_branch(w, new_target - new_pc)

                if nw != w:
                    reloc += 1

                hx = f"{nw:08x}"

            elif opcode == 0x6f:
                old_target = old_pc + jal_imm(w)
                new_target = global_new_pc(old_target, deleted_pcs)
                nw = encode_jal(w, new_target - new_pc)

                if nw != w:
                    reloc += 1

                hx = f"{nw:08x}"

        out.append(hx)

    # Return each pair's NEW PC as well.
    for x in located:
        x["new_pc"] = global_new_pc(x["old_pc"], deleted_pcs)

    expected = len(words) - len(located)

    if len(out) != expected:
        die(
            f"compactação global inconsistente: esperado {expected} palavras, "
            f"obtido {len(out)}"
        )

    verify_control_relocation(
        words,
        out,
        set(deleted_pcs),
    )

    return out, located, reloc


# ============================================================================
# CUSTOM
# ============================================================================

def choose_custom(words, rtl, extras):
    used = set(words)
    used.update(extras)

    used.update(
        x.lower()
        for x in re.findall(
            r"32'h([0-9a-fA-F]{8})",
            rtl,
        )
    )

    # opcode 0x53, funct3=011 reservado para REPLAY2.
    for funct7 in range(1, 128):
        w = (funct7 << 25) | (0b011 << 12) | 0x53
        h = f"{w:08x}"

        if h not in used:
            return h

    die("nenhuma CUSTOM livre.")


# ============================================================================
# pipeline.v
# ============================================================================

def patch_memory(path):
    s = read(path)

    # ---------------------------------------------------------------
    # 1) Portas adicionais
    # ---------------------------------------------------------------
    if "fast_read1_address" not in s:
        port_re = re.compile(
            r"(?P<line>"
            r"input\s+\[\s*31\s*:\s*2\s*\]\s+read2_address\s*"
            r")"
            r"(?P<close>\n\s*\)\s*;)",
            re.MULTILINE,
        )

        m = port_re.search(s)

        if not m:
            die(
                "memory.v: porta read2_address/fim da lista de portas "
                "não localizada."
            )

        replacement = (
            m.group("line").rstrip()
            + ",\n"
            + "    input       [31: 2] fast_read1_address,\n"
            + "    input       [31: 2] fast_read2_address,\n"
            + "    output      [31: 0] fast_read1_data,\n"
            + "    output      [31: 0] fast_read2_data"
            + m.group("close")
        )

        s = s[:m.start()] + replacement + s[m.end():]

    # ---------------------------------------------------------------
    # 2) Declarações internas dos índices.
    #
    # Não dependemos mais especificamente de "write2_addr".
    # Procuramos a última declaração wire [ADDR-1:0] *_addr existente
    # e acrescentamos os wires logo depois.
    # ---------------------------------------------------------------
    if not re.search(r"\bfast_read1_addr\b\s*;", s):
        addr_wire_re = re.compile(
            r"(?P<line>"
            r"\bwire\s+"
            r"\[\s*ADDR\s*-\s*1\s*:\s*0\s*\]\s+"
            r"[A-Za-z_][A-Za-z0-9_]*_addr\s*;"
            r")"
        )

        matches = list(addr_wire_re.finditer(s))

        if matches:
            m = matches[-1]
            insertion = (
                m.group("line")
                + "\n"
                + "    wire        [ADDR-1: 0] fast_read1_addr;\n"
                + "    wire        [ADDR-1: 0] fast_read2_addr;"
            )
            s = s[:m.start()] + insertion + s[m.end():]
        else:
            # Fallback: insere antes do primeiro assign de endereço.
            assign_pos = re.search(r"\n\s*assign\s+", s)

            if not assign_pos:
                die(
                    "memory.v: não encontrei região para declarar "
                    "fast_read1_addr/fast_read2_addr."
                )

            decl = (
                "\n    wire        [ADDR-1: 0] fast_read1_addr;\n"
                "    wire        [ADDR-1: 0] fast_read2_addr;\n"
            )

            s = s[:assign_pos.start()] + decl + s[assign_pos.start():]

    # Validação imediata das declarações.
    if not re.search(
        r"\bwire\s+\[\s*ADDR\s*-\s*1\s*:\s*0\s*\]\s+fast_read1_addr\s*;",
        s,
    ):
        die("memory.v: falha ao declarar fast_read1_addr.")

    if not re.search(
        r"\bwire\s+\[\s*ADDR\s*-\s*1\s*:\s*0\s*\]\s+fast_read2_addr\s*;",
        s,
    ):
        die("memory.v: falha ao declarar fast_read2_addr.")

    # ---------------------------------------------------------------
    # 3) Assigns dos índices e leituras combinacionais.
    # ---------------------------------------------------------------
    if "assign fast_read1_addr" not in s:
        # Usa como âncora qualquer assign de *_addr derivado de *_address.
        candidates = list(
            re.finditer(
                r"assign\s+"
                r"[A-Za-z_][A-Za-z0-9_]*_addr"
                r"(?:\s*\[\s*ADDR\s*-\s*1\s*:\s*0\s*\])?"
                r"\s*=\s*"
                r"[A-Za-z_][A-Za-z0-9_]*_address"
                r"\s*\[\s*ADDR\s*\+\s*1\s*:\s*2\s*\]\s*;",
                s,
            )
        )

        if not candidates:
            die(
                "memory.v: nenhum assign *_addr = *_address[ADDR+1:2] "
                "localizado."
            )

        m = candidates[-1]

        extra = (
            m.group(0)
            + "\n"
            + "assign fast_read1_addr[ADDR-1:0] = "
              "fast_read1_address[ADDR+1:2];\n"
            + "assign fast_read2_addr[ADDR-1:0] = "
              "fast_read2_address[ADDR+1:2];\n"
            + "assign fast_read1_data = memory[fast_read1_addr];\n"
            + "assign fast_read2_data = memory[fast_read2_addr];"
        )

        s = s[:m.start()] + extra + s[m.end():]

    # ---------------------------------------------------------------
    # 4) Sanidade final do memory.v gerado.
    # ---------------------------------------------------------------
    required = (
        "fast_read1_address",
        "fast_read2_address",
        "fast_read1_data",
        "fast_read2_data",
        "fast_read1_addr",
        "fast_read2_addr",
        "assign fast_read1_addr",
        "assign fast_read2_addr",
    )

    missing = [x for x in required if x not in s]

    if missing:
        die(
            "memory.v: validação das portas rápidas falhou: "
            + ", ".join(missing)
        )

    write(path, s)

def patch_tb(path):
    s=read(path)

    # Wires.
    if "dmem_fast_read1_data_temp" not in s:
        needle="    wire    [31: 0] dmem_read2_data_temp;\n"
        if needle not in s:
            die("tb_pipeline.v: dmem_read2_data_temp não localizado.")
        s=s.replace(
            needle,
            needle+
            "    wire    [31: 0] dmem_fast_read1_data_temp;\n"
            "    wire    [31: 0] dmem_fast_read2_data_temp;\n",
            1
        )

    # Data-memory instance.
    if ".fast_read1_address" not in s:
        needle="""        .read2_data(dmem_read2_data_temp),
        .read2_address(pipe.dmem_read2_address[31:2]),"""
        if needle not in s:
            die("tb_pipeline.v: portas read2 da DMEM não localizadas.")
        s=s.replace(
            needle,
            needle+
            """
        .fast_read1_address(pipe.fused_lw_fast_addr1[31:2]),
        .fast_read2_address(pipe.fused_lw_fast_addr2[31:2]),
        .fast_read1_data(dmem_fast_read1_data_temp),
        .fast_read2_data(dmem_fast_read2_data_temp),""",
            1
        )

        # Instruction-memory instance must also satisfy the new memory ports.
        needle="""        .read2_data(inst_mem_read2_data),
        .read2_address(pipe.inst_mem_port2_address[31:2]),"""
        if needle not in s:
            die("tb_pipeline.v: portas read2 da IMEM não localizadas.")
        s=s.replace(
            needle,
            needle+
            """
        .fast_read1_address(30'h0),
        .fast_read2_address(30'h0),
        .fast_read1_data(),
        .fast_read2_data(),""",
            1
        )

    # Pipeline instance.
    if ".dmem_fast_read1_data_temp" not in s:
        needle="""    .dmem_read2_data_temp(dmem_read2_data_temp),"""
        if needle not in s:
            die("tb_pipeline.v: porta dmem_read2_data_temp não localizada.")
        s=s.replace(
            needle,
            needle+
            """
    .dmem_fast_read1_data_temp(dmem_fast_read1_data_temp),
    .dmem_fast_read2_data_temp(dmem_fast_read2_data_temp),""",
            1
        )

    write(path,s)


def _ternary_map(mappings, key, fmt, default):
    parts=[]
    for mp in mappings:
        parts.append(
            f"(inst_mem_read_data == 32'h{mp['custom']}) ? {fmt(mp)} :"
        )
    return "\n        ".join(parts) + f"\n        {default}"


def verilog_s32(value):
    value = int(value)
    if value < 0:
        return f"-32'sd{abs(value)}"
    return f"32'sd{value}"


def _prepend_ternary(s, signal, custom, value):
    """
    Acrescenta:
       (inst_mem_read_data == CUSTOM) ? VALUE :
    no início do RHS de um assign existente.
    """
    pat = re.compile(
        rf"(assign\s+{re.escape(signal)}\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die(f"pipeline.v: assign {signal} não localizado.")

    rhs = m.group(2)

    clause = (
        f"(inst_mem_read_data == 32'h{custom}) ? {value} :\n        "
    )

    new_rhs = clause + rhs.lstrip()

    return s[:m.start(2)] + new_rhs + s[m.end(2):]


def _extend_match(s, custom):
    pat = re.compile(
        r"(assign\s+fused_lw_match\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die("pipeline.v: assign fused_lw_match não localizado.")

    rhs = m.group(2).rstrip()

    clause = f"(inst_mem_read_data == 32'h{custom})"

    if clause in rhs:
        die(f"CUSTOM {custom} já está em fused_lw_match.")

    new_rhs = rhs + "\n        || " + clause

    return s[:m.start(2)] + new_rhs + s[m.end(2):]


def patch_pipeline(path, mappings):
    s = read(path)

    # ================================================================
    # MODO INCREMENTAL:
    # FUSED_LW já existe -> somente amplia as tabelas.
    # ================================================================
    if "fused_lw_valid" in s:
        print("pipeline.v: FUSED_LW existente; ampliando tabela de CUSTOMs.")

        for m in mappings:
            custom = m["custom"]

            s = _extend_match(
                s,
                custom,
            )

            s = _prepend_ternary(
                s,
                "fused_lw_rs1_1",
                custom,
                f"5'd{m['first']['rs1']}",
            )

            s = _prepend_ternary(
                s,
                "fused_lw_rs1_2",
                custom,
                f"5'd{m['second']['rs1']}",
            )

            s = _prepend_ternary(
                s,
                "fused_lw_rd1",
                custom,
                f"5'd{m['first']['rd']}",
            )

            s = _prepend_ternary(
                s,
                "fused_lw_rd2",
                custom,
                f"5'd{m['second']['rd']}",
            )

            s = _prepend_ternary(
                s,
                "fused_lw_imm1",
                custom,
                verilog_s32(m["first"]["imm"]),
            )

            s = _prepend_ternary(
                s,
                "fused_lw_imm2",
                custom,
                verilog_s32(m["second"]["imm"]),
            )

        bad_signed = re.search(r"\d+'sd-\d+", s)

        if bad_signed:
            die(
                "pipeline.v: literal signed inválido após extensão: "
                + bad_signed.group(0)
            )

        write(path, s)
        return

    # ================================================================
    # PRIMEIRA INSTALAÇÃO
    # ================================================================

    # Add input ports for combinational dual-read data.
    needle = """    input           [31: 0] dmem_read2_data_temp,"""

    if needle not in s:
        die(
            "pipeline.v: dmem_read2_data_temp não localizado "
            "na lista de portas."
        )

    s = s.replace(
        needle,
        needle
        + """
    input           [31: 0] dmem_fast_read1_data_temp,
    input           [31: 0] dmem_fast_read2_data_temp,""",
        1,
    )

    anchor = "    // PC"

    if anchor not in s:
        die("pipeline.v: seção // PC não localizada.")

    rs11 = _ternary_map(
        mappings,
        "rs11",
        lambda m: f"5'd{m['first']['rs1']}",
        "5'd0",
    )

    rs12 = _ternary_map(
        mappings,
        "rs12",
        lambda m: f"5'd{m['second']['rs1']}",
        "5'd0",
    )

    rd1 = _ternary_map(
        mappings,
        "rd1",
        lambda m: f"5'd{m['first']['rd']}",
        "5'd0",
    )

    rd2 = _ternary_map(
        mappings,
        "rd2",
        lambda m: f"5'd{m['second']['rd']}",
        "5'd0",
    )

    imm1 = _ternary_map(
        mappings,
        "imm1",
        lambda m: verilog_s32(m["first"]["imm"]),
        "32'sd0",
    )

    imm2 = _ternary_map(
        mappings,
        "imm2",
        lambda m: verilog_s32(m["second"]["imm"]),
        "32'sd0",
    )

    matches = " ||\n        ".join(
        f"(inst_mem_read_data == 32'h{m['custom']})"
        for m in mappings
    )

    block = f"""
    // ================================================================
    // FUSED_LW - CUSTOM LW+LW real, dual-port, sem replay/sem NOP no HEX
    // ================================================================
    wire fused_lw_match;
    wire fused_lw_valid;
    wire [4:0] fused_lw_rs1_1;
    wire [4:0] fused_lw_rs1_2;
    wire [4:0] fused_lw_rd1;
    wire [4:0] fused_lw_rd2;
    wire signed [31:0] fused_lw_imm1;
    wire signed [31:0] fused_lw_imm2;
    wire [31:0] fused_lw_base1;
    wire [31:0] fused_lw_base2;
    wire [31:0] fused_lw_fast_addr1;
    wire [31:0] fused_lw_fast_addr2;
    wire [31:0] fused_lw_data1;
    wire [31:0] fused_lw_data2;

    assign fused_lw_match =
        {matches};

    assign fused_lw_valid =
        fused_lw_match &&
        !stall_read &&
        !branch_stall;

    assign fused_lw_rs1_1 =
        {rs11};

    assign fused_lw_rs1_2 =
        {rs12};

    assign fused_lw_rd1 =
        {rd1};

    assign fused_lw_rd2 =
        {rd2};

    assign fused_lw_imm1 =
        {imm1};

    assign fused_lw_imm2 =
        {imm2};

    assign fused_lw_base1 =
        (fused_lw_rs1_1 == 5'd0) ? 32'd0 :
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_lw_rs1_1) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[fused_lw_rs1_1];

    assign fused_lw_base2 =
        (fused_lw_rs1_2 == 5'd0) ? 32'd0 :
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_lw_rs1_2) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[fused_lw_rs1_2];

    assign fused_lw_fast_addr1 =
        fused_lw_base1 + fused_lw_imm1;

    assign fused_lw_fast_addr2 =
        fused_lw_base2 + fused_lw_imm2;

    assign fused_lw_data1 = dmem_fast_read1_data_temp;
    assign fused_lw_data2 = dmem_fast_read2_data_temp;

"""

    s = s.replace(
        anchor,
        block + anchor,
        1,
    )

    bad_signed = re.search(
        r"\d+'sd-\d+",
        s,
    )

    if bad_signed:
        die(
            "pipeline.v: literal Verilog signed inválido gerado: "
            + bad_signed.group(0)
        )

    write(path, s)

def patch_ifid(path, mappings):
    s=read(path)

    if "FUSED_LW_MASK" in s:
        print("IF_ID.v: FUSED_LW já instalado; nenhuma alteração necessária.")
        return

    # Mask the custom from the normal decoder. The fused hardware performs
    # the architectural effect directly.
    pat="assign pipe.instruction = pipe.stall_read ? NOP :"
    if pat not in s:
        die("IF_ID.v: assign pipe.instruction esperado não localizado.")

    s=s.replace(
        pat,
        """// FUSED_LW_MASK
assign pipe.instruction = pipe.stall_read ? NOP :
                          pipe.fused_lw_valid ? NOP :""",
        1
    )

    # Insert highest-priority register-file write after reset.
    regpos=s.find("integer i;")
    if regpos<0:
        die("IF_ID.v: banco de registradores não localizado.")

    # Find first else-if after the reset branch.
    m=re.search(r"\nelse\s+if\s*\(",s[regpos:])
    if not m:
        die("IF_ID.v: primeiro else-if do register file não localizado.")

    at=regpos+m.start()

    wb="""else if (pipe.fused_lw_valid)
begin
    if (pipe.fused_lw_rd1 != 5'd0)
        pipe.regs[pipe.fused_lw_rd1] <= pipe.fused_lw_data1;

    if (pipe.fused_lw_rd2 != 5'd0)
        pipe.regs[pipe.fused_lw_rd2] <= pipe.fused_lw_data2;

    $display(
        "[FUSED_LW] rd1=x%0d data1=%h addr1=%h rd2=x%0d data2=%h addr2=%h",
        pipe.fused_lw_rd1, pipe.fused_lw_data1, pipe.fused_lw_fast_addr1,
        pipe.fused_lw_rd2, pipe.fused_lw_data2, pipe.fused_lw_fast_addr2
    );
end
"""

    s=s[:at]+"\n"+wb+s[at:]
    write(path,s)


def validate(dest,mappings):
    p=read(dest/"pipeline.v")
    i=read(dest/"IF_ID.v")
    m=read(dest/"memory.v")
    t=read(dest/"tb_pipeline.v")

    checks={
        "dual memory":"fast_read1_data" in m and "fast_read2_data" in m,
        "pipeline fast inputs":"dmem_fast_read1_data_temp" in p,
        "fused valid":"fused_lw_valid" in p,
        "mask normal decode":"FUSED_LW_MASK" in i,
        "dual writeback":"pipe.fused_lw_rd1" in i and "pipe.fused_lw_rd2" in i,
        "tb dmem fast":".fast_read1_address(pipe.fused_lw_fast_addr1[31:2])" in t,
        "sem replay":"replay2_state" not in p,
    }

    for mp in mappings:
        checks[f"custom {mp['pair']}"]=f"32'h{mp['custom']}" in p

    bad=[k for k,v in checks.items() if not v]
    if bad:
        die("validação FUSED_LW falhou: "+", ".join(bad))

    print("Validação FUSED_LW: OK")
def apply(base,dest):
    for name in (
        "pipeline.v",
        "IF_ID.v",
        "memory.v",
        "tb_pipeline.v",
        "imem_custom.hex",
    ):
        src=dest/name
        if not src.exists():
            continue
        dst=base/name
        if dst.exists():
            bak=base/f"{name}.pre_fused_lw"
            if not bak.exists():
                shutil.copy2(dst,bak)
        shutil.copy2(src,dst)
        print(f"aplicado: {src} -> {dst}")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Customizador LW+LW 2 -> 1 sem NOP, "
            "com compactação GLOBAL e relocação segura."
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
        help=(
            "Ocorrência 1-based de cada par no HEX original. "
            "Use quando um mesmo par aparece mais de uma vez. "
            "Ex.: --ocorrencias 2 1 3"
        ),
    )

    ap.add_argument("--hex-entrada", type=Path, required=True)
    ap.add_argument("--hex-saida", type=Path, required=True)
    ap.add_argument("--sobrescrever", action="store_true")
    ap.add_argument("--aplicar-no-base", action="store_true")

    args = ap.parse_args()

    if len(args.originais) < 2 or len(args.originais) % 2:
        die("--originais precisa conter quantidade PAR de instruções.")

    if not args.base.is_dir():
        die(f"base inexistente: {args.base}")

    ptxt = read(args.base / "pipeline.v")

    if "replay2_state" in ptxt:
        die(
            "A base já contém REPLAY2. Para evitar acumular relocação incorreta, "
            "use a base anterior à primeira REPLAY2 e passe TODOS os pares "
            "LW/ADDI nesta mesma execução."
        )

    if args.destino.exists():
        if not args.sobrescrever:
            die("destino existe; use --sobrescrever.")
        shutil.rmtree(args.destino)

    shutil.copytree(args.base, args.destino)

    words = parse_hex(args.hex_entrada)

    rtl = "".join(
        read(args.destino / n)
        for n in ("pipeline.v", "IF_ID.v", "execute.v", "wb.v")
    )

    pair_count = len(args.originais) // 2

    if args.ocorrencias is not None and len(args.ocorrencias) != pair_count:
        die(
            f"--ocorrencias deve ter exatamente {pair_count} valor(es), "
            f"um para cada par."
        )

    mappings = []
    custom_extra = set()

    # Primeiro decodifica e escolhe TODAS as CUSTOMs, sem tocar no HEX.
    for i in range(0, len(args.originais), 2):
        first = decode_lw(args.originais[i])
        second = decode_lw(args.originais[i + 1])

        custom = choose_custom(
            words,
            rtl,
            custom_extra,
        )

        custom_extra.add(custom)

        mappings.append(
            {
                "pair": i // 2 + 1,
                "occurrence": (
                    args.ocorrencias[i // 2]
                    if args.ocorrencias is not None
                    else None
                ),
                "type": "LW",
                "inst1": first["hex"],
                "inst2": second["hex"],
                "rd1": first["rd"],
                "rd2": second["rd"],
                "custom": custom,
                "first": first,
                "second": second,
            }
        )

    # Agora faz UMA compactação global.
    work, located, total_reloc = compact_all_global(words, mappings)

    # Atualiza mappings com PCs reais localizados.
    by_custom = {x["custom"]: x for x in located}

    for m in mappings:
        loc = by_custom[m["custom"]]
        m["index"] = loc["old_index"]
        m["old_pc"] = loc["old_pc"]
        m["new_pc"] = loc["new_pc"]

    args.hex_saida.parent.mkdir(parents=True, exist_ok=True)

    args.hex_saida.write_text(
        "\n".join(work) + "\n",
        encoding="utf-8",
    )

    dest_hex = args.destino / "imem_custom.hex"

    if args.hex_saida.resolve() != dest_hex.resolve():
        shutil.copy2(args.hex_saida, dest_hex)

    patch_memory(args.destino / "memory.v")
    patch_pipeline(args.destino / "pipeline.v", mappings)
    patch_ifid(args.destino / "IF_ID.v", mappings)
    patch_tb(args.destino / "tb_pipeline.v")

    validate(args.destino, mappings)

    print()
    print("=" * 76)
    print("FUSED_LW DUAL-PORT MULTI - LW+LW, 2 -> 1 SEM NOP")
    print("=" * 76)

    for mp in mappings:
        print(
            f"Par {mp['pair']:02d} [LW]: "
            f"{mp['inst1']} + {mp['inst2']} "
            f"-> CUSTOM={mp['custom']} "
            f"PC antigo=0x{mp['old_pc']:08x} "
            f"PC novo=0x{mp['new_pc']:08x}"
        )

    print(f"HEX: {len(words)} -> {len(work)} palavras")
    print(f"Relocações BRANCH/JAL: {total_reloc}")
    print("Validação de destinos BRANCH/JAL: OK")
    print("NOP inserido no HEX: NÃO")
    print("Compactação: GLOBAL")
    print("FSM: NÃO; duas leituras combinacionais em paralelo")
    print("=" * 76)

    if args.aplicar_no_base:
        apply(args.base, args.destino)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())