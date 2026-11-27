#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruct the real program logic from a full instruction capture.

Input: a .instr.txt capture (per-fetch rows + full SoA column dumps) and
the dispatch tree (from the protected file) for opcode semantics.

Output: the real instruction stream — per-PC operations with operands,
annotated with lifted semantics, plus PC execution order.

Usage: python3 reconstruct.py <capture.instr.txt> <protected.lua> [-o out.txt]
"""

import re
import sys


def parse_capture(text):
    """Parse the capture: fetch rows + full column dumps."""
    rows = []
    m = re.search(r"=== LPH_INSTR_BEGIN fetches=(\d+) last_pc=(-?\d+) ===\n(.*?)(?:\n=== COL|\Z)",
                  text, re.S)
    if m:
        fetches = int(m.group(1))
        last_pc = int(m.group(2))
        for line in m.group(3).splitlines():
            d = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
            rows.append(d)
    cols = {}
    for m in re.finditer(r"=== COL (\w+) n=(\d+) ===\n(.*?)(?=\n===|\Z)", text, re.S):
        name, n, body = m.group(1), int(m.group(2)), m.group(3)
        vals = body.split()
        cols[name] = {"n": n, "vals": vals}
    return rows, cols


def to_num(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return s


def parse_dispatch_map(src):
    """Extract the dispatch tree from the dispatch loop."""
    from parse_dispatch import tokenize, Parser
    from lift import extract_dispatch_loop
    loop = extract_dispatch_loop(src)
    if not loop:
        return None
    p = Parser(list(tokenize(loop)))
    return p.parse_if_chain()


def find_sem(op, tree, _cache={}):
    """Resolve the handler body for a concrete opcode by walking the tree
    with the value; classify recognized semantics."""
    from parse_dispatch import resolve_leaves
    from lift import classify_body
    if op in _cache:
        return _cache[op]
    body = None
    if tree is not None:
        matches = resolve_leaves(tree, op)
        if matches:
            body = matches[0][1]
    sem = classify_body(body) if body else None
    _cache[op] = (sem, body)
    return _cache[op]


def render_logic(rows, cols, tree):
    out = []
    out.append("=" * 62)
    out.append("RECONSTRUCTED PROGRAM LOGIC (VM instruction stream)")
    out.append("=" * 62)
    Y = cols.get("Y", {"vals": []})
    total = len(Y["vals"])
    out.append(f"total instructions: {total}")
    out.append(f"executed fetches captured: {len(rows)}")
    out.append("")

    # semantic histogram over the full opcode array
    from collections import Counter
    hist = Counter()
    for v in Y["vals"]:
        op = to_num(v)
        if isinstance(op, int):
            sem, _ = find_sem(op, tree)
            hist[sem or f"op{op}"] += 1
    out.append("--- semantic histogram over the full stream ---")
    for sem, cnt in hist.most_common(20):
        out.append(f"  {cnt:>6}  {sem}")
    out.append("")

    out.append("--- executed instruction trace (in fetch order) ---")
    for r in rows[:150]:
        pc = to_num(r.get("pc", "?"))
        op = to_num(r.get("Y", "?"))
        sem, body = (None, None)
        if isinstance(op, int):
            sem, body = find_sem(op, tree)
        operands = []
        for name in ("S", "z", "w", "C", "U", "n"):
            v = r.get(name)
            if v is not None and v != "nil":
                operands.append(f"{name}={v}")
        out.append(f"  pc={pc:<6} op={op:<5} {(sem or '?'):<24} "
                   f"{' '.join(operands)}")
    if len(rows) > 150:
        out.append(f"  ... +{len(rows) - 150} more executed fetches")
    out.append("")

    out.append("--- full stream head (static, first 60 instructions) ---")
    s = cols.get("S", {}).get("vals", [])
    z = cols.get("z", {}).get("vals", [])
    w = cols.get("w", {}).get("vals", [])
    c = cols.get("C", {}).get("vals", [])
    for i, v in enumerate(Y["vals"][:60], start=1):
        op = to_num(v)
        sem, body = (None, None)
        if isinstance(op, int):
            sem, body = find_sem(op, tree)
        sv = s[i - 1] if i - 1 < len(s) else "?"
        zv = z[i - 1] if i - 1 < len(z) else "?"
        wv = w[i - 1] if i - 1 < len(w) else "?"
        cv = c[i - 1] if i - 1 < len(c) else "?"
        out.append(f"  pc={i:<5} op={op:<5} {(sem or '?'):<24} "
                   f"dest={sv} src1={zv} aux={wv} imm={cv}")
    return "\n".join(out)


def main():
    cap_text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    src = open(sys.argv[2], encoding="utf-8", errors="replace").read()
    rows, cols = parse_capture(cap_text)
    tree = parse_dispatch_map(src)
    text = render_logic(rows, cols, tree)
    if "-o" in sys.argv:
        out_path = sys.argv[sys.argv.index("-o") + 1]
        open(out_path, "w", encoding="utf-8").write(text + "\n")
        print(f"logic reconstruction -> {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
