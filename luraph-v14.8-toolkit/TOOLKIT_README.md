# Luraph v14.8 Deobfuscation Toolkit

A research-oriented **offline toolkit for analyzing Luraph v14.8 protected Lua/Luau scripts**.
Pure Python 3, no dependencies. Built and verified against 16 real Luraph v14.8 samples
collected from public sample repositories (see Credits).

## What this tool does

Luraph v14.8 is a VM-based obfuscator. A protected file is one giant Lua expression that
builds a table of VM functions and runs obfuscated bytecode. The original program's data
(constants, instructions, prototypes) is serialized into one or more blobs starting with
the plaintext signature `LPH?` (4 chars, 4th char varies per build), stored in Lua
long-bracket strings at whatever `[`...`]` level avoids conflicts in the data.

This toolkit reverses the parts of the pipeline that are stable across samples:

| Command | What it does | Status |
|---|---|---|
| `detect` | Detect Luraph version and output style (vm / loader) | works on all samples |
| `blobs` | Locate and list every serialized `LPH?` blob | works on all samples |
| `strings` | **Decode the script's string constants** from the blob (auto-detects the per-file randomized type marker, parses varint-length entries) | works on 13/16 samples |
| `beautify` | Pretty-print the minified one-line VM code into readable, indented Lua | works on all samples |
| `unpack` | Arithmetic/LZ-decode loader-style blobs (port of the loader's range coder + LZ77 decoder) | works on loader-style samples |
| `all` | detect + blobs + strings + beautify in one shot | — |

### How the string extraction works

Reverse-engineered from the VM source in the samples:

1. The blob is stripped of the `LPH?` signature, then `z` placeholders are expanded
   (`z` compresses a 32-bit zero word into one character).
2. Every 5 characters decode to one 32-bit word in **base-85, little-endian digit
   order**, packed as `<I4`.
3. The constants section is a stream of `<type> <varint len> <data>` entries. The
   string-type byte is randomized per file (e.g. `0x29`, `0x58`, `0x73`, `0xc8`...), so
   the tool auto-detects it by scoring valid clean-string parses.

The recovered constants include the original script's strings (Roblox API names, URLs,
messages) plus the VM's internal strings — the fastest way to understand what a
protected script actually does.

### Honest limitations

* This is **not** a full devirtualizer. Rebuilding original source from the VM bytecode
  (SoA instruction arrays, polymorphic IR, runtime instruction patching) is a much
  larger research project and is out of scope here.
* Samples where the blob decodes to an encrypted/high-entropy layer are detected and
  reported, but their constants cannot be extracted statically.
* Variable names and formatting are not recovered (Luraph randomizes them per build).

## Usage

```bash
# detect version + style
python3 luraph_deobf.py detect protected.lua

# list serialized blobs
python3 luraph_deobf.py blobs protected.lua

# decode string constants (the main feature)
python3 luraph_deobf.py strings protected.lua -o strings.txt -v

# include VM-internal strings too
python3 luraph_deobf.py strings protected.lua --all --full

# pretty-print the VM
python3 luraph_deobf.py beautify protected.lua -o pretty.lua

# unpack loader-style blobs (arithmetic/LZ decode)
python3 luraph_deobf.py unpack protected.lua -d unpacked/

# everything at once
python3 luraph_deobf.py all protected.lua
```

`luraph_arith.py` must sit next to `luraph_deobf.py` (it is the port of the loader's
range-coder/LZ77 decompressor, including the 11-bit adaptive probability model bit
decoder, bit trees, matched-literal decoding, and the 12-state match state machine).

## Requirements

Python 3.8+ (tested on 3.14). No third-party packages.

## Files

* `luraph_deobf.py` — main CLI: detection, blob extraction, base-85 decoding,
  string-constant recovery, Lua beautifier, unpack driver
* `luraph_arith.py` — port of the loader-stage arithmetic/LZ77 decompressor

## Credits

Built and verified against real Luraph v14.8 samples from the public sample collections:

* [Zain20m/Samples](https://github.com/Zain20m/Samples) — Luraph v14.8 samples
* [SixZensED/luau-obfuscator-samples](https://github.com/SixZensED/luau-obfuscator-samples) — Luraph V14.8 samples

Sample attribution preserved per those repositories' guidelines.

## License

MIT — use at your own risk, for research and authorized analysis only.
