#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opcode lifting: combine a captured instruction sequence with the parsed
dispatch tree to emit a semantic instruction listing.

Two inputs:
  1. the protected file (to extract + parse the dispatch tree), and
  2. optionally, a sandbox capture (.instr.txt) containing the materialized
     opcode sequence (LPH_INSTR section)

Outputs:
  - opcode -> handler body map with recognized semantics (JMP / GETGLOBAL /
    CALL / VARARG / arithmetic...)
  - when a capture is available: an instruction listing PC -> semantics

Usage: python3 lift.py <protected.lua> [capture.txt] [-o out.txt]
"""

import re
import sys

# handler body -> recognized semantics (patterns from real Luraph v14.8
# dispatch trees; array names are randomized per build so patterns are
# structural)
SEMANTIC_PATTERNS = [
    (r"\b(\w+)\s*=\s*\(\s*(\w+)\[\s*(\w+)\s*\]\s*\)\s*;\s*$", "JMP (PC = target)"),
    (r"\[\s*(\w+)\[\s*(\w+)\s*\]\s*\]\s*=\s*\(\s*(\w+)\[\s*0[xXbB]", "SETFIELD/ENV"),
    (r"\bfor\s+(\w+)\s*=\s*1\s*,\s*(\w+)\[\s*(\w+)\s*\]\s+do", "VARARG SETUP"),
    (r"\(\s*(\w+)\s*\)\s*\[\s*(\w+)\[\s*(\w+)\s*\]\s*\]\s*=\s*\(", "CALL/SETREG"),
]


def extract_dispatch_loop(src):
    """Extract the dispatch loop (repeat local op=(ARR[pc]); ... until ...)."""
    m = re.search(r"repeat\s+local\s+(\w+)\s*=\s*\(\s*(\w+)\[(\w+)\]\s*\)\s*;", src)
    if not m:
        return None
    start = m.start()
    # walk to the closing until (depth-tracked)
    depth = 1
    j = start + 7
    n = len(src)
    while j < n:
        c = src[j]
        if c.isalpha() or c == "_":
            km = re.match(r"[A-Za-z_]\w*", src[j:])
            kw = km.group(0)
            if kw in ("repeat", "function"):
                depth += 1
            elif kw == "until":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            elif kw in ("if", "while", "for"):
                depth += 1
            elif kw == "end":
                depth -= 1
            j += len(kw)
            continue
        j += 1
    else:
        return None
    m2 = re.match(r"until\s+([^;]+);", src[end:])
    end_full = end + (m2.end() if m2 else 12)
    return src[start:end_full]


def classify_body(text):
    """Recognize semantics from a handler body (structural patterns;
    array names are randomized per build so patterns are positional)."""
    c = re.sub(r"\s+", " ", text).strip()
    if not c:
        return None
    # JMP: PC reassigned from an SoA column fetch
    if re.fullmatch(r"\w+\s*=\s*\(\s*\w+\[\s*\w+\s*\]\s*\)", c):
        return "JMP (PC = target)"
    # LOADNIL
    if re.fullmatch(r"\w+\[\s*\w+\[\s*\w+\s*\]\s*\]\s*=\s*nil", c):
        return "LOADNIL"
    # arithmetic with a constant column
    if re.search(r"\[\s*(\w+)\s*\]\s*=\s*\w+\[\s*(\w+)\s*\]\s*\+\s*\w+\[", c):
        return "ADD (R = R + K)"
    if re.search(r"=\s*\w+\[\s*\w+\s*\]\s*-\s*\w+\[\s*\w+\s*\]", c):
        return "SUB (R = R - K)"
    if re.search(r"=\s*\w+\[\s*\w+\s*\]\s*\*\s*\w+\[\s*\w+\s*\]", c):
        return "MUL (R = R * K)"
    if re.search(r"=\s*\w+\[\s*\w+\s*\]\s*/\s*\w+\[\s*\w+\s*\]", c):
        return "DIV (R = R / K)"
    # GETTABLE / SETTABLE
    if re.search(r"\w+\s*=\s*\w+\[\s*\w+\s*\]\s*\[\s*\w+\[\s*\w+\s*\]\s*\]", c):
        return "GETTABLE (indexed load)"
    if re.search(r"\]\s*\[\s*\w+\[\s*\w+\s*\]\s*\]\s*=", c):
        return "SETTABLE (indexed store)"
    if re.search(r"\)\s*\[\s*\w+\[\s*\w+\s*\]\s*\]\s*=\s*\w+\[\s*\w+\s*\]", c):
        return "SETTABLE/SETFIELD"
    if re.search(r"\[\s*\w+\[\s*\w+\s*\]\s*\]\s*=\s*\w+\[\s*\w+\s*\]", c):
        return "SETGLOBAL/SETUPVAL"
    # MOVE
    if re.search(r"\[\s*\w+\s*\]\s*=\s*\w+\[\s*\w+\s*\]\s*;", c) and \
            len(re.findall(r"\w+\[", c)) <= 3:
        return "MOVE (register copy)"
    # CALL: library helper invoked with register/constant args
    if re.search(r"=\s*\(\s*\w+\[\s*0?[xXbB]?[0-9a-fA-F_]+\s*\]\s*\(\s*\w+\[\s*\w+\s*\]\s*,", c):
        return "CALL (helper + args)"
    if re.search(r"\w+\[\s*0[xXbB][^\]]*\]\s*\(\s*\w+\s*,\s*\w+", c):
        return "CALL/HELPER"
    # FORLOOP / FORPREP
    if re.search(r"\+\s*\w+\s*-\s*0[xX]?\w*\s*;\s*end", c):
        return "FORLOOP/FORPREP"
    # VARARG
    if re.search(r"\bfor\s+\w+\s*=\s*1\s*,\s*\w+\[\s*\w+\s*\]\s+do\b", c):
        return "VARARG SETUP"
    # SELF (method call prep)
    if re.search(r"\w+\s*=\s*\w+\[\s*\w+\s*\]\s*;\s*\w+\[\s*\w+\s*\+\s*1\s*\]\s*=\s*\w+", c):
        return "SELF (method call prep)"
    # CONCAT
    if "\.\.\." in c:
        return "CONCAT"
    # LEN
    if re.search(r"#\s*\w+\[", c):
        return "LEN"
    # NOT
    if re.search(r"=\s*not\s+\w+\[", c):
        return "NOT"
    # compare + branch
    if re.search(r"\w+\[\s*\w+\s*\]\s*==\s*\w+\[\s*\w+\s*\]", c) or \
            re.search(r"\w+\[\s*\w+\s*\]\s*<\s*\w+\[\s*\w+\s*\]", c):
        return "COMPARE+BRANCH"
    return None


def parse_dispatch(tree_text):
    """Very small structural scan: collect leaf handlers with their
    g-register constraint paths (simplified: uses parse_dispatch)."""
    from parse_dispatch import tokenize, Parser, walk
    p = Parser(list(tokenize(tree_text)))
    tree = p.parse_if_chain()
    out = []
    walk(tree, [], out)
    return out


def build_handler_map(leaves):
    """Map opcode value -> (constraints, body, semantics)."""
    handlers = []
    for path, text in leaves:
        lo, hi = 0, 2 ** 32
        for op, v in path:
            if op == ">=":
                lo = max(lo, v)
            elif op == "<":
                hi = min(hi, v)
            elif op == "==":
                lo = max(lo, v)
                hi = min(hi, v)
            elif op == "~=":
                continue  # refinement, ignore for range purposes
        sem = classify_body(text)
        handlers.append({"lo": lo, "hi": hi, "constraints": path,
                         "body": text, "semantics": sem})
    return handlers


def parse_capture(capture_text):
    """Extract the opcode sequence from an LPH_INSTR capture."""
    m = re.search(r"=== LPH_INSTR_BEGIN n=(\d+) pc=(\d+) ===\n(.*?)\n=== LPH_INSTR_END ===",
                  capture_text, re.S)
    if not m:
        return None
    n, pc = int(m.group(1)), int(m.group(2))
    seq = [int(x) for x in m.group(3).split() if x.strip().lstrip("-").isdigit()]
    return {"n": n, "pc": pc, "seq": seq}


def render(handlers, capture=None):
    out = []
    out.append("=" * 62)
    out.append("OPCODE LIFTING REPORT")
    out.append("=" * 62)
    out.append(f"handlers parsed: {len(handlers)}")
    recognized = [h for h in handlers if h["semantics"]]
    out.append(f"semantics recognized: {len(recognized)}/{len(handlers)}")
    out.append("")
    out.append("--- handler map (opcode range -> semantics) ---")
    for h in sorted(handlers, key=lambda x: (x["lo"], x["hi"])):
        rng = f"[{h['lo']}..{h['hi']}]" if h["lo"] != h["hi"] else f"[{h['lo']}]"
        sem = h["semantics"] or "?"
        out.append(f"  {rng:<14} {sem}")
        out.append(f"      body: {h['body'][:130]}")
    if capture:
        out.append("")
        out.append(f"--- instruction listing (from capture: "
                   f"n={capture['n']}, start pc={capture['pc']}) ---")
        seq = capture["seq"]
        pc0 = capture["pc"]
        for i, op in enumerate(seq):
            sem = "?"
            for h in handlers:
                if h["lo"] <= op <= h["hi"]:
                    sem = h["semantics"] or "handler[body not recognized]"
                    break
            out.append(f"  pc={pc0 + i:<4} op={op:<5} {sem}")
    return "\n".join(out)


def main():
    src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    loop = extract_dispatch_loop(src)
    if not loop:
        print("dispatch loop not found in this build", file=sys.stderr)
        sys.exit(1)
    from parse_dispatch import tokenize, Parser, walk
    p = Parser(list(tokenize(loop)))
    tree = p.parse_if_chain()
    leaves = []
    walk(tree, [], leaves)
    handlers = build_handler_map(leaves)

    capture = None
    if len(sys.argv) > 2 and not sys.argv[2] == "-o":
        capture = parse_capture(open(sys.argv[2], encoding="utf-8",
                                     errors="replace").read())

    text = render(handlers, capture)
    if "-o" in sys.argv:
        out_path = sys.argv[sys.argv.index("-o") + 1]
        open(out_path, "w", encoding="utf-8").write(text + "\n")
        print(f"lift report -> {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
