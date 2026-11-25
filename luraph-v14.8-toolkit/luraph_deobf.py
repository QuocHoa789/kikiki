#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Luraph v14.8 Deobfuscation Toolkit
==================================
Reverse-engineered from real Luraph v14.8 samples (16 files collected from
public sample repositories). Works fully offline, pure Python 3, no deps.

Pipeline reverse-engineered from the VM source itself:

  1. The protected file is one giant Lua expression:
         return({ <VM functions + encoded blobs> }):ENTRY(...)()
     or a loader wrapper that decompresses + loadstring()s the payload.

  2. The original chunk (constants + bytecode + prototypes) is serialized
     into a blob that starts with the plaintext signature `LPH?` (4 bytes,
     4th char varies per build), stored in a Lua long-bracket string at
     whatever level `[`...`]` / `[=[...]=]` / ... avoids conflicts.

  3. Decoding (ported from the VM's own decoder):
         a. string.sub(blob, 5)        -- strip `LPH?`
         b. gsub(blob, "z", "!!!!!")   -- `z` compresses a 32-bit zero word
         c. every 5 chars -> one u32, base-85, little-endian digit order:
              z = (c5-33) + (c4-33)*85 + (c3-33)*85^2 + (c2-33)*85^3
                  + (c1-33)*85^4
            packed string.pack("<I4", z)

  4. The constants section is a stream of `<type> <varint len> <data>`
     entries. The type byte for strings is randomized per file (0x29,
     0x58, ...), so it is auto-detected by scoring valid string parses.

  5. Control flow inside the VM is flattened (state machines with magic
     constants) and identifiers are randomized per file; nothing is stable
     across files except stdlib references and the blob format.

Usage:
    python3 luraph_deobf.py detect  <file.lua> [...]
    python3 luraph_deobf.py blobs   <file.lua>
    python3 luraph_deobf.py strings <file.lua> [-o out.txt] [--all]
    python3 luraph_deobf.py beautify <file.lua> [-o out.lua]
    python3 luraph_deobf.py all     <file.lua>
"""

import argparse
import os
import re
import struct
import sys
from collections import Counter

# ---------------------------------------------------------------- detection

HEADER_RE = re.compile(
    r"--\s*This file was protected using Luraph Obfuscator\s+v?([\d.]+)",
    re.I,
)

# long-bracket strings of any level, non-greedy, DOTALL
def _long_bracket_pattern(level):
    eq = "=" * level
    return re.compile(r"\[" + eq + r"\[(.*?)\]" + eq + r"\]", re.S)


def detect(path):
    """Return (version_string, style, is_loader)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    m = HEADER_RE.search(data)
    version = m.group(1) if m else "?"
    is_loader = "decompression error" in data or "loadstring" in data.split("return(")[0] \
        if "return(" in data else False
    style = "loader" if is_loader else "vm"
    return version, style, is_loader


# ---------------------------------------------------------------- blob layer

def extract_blobs(data):
    """Extract all long-bracket strings at any level.

    Returns list of (level, start_offset, content). Level-0 `[[...]]` is
    only matched when not part of a higher-level opener.
    """
    found = []
    taken = []  # (start, end) spans already claimed by higher levels

    for level in range(5, -1, -1):
        pat = _long_bracket_pattern(level)
        for m in pat.finditer(data):
            s, e = m.span()
            if any(s >= t0 and e <= t1 for t0, t1 in taken):
                continue  # inside an already-claimed higher-level string
            taken.append((s, e))
            found.append((level, s, m.group(1)))
    found.sort(key=lambda x: x[1])
    return found


def extract_lph_blobs(data):
    """Only the serialized-chunk blobs (content starts with `LPH`)."""
    return [(lvl, off, c) for (lvl, off, c) in extract_blobs(data)
            if c.startswith("LPH")]


# base-85 decoding table
_B85_POW = [85 ** i for i in range(5)]


def decode_blob(content):
    """LPH blob content -> raw decoded bytes.

    a. strip 4-byte `LPH?` signature
    b. expand compressed zero words: 'z' -> '!!!!!'
    c. 5 chars -> u32 (base-85, LE digits), packed little-endian
    """
    if not content.startswith("LPH"):
        raise ValueError("not an LPH blob")
    body = content[4:].replace("z", "!!!!!")
    out = bytearray()
    n = len(body)
    for i in range(0, n - 4, 5):
        c1, c2, c3, c4, c5 = (ord(x) for x in body[i:i + 5])
        z = ((c5 - 33)
             + (c4 - 33) * _B85_POW[1]
             + (c3 - 33) * _B85_POW[2]
             + (c2 - 33) * _B85_POW[3]
             + (c1 - 33) * _B85_POW[4])
        out += struct.pack("<I", z & 0xFFFFFFFF)
    return bytes(out)


def decode_file(path):
    """Decode every LPH blob in a file; returns (data, [(level, off, bytes)])."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    out = []
    for lvl, off, content in extract_lph_blobs(data):
        try:
            out.append((lvl, off, decode_blob(content)))
        except ValueError:
            pass
    return data, out


# ------------------------------------------------------- constants / strings

def _read_varint(dec, i):
    """LEB128-style varint at dec[i]; returns (value, next_index) or None."""
    n = len(dec)
    val = 0
    shift = 0
    while i < n:
        b = dec[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7
        if shift > 35:
            return None
    return None


def _string_ratio(s):
    if not s:
        return 0.0
    return (len(s) - len(s.translate(None, _NON_PRINT))) / len(s)


# bytes outside printable-ASCII + tab/newline/CR
_NON_PRINT = bytes(
    b for b in range(256) if not (9 <= b < 127)
)


def parse_strings_with_marker(dec, marker, min_len=2, max_len=250_000,
                              min_ratio=0.85, clean_only=False):
    """Scan `dec` for `<marker> <varint len> <bytes>` string constants.

    Uses bytes.find (C-level) to jump between marker occurrences instead
    of a Python-level scan over every byte.
    """
    n = len(dec)
    pat = bytes((marker,))
    out = []
    i = 0
    while True:
        i = dec.find(pat, i)
        if i < 0 or i >= n - 2:
            break
        r = _read_varint(dec, i + 1)
        if r:
            ln, j = r
            if min_len <= ln <= max_len and j + ln <= n:
                s = dec[j:j + ln]
                if clean_only:
                    if not _is_clean(s):
                        i += 1
                        continue
                elif _string_ratio(s) < min_ratio:
                    i += 1
                    continue
                out.append(s)
                i = j + ln
                continue
        i += 1
    return out


def _is_clean(s):
    """True if the bytes look like genuine Lua string content:
    printable ASCII plus only tab/newline/CR whitespace. (C-level via
    bytes.translate — this runs ~1M times per detection pass.)"""
    return len(s.translate(None, _CLEAN_DELETE)) == len(s)


# bytes NOT allowed inside a genuine string constant
_CLEAN_DELETE = bytes(
    b for b in range(256) if not (b in (9, 10, 13) or 32 <= b < 127)
)


def detect_string_marker(dec):
    """Auto-detect the per-file randomized string type byte.

    The base-85 decoded stream is mostly printable ASCII, so a plain
    ratio check is not enough: wrong markers can "parse" long garbage
    spans. We therefore only score parses whose strings are fully clean
    (`_is_clean`); garbage spans almost always contain instruction/marker
    bytes (e.g. 0x8a) and get rejected. The real marker wins by a wide
    margin on recovered character count.
    """
    best = (0, 0, None, [])
    # one cheap pass for byte frequencies: a genuine string-type byte is
    # sparse (strings are rare relative to instructions), so skip bytes
    # that never appear or that saturate the stream
    freq = Counter(dec)
    cap = max(len(dec) // 10, 16)
    for m in range(1, 256):
        if not 3 <= freq.get(m, 0) <= cap:
            continue
        ss = parse_strings_with_marker(dec, m, clean_only=True)
        if not ss:
            continue
        total = sum(len(s) for s in ss)
        if total > best[0]:
            best = (total, len(ss), m, ss)
    return best[2], best[1], best[3]


def extract_strings(path, include_vm_strings=False):
    """All decoded string constants of a protected file.

    Returns (all_strings, per_blob_info). VM-internal strings (stdlib
    names, error messages, the Luraph banner) can be filtered out.
    """
    _, decoded = decode_file(path)
    all_strings = []
    infos = []
    for lvl, off, dec in decoded:
        marker, count, ss = detect_string_marker(dec)
        infos.append({"level": lvl, "offset": off, "decoded": len(dec),
                      "marker": marker, "count": count})
        all_strings.extend(ss)
    if not include_vm_strings:
        all_strings = [s for s in all_strings if not _is_vm_string(s)]
    return all_strings, infos


_VM_MARKERS = (
    b"lura.ph", b"Luraph", b"debug library", b"load or loadstring",
    b"environment", b"error in error handling", b"setfenv' cannot",
    b"decompression error", b"[[%s]]", b"(%d+)",
)


def _is_vm_string(s):
    for marker in _VM_MARKERS:
        if marker in s:
            return True
    return False


# ------------------------------------------------------------- VM structure

def vm_stats(path):
    """Crude structural fingerprint of the VM wrapper."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    stats = {}
    stats["size"] = len(data)
    stats["lines"] = data.count("\n") + 1
    m = re.search(r"\}\)\s*:\s*(\w+)\s*\(\s*\.\.\.\s*\)\s*;?\s*$", data)
    stats["entry"] = m.group(1) if m else "?"
    stats["func_fields"] = len(re.findall(r"\w+=function\(", data))
    stats["bit32_refs"] = len(re.findall(r"bit32\.\w+", data))
    stats["buffer_refs"] = len(re.findall(r"buffer\.\w+", data))
    stats["coroutine_refs"] = len(re.findall(r"coroutine\.\w+", data))
    stats["number_literals"] = len(re.findall(r"0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\b\d+\b", data))
    return stats


# ---------------------------------------------------------------- beautifier

LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "goto", "if", "in", "local", "nil", "not", "or", "repeat",
    "return", "then", "true", "until", "while", "continue",
}

TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<lcomment>--\[(?P<leq>=*)\[.*?\](?P=leq)\])        # long comment
  | (?P<scomment>--[^\[\n][^\n]*)
  | (?P<lstr>\[(?P<seq>=*)\[.*?\](?P=seq)\])               # long string
  | (?P<qstr>"(?:[^"\\\n]|\\.)*")
  | (?P<astr>'(?:[^'\\\n]|\\.)*')
  | (?P<num>0[Xx][0-9A-Fa-f_]+(?:\.[0-9A-Fa-f_]*)?(?:[Pp][+-]?\d+)?    # hex
          |0[Bb][01_]+                                                  # binary
          |(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[Ee][+-]?\d+)?)          # dec
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.\.|\.\.|==|~=|<=|>=|::|->|[-+*/%^#<>=(){}\[\];:,.])
""", re.X | re.S)


def tokenize_lua(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        m = TOKEN_RE.match(src, i)
        if not m:
            toks.append(("unk", src[i]))
            i += 1
            continue
        kind = m.lastgroup
        if kind == "ws":
            i = m.end()
            continue
        toks.append((kind, m.group(0)))
        i = m.end()
    return toks


def beautify_lua(src, indent_str="    "):
    """Pretty-print minified Lua.

    Heuristics tuned for obfuscator output (one giant expression with
    flattened control flow):
      * newlines after `;`, after `end`/`until`, and after `then`/`do` that
        open a block, plus before `local`/`if`/`for`/`while`/`repeat`
      * depth tracking for (), {}, function...end, do...end,
        if/then...end, repeat...until
    """
    toks = tokenize_lua(src)
    out = []
    depth = 0          # block depth (function/if/for/while/do/repeat)
    line = []
    paren = 0          # ( [ { depth -> suppress newlines inside exprs

    def flush():
        if line:
            out.append(indent_str * max(depth, 0) + "".join(line).strip())
            line.clear()

    def pending():
        return "".join(line).strip()

    i = 0
    N = len(toks)
    while i < N:
        kind, val = toks[i]
        nxt = toks[i + 1][1] if i + 1 < N else ""

        if val in "([{":
            paren += 1
            line.append(val)
        elif val in ")]}":
            paren = max(paren - 1, 0)
            line.append(val)
        elif val == "function":
            depth += 1
            paren += 1          # function( behaves like an open paren
            line.append(val)
        elif val == "end":
            # close the innermost block opened by function/do/then
            depth -= 1
            paren = max(paren - 1, 0)
            flush()
            out.append(indent_str * max(depth, 0) + "end")
        elif val in ("do", "then"):
            line.append(val)
            # `do` after `for`/`while` head, or `then` after `if` head:
            # open a block and break the line
            flush()
            depth += 1
        elif val == "else":
            depth -= 1
            flush()
            out.append(indent_str * max(depth, 0) + "else")
            depth += 1
        elif val == "elseif":
            depth -= 1
            flush()
            out.append(indent_str * max(depth, 0) + val)
            depth += 1
        elif val == "repeat":
            line.append(val)
            flush()
            depth += 1
        elif val == "until":
            depth -= 1
            flush()
            # keep `until <cond>` on one line
            j = i + 1
            cond = []
            while j < N and toks[j][1] not in (";", "end", "until") \
                    and toks[j][1] not in (")", "]") or (j < N and paren > 0 and False):
                cond.append(toks[j][1])
                j += 1
                if len(cond) > 60:
                    break
            out.append(indent_str * max(depth, 0) + "until " + " ".join(cond).strip())
            i = j - 1
        elif val == ";":
            line.append(val)
            if paren == 0:
                flush()
        elif val in ("local",) or (val in ("if", "for", "while") and paren == 0
                                   and not pending().endswith(tuple("([{,=<>~+-*/%^#"))):
            if pending():
                flush()
            line.append(val)
        elif kind == "scomment" or kind == "lcomment":
            flush()
            out.append(indent_str * max(depth, 0) + val)
        else:
            line.append(val)
            if val in (",",) and paren >= 1 and nxt in ("function",):
                pass
        i += 1
    flush()
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------- CLI

def _cmd_detect(args):
    for path in args.files:
        version, style, loader = detect(path)
        print(f"{os.path.basename(path)}: Luraph v{version}  style={style}")


def _cmd_blobs(args):
    for path in args.files:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        blobs = extract_lph_blobs(data)
        print(f"== {os.path.basename(path)} ==")
        for i, (lvl, off, content) in enumerate(blobs):
            raw = decode_blob(content)
            print(f"  blob[{i}] level={lvl} offset={off} "
                  f"encoded={len(content)}B decoded={len(raw)}B "
                  f"sig={content[:4]!r}")


def _cmd_strings(args):
    for path in args.files:
        ss, infos = extract_strings(path, include_vm_strings=args.all)
        print(f"== {os.path.basename(path)}: {len(ss)} string constants ==")
        if args.verbose:
            for info in infos:
                print(f"   [blob level={info['level']} decoded="
                      f"{info['decoded']}B marker=0x{info['marker']:02x} "
                      f"count={info['count']}]" if info['marker'] is not None
                      else f"   [blob level={info['level']} decoded="
                           f"{info['decoded']}B marker=none]")
        lines = []
        for s in ss:
            t = s.decode("utf-8", "replace")
            if len(t) > 300 and not args.full:
                t = t[:300] + f"... [+{len(s) - 300} chars]"
            lines.append(t)
        out_text = "\n".join(lines)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_text + "\n")
            print(f"   -> written to {args.output}")
        else:
            print(out_text)


def _cmd_beautify(args):
    for path in args.files:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        pretty = beautify_lua(src, args.indent)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(pretty)
            print(f"{os.path.basename(path)} -> {args.output} "
                  f"({len(pretty.splitlines())} lines)")
        else:
            sys.stdout.write(pretty)


def _cmd_all(args):
    path = args.file
    base = os.path.splitext(os.path.basename(path))[0]
    version, style, _ = detect(path)
    print(f"== {os.path.basename(path)} ==")
    print(f"  Luraph v{version}  ({style})")
    stats = vm_stats(path)
    print(f"  {stats['size']}B, {stats['func_fields']} VM function fields, "
          f"entry={stats['entry']}")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    blobs = extract_lph_blobs(data)
    print(f"  {len(blobs)} serialized blob(s)")
    # strings
    ss, infos = extract_strings(path)
    out_path = f"{base}.strings.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for s in ss:
            t = s.decode("utf-8", "replace")
            f.write(t + "\n" if len(t) < 2000 else t[:2000] + "\n")
    print(f"  {len(ss)} script string constants -> {out_path}")
    # beautified
    pretty = beautify_lua(data)
    out_path = f"{base}.pretty.lua"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(pretty)
    print(f"  beautified VM -> {out_path} ({len(pretty.splitlines())} lines)")


def _cmd_unpack(args):
    """Unpack loader-style files: LPH blob -> base85 -> arithmetic/LZ decode."""
    try:
        from luraph_arith import decompress
    except ImportError:
        print("error: luraph_arith.py must be next to luraph_deobf.py")
        return
    for path in args.files:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        base = os.path.splitext(os.path.basename(path))[0]
        blobs = extract_lph_blobs(data)
        print(f"== {os.path.basename(path)}: {len(blobs)} blob(s) ==")
        for i, (lvl, off, content) in enumerate(blobs):
            raw = decode_blob(content)
            print(f"  blob[{i}] level={lvl} sig={content[:4]!r} "
                  f"encoded={len(content)}B base85={len(raw)}B")
            try:
                out = decompress(raw)
                kind = "lua" if b"local" in out[:200] or b"return" in out[:200] \
                    else "binary/layered"
                print(f"          arith-decoded -> {len(out)}B ({kind})")
                if args.out_dir:
                    os.makedirs(args.out_dir, exist_ok=True)
                    out_path = os.path.join(args.out_dir,
                                            f"{base}.blob{i}.unpack.lua")
                    with open(out_path, "wb") as f:
                        f.write(out)
                    print(f"          -> {out_path}")
                elif len(out) < 1200:
                    print(repr(out))
            except Exception as e:
                print(f"          arith-decode failed: {e} "
                      f"(encrypted blob or different variant)")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="luraph_deobf",
        description="Luraph v14.8 deobfuscation toolkit (offline, no deps)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("detect", help="detect Luraph version/style")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(fn=_cmd_detect)

    sp = sub.add_parser("blobs", help="list serialized LPH blobs")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(fn=_cmd_blobs)

    sp = sub.add_parser("strings", help="decode script string constants")
    sp.add_argument("files", nargs="+")
    sp.add_argument("-o", "--output")
    sp.add_argument("--all", action="store_true",
                    help="include VM-internal strings")
    sp.add_argument("--full", action="store_true",
                    help="do not truncate long strings")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(fn=_cmd_strings)

    sp = sub.add_parser("beautify", help="pretty-print the protected file")
    sp.add_argument("files", nargs="+")
    sp.add_argument("-o", "--output")
    sp.add_argument("-i", "--indent", default="    ")
    sp.set_defaults(fn=_cmd_beautify)

    sp = sub.add_parser("unpack", help="arith-decode loader-style blobs")
    sp.add_argument("files", nargs="+")
    sp.add_argument("-d", "--out-dir",
                    help="write unpacked blobs to this directory")
    sp.set_defaults(fn=_cmd_unpack)

    sp = sub.add_parser("all", help="detect + blobs + strings + beautify")
    sp.add_argument("file")
    sp.set_defaults(fn=_cmd_all)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
