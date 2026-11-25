#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the combined sandbox script: stubs + protected source + runner.

Usage: python3 build_combined.py <protected.lua> <combined_out.lua>
"""

import sys

pre = open('/data/data/com.termux/files/home/luraph-work/sandbox/harness_pre.lua').read()
post = open('/data/data/com.termux/files/home/luraph-work/sandbox/harness_post.lua').read()
protected = open(sys.argv[1], encoding='utf-8', errors='replace').read()

combined = (
    pre
    + "\nlocal function RUN_PROTECTED(...)\n"
    + "-- === PROTECTED SOURCE START ===\n"
    + protected
    + "\n-- === PROTECTED SOURCE END ===\nend\n"
    + post
)
open(sys.argv[2], 'w', encoding='utf-8').write(combined)
print('combined written:', sys.argv[2], f'({len(combined)}B)')
