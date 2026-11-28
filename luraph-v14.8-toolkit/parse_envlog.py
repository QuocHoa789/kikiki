#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse the output of the luraphruntime (envlog.luau) run.

Extracts from a combined-runtime `luau` run:
  * run status + statement count (header lines)
  * the reconstructed readable Luau source (stage 5 output: clean source)
  * the opcode trace ring (\0TR entries, if inline tracing was enabled)
  * collected string constants (\0ENVLOG-STRINGS section, if dump_strings=1)

Usage: python3 parse_envlog.py <run_output.txt> [-o out_dir]
Writes out_dir/source.luau, out_dir/strings.txt, out_dir/trace.txt (when present)
and prints a summary.
"""

import sys
import os
import re


def parse(text):
    """Split a runtime run into its blocks."""
    begin = text.find('\0ENVLOG-BEGIN')
    end = text.find('\0ENVLOG-END')
    if begin == -1:
        return None
    block = text[begin + len('\0ENVLOG-BEGIN'):end if end != -1 else None]

    header = []
    body_start = None
    lines = block.split('\n')
    tr = []
    chunks = []
    strings = []
    i = 0
    # header: leading \0-prefixed lines then '-- ' comment lines, then a
    # blank line, then the reconstructed source
    while i < len(lines):
        l = lines[i]
        if l.startswith('\0'):
            kind, _, rest = l.partition(' ')
            if kind == '\0TR':
                tr.append(rest)
            elif kind == '\0CHUNK':
                chunks.append((rest, lines[i + 1] if i + 1 < len(lines) else ''))
                i += 1
            i += 1
            continue
        if l.startswith('--') or l.strip() == '':
            header.append(l)
            i += 1
            continue
        body_start = i
        break

    # strings section: \0ENVLOG-STRINGS .. \0ENVLOG-END (rest of block)
    sm = re.search(r"\0ENVLOG-STRINGS\n(.*?)\0ENVLOG-END", block, re.S)
    if sm:
        strings = [l for l in sm.group(1).split('\n') if l.strip()]

    body = '\n'.join(lines[body_start:]) if body_start is not None else ''
    # strip the trailing \0ENVLOG-STRINGS section from the body
    if '\0ENVLOG-STRINGS' in body:
        body = body[:body.index('\0ENVLOG-STRINGS')]
    return {
        'header': '\n'.join(h for h in header if h.strip()),
        'source': body.strip('\n') + '\n',
        'tr': tr,
        'chunks': chunks,
        'strings': strings,
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = [a for a in sys.argv[1:] if a.startswith('-')]
    if not args:
        sys.exit(__doc__)
    text = open(args[0], encoding='utf-8', errors='replace').read()
    parsed = parse(text)
    if parsed is None:
        print('no \0ENVLOG-BEGIN block found — runtime did not produce output')
        sys.exit(1)

    out_dir = args[1] if len(args) > 1 else 'envlog-out'
    os.makedirs(out_dir, exist_ok=True)
    src_path = os.path.join(out_dir, 'source.luau')
    with open(src_path, 'w', encoding='utf-8') as f:
        f.write(parsed['source'])
    print(parsed['header'])
    n_lines = parsed['source'].count('\n')
    print(f"reconstructed source: {src_path} ({n_lines} lines)")
    if parsed['strings']:
        sp = os.path.join(out_dir, 'strings.txt')
        with open(sp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(parsed['strings']) + '\n')
        print(f"strings: {sp} ({len(parsed['strings'])})")
    if parsed['tr']:
        tp = os.path.join(out_dir, 'trace.txt')
        with open(tp, 'w', encoding='utf-8') as f:
            f.write('\n'.join(parsed['tr']) + '\n')
        print(f"opcode trace: {tp} ({len(parsed['tr'])} entries)")
    if parsed['chunks']:
        cp = os.path.join(out_dir, 'chunks.txt')
        with open(cp, 'w', encoding='utf-8') as f:
            for k, h in parsed['chunks']:
                f.write(f"== {k}\n{h}\n")
        print(f"chunks: {cp} ({len(parsed['chunks'])})")


if __name__ == '__main__':
    main()
