# Luraph v14.8 Deobfuscation Outputs

Results of running the [luraph-v14.8-toolkit](../luraph-v14.8-toolkit/) on
16 real Luraph v14.8 samples plus one live wild sample.

## Contents

* `<sample>/strings.txt` — decoded string constants (the original script's
  strings: Roblox API names, messages) + VM-internal strings
* `<sample>/pretty.lua` — the protected file pretty-printed (readable Lua,
  VM structure visible)
* `<sample>/devirt_report.txt` — full IR-level analysis report: version,
  style, blob states, string constants split application/VM-internal
* `6z_1/` additionally contains the complete instrumentation results:
  * `full_logic_2849instr.txt` — the reconstructed program logic:
    2849 instructions across 11 prototypes, 98.3% resolved to handler
    bodies
  * `logic.txt`, `lift.txt`, `opmap.txt` — opcode→semantics lifting
  * `instr.txt` — per-fetch execution trace with all SoA operands
    (C = global-name column, U = constant pool, S = dest, z = src1,
    w = jump/aux)
  * `trees.txt` — captured prototype dispatch trees
  * `irview.txt` — execution-data capture (key table, byte cache,
    VM helpers, math constants)
* `all_trees_sem.txt` — all 11 dispatch trees parsed, 256 ops each,
  with recognized semantics per opcode
* `Library_test/` — live test on a wild sample from another repository
  (4 prototype trees captured)
* `unpacked/` — loader-stage blobs decoded to Lua stubs

## Sample coverage

| Sample | Strings | Pretty | Notes |
|---|---|---|---|
| 6z_1, 6z_7 | 87 | 4450 lines | full instrumentation, logic reconstruction |
| 6z_10, 6z_6 | 173 | 6592 lines | identical builds (same program) |
| 6z_2 | 170 | — | encrypted-layer blob, strings via alternate path |
| 6z_3 | 170 | 45718 lines | 32 dispatch loops (per-prototype trees) |
| 6z_4 | 4 | — | loader-style, blobs unpacked to Lua stubs |
| 6z_5 | 155 | 4765 lines | |
| 6z_8 | 5 | — | loader-style |
| 6z_9 | 171 | 6487 lines | 25 chain-step dumps (lazy decrypt) |
| z20_1 | 12 | 259 lines | executor-check script, behaviour traced |
| z20_2 | 157 | 4703 lines | IR capture perfect |
| z20_3, z20_5, z20_6 | 156/156/158 | 4601/5071/4502 lines | |
| z20_4 | 157 | 4608 lines | 21 chain-step dumps |

## Constant tables recovered

The recovered constant tables include the Roblox APIs the original
scripts use (Instance, RunService, StarterGui, Vector3, Path2D,
DataModel, EnumType, HttpService...), plus loader/anti-tamper strings
("Your executor is not supported...", debug library checks).
