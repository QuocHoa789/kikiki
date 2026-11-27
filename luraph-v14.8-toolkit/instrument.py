#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instrument a Luraph v14.8 protected file for IR capture.

Finds the deserializer tail (the point where the Real VM interpreter is
about to be invoked), injects a LPH_DUMP(...) call with every visible
local, and disables the interpreter invocation. The combined sandbox then
deserializes fully, dumps the execution-data tables to stdout, and
returns -- giving a clean IR capture without running the payload.

Usage: python3 instrument.py <protected.lua> <out.lua> [--mode instr]
Modes:
  ir    (default) capture execution data after deserialization
  instr capture the materialized instruction array from the dispatch loop
"""

import re
import sys

MODE = "ir"
if "--mode" in sys.argv:
    i = sys.argv.index("--mode")
    if i + 1 < len(sys.argv):
        MODE = sys.argv[i + 1]
        sys.argv.pop(i)
        sys.argv.pop(i)


def instrument(src: str) -> str:
    # find the deserializer tail:  X = TBL[IDX](a, TBL2[IDX2])(args...)
    m = re.search(
        r'(\w+)\s*=\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\d+)\]'
        r'\(\s*(\w+)\s*,\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\d+)\]\s*\)\s*\(',
        src,
    )
    if not m:
        raise ValueError("deserializer tail not found")

    dest, tbl, idx, a1, tbl2, idx2 = m.group(1), m.group(2), m.group(3), \
        m.group(4), m.group(5), m.group(6)
    start = m.end() - 1  # position of the open paren of the interpreter call

    # bracket-match the interpreter call's argument list
    depth = 0
    i = start
    while i < len(src):
        c = src[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                break
        elif c == '"':
            i += 1
            while i < len(src) and src[i] != '"':
                if src[i] == "\\":
                    i += 1
                i += 1
        i += 1
    end = i + 1

    # collect candidate local names from the enclosing region (4KB before
    # the invoke) -- undeclared ones are simply nil and get skipped by
    # LPH_DUMP
    window = src[max(0, m.start() - 4000):m.start()]
    idents = re.findall(r"[A-Za-z_]\w*", window)
    keywords = {"and", "break", "do", "else", "elseif", "end", "false",
                "for", "function", "if", "in", "local", "nil", "not", "or",
                "repeat", "return", "then", "true", "until", "while",
                "continue", "function"}
    names = []
    seen = set()
    for x in idents:
        if x in keywords or x in seen:
            continue
        seen.add(x)
        names.append(x)
        if len(names) >= 24:
            break

    dump_call = f";LPH_DUMP({','.join(names)})"
    if MODE == "instr":
        # dispatch-loop capture mode: leave the interpreter invocation
        # INTACT so the Real VM runs; LPH_INSTR fires at the first opcode
        # fetch, dumps the materialized instruction array, then aborts
        instrumented = src
        # extract the SoA column names from the dispatch loop: every
        # `COL[F]` access (F = the PC variable) is an instruction column
        dm = re.search(r"repeat\s+local\s+(\w+)\s*=\s*\(\s*(\w+)\[(\w+)\]\s*\)\s*;",
                       instrumented)
        if dm:
            pc_var = dm.group(3)
            loop_start = dm.start()
            # find the loop end (depth-tracked) to scan for column accesses
            j = loop_start + 7
            depth = 1
            n = len(instrumented)
            loop_end = n
            while j < n:
                c = instrumented[j]
                if c.isalpha() or c == "_":
                    km = re.match(r"[A-Za-z_]\w*", instrumented[j:])
                    kw = km.group(0)
                    if kw in ("repeat", "function"):
                        depth += 1
                    elif kw == "until":
                        depth -= 1
                        if depth == 0:
                            loop_end = j
                            break
                    elif kw in ("if", "while", "for"):
                        depth += 1
                    elif kw == "end":
                        depth -= 1
                    j += len(kw)
                    continue
                j += 1
            loop_text = instrumented[loop_start:loop_end]
            cols = sorted(set(re.findall(r"(\w+)\[" + re.escape(pc_var) + r"\]",
                                         loop_text)))
            cols = [c for c in cols if c != pc_var]
            op_arr = dm.group(2)
            cols_tbl = "{" + f"{op_arr}={op_arr}" + \
                "".join(f",{c}={c}" for c in cols) + "}"
            hook = (f"repeat LPH_INSTR({cols_tbl},{pc_var});"
                    f"local {dm.group(1)}=({op_arr}[{pc_var}]);")
            instrumented = instrumented[:loop_start] + hook + \
                instrumented[loop_start + len(dm.group(0)):]
            print(f"dispatch loop hooked: op={dm.group(1)} arr={op_arr} "
                  f"pc={pc_var} columns={cols}", file=sys.stderr)
        else:
            print("dispatch loop NOT found", file=sys.stderr)
        return instrumented

    # NOTE: the outer tail `}):J()(...)` stays UNTOUCHED. Removing the
    # interpreter's argument list above already prevents the Real VM from
    # running: `u[0X3d](h, u[0X10])` only creates the coroutine/wrapper --
    # the resume call with the payload args was deleted. Replacing the tail
    # breaks Luau parsing ("got 'J'"), so it must never be done.

    # inject a dump probe after every statement inside the chain region:
    # the chain spans from the enclosing entry-function definition to the
    # (now neutralized) interpreter invocation. This lets us watch when the
    # lazy constant decryption happens step by step. All positions are
    # recomputed on the already-replaced text.
    inv = re.search(
        r'(\w+)\s*=\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\d+)\]'
        r'\(\s*(\w+)\s*,\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\d+)\]\s*\)\s*;',
        instrumented,
    )
    if inv:
        # find the enclosing entry function by counting block keywords
        # backwards from the invocation: end/until open, function/if/for/
        # while/do/repeat close; the first keyword that drives the depth
        # negative is the entry function's `function` keyword
        depth = 0
        entry_pos = None
        words = list(re.finditer(
            r'\b(end|until|function|if|for|while|do|repeat)\b',
            instrumented[:inv.start()],
        ))
        for wm in reversed(words):
            w = wm.group(0)
            if w in ("end", "until"):
                depth += 1
            else:
                depth -= 1
            if depth < 0:
                entry_pos = wm.start()
                break
        if entry_pos is not None:
            region = instrumented[entry_pos:inv.start()]
            if '"' not in region and "'" not in region:
                # inject only in the chain part (before the interpreter
                # dispatch loop), and only at top-level statements
                # (paren/brace/bracket depth zero) — probes placed inside
                # call arguments produce invalid syntax
                marker = region.find("while true do")
                head, tail_part = (region, "") if marker < 0 else \
                    (region[:marker], region[marker:])
                probe = f";LPH_DUMP({','.join(names)})"
                out = []
                depth = 0
                i = 0
                n = len(head)
                last_stmt_start = 0
                while i < n:
                    c = head[i]
                    if c == "[":  # long-bracket string
                        j = i + 1; eq = 0
                        while j < n and head[j] == "=":
                            eq += 1; j += 1
                        if j < n and head[j] == "[":
                            closer = "]" + "=" * eq + "]"
                            k = head.find(closer, j + 1)
                            if k >= 0:
                                out.append(head[i:k + len(closer)])
                                i = k + len(closer)
                                continue
                    if c in "([{":
                        depth += 1
                    elif c in ")]}":
                        depth -= 1
                    elif c == ";" and depth == 0:
                        out.append(c)
                        # in Luau, break/continue/return must be the LAST
                        # statement of a block -- no probe after them
                        stmt = head[last_stmt_start:i].rstrip().lstrip()
                        if not (stmt.endswith("break")
                                or stmt.endswith("continue")
                                or stmt == ""
                                or stmt.endswith(("then", "do", "else", "repeat"))
                                or re.search(r'\breturn\b', stmt)):
                            out.append(probe)
                        i += 1
                        last_stmt_start = i
                        continue
                    out.append(c)
                    i += 1
                region = "".join(out) + tail_part
                instrumented = instrumented[:entry_pos] + region + \
                    instrumented[inv.start():]
    # normalize double-semicolons outside strings (Luau rejects empty
    # statements; some originals contain them under Lua 5.1 semantics)
    cleaned = []
    i = 0
    n = len(instrumented)
    while i < n:
        c = instrumented[i]
        # long-bracket strings [=*[ ... ]=*]: skip entirely (blob data
        # legitimately contains `;;`)
        if c == "[":
            j = i + 1
            eq = 0
            while j < n and instrumented[j] == "=":
                eq += 1
                j += 1
            if j < n and instrumented[j] == "[":
                closer = "]" + "=" * eq + "]"
                k = instrumented.find(closer, j + 1)
                if k >= 0:
                    cleaned.append(instrumented[i:k + len(closer)])
                    i = k + len(closer)
                    continue
        if c == '"':
            j = i + 1
            while j < n and instrumented[j] != '"':
                if instrumented[j] == "\\":
                    j += 1
                j += 1
            cleaned.append(instrumented[i:j + 1])
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n and instrumented[j] != "'":
                if instrumented[j] == "\\":
                    j += 1
                j += 1
            cleaned.append(instrumented[i:j + 1])
            i = j + 1
            continue
        if c == ";" and i + 1 < n and instrumented[i + 1] == ";":
            i += 1
            continue
        cleaned.append(c)
        i += 1
    instrumented = "".join(cleaned)
    return instrumented


if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    try:
        out = instrument(src)
    except ValueError as e:
        print(f"instrumentation failed: {e}", file=sys.stderr)
        # fall back to uninstrumented
        out = src
    open(sys.argv[2], "w", encoding="utf-8").write(out)
    print("instrumented ->", sys.argv[2])
