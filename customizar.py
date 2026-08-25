#!/usr/bin/env python3
"""
Adiciona MAIS UMA CUSTOM LW+LW em uma base que já usa LWSLOT.

Compatível com customizar_lw_multi_timing_preservado.py.

Não cria nova FSM.
Não altera execute.v / wb.v.
Não mexe no fetch.
Não usa resume_pc.

HEX:
    LW1 -> nova CUSTOM
    LW2 -> NOP

Decode existente:
    CUSTOM -> emite LW1
    ciclo seguinte -> emite LW2
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


def read(path):
    if not path.exists():
        die(f"arquivo não encontrado: {path}")
    return path.read_text(encoding="utf-8")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def sext(v, bits):
    sign = 1 << (bits - 1)
    return (v ^ sign) - sign


def decode_lw(h):
    h = h.lower().replace("0x", "")

    if not re.fullmatch(r"[0-9a-f]{8}", h):
        die(f"HEX inválido: {h}")

    w = int(h, 16)

    if (w & 0x7f) != 0x03 or ((w >> 12) & 7) != 0b010:
        die(f"{h} não é LW RV32I.")

    return {
        "hex": h,
        "rd": (w >> 7) & 31,
        "rs1": (w >> 15) & 31,
        "imm": sext((w >> 20) & 0xfff, 12),
    }


def parse_hex(path):
    words = []

    for raw in read(path).splitlines():
        line = raw.split("//", 1)[0].strip()

        if not line:
            continue

        token = line.split()[0].lower().replace("0x", "")

        if re.fullmatch(r"[0-9a-f]{8}", token):
            words.append(token)

    if not words:
        die(f"HEX vazio: {path}")

    return words


def choose_custom(words, ifid_text):
    used = set(words)

    used.update(
        x.lower()
        for x in re.findall(
            r"32'h([0-9a-fA-F]{8})",
            ifid_text,
        )
    )

    # opcode 0x53, funct3=110, mesmo namespace da versão LWSLOT.
    for funct7 in range(1, 128):
        w = (funct7 << 25) | (0b110 << 12) | 0x53
        h = f"{w:08x}"

        if h not in used:
            return h

    die("não foi possível encontrar uma CUSTOM livre.")


def replace_pair(words, lw1, lw2, custom):
    """
    Preserva o layout:
      LW1 -> CUSTOM
      LW2 -> NOP
    """
    for i in range(len(words) - 1):
        if words[i] == lw1 and words[i + 1] == lw2:
            out = list(words)
            out[i] = custom
            out[i + 1] = "00000013"
            return i, out

    die(
        f"par consecutivo não encontrado no HEX atual: "
        f"{lw1} {lw2}"
    )


def extend_ifid(path, custom, first, second):
    s = read(path)

    if "LWSLOT_MULTI_BEGIN" not in s:
        die(
            "IF_ID.v não contém LWSLOT_MULTI_BEGIN. "
            "A base não parece ter sido gerada por "
            "customizar_lw_multi_timing_preservado.py."
        )

    if f"32'h{custom}" in s:
        die(f"CUSTOM {custom} já existe.")

    # ---------------------------------------------------------
    # 1) Estender lwslot_match
    # ---------------------------------------------------------
    needle = "assign pipe.lwslot_match =\n"
    pos = s.find(needle)

    if pos < 0:
        die("IF_ID.v: tabela lwslot_match não localizada.")

    pos += len(needle)

    s = (
        s[:pos]
        + f"    (inst_mem_read_data == 32'h{custom}) ||\n"
        + s[pos:]
    )

    # ---------------------------------------------------------
    # 2) Estender seletor LW1
    # ---------------------------------------------------------
    needle = "assign pipe.lwslot_lw1_selected =\n"
    pos = s.find(needle)

    if pos < 0:
        die("IF_ID.v: seletor lwslot_lw1_selected não localizado.")

    pos += len(needle)

    s = (
        s[:pos]
        + (
            f"    (inst_mem_read_data == 32'h{custom}) "
            f"? 32'h{first['hex']} :\n"
        )
        + s[pos:]
    )

    # ---------------------------------------------------------
    # 3) Acrescentar captura da LW2
    #
    # Procuramos a sequência de capturas dentro do controller:
    # if (inst_mem_read_data == CUSTOM)
    #     pipe.lwslot_lw2_word <= LW2;
    #
    # Inserimos antes da primeira atribuição de lwslot_pending <= 1.
    # ---------------------------------------------------------
    marker = "                pipe.lwslot_pending <= 1'b1;"

    pos = s.find(marker)

    if pos < 0:
        die(
            "IF_ID.v: ponto de captura da segunda LW "
            "(lwslot_pending <= 1) não localizado."
        )

    capture = (
        f"            if (inst_mem_read_data == 32'h{custom})\n"
        f"                pipe.lwslot_lw2_word <= 32'h{second['hex']};\n\n"
    )

    s = s[:pos] + capture + s[pos:]

    write(path, s)


def validate(dest, custom, first, second):
    pipeline = read(dest / "pipeline.v")
    ifid = read(dest / "IF_ID.v")

    checks = {
        "infraestrutura LWSLOT":
            "lwslot_pending" in pipeline,

        "LWSLOT multi":
            "LWSLOT_MULTI_BEGIN" in ifid,

        "nova CUSTOM":
            f"32'h{custom}" in ifid,

        "nova LW1":
            f"32'h{first['hex']}" in ifid,

        "nova LW2":
            f"32'h{second['hex']}" in ifid,

        "sem LW2R":
            "lw2r_state" not in pipeline,

        "sem LW2RM":
            "lw2rm_state" not in pipeline,

        "sem resume_pc":
            "lwslot_resume_pc" not in pipeline + ifid,

        "sem fetch hold":
            "lwslot_hold_fetch" not in pipeline + ifid,
    }

    bad = [name for name, ok in checks.items() if not ok]

    if bad:
        die(
            "validação da nova CUSTOM LWSLOT falhou: "
            + ", ".join(bad)
        )

    print("Validação da nova CUSTOM LWSLOT: OK")

    for name in checks:
        print(f"  {name}: OK")


def apply_to_base(base, dest):
    for name in ("IF_ID.v", "imem_custom.hex"):
        src = dest / name

        if not src.exists():
            continue

        dst = base / name

        if dst.exists():
            backup = base / f"{name}.before_add_lwslot"

            if not backup.exists():
                shutil.copy2(dst, backup)

        shutil.copy2(src, dst)

        print(f"aplicado: {src} -> {dst}")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Adiciona mais uma CUSTOM LW+LW "
            "a uma implementação LWSLOT existente."
        )
    )

    ap.add_argument("base", type=Path)
    ap.add_argument("destino", type=Path)

    ap.add_argument(
        "--originais",
        nargs=2,
        required=True,
        metavar=("LW1", "LW2"),
    )

    ap.add_argument(
        "--hex-entrada",
        type=Path,
        required=True,
    )

    ap.add_argument(
        "--hex-saida",
        type=Path,
        required=True,
    )

    ap.add_argument(
        "--sobrescrever",
        action="store_true",
    )

    ap.add_argument(
        "--aplicar-no-base",
        action="store_true",
    )

    args = ap.parse_args()

    first = decode_lw(args.originais[0])
    second = decode_lw(args.originais[1])

    if not args.base.is_dir():
        die(f"base inexistente: {args.base}")

    pipeline = read(args.base / "pipeline.v")
    ifid = read(args.base / "IF_ID.v")

    if "lwslot_pending" not in pipeline:
        die(
            "pipeline.v não contém lwslot_pending. "
            "Esta base ainda não possui a infraestrutura LWSLOT."
        )

    if "LWSLOT_MULTI_BEGIN" not in ifid:
        die(
            "IF_ID.v não contém LWSLOT_MULTI_BEGIN. "
            "Não é seguro adicionar outra CUSTOM automaticamente."
        )

    if args.destino.exists():
        if not args.sobrescrever:
            die("destino já existe; use --sobrescrever.")

        shutil.rmtree(args.destino)

    shutil.copytree(
        args.base,
        args.destino,
    )

    words = parse_hex(args.hex_entrada)

    custom = choose_custom(
        words,
        read(args.destino / "IF_ID.v"),
    )

    index, new_words = replace_pair(
        words,
        first["hex"],
        second["hex"],
        custom,
    )

    args.hex_saida.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.hex_saida.write_text(
        "\n".join(new_words) + "\n",
        encoding="utf-8",
    )

    dest_hex = args.destino / "imem_custom.hex"

    if args.hex_saida.resolve() != dest_hex.resolve():
        shutil.copy2(
            args.hex_saida,
            dest_hex,
        )

    extend_ifid(
        args.destino / "IF_ID.v",
        custom,
        first,
        second,
    )

    validate(
        args.destino,
        custom,
        first,
        second,
    )

    print()
    print("=" * 68)
    print("NOVA CUSTOM LW ADICIONADA AO LWSLOT")
    print("=" * 68)

    print(
        f"LW1    : {first['hex']}  "
        f"lw x{first['rd']},{first['imm']}(x{first['rs1']})"
    )

    print(
        f"LW2    : {second['hex']}  "
        f"lw x{second['rd']},{second['imm']}(x{second['rs1']})"
    )

    print(f"CUSTOM : {custom}")
    print(f"PC     : 0x{index * 4:08x}")
    print("LW2 HEX: substituída por NOP")
    print("FSM nova: NÃO")
    print("Fetch hold: NÃO")
    print("Resume PC: NÃO")

    print("=" * 68)

    if args.aplicar_no_base:
        apply_to_base(
            args.base,
            args.destino,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())