#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the combined sandbox script: stubs + protected source + runner.

Usage:
  python3 build_combined.py <protected.lua> <combined_out.lua> [--api apiroblox.luau] [--envlog]

--api       : splice apiroblox.luau (full Roblox API stub) into the harness;
              its environment table is exposed to the protected chunk as
              _LPH_API (harness_post merges it into the sandbox env).
--envlog    : include envlog.luau and wrap the API env with the tracer;
              every global read/call performed by the VM is logged to stdout
              as "path read -> value" / "path(args)" lines.
"""

import sys

HERE = '/data/data/com.termux/files/home/luraph-work/sandbox/'

pre = open(HERE + 'harness_pre.lua').read()
post = open(HERE + 'harness_post.lua').read()
protected = open(sys.argv[1], encoding='utf-8', errors='replace').read()

use_api = '--api' in sys.argv
use_envlog = '--envlog' in sys.argv
out = sys.argv[2]

extra = ''
if use_api:
    extra += '\n-- === APIROBLOX STUB START ===\n'
    extra += 'local _LPH_API = (function()\n'
    extra += open(HERE + 'apiroblox.luau', encoding='utf-8').read()
    extra += '\nend)()\n-- === APIROBLOX STUB END ===\n'
    if use_envlog:
        extra += ('-- === ENVLOG START ===\n'
                  'local _LPH_ENVLOG = (function()\n'
                  + open(HERE + 'envlog.luau', encoding='utf-8').read()
                  + '\nend)()\n'
                  '_LPH_API = _LPH_ENVLOG.wrap(_LPH_API, _LPH_ENVLOG.logf(), '
                  '{ call_depth = 2 })\n'
                  '-- === ENVLOG END ===\n')
    # merge the API stub into the sandbox env so the VM sees it.
    # this runs after harness_pre's real_globals proxy is active, so
    # writes through env land in real_globals
    extra += ('for k, v in pairs(_LPH_API) do\n'
              '    local cur = env[k]\n'
              '    if cur == nil then env[k] = v end\n'
              'end\n')

combined = (
    pre
    + extra
    + "\nlocal function RUN_PROTECTED(...)\n"
    + "-- === PROTECTED SOURCE START ===\n"
    + protected
    + "\n-- === PROTECTED SOURCE END ===\nend\n"
    + post
)
open(out, 'w', encoding='utf-8').write(combined)
print('combined written:', out, f'({len(combined)}B)')
