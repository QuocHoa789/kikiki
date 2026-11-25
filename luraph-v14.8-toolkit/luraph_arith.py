#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port of the Luraph v14.8 loader-stage-1 arithmetic decompressor.

The protected file's loader wrapper contains (in obfuscated Lua) a
range-coder / LZ77 hybrid decompressor that is byte-for-byte equivalent
to a simplified LZMA decoder:

  * rc_bit            - LZMA adaptive 11-bit probability bit
  * rc_bit_tree       - LZMA bit tree
  * rc_bit_tree_reverse
  * rc_matched_literal- literal decoded against the match byte
  * length decoder    - choice / low(3) / mid(3) / high(8)
  * posSlot           - 6-bit tree; direct bits + 4-bit align reverse
  * 12-state match state machine

Model layout (as declared in the VM source):
  literal coder : s = model[8 contexts][0x300], context = prev_byte >> 5
  isMatch       : h[12][1]    isRep     : t[12]
  isRepG0       : E[12]       isRepG1   : S[12]
  isRepG2       : i[12]       isRep0Long: N[12][1]
  posSlot       : W[4][64]    dist low  : K[115]    align: m[16]
  len models    : U (simple match), J (rep match)
                  each = {1:1024, 2:1024, 3:low[1][8], 4:mid[1][8], 5:high[256]}

Usage:
    from luraph_arith import decompress
    out = decompress(raw_bytes_from_base85_blob)
"""

POW = [1 << i for i in range(34)]  # 2^0 .. 2^33


def decompress(data: bytes) -> bytes:
    if not data:
        return b""

    V = 0                 # next byte to read (0-based)
    A = len(data)
    code = 0              # Lua 'd': code/low register (up to 2^40)
    state = 0             # Lua 'X'
    out_pos = 0           # Lua 'p'
    dic = {0: 0}          # Lua 'd' table: output byte dictionary

    def read_byte():
        nonlocal V
        V += 1
        if V - 1 >= A:
            raise EOFError("decompressor ran past input")
        return data[V - 1]

    # prime code register with 5 bytes
    for _ in range(5):
        code = code * 256 + read_byte()

    rng = 0xFFFFFFFF      # Lua 'b': range register

    def rc_direct(w: int) -> int:
        """Decode w direct bits, MSB first (uses rng/code only)."""
        nonlocal rng, code
        res = 0
        for _ in range(w):
            rng //= 2
            res *= 2
            if not (code < rng):
                code -= rng
                res += 1
            if rng <= 0x00FFFFFF:
                rng *= 256
                code = code * 256 + read_byte()
        return res

    def rc_bit(model, key) -> int:
        """One adaptive bit (LZMA style)."""
        nonlocal rng, code
        q = rng // 2048
        prob = model[key]
        bound = q * prob
        if code < bound:
            rng = bound
            model[key] = prob + (2048 - prob) // 32
            bit = 0
        else:
            rng -= bound
            code -= bound
            model[key] = prob - prob // 32
            bit = 1
        if rng <= 0x00FFFFFF:
            rng *= 256
            code = code * 256 + read_byte()
        return bit

    def rc_bit_tree(model, num_bits: int, offset: int) -> int:
        """Decode num_bits via bit tree; returns value - offset."""
        m = 1
        for _ in range(num_bits):
            m = m * 2 + rc_bit(model, m)
        return m - offset

    def rc_bit_tree_reverse(model, num_bits: int, base: int) -> int:
        """Decode num_bits via reversed bit tree."""
        val = 0
        m = 1
        for u in range(num_bits):
            bit = rc_bit(model, base + m)
            m = m * 2 + bit
            val += bit * POW[u]
        return val

    def rc_matched_literal(model, match_byte: int) -> int:
        """Literal decoded against the match byte."""
        m = 1
        for p in range(7, -1, -1):
            mb_bit = (match_byte // POW[p]) % 2
            bit = rc_bit(model, m + mb_bit * 256 + 256)
            m = m * 2 + bit
            if mb_bit != bit:
                while m < 0x100:
                    m = m * 2 + rc_bit(model, m)
                break
        return m % 256

    def rc_length(model, pos_state) -> int:
        """LZMA-style length decoder."""
        if rc_bit(model, 1) == 0:
            return rc_bit_tree(model[3][pos_state], 3, 8)
        elif rc_bit(model, 2) == 0:
            return 8 + rc_bit_tree(model[4][pos_state], 3, 8)
        return rc_bit_tree(model[5], 8, 256) + 16

    # ---- model factories (from the VM source) ----
    def probs(n):
        return {i: 1024 for i in range(n)}

    def probs2d(rows, cols):
        return [{i: 1024 for i in range(cols)} for _ in range(rows)]

    def len_model():
        return {1: 1024, 2: 1024,
                3: probs2d(1, 8), 4: probs2d(1, 8), 5: probs(256)}

    # ---- models ----
    lit = probs2d(8, 0x300)        # s
    is_match = probs2d(12, 1)      # h
    rep0 = 0                       # L
    rep1 = 0                       # Q  (also the current match distance)
    rep2 = 0                       # F
    rep3 = 0                       # r
    is_rep = probs(12)             # t
    is_repg0 = probs(12)           # E
    is_repg1 = probs(12)           # S
    is_repg2 = probs(12)           # i
    is_rep0_long = probs2d(12, 1)  # N
    pos_slot = probs2d(4, 64)      # W
    dist_low = probs(115)          # K
    align = probs(16)              # m
    match_len = len_model()        # U
    rep_len = len_model()          # J

    # Lua: w = {[0]=0,0,0,0,1,2,3,4,5,6,4,5}
    transitions = [0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 4, 5]

    while V <= A:
        pos_state = 0  # Lua `p % 1` == 0.0 (out_pos always integer-valued)

        if rc_bit(is_match[state], pos_state) == 0:
            # ---- literal ----
            prev_byte = dic.get(out_pos, 0)
            ctx = (prev_byte // POW[5]) % 256   # prev_byte >> 5
            model = lit[ctx]
            out_pos += 1
            if state < 7:
                dic[out_pos] = rc_bit_tree(model, 8, 256)
            else:
                match_byte = dic.get(out_pos - rep1 - 1, 0)
                dic[out_pos] = rc_matched_literal(model, match_byte)
            state = transitions[state]
        else:
            # ---- match ----
            length = None
            if rc_bit(is_rep, state) != 0:
                # rep match
                if rc_bit(is_repg0, state) == 0:
                    if rc_bit(is_rep0_long[state], pos_state) == 0:
                        state = 9 if state < 7 else 11
                        length = 1
                else:
                    if rc_bit(is_repg1, state) == 0:
                        sel = rep0
                    else:
                        if rc_bit(is_repg2, state) == 0:
                            sel = rep2
                        else:
                            sel = rep3
                            rep3 = rep2
                        rep2 = rep0
                    rep0 = rep1
                    rep1 = sel
                if length is None:
                    state = 8 if state < 7 else 11
                    length = 2 + rc_length(rep_len, pos_state)
            else:
                # simple match: shift rep distances
                rep3 = rep2
                rep2 = rep0
                rep0 = rep1
                length = 2 + rc_length(match_len, pos_state)
                len_state = length - 2
                if 4 <= len_state:
                    len_state = 3
                slot = rc_bit_tree(pos_slot[len_state], 6, 64)
                if slot >= 4:
                    num_bits = slot // 2 - 1
                    base = (2 + slot % 2) * POW[num_bits]
                    if slot < 14:
                        rep1 = base + rc_bit_tree_reverse(
                            dist_low, num_bits, base - slot)
                    else:
                        rep1 = base + rc_direct(num_bits - 4) * 16 \
                            + rc_bit_tree_reverse(align, 4, 0)
                        if rep1 == 0xFFFFFFFF:
                            # end-of-stream marker (return value ignored by caller)
                            return _materialize(dic)
                state = 7 if state < 7 else 10
                if rep1 >= out_pos:
                    return _materialize(dic)
            # LZ copy (positions out_pos+1 .. out_pos+length)
            end = out_pos + length
            for i in range(out_pos + 1, end + 1):
                dic[i] = dic.get(i - rep1 - 1, 0)
            out_pos = end

    return _materialize(dic)


def _materialize(dic) -> bytes:
    total = max(dic.keys())
    return bytes(dic.get(i, 0) for i in range(1, total + 1))
