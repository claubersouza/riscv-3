#!/usr/bin/env python3
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


def decode_sw(h):
    h = h.lower().replace("0x", "")

    if not re.fullmatch(r"[0-9a-f]{8}", h):
        die(f"HEX inválido: {h}")

    w = int(h, 16)
    opcode = w & 0x7f
    funct3 = (w >> 12) & 7

    if opcode != 0x23 or funct3 != 0b010:
        die(f"{h} não é SW RV32I.")

    imm12 = (((w >> 25) & 0x7f) << 5) | ((w >> 7) & 0x1f)

    return {
        "hex": h,
        "type": "SW",
        "rd": 0,
        "rs1": (w >> 15) & 31,
        "rs2": (w >> 20) & 31,
        "imm": sext(imm12, 12),
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


def verilog_s32(value):
    """
    Formata inteiro Python como constante signed de 32 bits em Verilog.
    Exemplos:
        12  -> 32'sd12
        -20 -> -32'sd20
    """
    value = int(value)

    if value < 0:
        return f"-32'sd{-value}"

    return f"32'sd{value}"


def _ternary_map(mappings, key, fmt, default):
    """
    Gera uma cadeia ternária Verilog baseada na CUSTOM atual.

    Exemplo:
        (inst_mem_read_data == 32'hXXXXXXXX) ? VALOR :
        (inst_mem_read_data == 32'hYYYYYYYY) ? VALOR :
        DEFAULT
    """
    parts = []

    for mp in mappings:
        parts.append(
            f"(inst_mem_read_data == 32'h{mp['custom']}) ? {fmt(mp)} :"
        )

    return "\n        ".join(parts) + f"\n        {default}"


def patch_pipeline_sw(path, mappings):
    """
    SWR_NORMAL:
      CUSTOM no HEX substitui SW1+SW2.
      As duas SW são reexecutadas pelo datapath RV32I NORMAL.

      Fluxo:
        DETECT
        -> DRAIN (espera instruções anteriores terminarem)
        -> ISSUE1
        -> ISSUE2
        -> WAIT_WRITE (espera 2 writes reais na DMEM)
        -> RESUME

    Não calcula endereço/dado da SW em hardware customizado.
    """
    if not mappings:
        return

    s = read(path)

    if "swr_state" in s:
        print("pipeline.v: SWR_NORMAL já instalada; reutilizando FSM.")
        return

    anchor = "    // PC"
    if anchor not in s:
        die("pipeline.v: seção // PC não localizada.")

    block = """
    // ================================================================
    // SWR_NORMAL - SW+SW 2 -> 1 no HEX, execução pelo datapath normal
    // ================================================================
    reg  [2:0]  swr_state;
    reg         swr_seen;
    reg  [1:0]  swr_write_count;
    reg  [31:0] swr_resume_pc;
    reg  [31:0] swr_inst2;

    wire [31:0] swr_inst1_selected;
    wire swr_match;
    wire swr_detect;
    wire swr_hold_fetch;
    wire swr_resume_valid;

"""
    s = s.replace(anchor, block + anchor, 1)
    write(path, s)


def _extend_assign_or(s, signal, custom):
    pat = re.compile(
        rf"(assign\s+pipe\.{re.escape(signal)}\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die(f"IF_ID.v: assign pipe.{signal} não localizado.")

    rhs = m.group(2).rstrip()
    clause = f"(inst_mem_read_data == 32'h{custom})"

    if clause in rhs:
        die(f"CUSTOM {custom} já existe em pipe.{signal}.")

    rhs = rhs + "\n        || " + clause
    return s[:m.start(2)] + rhs + s[m.end(2):]


def _prepend_inst1_selector(s, custom, inst1):
    pat = re.compile(
        r"(assign\s+pipe\.swr_inst1_selected\s*=\s*)(.*?)(;)",
        re.DOTALL,
    )
    m = pat.search(s)

    if not m:
        die("IF_ID.v: assign pipe.swr_inst1_selected não localizado.")

    rhs = m.group(2).lstrip()

    clause = (
        f"(inst_mem_read_data == 32'h{custom}) ? "
        f"32'h{inst1} :\n        "
    )

    if f"32'h{custom}" in rhs:
        die(f"CUSTOM {custom} já existe no seletor SW1.")

    rhs = clause + rhs
    return s[:m.start(2)] + rhs + s[m.end(2):]


def patch_ifid_sw(path, mappings):
    s = read(path)

    # ================================================================
    # INCREMENTAL: SWR_EXACT já existe.
    # ================================================================
    if "SWR_EXACT_BEGIN" in s:
        print("IF_ID.v: SWR_EXACT existente; ampliando tabela de CUSTOMs.")

        for mp in mappings:
            custom = mp["custom"]

            # 1) Amplia match.
            s = _extend_assign_or(
                s,
                "swr_match",
                custom,
            )

            # 2) Amplia seletor da primeira SW.
            s = _prepend_inst1_selector(
                s,
                custom,
                mp["inst1"],
            )

            # 3) Acrescenta SW2 na tabela do controller.
            marker = "                // SWR_PAIR_TABLE_END"
            pos = s.find(marker)

            if pos < 0:
                # Upgrade de uma V13 antiga que ainda não tinha marcador.
                # Insere o marcador antes de:
                # pipe.swr_state <= 3'd1;
                detect_marker = "                pipe.swr_state <= 3'd1;"

                pos2 = s.find(detect_marker)

                if pos2 < 0:
                    die(
                        "IF_ID.v: ponto de inserção da tabela SW2 "
                        "não localizado."
                    )

                s = (
                    s[:pos2]
                    + "                // SWR_PAIR_TABLE_END\n\n"
                    + s[pos2:]
                )

                pos = s.find(marker)

            entry = f"""                if(inst_mem_read_data == 32'h{custom})
                begin
                    pipe.swr_inst2 <= 32'h{mp['inst2']};
                end

"""

            s = s[:pos] + entry + s[pos:]

        write(path, s)
        return

    # ================================================================
    # PRIMEIRA INSTALAÇÃO.
    # ================================================================
    pat = re.compile(
        r"\bassign\s+pipe\s*\.\s*instruction\s*=\s*"
        r"(?P<rhs>.*?)"
        r";",
        re.DOTALL | re.MULTILINE,
    )
    m = pat.search(s)

    if not m:
        die("IF_ID.v: pipe.instruction não localizado.")

    old_rhs = m.group("rhs").strip()

    matches = " ||\n        ".join(
        f"(inst_mem_read_data == 32'h{mp['custom']})"
        for mp in mappings
    )

    inst1_select = "\n        ".join(
        f"(inst_mem_read_data == 32'h{mp['custom']}) ? "
        f"32'h{mp['inst1']} :"
        for mp in mappings
    ) + "\n        32'h00000000"

    pair_lines = []

    for mp in mappings:
        pair_lines.append(
            f"""                if(inst_mem_read_data == 32'h{mp['custom']})
                begin
                    pipe.swr_inst2 <= 32'h{mp['inst2']};
                end"""
        )

    pairs = "\n".join(pair_lines)

    new_assign = f"""// SWR_EXACT_BEGIN
assign pipe.swr_match =
        {matches};

assign pipe.swr_detect =
    (pipe.swr_state == 3'd0) &&
    !pipe.swr_seen &&
    pipe.swr_match &&
    !pipe.stall_read;

assign pipe.swr_inst1_selected =
        {inst1_select};

assign pipe.swr_hold_fetch =
    pipe.swr_detect ||
    (pipe.swr_state == 3'd1) ||
    (pipe.swr_state == 3'd2);

assign pipe.swr_resume_valid =
    (pipe.swr_state == 3'd3);

assign pipe.instruction =
    pipe.swr_detect ? pipe.swr_inst1_selected :
    (pipe.swr_state == 3'd1) ? pipe.swr_inst2 :
    // SWR_ORIGINAL_FALLBACK_BEGIN
    ({old_rhs});
    // SWR_ORIGINAL_FALLBACK_END
// SWR_EXACT_END"""

    s = s[:m.start()] + new_assign + s[m.end():]

    insert = s.find("// Stall read assignment")

    if insert < 0:
        die("IF_ID.v: seção Stall read assignment não localizada.")

    fsm = f"""
// ================================================================
// SWR_EXACT controller
// ================================================================
always @(posedge clk or negedge reset)
begin
    if(!reset)
    begin
        pipe.swr_state <= 3'd0;
        pipe.swr_seen <= 1'b0;
        pipe.swr_write_count <= 2'd0;
        pipe.swr_resume_pc <= 32'd0;
        pipe.swr_inst2 <= 32'd0;
    end
    else
    begin
        case(pipe.swr_state)

        3'd0:
        begin
            if(pipe.swr_detect)
            begin
                pipe.swr_seen <= 1'b1;
                pipe.swr_write_count <= 2'd0;
                pipe.swr_resume_pc <= pipe.fetch_pc + 32'd8;

{pairs}

                // SWR_PAIR_TABLE_END

                // SW1 já está sendo decodificada neste ciclo.
                pipe.swr_state <= 3'd1;

                $display(
                    "[SWR] DETECT+ISSUE1 pc=%h inst1=%h resume=%h",
                    pipe.fetch_pc,
                    pipe.swr_inst1_selected,
                    pipe.fetch_pc + 32'd8
                );
            end
            else if(!pipe.swr_match)
            begin
                pipe.swr_seen <= 1'b0;
            end
        end

        3'd1:
        begin
            pipe.swr_state <= 3'd2;

            if(pipe.dmem_write_ready)
            begin
                pipe.swr_write_count <= pipe.swr_write_count + 2'd1;

                $display(
                    "[SWR] WRITE count=%0d addr=%h data=%h",
                    pipe.swr_write_count + 2'd1,
                    pipe.dmem_write_address,
                    pipe.dmem_write_data
                );
            end

            $display("[SWR] ISSUE2=%h", pipe.swr_inst2);
        end

        3'd2:
        begin
            if(pipe.dmem_write_ready)
            begin
                $display(
                    "[SWR] WRITE count=%0d addr=%h data=%h",
                    pipe.swr_write_count + 2'd1,
                    pipe.dmem_write_address,
                    pipe.dmem_write_data
                );

                if(pipe.swr_write_count >= 2'd1)
                begin
                    pipe.swr_write_count <= 2'd0;
                    pipe.swr_state <= 3'd3;

                    $display(
                        "[SWR] duas SW concluidas; resume=%h",
                        pipe.swr_resume_pc
                    );
                end
                else
                begin
                    pipe.swr_write_count <= 2'd1;
                end
            end
        end

        3'd3:
        begin
            pipe.swr_state <= 3'd0;
        end

        default:
            pipe.swr_state <= 3'd0;

        endcase
    end
end

"""

    s = s[:insert] + fsm + s[insert:]

    target = "else if (!pipe.stall_read ||"

    if target not in s:
        die(
            "IF_ID.v: condição principal do decode "
            "'else if (!pipe.stall_read ||' não localizada."
        )

    s = s.replace(
        target,
        "else if (!pipe.stall_read || "
        "pipe.swr_detect || "
        "(pipe.swr_state == 3'd1) ||",
        1,
    )

    write(path, s)



def patch_execute_sw(path):
    s = read(path)

    if "pipe.swr_resume_valid" in s:
        print("execute.v: SWR_NORMAL já instalado.")
        return

    # Fetch PC priority.
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
        die("execute.v: bloco fetch_pc não localizado.")

    repl = (
        m.group(1)
        + """else if (pipe.swr_resume_valid)
    begin
        pipe.fetch_pc <= pipe.swr_resume_pc;
    end
    else if (pipe.swr_hold_fetch)
    begin
        pipe.fetch_pc <= pipe.fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]

    # Ensure replayed SWs progress into WB.
    # Find the WB pipeline always block condition and permit states 2/3.
    marker = "else if (!pipe.stall_read ||"
    pos = s.rfind(marker)
    if pos >= 0:
        s = (
            s[:pos]
            + "else if (!pipe.stall_read || "
              "(pipe.swr_state == 3'd1) || "
              "(pipe.swr_state == 3'd2) || "
              "(pipe.swr_state == 3'd3) ||"
            + s[pos + len(marker):]
        )

    write(path, s)


def patch_wb_sw(path):
    s = read(path)

    if "pipe.swr_resume_valid" in s:
        print("wb.v: SWR_NORMAL já instalado.")
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
        die("wb.v: bloco inst_fetch_pc não localizado.")

    repl = (
        m.group(1)
        + """else if (pipe.swr_resume_valid)
    begin
        pipe.inst_fetch_pc <= pipe.swr_resume_pc;
    end
    else if (pipe.swr_hold_fetch)
    begin
        pipe.inst_fetch_pc <= pipe.inst_fetch_pc;
    end
    else if (!pipe.stall_read)"""
    )

    s = s[:m.start()] + repl + s[m.end():]
    write(path, s)


def validate_sw(dest, mappings):
    p = read(dest / "pipeline.v")
    i = read(dest / "IF_ID.v")
    e = read(dest / "execute.v")
    w = read(dest / "wb.v")

    checks = {
        "state": "swr_state" in p,
        "exact block": "SWR_EXACT_BEGIN" in i,
        "SW1 no detect": "pipe.swr_detect ? pipe.swr_inst1_selected" in i,
        "SW2 no ciclo seguinte":
            "(pipe.swr_state == 3'd1) ? pipe.swr_inst2" in i,
        "sem drain": "swr_drain_count" not in p,
        "2 writes reais": "duas SW concluidas" in i,
        "hold fetch": "pipe.swr_hold_fetch" in e,
        "resume fetch": "pipe.fetch_pc <= pipe.swr_resume_pc;" in e,
        "resume wb": "pipe.inst_fetch_pc <= pipe.swr_resume_pc;" in w,
    }

    for mp in mappings:
        checks[f"custom {mp['pair']}"] = (
            f"32'h{mp['custom']}" in i
        )

    b = i.find("// SWR_EXACT_BEGIN")
    fallback = i.find("// SWR_ORIGINAL_FALLBACK_BEGIN", b)

    if b >= 0 and fallback > b:
        custom_region = i[b:fallback]
        checks["sem NOP custom"] = (
            "? NOP" not in custom_region
            and "32'h00000013" not in custom_region
        )
    else:
        checks["sem NOP custom"] = False

    bad = [k for k, v in checks.items() if not v]

    if bad:
        die("validação SWR_EXACT falhou: " + ", ".join(bad))

    print("Validação SWR_EXACT: OK")



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


def replace_pairs_in_place(words, mappings):
    work = list(words)
    located = []

    for mp in mappings:
        a = mp["inst1"]
        b = mp["inst2"]
        occurrence = mp.get("occurrence")

        matches = [
            i for i in range(len(work) - 1)
            if work[i] == a and work[i + 1] == b
        ]

        if not matches:
            die(
                f"Par {mp['pair']} [SW] não encontrado no HEX: "
                f"{a} + {b}"
            )

        if occurrence is None:
            if len(matches) != 1:
                die(
                    f"Par {mp['pair']} ocorre {len(matches)} vezes. "
                    "Informe --ocorrencias."
                )
            idx = matches[0]
        else:
            if occurrence < 1 or occurrence > len(matches):
                die(
                    f"Par {mp['pair']}: ocorrência {occurrence} inválida."
                )
            idx = matches[occurrence - 1]

        work[idx] = mp["custom"]

        located.append(
            {
                "custom": mp["custom"],
                "old_pc": idx * 4,
                "new_pc": idx * 4,
                "second_pc": (idx + 1) * 4,
            }
        )

    return work, located


def verify_in_place_hex(old_words, new_words, mappings):
    if len(old_words) != len(new_words):
        die("HEX in-place alterou o tamanho.")

    for mp in mappings:
        if mp["custom"] not in new_words:
            die(f"CUSTOM {mp['custom']} não apareceu no HEX final.")

    print("Validação HEX in-place: OK")
    print("PCs preservados; BRANCH/JAL não foram relocados.")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Customizador SW+SW 2 -> 1 sem NOP no HEX e sem NOP na FSM. "
            "Captura operandos com forwarding EX->WB->REG, "
            "espera stores antigas, executa WRITE1 e WRITE2 em sequência "
            "e então retoma o fluxo."
        )
    )

    ap.add_argument("base", type=Path)
    ap.add_argument("destino", type=Path)

    ap.add_argument(
        "--originais",
        nargs="+",
        required=True,
        help="Pares SW1 SW2 SW3 SW4 ...",
    )

    ap.add_argument(
        "--ocorrencias",
        nargs="+",
        type=int,
        help=(
            "Ocorrência 1-based de cada par SW no HEX atual. "
            "Use quando o mesmo par aparece mais de uma vez."
        ),
    )

    ap.add_argument("--hex-entrada", type=Path, required=True)
    ap.add_argument("--hex-saida", type=Path, required=True)
    ap.add_argument("--sobrescrever", action="store_true")
    ap.add_argument("--aplicar-no-base", action="store_true")

    args = ap.parse_args()

    if len(args.originais) < 2 or len(args.originais) % 2:
        die("--originais precisa conter uma quantidade PAR de SW.")

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
            f"--ocorrencias deve possuir {pair_count} valor(es), "
            "um para cada par SW."
        )

    rtl = "".join(
        read(args.destino / n)
        for n in ("pipeline.v", "IF_ID.v", "execute.v", "wb.v")
    )

    mappings = []
    custom_extra = set()

    for i in range(0, len(args.originais), 2):
        first = decode_sw(args.originais[i])
        second = decode_sw(args.originais[i + 1])

        custom = choose_custom(words, rtl, custom_extra)
        custom_extra.add(custom)

        mappings.append(
            {
                "pair": i // 2 + 1,
                "occurrence": (
                    args.ocorrencias[i // 2]
                    if args.ocorrencias is not None
                    else None
                ),
                "type": "SW",
                "inst1": first["hex"],
                "inst2": second["hex"],
                "custom": custom,
                "first": first,
                "second": second,
            }
        )

    work, located = replace_pairs_in_place(words, mappings)
    verify_in_place_hex(words, work, mappings)

    total_reloc = 0

    by_custom = {x["custom"]: x for x in located}

    for m in mappings:
        loc = by_custom[m["custom"]]
        m["old_pc"] = loc["old_pc"]
        m["new_pc"] = loc["new_pc"]
        m["second_pc"] = loc["second_pc"]

    args.hex_saida.parent.mkdir(parents=True, exist_ok=True)
    args.hex_saida.write_text(
        "\n".join(work) + "\n",
        encoding="utf-8",
    )

    dest_hex = args.destino / "imem_custom.hex"
    if args.hex_saida.resolve() != dest_hex.resolve():
        shutil.copy2(args.hex_saida, dest_hex)

    patch_pipeline_sw(args.destino / "pipeline.v", mappings)
    patch_ifid_sw(args.destino / "IF_ID.v", mappings)
    patch_execute_sw(args.destino / "execute.v")
    patch_wb_sw(args.destino / "wb.v")
    validate_sw(args.destino, mappings)

    print()
    print("=" * 76)
    print("SW CUSTOM MULTI - SW+SW -> 1 CUSTOM SEM NOP")
    print("=" * 76)

    for mp in mappings:
        print(
            f"Par {mp['pair']:02d} [SW]: "
            f"{mp['inst1']} + {mp['inst2']} "
            f"-> CUSTOM={mp['custom']} "
            f"PC CUSTOM=0x{mp['new_pc']:08x} "
            f"SW2 mantida em=0x{mp['second_pc']:08x}"
        )

    print(f"HEX: {len(words)} -> {len(work)} palavras (tamanho preservado)")
    print("Relocações BRANCH/JAL: 0 (PCs preservados)")
    print("NOP inserido no HEX: NÃO")
    print("SW2 permanece no HEX e é pulada com resume=PC+8")
    print("SW: DETECT+ISSUE1 -> ISSUE2 -> 2xDMEM_WRITE -> RESUME")
    print("Operandos SW: datapath/forwarding normal do processador")
    print("=" * 76)

    if args.aplicar_no_base:
        apply(args.base, args.destino)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())