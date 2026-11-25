#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instrument a Luraph v14.8 protected file for IR capture.

Finds the deserializer tail (the point where the Real VM interpreter is
about to be invoked), injects a LPH_DUMP(...) call with every visible
local, and disables the interpreter invocation. The combined sandbox then
deserializes fully, dumps the execution-data tables to stdout, and
returns -- giving a clean IR capture without running the payload.

Usage: python3 instrument.py <protected.lua> <out.lua>
"""

import re
import sys


def instrument(src: str) -> str:
    # find the deserializer tail:  X = TBL[IDX](a, TBL2[IDX2])(args...)
    m = re.search(
        r'(\w+)\s*=\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|\d+)\]'
        r'\(\s*(\w+)\s*,\s*(\w+)\[(0[Xx][0-9A-Fa-f_]+|\d+)\]\s*\)\s*\(',
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
    instrumented = src[:start] + dump_call + src[end:]

    # neutralize the outer interpreter invocation: `}):J()(...)` runs the
    # returned coroutine immediately -- keep only the deserializer call
    tail = re.search(r'\}\)\s*:\s*(\w+)\s*\(\s*\)\s*\(\s*\.\.\.\s*\)\s*;?\s*$', instrumented)
    if tail:
        # call the deserializer entry (J) so it runs + dumps, but discard the
        # returned interpreter coroutine instead of invoking it
        instrumented = instrumented[:tail.start()] + \
            f"}}):{tail.group(1)}(...);" + instrumented[tail.end():]
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
