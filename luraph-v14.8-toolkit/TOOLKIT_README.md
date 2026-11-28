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

## The 5-stage deobfuscation pipeline (runtime-based)

The classic 5-stage flow (AST hooking → sandboxed simulation → live REPL
decryption → CFG/SSA lifting → polish naming) maps to Luraph v14.8's actual
mechanism like this:

| Stage (generic) | Luraph v14.8 reality | Tool here |
|---|---|---|
| 1. AST hooking | the protected file is ONE Lua expression that builds the VM; hook it at the **source level**: probes into the blob deserializer and every dispatch opcode fetch (dispatch array names are randomized per build — auto-detected by fetch frequency) | `instrument.py` |
| 2. sandboxed simulation | run the instrumented VM in the **Luau CLI outside Roblox** against a stub env; the sandbox traces globals, captures the key table, lazy-decrypt chain evolution and full SoA instruction columns | `build_combined.py --api --envlog` + `harness_pre/post.lua` |
| 3. live REPL decryption | Luraph decrypts constants lazily at runtime; capture them as they materialize. The runtime below runs the real payload and exposes the decrypted chunks (`\0CHUNK` hex blocks) and a serve/REPL JSON loop | `build_runtime.py serve=1` |
| 4. CFG/SSA lifting | the VM dispatch is a chain of **flattened if-trees** (one per prototype, 256 ops each, semantically shuffled per build); parse the trees, evaluate the branch conditions with concrete opcodes, resolve every opcode to its handler body → linear IR with branch edges | `parse_dispatch.py`, `lift.py`, `reconstruct.py` |
| 5. polish naming → clean Luau | the runtime records every operation the payload performs and **reconstructs readable Luau source** from the observed behavior (statements, calls, service lookups); string constants recovered statically fill in the rest | `build_runtime.py` + `parse_envlog.py` |

## The runtime (luraphruntime)

`runtime/` bundles the dynamic deobfuscation runtime:

* `envlog.luau` — the main runtime (4700 lines): fake Roblox/executor
  environment of logging proxies; executes the payload and renders readable
  Luau from the observed operations; handles Luraph anti-tamper; exposes a
  serve/REPL mode (`CFG.serve=1`) with JSON output blocks
* `datatypes.luau` — offline math models of Roblox datatypes (CFrame with
  float32 rotation, Vector3/2, UDim2, ...) used as "real twins" for proxies
* `unicode_data.luau` — Unicode decomposition/CCC/composition tables
* `roblox_api_data.luau` — generated by `gen_roblox_data.py`: the enums and
  per-class method/event/property data envlog validates `GetService` against
  (replaces the broken `roblox_api.luau` fragment of the original zip)

Usage:

```bash
# build + run the runtime on a protected file
python3 build_runtime.py protected.lua combined.luau max_stmts=500000 dump_strings=1
luau combined.luau > run.txt

# extract the reconstructed Luau source, strings, chunks, status
python3 parse_envlog.py run.txt out_dir/
```

Verified on real samples: the runtime passes Luraph's decompression and
anti-tamper stages, and reconstructs the payload's actual statements into
readable Luau (see `deobf-output/6z_7/runtime_source.luau` — the recovered
source of a moonlight-hub egg script: GetService(TweenService/RunService/
CoreGui), FindFirstChild, global toggles...). Budget note: per-sample VM
decompression needs 80K–700K counted statements; too small aborts with
"budget exhausted", too large can loop forever — tune `max_stmts=`.

## Luau sandbox (dynamic analysis)

`instrument.py` + `build_combined.py` + `harness_pre.lua`/`harness_post.lua` run a
protected file inside the Luau CLI outside Roblox:

```bash
# instrument (hook deserializer / dispatch loop) then build + run
python3 instrument.py protected.lua instr.lua --mode trees   # ir | instr | trees
python3 build_combined.py instr.lua combined.lua
luau combined.lua -a

# with the full Roblox API stub (apiroblox.luau): the VM passes executor
# checks and the actual payload body runs (event loops keep it alive —
# use timeout)
python3 build_combined.py instr.lua combined.lua --api

# additionally trace every API call the payload makes (envlog.luau)
python3 build_combined.py instr.lua combined.lua --api --envlog
```

* `apiroblox.luau` — standalone Roblox environment stub: game/GetService for all
  common services, Instance.new with auto-signal properties, Enum, task,
  Vector3/Vector2/CFrame/Color3/UDim2/TweenInfo (and other constructors as
  `.new`-style tables), getgenv/getrenv (return the stub env), executor-compat
  functions (hookfunction, cloneref, request, readfile/writefile, ...).
  Verified standalone with `luau test_api.lua` (all API tests pass).
* `envlog.luau` — environment tracer: wraps an env table so every global read,
  write and function call is logged (`path read -> value`, `path(args)`).
  Use standalone or via `build_combined.py --envlog`.
* Known limitations: some samples (z20_1, z20_2, z20_4, 6z_3, 6z_6, 6z_9) hit
  a VM dispatch variant the harness cannot execute ("attempt to index nil
  with 'new'"); payloads waiting on real Roblox events (Heartbeat, WaitForChild)
  run forever under `--api` — that is expected and shows the stub got them past
  all executor/anti-tamper checks.

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
