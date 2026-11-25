#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse an LPH_DUMP capture into a readable IR view.

The capture comes from the Luau sandbox: the protected script is
instrumented so the deserializer runs fully, dumps every visible
execution-data table (VM helper arrays, constant pool, math constants),
and returns without executing the payload.

Usage: python3 parse_ir.py <ir.txt> [-o out.txt]
"""

import sys

T, V, S, K = "T", "V", "S", "K"


def parse(lines):
    tables = []
    cur = None
    for line in lines:
        parts = line.split(" ", 4)
        if not parts:
            continue
        if parts[0] == T and len(parts) >= 5:
            cur = {"name": parts[1], "kind": parts[2], "depth": int(parts[3]),
                   "len": int(parts[4]), "fields": [], "arrays": []}
            tables.append(cur)
        elif parts[0] == V and cur is not None and len(parts) >= 3:
            cur["arrays"].append(("values", parts[2] if len(parts) > 2 else ""))
        elif parts[0] == S and cur is not None and len(parts) >= 4:
            try:
                idx = int(parts[2])
            except ValueError:
                idx = -1
            cur["arrays"].append(("str", idx, parts[3]))
        elif parts[0] == K and cur is not None and len(parts) >= 3:
            cur["fields"].append(parts[2] if len(parts) > 2 else "")
    return tables


def render(tables):
    out = []
    out.append("=" * 62)
    out.append("CAPTURED EXECUTION DATA (IR level)")
    out.append("=" * 62)
    for t in tables:
        out.append("")
        out.append(f"[{t['name']}] kind={t['kind']} len={t['len']}")
        for a in t["arrays"]:
            if a[0] == "values":
                out.append(f"  values: {a[1][:600]}")
            elif a[0] == "str":
                out.append(f"  [{a[1]}] {a[2]!r}")
        for f in t["fields"]:
            out.append(f"  {f}")
    return "\n".join(out)


if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    # take only the dump section
    beg = src.find("=== LPH_DUMP_BEGIN ===")
    end = src.find("=== LPH_DUMP_END ===")
    if beg < 0 or end < 0:
        print("no dump section found", file=sys.stderr)
        sys.exit(1)
    dump_lines = src[beg:end].splitlines()[1:]
    tables = parse(dump_lines)
    text = render(tables)
    if len(sys.argv) > 3 and sys.argv[2] == "-o":
        open(sys.argv[3], "w", encoding="utf-8").write(text + "\n")
        print("ir view ->", sys.argv[3])
    else:
        print(text)
