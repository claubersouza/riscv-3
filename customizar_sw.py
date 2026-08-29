#!/usr/bin/env python3
# SW SINGLE-CYCLE V7 INCREMENTAL - reutiliza FUSED_SW existente
"""
CUSTOMIZADOR FINAL LW+LW / ADDI+ADDI / SW+SW, 2 -> 1, SEM NOP NO HEX.

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


def decode_inst(h):
    h = h.lower().replace("0x", "")

    if not re.fullmatch(r"[0-9a-f]{8}", h):
        die(f"HEX inválido: {h}")

    w = int(h, 16)
    opcode = w & 0x7f
    funct3 = (w >> 12) & 7

    if opcode == 0x03 and funct3 == 0b010:
        return {
            "hex": h,
            "type": "LW",
            "rd": (w >> 7) & 31,
            "rs1": (w >> 15) & 31,
            "imm": sext((w >> 20) & 0xfff, 12),
        }

    if opcode == 0x13 and funct3 == 0b000:
        return {
            "hex": h,
            "type": "ADDI",
            "rd": (w >> 7) & 31,
            "rs1": (w >> 15) & 31,
            "imm": sext((w >> 20) & 0xfff, 12),
        }

    if opcode == 0x23 and funct3 == 0b010:
        imm12 = (((w >> 25) & 0x7f) << 5) | ((w >> 7) & 0x1f)
        return {
            "hex": h,
            "type": "SW",
            "rd": 0,
            "rs1": (w >> 15) & 31,
            "rs2": (w >> 20) & 31,
            "imm": sext(imm12, 12),
        }

    die(f"{h} não é LW, ADDI nem SW RV32I.")



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



def _extend_sw_match(s, custom):
    pat = re.compile(
        r"(assign\s+fused_sw_match\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die("pipeline.v: assign fused_sw_match não localizado.")

    rhs = m.group(2).rstrip()
    clause = f"(inst_mem_read_data == 32'h{custom})"

    if clause in rhs:
        die(f"CUSTOM {custom} já está em fused_sw_match.")

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

    // Dependências de endereço: uma LW fundida não pode calcular o
    // endereço usando um registrador-base ainda pendente.
    wire fused_lw_dep_ex;
    wire fused_lw_dep_wb;

    assign fused_lw_dep_ex =
        mem_to_reg &&
        (dest_reg_sel != 5'd0) &&
        ((dest_reg_sel == fused_lw_rs1_1) ||
         (dest_reg_sel == fused_lw_rs1_2));

    assign fused_lw_dep_wb =
        wb_stall &&
        (wb_dest_reg_sel != 5'd0) &&
        ((wb_dest_reg_sel == fused_lw_rs1_1) ||
         (wb_dest_reg_sel == fused_lw_rs1_2));

    assign fused_lw_valid =
        fused_lw_match &&
        !stall_read &&
        !branch_stall &&
        !fused_lw_dep_ex &&
        !fused_lw_dep_wb;

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
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_lw_rs1_1) ?
            result :
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_lw_rs1_1) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :
            regs[fused_lw_rs1_1];

    assign fused_lw_base2 =
        (fused_lw_rs1_2 == 5'd0) ? 32'd0 :
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_lw_rs1_2) ?
            result :
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



def _extend_addir_match(s, custom):
    pat = re.compile(
        r"(assign\s+pipe\.addir_match\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die("IF_ID.v: assign pipe.addir_match não localizado.")

    rhs = m.group(2).rstrip()
    clause = f"(inst_mem_read_data == 32'h{custom})"

    if clause in rhs:
        die(f"CUSTOM ADDI {custom} já existe.")

    rhs += "\n        || " + clause
    return s[:m.start(2)] + rhs + s[m.end(2):]


def patch_pipeline_addi(path, mappings):
    """
    ADDIR usa o pipeline normal. pipeline.v guarda somente estado/tabela.
    """
    if not mappings:
        return

    s = read(path)

    if "addir_state" in s:
        changed = False
        if "addir_is_sw" not in s:
            anchor_decl = "    reg  [4:0] addir_rd2;"
            if anchor_decl not in s:
                die("pipeline.v: addir_rd2 não localizado para upgrade SW.")
            s = s.replace(
                anchor_decl,
                anchor_decl +
                "\n    reg        addir_is_sw;" +
                "\n    reg  [2:0] addir_wait_count;",
                1,
            )
            changed = True
        if changed:
            write(path, s)
            print("pipeline.v: ADDIR atualizada para suportar SW.")
        else:
            print("pipeline.v: SEQR ADDI/SW existente; reutilizando FSM.")
        return

    anchor = "    // PC"

    if anchor not in s:
        die("pipeline.v: seção // PC não localizada para ADDIR.")

    block = """
    // ================================================================
    // SEQR - ADDI+ADDI / SW+SW 2 -> 1 sem NOP no HEX
    // Executa ADDI/SW pelo datapath normal para preservar ordem e efeitos.
    // ================================================================
    reg  [2:0] addir_state;
    reg        addir_seen;
    reg [31:0] addir_resume_pc;
    reg [31:0] addir_addi1_word;
    reg [31:0] addir_addi2_word;
    reg  [4:0] addir_rd2;
    reg        addir_is_sw;
    reg  [2:0] addir_wait_count;
    wire       addir_match;
    wire       addir_detect_now;
    wire       addir_hold_fetch;
    wire       addir_resume_valid;
    wire [31:0] addir_inst1_selected;

"""

    s = s.replace(anchor, block + anchor, 1)
    write(path, s)


def patch_ifid_addi(path, mappings):
    if not mappings:
        return

    s = read(path)

    # ---------------------------------------------------------------
    # Incremental extension of existing ADDIR.
    # ---------------------------------------------------------------
    if "ADDIR_MULTI_BEGIN" in s:
        die(
            "IF_ID.v já contém ADDIR antiga. "
            "Para instalar o SW com emissão imediata, use uma base anterior "
            "à primeira customização ADDI/SW, mantendo FUSED_LW se desejar."
        )

        for mp in mappings:
            custom = mp["custom"]

            s = _extend_addir_match(s, custom)

            marker = "                // ADDIR_PAIR_TABLE_END"
            pos = s.find(marker)

            if pos < 0:
                die("IF_ID.v: ADDIR_PAIR_TABLE_END não localizado.")

            pair = f"""                if(inst_mem_read_data == 32'h{custom})
                begin
                    pipe.addir_addi1_word <= 32'h{mp['inst1']};
                    pipe.addir_addi2_word <= 32'h{mp['inst2']};
                    pipe.addir_rd2 <= 5'd{mp['second']['rd']};
                    pipe.addir_is_sw <= 1'b{1 if mp['type'] == 'SW' else 0};
                end

"""

            s = s[:pos] + pair + s[pos:]

        write(path, s)
        return

    # ---------------------------------------------------------------
    # First ADDIR installation.
    # Wrap the CURRENT instruction RHS. It may already include FUSED_LW.
    # ---------------------------------------------------------------
    # Localiza a atribuição de pipe.instruction de forma tolerante.
    # Aceita:
    #   assign pipe.instruction = ...;
    # e também variantes em que o gerador anterior inseriu comentários,
    # quebras de linha ou espaços entre "assign" e "pipe.instruction".
    pat = re.compile(
        r"\bassign\s+"
        r"pipe\s*\.\s*instruction\s*=\s*"
        r"(?P<rhs>.*?)"
        r";",
        re.DOTALL | re.MULTILINE,
    )
    m = pat.search(s)

    if not m:
        # Fallback: procura somente "pipe.instruction =" e preserva
        # tudo até o próximo ';'. Isso cobre IF_ID customizado anteriormente.
        pat = re.compile(
            r"pipe\s*\.\s*instruction\s*=\s*"
            r"(?P<rhs>.*?)"
            r";",
            re.DOTALL | re.MULTILINE,
        )
        m = pat.search(s)

    if not m:
        # Diagnóstico útil em vez de simplesmente abortar.
        candidates = [
            line.strip()
            for line in s.splitlines()
            if "instruction" in line.lower()
        ][:12]

        die(
            "IF_ID.v: não consegui localizar a atribuição de "
            "pipe.instruction. Linhas candidatas: "
            + " | ".join(candidates)
        )

    old_rhs = m.group("rhs").strip()

    matches = " ||\n        ".join(
        f"(inst_mem_read_data == 32'h{mp['custom']})"
        for mp in mappings
    )

    inst1_select = "\n        ".join(
        f"(inst_mem_read_data == 32'h{mp['custom']}) ? 32'h{mp['inst1']} :"
        for mp in mappings
    ) + "\n        32'h00000013"

    sw_detect = " ||\n        ".join(
        f"(inst_mem_read_data == 32'h{mp['custom']})"
        for mp in mappings
        if mp["type"] == "SW"
    ) or "1'b0"

    pair_lines = []

    for mp in mappings:
        pair_lines.append(
            f"""                if(inst_mem_read_data == 32'h{mp['custom']})
                begin
                    pipe.addir_addi1_word <= 32'h{mp['inst1']};
                    pipe.addir_addi2_word <= 32'h{mp['inst2']};
                    pipe.addir_rd2 <= 5'd{mp['second']['rd']};
                    pipe.addir_is_sw <= 1'b{1 if mp['type'] == 'SW' else 0};
                end"""
        )

    pairs = "\n".join(pair_lines)

    block = f"""// ADDIR_MULTI_BEGIN
assign pipe.addir_match =
        {matches};

assign pipe.addir_detect_now =
    (pipe.addir_state == 3'd0) &&
    !pipe.addir_seen &&
    pipe.addir_match;

assign pipe.addir_inst1_selected =
        {inst1_select};

wire addir_detect_is_sw =
        {sw_detect};

assign pipe.addir_hold_fetch =
    pipe.addir_detect_now ||
    (pipe.addir_state == 3'd1) ||
    (pipe.addir_state == 3'd2) ||
    (pipe.addir_state == 3'd3) ||
    (pipe.addir_state == 3'd4);

assign pipe.addir_resume_valid =
    (pipe.addir_state == 3'd5);

assign pipe.instruction =
    // SW: emite a primeira store no MESMO ciclo da detecção.
    (pipe.addir_detect_now && addir_detect_is_sw)
        ? pipe.addir_inst1_selected :
    (pipe.addir_state == 3'd1) ? NOP :
    (pipe.addir_state == 3'd2) ? pipe.addir_addi1_word :
    (pipe.addir_state == 3'd3) ? pipe.addir_addi2_word :
    ((pipe.addir_state == 3'd4) ||
     (pipe.addir_state == 3'd5) ||
     pipe.addir_detect_now ||
     (pipe.addir_seen && pipe.addir_match)) ? NOP :
    ({old_rhs});
// ADDIR_MULTI_END"""

    # Substitui a atribuição inteira. No fallback, garante que um possível
    # "assign" imediatamente anterior também seja consumido.
    replace_start = m.start()
    prefix = s[max(0, replace_start - 16):replace_start]
    if not s[replace_start:m.start("rhs")].lstrip().startswith("assign"):
        am = re.search(r"assign\s*$", prefix)
        if am:
            replace_start = max(0, replace_start - 16) + am.start()

    s = s[:replace_start] + block + s[m.end():]

    insert = s.find("// Stall read assignment")

    if insert < 0:
        die("IF_ID.v: Stall read assignment não localizado para ADDIR.")

    fsm = f"""
// -----------------------------------------------------------------------------
// ADDIR controller
//
// 0 IDLE
// 1 WAIT_OLD_WB
// 2 ISSUE1
// 3 ISSUE2
// 4 WAIT_WB2
// 5 RESUME
// -----------------------------------------------------------------------------
always @(posedge clk or negedge reset)
begin
    if(!reset)
    begin
        pipe.addir_state <= 3'd0;
        pipe.addir_seen <= 1'b0;
        pipe.addir_resume_pc <= 32'd0;
        pipe.addir_addi1_word <= 32'd0;
        pipe.addir_addi2_word <= 32'd0;
        pipe.addir_rd2 <= 5'd0;
        pipe.addir_is_sw <= 1'b0;
        pipe.addir_wait_count <= 3'd0;
    end
    else
    begin
        case(pipe.addir_state)

        3'd0:
        begin
            if(pipe.addir_detect_now)
            begin
                pipe.addir_resume_pc <= pipe.fetch_pc + 32'd4;
                pipe.addir_seen <= 1'b1;
                pipe.addir_wait_count <= 3'd0;

{pairs}
                // ADDIR_PAIR_TABLE_END

                // Para SW, SW1 já está sendo emitida pelo mux neste ciclo.
                // Portanto o próximo estado deve emitir diretamente SW2.
                if(addir_detect_is_sw)
                    pipe.addir_state <= 3'd3;
                else
                    pipe.addir_state <= 3'd1;

                $display(
                    "[SEQR] detect fetch=%h resume=%h is_sw=%b inst1_now=%h",
                    pipe.fetch_pc,
                    pipe.fetch_pc + 32'd4,
                    addir_detect_is_sw,
                    pipe.addir_inst1_selected
                );
            end
            else if(!pipe.addir_match)
            begin
                pipe.addir_seen <= 1'b0;
            end
        end

        // Aguarda instruções antigas saírem do WB.
        // Dois ciclos limpos são usados porque a CUSTOM é detectada
        // enquanto instruções anteriores ainda podem estar em EX/WB.
        3'd1:
        begin
            if(!pipe.wb_stall &&
               !pipe.stall_read &&
               !(pipe.wb_alu_to_reg && pipe.wb_dest_reg_sel != 5'd0))
            begin
                pipe.addir_state <= 3'd2;
                $display("[ADDIR] pipeline anterior drenado");
            end
        end

        // ADDI1 entra no decoder normal.
        3'd2:
        begin
            pipe.addir_state <= 3'd3;
            $display("[SEQR] issue1=%h", pipe.addir_addi1_word);
        end

        // ADDI2 entra no decoder normal no ciclo seguinte.
        3'd3:
        begin
            pipe.addir_state <= 3'd4;
            if(pipe.addir_is_sw)
                $display("[SWR] issue2=%h", pipe.addir_addi2_word);
            else
                $display("[SEQR] issue2=%h", pipe.addir_addi2_word);
        end

        // ADDI: espera o WB2 normal.
        // SW: não possui write-back de registrador; aguarda a segunda SW
        // atravessar EX/WB antes de liberar o fetch.
        3'd4:
        begin
            if(pipe.addir_is_sw)
            begin
                if(pipe.addir_wait_count == 3'd2)
                begin
                    pipe.addir_state <= 3'd5;
                    pipe.addir_wait_count <= 3'd0;
                    $display("[SWR] SW2 concluida; retomando fetch");
                end
                else
                begin
                    pipe.addir_wait_count <= pipe.addir_wait_count + 3'd1;
                end
            end
            else if(pipe.wb_alu_to_reg &&
                    !pipe.wb_mem_to_reg &&
                    !pipe.wb_stall &&
                    (pipe.wb_dest_reg_sel == pipe.addir_rd2))
            begin
                pipe.addir_state <= 3'd5;

                $display(
                    "[ADDIR] WB2 concluido rd=x%0d data=%h",
                    pipe.addir_rd2,
                    pipe.wb_result
                );
            end
        end

        3'd5:
        begin
            pipe.addir_state <= 3'd0;
        end

        default:
            pipe.addir_state <= 3'd0;

        endcase
    end
end

"""

    s = s[:insert] + fsm + s[insert:]

    # Permit replayed instructions to advance through decode.
    target = "else if (!pipe.stall_read ||"

    if target in s:
        s = s.replace(
            target,
            (
                "else if (!pipe.stall_read || "
                "(pipe.addir_state == 3'd2) || "
                "(pipe.addir_state == 3'd3) ||"
            ),
            1,
        )

    write(path, s)


def patch_execute_addi(path):
    s = read(path)

    if "pipe.addir_resume_valid" in s:
        print("execute.v: ADDIR já instalado.")
        return

    # Insert priority immediately before the normal !stall_read PC update.
    pat = re.compile(
        r"(if\s*\(\s*!reset\s*\)\s*"
        r"\n\s*begin\s*"
        r"\n\s*pipe\.fetch_pc\s*<=\s*RESET\s*;"
        r"\s*\n\s*end\s*)"
        r"(else\s+if\s*\(\s*!pipe\.stall_read\s*\))",
        re.DOTALL,
    )

    m = pat.search(s)

    if not m:
        die("execute.v: bloco fetch_pc original não localizado para ADDIR.")

    repl = (
        m.group(1)
        + """else if (pipe.addir_resume_valid)
    begin
        pipe.fetch_pc <= pipe.addir_resume_pc;
    end
    else if (pipe.addir_hold_fetch)
    begin
        pipe.fetch_pc <= pipe.fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]

    # Keep replayed ADDIs moving through EX even though fetch is held.
    occurrences = list(
        re.finditer(
            r"else\s+if\s*\(!pipe\.stall_read\s*\|\|",
            s,
        )
    )

    if occurrences:
        m2 = occurrences[-1]

        s = (
            s[:m2.start()]
            + (
                "else if (!pipe.stall_read || "
                "(pipe.addir_state == 3'd2) || "
                "(pipe.addir_state == 3'd3) ||"
            )
            + s[m2.end():]
        )

    write(path, s)


def patch_wb_addi(path):
    s = read(path)

    if "pipe.addir_resume_valid" in s:
        print("wb.v: ADDIR já instalado.")
        return

    pat = re.compile(
        r"(if\s*\(\s*!reset\s*\)\s*"
        r"\n\s*begin\s*"
        r"\n\s*pipe\.inst_fetch_pc\s*<=\s*RESET\s*;[^\n]*"
        r"\n\s*end\s*)"
        r"(else\s+if\s*\(\s*!pipe\.stall_read\s*\))",
        re.DOTALL,
    )

    m = pat.search(s)

    if not m:
        die("wb.v: bloco inst_fetch_pc não localizado para ADDIR.")

    repl = (
        m.group(1)
        + """else if (pipe.addir_resume_valid)
    begin
        pipe.inst_fetch_pc <= pipe.addir_resume_pc;
    end
    else if (pipe.addir_hold_fetch)
    begin
        pipe.inst_fetch_pc <= pipe.inst_fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]
    write(path, s)


def validate_addi(dest, mappings):
    if not mappings:
        return

    p = read(dest / "pipeline.v")
    i = read(dest / "IF_ID.v")
    e = read(dest / "execute.v")
    w = read(dest / "wb.v")

    checks = {
        "ADDIR state": "addir_state" in p,
        "ADDIR table": "ADDIR_MULTI_BEGIN" in i,
        "normal datapath issue1": "pipe.addir_addi1_word" in i,
        "normal datapath issue2": "pipe.addir_addi2_word" in i,
        "tipo SW": "addir_detect_is_sw" in i and "pipe.addir_is_sw" in i,
        "SW1 imediata": "pipe.addir_detect_now && addir_detect_is_sw" in i,
        "wait ADDI/SW": "addir_wait_count" in p,
        "fetch hold": "pipe.addir_hold_fetch" in e,
        "fetch resume": "pipe.fetch_pc <= pipe.addir_resume_pc;" in e,
        "inst resume": "pipe.inst_fetch_pc <= pipe.addir_resume_pc;" in w,
        "sem direct fused write": "FUSED_ADDI_WRITEBACK" not in i,
    }

    for mp in mappings:
        checks[f"{mp['type']} custom {mp['pair']}"] = (
            f"32'h{mp['custom']}" in i
        )

    bad = [k for k, v in checks.items() if not v]

    if bad:
        die("validação ADDIR falhou: " + ", ".join(bad))

    print("Validação SEQR ADDI/SW: OK")




def _extend_fused_sw_match(s, custom):
    pat = re.compile(
        r"(assign\s+fused_sw_match\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die("pipeline.v: assign fused_sw_match não localizado.")

    rhs = m.group(2).rstrip()
    clause = f"(inst_mem_read_data == 32'h{custom})"

    if clause in rhs:
        die(f"CUSTOM SW {custom} já existe.")

    rhs += "\n        || " + clause

    return s[:m.start(2)] + rhs + s[m.end(2):]


def _wrap_assign_rhs(s, signal, new_rhs_builder):
    """
    Localiza 'assign signal = RHS;' e substitui somente o RHS.
    """
    pat = re.compile(
        rf"(assign\s+{re.escape(signal)}\s*=\s*)(?P<rhs>.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die(f"pipeline.v: assign {signal} não localizado.")

    old_rhs = m.group("rhs").strip()
    new_rhs = new_rhs_builder(old_rhs)

    return s[:m.start("rhs")] + new_rhs + s[m.end("rhs"):]


def patch_pipeline_sw(path, mappings):
    """
    FUSED_SW ordenada:
      - captura addr/data das duas SW no ciclo da CUSTOM;
      - NÃO escreve imediatamente na DMEM;
      - segura fetch;
      - aguarda stores antigas saírem;
      - usa as duas portas da DMEM no commit;
      - retoma em PC+4.
    """
    if not mappings:
        return

    s = read(path)

    if "fused_sw_pending" in s:
        # Modo incremental: a arquitetura já está instalada.
        # Apenas acrescenta os novos CUSTOMs às tabelas existentes.
        for mp in mappings:
            custom = mp["custom"]

            s = _extend_sw_match(s, custom)

            s = _prepend_ternary(
                s,
                "fused_sw_rs1_1",
                custom,
                f"5'd{mp['first']['rs1']}",
            )
            s = _prepend_ternary(
                s,
                "fused_sw_rs2_1",
                custom,
                f"5'd{mp['first']['rs2']}",
            )
            s = _prepend_ternary(
                s,
                "fused_sw_rs1_2",
                custom,
                f"5'd{mp['second']['rs1']}",
            )
            s = _prepend_ternary(
                s,
                "fused_sw_rs2_2",
                custom,
                f"5'd{mp['second']['rs2']}",
            )
            s = _prepend_ternary(
                s,
                "fused_sw_imm1",
                custom,
                verilog_s32(mp["first"]["imm"]),
            )
            s = _prepend_ternary(
                s,
                "fused_sw_imm2",
                custom,
                verilog_s32(mp["second"]["imm"]),
            )

        write(path, s)
        print(
            f"pipeline.v: FUSED_SW existente reutilizada; "
            f"{len(mappings)} novo(s) par(es) adicionado(s)."
        )
        return

    anchor = "    // PC"

    if anchor not in s:
        die("pipeline.v: seção // PC não localizada para FUSED_SW.")

    rs11 = _ternary_map(
        mappings, "sw_rs11",
        lambda m: f"5'd{m['first']['rs1']}",
        "5'd0",
    )
    rs21 = _ternary_map(
        mappings, "sw_rs21",
        lambda m: f"5'd{m['first']['rs2']}",
        "5'd0",
    )
    rs12 = _ternary_map(
        mappings, "sw_rs12",
        lambda m: f"5'd{m['second']['rs1']}",
        "5'd0",
    )
    rs22 = _ternary_map(
        mappings, "sw_rs22",
        lambda m: f"5'd{m['second']['rs2']}",
        "5'd0",
    )
    imm1 = _ternary_map(
        mappings, "sw_imm1",
        lambda m: verilog_s32(m["first"]["imm"]),
        "32'sd0",
    )
    imm2 = _ternary_map(
        mappings, "sw_imm2",
        lambda m: verilog_s32(m["second"]["imm"]),
        "32'sd0",
    )

    matches = " ||\n        ".join(
        f"(inst_mem_read_data == 32'h{m['custom']})"
        for m in mappings
    )

    block = f"""
    // ================================================================
    // FUSED_SW_ORDERED - SW+SW 2 -> 1
    // Captura primeiro, escreve depois, preservando ordem arquitetural.
    // ================================================================
    wire fused_sw_match;
    wire fused_sw_detect;
    reg  fused_sw_pending;
    reg  [1:0] fused_sw_age;

    reg  [31:0] fused_sw_resume_pc;
    reg  [31:0] fused_sw_addr1_latched;
    reg  [31:0] fused_sw_addr2_latched;
    reg  [31:0] fused_sw_data1_latched;
    reg  [31:0] fused_sw_data2_latched;

    wire [4:0] fused_sw_rs1_1;
    wire [4:0] fused_sw_rs2_1;
    wire [4:0] fused_sw_rs1_2;
    wire [4:0] fused_sw_rs2_2;

    wire signed [31:0] fused_sw_imm1;
    wire signed [31:0] fused_sw_imm2;

    wire [31:0] fused_sw_base1_now;
    wire [31:0] fused_sw_base2_now;
    wire [31:0] fused_sw_data1_now;
    wire [31:0] fused_sw_data2_now;

    wire fused_sw_ports_free;
    wire fused_sw_fast_commit;
    wire fused_sw_pending_commit;
    wire fused_sw_commit;
    wire fused_sw_hold_fetch;
    wire fused_sw_resume_valid;

    assign fused_sw_match =
        {matches};

    assign fused_sw_detect =
        fused_sw_match &&
        !fused_sw_pending &&
        !stall_read &&
        !branch_stall;

    assign fused_sw_rs1_1 =
        {rs11};

    assign fused_sw_rs2_1 =
        {rs21};

    assign fused_sw_rs1_2 =
        {rs12};

    assign fused_sw_rs2_2 =
        {rs22};

    assign fused_sw_imm1 =
        {imm1};

    assign fused_sw_imm2 =
        {imm2};

    // Resolve operandos no ciclo da detecção, antes que registradores mudem.
    assign fused_sw_base1_now =
        (fused_sw_rs1_1 == 5'd0) ? 32'd0 :

        // Forwarding EX -> CUSTOM.
        // A instrução imediatamente anterior ainda pode não ter chegado ao WB.
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_sw_rs1_1) ?
            result :

        // Forwarding WB -> CUSTOM.
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_sw_rs1_1) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :

        regs[fused_sw_rs1_1];

    assign fused_sw_data1_now =
        (fused_sw_rs2_1 == 5'd0) ? 32'd0 :

        // Forwarding EX -> CUSTOM para dado da primeira SW.
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_sw_rs2_1) ?
            result :

        // Forwarding WB -> CUSTOM.
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_sw_rs2_1) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :

        regs[fused_sw_rs2_1];

    assign fused_sw_base2_now =
        (fused_sw_rs1_2 == 5'd0) ? 32'd0 :

        // Forwarding EX -> CUSTOM.
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_sw_rs1_2) ?
            result :

        // Forwarding WB -> CUSTOM.
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_sw_rs1_2) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :

        regs[fused_sw_rs1_2];

    assign fused_sw_data2_now =
        (fused_sw_rs2_2 == 5'd0) ? 32'd0 :

        // Forwarding EX -> CUSTOM para dado da segunda SW.
        ((alu || lui || jal || jalr) &&
         !mem_to_reg &&
         dest_reg_sel != 5'd0 &&
         dest_reg_sel == fused_sw_rs2_2) ?
            result :

        // Forwarding WB -> CUSTOM.
        (!wb_stall &&
         wb_alu_to_reg &&
         wb_dest_reg_sel != 5'd0 &&
         wb_dest_reg_sel == fused_sw_rs2_2) ?
            (wb_mem_to_reg ? wb_read_data : wb_result) :

        regs[fused_sw_rs2_2];

    // Só comita quando nenhuma store mais antiga está usando a porta 1.
    // wb_custom_sw4/custom_sw_write_valid também fazem parte da lógica
    // histórica deste pipeline.
    assign fused_sw_ports_free =
        !wb_mem_write &&
        !wb_custom_sw4 &&
        !custom_sw_write_valid;

    // SINGLE-CYCLE V6
    assign fused_sw_fast_commit =
        fused_sw_detect &&
        fused_sw_ports_free;

    assign fused_sw_pending_commit =
        fused_sw_pending &&
        fused_sw_ports_free;

    assign fused_sw_commit =
        fused_sw_fast_commit ||
        fused_sw_pending_commit;

    assign fused_sw_hold_fetch =
        (fused_sw_detect && !fused_sw_ports_free) ||
        (fused_sw_pending && !fused_sw_pending_commit);

    // Somente o fallback precisa redirecionar o PC.
    assign fused_sw_resume_valid =
        fused_sw_pending_commit;

    always @(posedge clk or negedge reset)
    begin
        if(!reset)
        begin
            fused_sw_pending <= 1'b0;
            fused_sw_age <= 2'd0;
            fused_sw_resume_pc <= 32'd0;
            fused_sw_addr1_latched <= 32'd0;
            fused_sw_addr2_latched <= 32'd0;
            fused_sw_data1_latched <= 32'd0;
            fused_sw_data2_latched <= 32'd0;
        end
        else
        begin
            if(fused_sw_detect)
            begin
                fused_sw_pending <= !fused_sw_ports_free;
                fused_sw_age <= 2'd0;
                fused_sw_resume_pc <= fetch_pc + 32'd4;

                fused_sw_addr1_latched <=
                    fused_sw_base1_now + fused_sw_imm1;

                fused_sw_addr2_latched <=
                    fused_sw_base2_now + fused_sw_imm2;

                fused_sw_data1_latched <= fused_sw_data1_now;
                fused_sw_data2_latched <= fused_sw_data2_now;

                $display(
                    "[FUSED_SW CAP] pc=%h addr1=%h data1=%h addr2=%h data2=%h",
                    fetch_pc,
                    fused_sw_base1_now + fused_sw_imm1,
                    fused_sw_data1_now,
                    fused_sw_base2_now + fused_sw_imm2,
                    fused_sw_data2_now
                );

                $display(
                    "[FUSED_SW FWD] ex_dest=x%0d ex_result=%h alu=%b wb_dest=x%0d wb_result=%h",
                    dest_reg_sel,
                    result,
                    alu,
                    wb_dest_reg_sel,
                    wb_mem_to_reg ? wb_read_data : wb_result
                );
            end

            if(fused_sw_pending && !fused_sw_commit)
            begin
                if(fused_sw_age < 2'd3)
                    fused_sw_age <= fused_sw_age + 2'd1;

                $display(
                    "[FUSED_SW WAIT] age=%0d old_store=%b ports_free=%b",
                    fused_sw_age,
                    wb_mem_write,
                    fused_sw_ports_free
                );
            end

            if(fused_sw_pending_commit)
            begin
                fused_sw_pending <= 1'b0;
                fused_sw_age <= 2'd0;

                $display(
                    "[FUSED_SW COMMIT] addr1=%h data1=%h addr2=%h data2=%h resume=%h",
                    fused_sw_addr1_latched,
                    fused_sw_data1_latched,
                    fused_sw_addr2_latched,
                    fused_sw_data2_latched,
                    fused_sw_resume_pc
                );
            end
        end
    end

"""

    s = s.replace(anchor, block + anchor, 1)

    # Highest priority only at COMMIT, not at detection.
    s = _wrap_assign_rhs(
        s,
        "dmem_write_ready",
        lambda old: f"fused_sw_commit || ({old})",
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write_address",
        lambda old: (
            "fused_sw_fast_commit ? (fused_sw_base1_now + fused_sw_imm1) :\n"
            "                                      fused_sw_pending_commit ? fused_sw_addr1_latched :\n"
            f"                                      ({old})"
        ),
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write_data",
        lambda old: (
            "fused_sw_fast_commit ? fused_sw_data1_now :\n"
            "                                      fused_sw_pending_commit ? fused_sw_data1_latched :\n"
            f"                                      ({old})"
        ),
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write_byte",
        lambda old: (
            "fused_sw_commit ? 4'b1111 :\n"
            f"                                      ({old})"
        ),
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write2_ready",
        lambda old: f"fused_sw_commit || ({old})",
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write2_address",
        lambda old: (
            "fused_sw_fast_commit ? (fused_sw_base2_now + fused_sw_imm2) :\n"
            "                                      fused_sw_pending_commit ? fused_sw_addr2_latched :\n"
            f"                                      ({old})"
        ),
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write2_data",
        lambda old: (
            "fused_sw_fast_commit ? fused_sw_data2_now :\n"
            "                                      fused_sw_pending_commit ? fused_sw_data2_latched :\n"
            f"                                      ({old})"
        ),
    )

    s = _wrap_assign_rhs(
        s,
        "dmem_write2_byte",
        lambda old: (
            "fused_sw_commit ? 4'b1111 :\n"
            f"                                      ({old})"
        ),
    )

    write(path, s)


def patch_execute_sw(path):
    s = read(path)

    if "fused_sw_resume_valid" in s:
        print("execute.v: FUSED_SW_ORDERED já instalado.")
        return

    pat = re.compile(
        r"(if\s*\(\s*!reset\s*\)\s*"
        r"\n\s*begin\s*"
        r"\n\s*pipe\.fetch_pc\s*<=\s*RESET\s*;"
        r"\s*\n\s*end\s*)"
        r"(else\s+if\s*\(\s*!pipe\.stall_read\s*\))",
        re.DOTALL,
    )

    m = pat.search(s)

    if not m:
        die("execute.v: bloco fetch_pc não localizado para FUSED_SW.")

    repl = (
        m.group(1)
        + """else if (pipe.fused_sw_resume_valid)
    begin
        pipe.fetch_pc <= pipe.fused_sw_resume_pc;
    end
    else if (pipe.fused_sw_hold_fetch)
    begin
        pipe.fetch_pc <= pipe.fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]
    write(path, s)


def patch_wb_sw(path):
    s = read(path)

    if "fused_sw_resume_valid" in s:
        print("wb.v: FUSED_SW_ORDERED já instalado.")
        return

    pat = re.compile(
        r"(if\s*\(\s*!reset\s*\)\s*"
        r"\n\s*begin\s*"
        r"\n\s*pipe\.inst_fetch_pc\s*<=\s*RESET\s*;[^\n]*"
        r"\n\s*end\s*)"
        r"(else\s+if\s*\(\s*!pipe\.stall_read\s*\))",
        re.DOTALL,
    )

    m = pat.search(s)

    if not m:
        die("wb.v: bloco inst_fetch_pc não localizado para FUSED_SW.")

    repl = (
        m.group(1)
        + """else if (pipe.fused_sw_resume_valid)
    begin
        pipe.inst_fetch_pc <= pipe.fused_sw_resume_pc;
    end
    else if (pipe.fused_sw_hold_fetch)
    begin
        pipe.inst_fetch_pc <= pipe.inst_fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]
    write(path, s)


def patch_ifid_sw(path):
    s = read(path)

    if "FUSED_SW_ORDERED_MASK" in s:
        print("IF_ID.v: FUSED_SW_ORDERED já instalada.")
        return

    pat = re.compile(
        r"\bassign\s+pipe\s*\.\s*instruction\s*=\s*"
        r"(?P<rhs>.*?)"
        r";",
        re.DOTALL | re.MULTILINE,
    )

    m = pat.search(s)

    if not m:
        die("IF_ID.v: pipe.instruction não localizado para FUSED_SW.")

    old_rhs = m.group("rhs").strip()

    new_assign = f"""// FUSED_SW_ORDERED_MASK
assign pipe.instruction =
    (pipe.fused_sw_detect || pipe.fused_sw_pending) ? NOP :
    ({old_rhs});"""

    s = s[:m.start()] + new_assign + s[m.end():]
    write(path, s)


def validate_sw(dest, mappings):
    if not mappings:
        return

    p = read(dest / "pipeline.v")
    i = read(dest / "IF_ID.v")
    e = read(dest / "execute.v")
    w = read(dest / "wb.v")

    checks = {
        "pending": "fused_sw_pending" in p,
        "timing SW": "fused_sw_age" in p and "age=%0d" in p,
        "capture": "[FUSED_SW CAP]" in p,
        "commit": "fused_sw_commit" in p,
        "ordem": "fused_sw_ports_free" in p,
        "latched data1": "fused_sw_data1_latched" in p,
        "latched data2": "fused_sw_data2_latched" in p,
        "EX forwarding": "dest_reg_sel == fused_sw_rs2_1" in p and "result :" in p,
        "WB fallback": "wb_dest_reg_sel == fused_sw_rs2_1" in p,
        "capture/commit same latch": "fused_sw_data1_latched" in p and "fused_sw_addr1_latched" in p,
        "hold fetch": "pipe.fused_sw_hold_fetch" in e,
        "resume fetch": "pipe.fetch_pc <= pipe.fused_sw_resume_pc;" in e,
        "resume wb": "pipe.inst_fetch_pc <= pipe.fused_sw_resume_pc;" in w,
        "mask": "FUSED_SW_ORDERED_MASK" in i,
    }

    for mp in mappings:
        checks[f"SW custom {mp['pair']}"] = (
            f"32'h{mp['custom']}" in p
        )

    bad = [k for k, v in checks.items() if not v]

    if bad:
        die("validação FUSED_SW_ORDERED falhou: " + ", ".join(bad))

    print("Validação FUSED_SW_ORDERED: OK")



def patch_ifid(path, mappings):
    s = read(path)

    # ================================================================
    # DETECÇÃO ROBUSTA DE FUSED_LW JÁ INSTALADA
    #
    # Versões anteriores podem não conter o comentário FUSED_LW_MASK.
    # Portanto verificamos a lógica real, e não apenas o marcador textual.
    # ================================================================
    already_has_mask = (
        "FUSED_LW_MASK" in s
        or "pipe.fused_lw_valid ? NOP" in s
        or "pipe.fused_lw_valid" in s
    )

    already_has_writeback = (
        "pipe.fused_lw_rd1" in s
        and "pipe.fused_lw_rd2" in s
        and "pipe.fused_lw_data1" in s
        and "pipe.fused_lw_data2" in s
    )

    if already_has_mask and already_has_writeback:
        print(
            "IF_ID.v: FUSED_LW já instalada "
            "(detectada estruturalmente); reutilizando."
        )
        return

    # ---------------------------------------------------------------
    # Caso parcialmente instalado: não duplicar o que já existe.
    # ---------------------------------------------------------------

    # 1) Mascara CUSTOM LW no decoder normal.
    if not already_has_mask:
        pat = re.compile(
            r"\bassign\s+pipe\s*\.\s*instruction\s*=\s*"
            r"(?P<rhs>.*?)"
            r";",
            re.DOTALL | re.MULTILINE,
        )

        m = pat.search(s)

        if not m:
            candidates = [
                line.strip()
                for line in s.splitlines()
                if "instruction" in line.lower()
            ][:15]

            die(
                "IF_ID.v: pipe.instruction não localizado para instalar "
                "FUSED_LW. Candidatas: "
                + " | ".join(candidates)
            )

        old_rhs = m.group("rhs").strip()

        new_assign = f"""// FUSED_LW_MASK
assign pipe.instruction =
    pipe.fused_lw_valid ? NOP :
    ({old_rhs});"""

        s = s[:m.start()] + new_assign + s[m.end():]

    # 2) Writeback duplo.
    if not already_has_writeback:
        regpos = s.find("integer i;")

        if regpos < 0:
            die(
                "IF_ID.v: banco de registradores não localizado "
                "para FUSED_LW."
            )

        m = re.search(
            r"\nelse\s+if\s*\(",
            s[regpos:],
        )

        if not m:
            die(
                "IF_ID.v: primeiro else-if do register file "
                "não localizado para FUSED_LW."
            )

        at = regpos + m.start()

        wb = """// FUSED_LW_WRITEBACK
else if (pipe.fused_lw_valid)
begin
    if (pipe.fused_lw_rd1 != 5'd0)
        pipe.regs[pipe.fused_lw_rd1] <= pipe.fused_lw_data1;

    if (pipe.fused_lw_rd2 != 5'd0)
        pipe.regs[pipe.fused_lw_rd2] <= pipe.fused_lw_data2;

    $display(
        "[FUSED_LW] rd1=x%0d data1=%h addr1=%h rd2=x%0d data2=%h addr2=%h",
        pipe.fused_lw_rd1,
        pipe.fused_lw_data1,
        pipe.fused_lw_fast_addr1,
        pipe.fused_lw_rd2,
        pipe.fused_lw_data2,
        pipe.fused_lw_fast_addr2
    );
end
"""

        s = s[:at] + "\n" + wb + s[at:]

    write(path, s)

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
def apply(base, dest):
    """
    Aplica todos os arquivos necessários para LW/ADDI/SW.
    """
    for name in (
        "pipeline.v",
        "IF_ID.v",
        "execute.v",
        "wb.v",
        "memory.v",
        "tb_pipeline.v",
        "imem_custom.hex",
    ):
        src = dest / name
        if not src.exists():
            continue

        dst = base / name

        if dst.exists():
            bak = base / f"{name}.pre_custom_multi"
            if not bak.exists():
                shutil.copy2(dst, bak)

        shutil.copy2(src, dst)
        print(f"aplicado: {src} -> {dst}")



def verify_generated_hex(old_words, new_words, mappings):
    """
    Garante que cada par selecionado virou uma CUSTOM no HEX final.
    """
    errors = []

    for mp in mappings:
        custom = mp["custom"]
        inst1 = mp["inst1"]
        inst2 = mp["inst2"]

        if custom not in new_words:
            errors.append(
                f"Par {mp['pair']} [{mp['type']}]: CUSTOM {custom} não apareceu no HEX final."
            )

        # Se o mesmo par continuar consecutivo, algo deu errado na compactação.
        if any(
            new_words[i] == inst1 and new_words[i + 1] == inst2
            for i in range(len(new_words) - 1)
        ):
            errors.append(
                f"Par {mp['pair']} [{mp['type']}]: "
                f"{inst1} {inst2} ainda aparece consecutivo no HEX final."
            )

    if errors:
        die(
            "validação do HEX customizado falhou:\n  "
            + "\n  ".join(errors)
        )

    print("Validação do HEX 2->1: OK")
    for mp in mappings:
        print(
            f"  Par {mp['pair']:02d} [{mp['type']}]: "
            f"{mp['inst1']} + {mp['inst2']} -> {mp['custom']}"
        )


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Customizador dedicado SW+SW, 2 -> 1 sem NOP no HEX, "
            "com forwarding EX->WB->REG e commit ordenado."
        )
    )

    ap.add_argument("base", type=Path)
    ap.add_argument("destino", type=Path)

    ap.add_argument(
        "--originais",
        nargs="+",
        required=True,
        help=(
            "Pares LW+LW, ADDI+ADDI ou SW+SW. "
            "Ex.: LW1 LW2 ADDI1 ADDI2 SW1 SW2"
        ),
    )

    ap.add_argument(
        "--ocorrencias",
        nargs="+",
        type=int,
        help=(
            "Ocorrência 1-based de cada par no HEX atual."
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

    if args.destino.exists():
        if not args.sobrescrever:
            die("destino existe; use --sobrescrever.")
        shutil.rmtree(args.destino)

    shutil.copytree(args.base, args.destino)

    words = parse_hex(args.hex_entrada)

    pair_count = len(args.originais) // 2

    if args.ocorrencias is not None and len(args.ocorrencias) != pair_count:
        die(
            f"--ocorrencias deve possuir {pair_count} valor(es)."
        )

    rtl = "".join(
        read(args.destino / n)
        for n in ("pipeline.v", "IF_ID.v", "execute.v", "wb.v")
    )

    mappings = []
    custom_extra = set()

    for i in range(0, len(args.originais), 2):
        first = decode_inst(args.originais[i])
        second = decode_inst(args.originais[i + 1])

        if first["type"] != "SW" or second["type"] != "SW":
            die(
                f"Par {i//2+1}: este arquivo aceita somente SW+SW; "
                f"recebido {first['type']} + {second['type']}."
            )

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
                "type": first["type"],
                "inst1": first["hex"],
                "inst2": second["hex"],
                "custom": custom,
                "first": first,
                "second": second,
            }
        )

    # Compacta todos os pares NOVOS desta execução em uma única passagem.
    work, located, total_reloc = compact_all_global(words, mappings)

    verify_generated_hex(words, work, mappings)

    by_custom = {x["custom"]: x for x in located}

    for m in mappings:
        loc = by_custom[m["custom"]]
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

    lw_maps = []
    addi_maps = []
    sw_maps = mappings

    # LW dual-port.
    if lw_maps:
        patch_memory(args.destino / "memory.v")
        patch_pipeline(args.destino / "pipeline.v", lw_maps)
        patch_ifid(args.destino / "IF_ID.v", lw_maps)
        patch_tb(args.destino / "tb_pipeline.v")
        validate(args.destino, lw_maps)

    # SW usa as duas portas de escrita existentes da DMEM.
    if sw_maps:
        patch_pipeline_sw(
            args.destino / "pipeline.v",
            sw_maps,
        )
        patch_ifid_sw(
            args.destino / "IF_ID.v",
        )
        patch_execute_sw(
            args.destino / "execute.v",
        )
        patch_wb_sw(
            args.destino / "wb.v",
        )
        validate_sw(
            args.destino,
            sw_maps,
        )

    # ADDI usa replay pelo datapath normal para preservar ordem de WB.
    if addi_maps:
        patch_pipeline_addi(
            args.destino / "pipeline.v",
            addi_maps,
        )
        patch_ifid_addi(
            args.destino / "IF_ID.v",
            addi_maps,
        )
        patch_execute_addi(
            args.destino / "execute.v",
        )
        patch_wb_addi(
            args.destino / "wb.v",
        )
        validate_addi(
            args.destino,
            addi_maps,
        )

    print()
    print("=" * 76)
    print("SW SINGLE-CYCLE V7 INCREMENTAL - SW+SW, 2 -> 1 SEM NOP")
    print("=" * 76)

    for mp in mappings:
        print(
            f"Par {mp['pair']:02d} [{mp['type']}]: "
            f"{mp['inst1']} + {mp['inst2']} "
            f"-> CUSTOM={mp['custom']} "
            f"PC antigo=0x{mp['old_pc']:08x} "
            f"PC novo=0x{mp['new_pc']:08x}"
        )

    print(f"HEX: {len(words)} -> {len(work)} palavras")
    print(f"Relocações BRANCH/JAL: {total_reloc}")
    print("NOP inserido no HEX: NÃO")
    print("SW: dual-write no ciclo da detecção; pending só em conflito real")
    print("Dependência da instrução imediatamente anterior: suportada via EX forwarding")
    print("=" * 76)

    if args.aplicar_no_base:
        apply(args.base, args.destino)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
