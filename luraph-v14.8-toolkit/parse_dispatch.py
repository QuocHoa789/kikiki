#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse the Luraph v14.8 VM dispatch tree into an opcode->handler map.

The dispatch loop is a nested binary-search if-tree over the opcode
register (g). Each leaf is a handler body operating on the SoA columns.
This script walks the tree, records the opcode constraint path for every
leaf, and dumps the mapping for semantic lifting.

Usage: python3 parse_dispatch.py <dispatch.lua> [-o out.txt]
"""

import re
import sys


def tokenize(src):
    """Yield (kind, value) tokens; kinds: kw, str, num, name, op, punct."""
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                if src[j] == "\\":
                    j += 1
                j += 1
            yield ("str", src[i:j + 1])
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                if src[j] == "\\":
                    j += 1
                j += 1
            yield ("str", src[i:j + 1])
            i = j + 1
            continue
        if c == "[":
            j = i + 1
            eq = 0
            while j < n and src[j] == "=":
                eq += 1
                j += 1
            if j < n and src[j] == "[":
                closer = "]" + "=" * eq + "]"
                k = src.find(closer, j + 1)
                if k >= 0:
                    yield ("str", src[i:k + len(closer)])
                    i = k + len(closer)
                    continue
        m = re.match(r"[A-Za-z_]\w*", src[i:])
        if m:
            yield ("name", m.group(0))
            i += m.end()
            continue
        m = re.match(r"0[Xx][0-9A-Fa-f_]+|0[Bb][01_]+|\d[\d_]*(\.\d+)?", src[i:])
        if m:
            yield ("num", m.group(0))
            i += m.end()
            continue
        m = re.match(r"(>=|<=|~=|==|\.\.\.|\.\.|[-+*/%^#<>=(){}\[\];:,.])", src[i:])
        if m:
            yield ("punct", m.group(0))
            i += m.end()
            continue
        i += 1


def parse_value(tok):
    if tok[0] == "num":
        s = tok[1].replace("_", "")
        try:
            if s.lower().startswith("0x"):
                return int(s, 16)
            if s.lower().startswith("0b"):
                return int(s, 2)
            return int(float(s))
        except ValueError:
            return None
    return None


class Node:
    __slots__ = ("kind", "cond", "yes", "no", "body", "text")

    def __init__(self, kind):
        self.kind = kind  # 'if' | 'leaf'
        self.cond = None  # (op, value) for the g register
        self.yes = None
        self.no = None
        self.body = None
        self.text = ""


class Parser:
    def __init__(self, toks):
        self.toks = list(toks)
        self.pos = 0
        self.opname = "g"

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def next(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, val):
        t = self.next()
        if t is None or t[1] != val:
            ctx = self.toks[max(0, self.pos - 8):self.pos + 8]
            raise ValueError(f"expected {val}, got {t} | context: "
                             f"{[x[1] for x in ctx]}")

    def skip_block(self, stop_at_else=False):
        """Skip tokens until matching end/else (tracking depth)."""
        depth = 0
        while self.pos < len(self.toks):
            t = self.peek()
            v = t[1]
            if t[0] == "name" and v in ("if", "while", "for", "function", "do", "repeat"):
                depth += 1
            elif t[0] == "name" and v == "end":
                if depth == 0:
                    return
                depth -= 1
            elif t[0] == "name" and v in ("else", "elseif"):
                if depth == 0 and stop_at_else:
                    return
                if v == "elseif":
                    continue  # part of same if
            self.next()

    def parse_if_chain(self):
        """Parse: if <cond on g> then B (elseif <cond> then B)* (else B)? end"""
        root = None
        node = None
        while True:
            t = self.peek()
            if t is None:
                break
            if t[0] == "name" and t[1] in ("if", "elseif"):
                self.next()
                cond = self.parse_cond()
                self.expect("then")
                branch = Node("if")
                branch.cond = cond
                branch.yes = self.parse_body()
                if node is None:
                    root = branch
                else:
                    node.no = branch
                node = branch
            elif t[0] == "name" and t[1] == "else":
                self.next()
                if node is not None:
                    node.no = self.parse_body()
                # skip trailing semicolons before the chain's end
                while self.peek() and self.peek()[1] == ";":
                    self.next()
                t = self.peek()
                if t and t[1] in ("end", "until"):
                    self.next()
                break
            elif t[0] == "name" and t[1] in ("end", "until"):
                self.next()
                break
            else:
                self.next()
        return root

    def parse_body(self):
        """Parse statements until else/elseif/end at this level."""
        t = self.peek()
        if t and t[0] == "name" and t[1] == "if":
            return self.parse_if_chain()
        # leaf: collect raw text until else/end at this level
        # NOTE: `do` is NOT an opener — for/while already account for it
        start = self.pos
        depth = 0
        while self.pos < len(self.toks):
            t = self.peek()
            v = t[1]
            if t[0] == "name" and v in ("if", "while", "for", "function", "repeat"):
                depth += 1
            elif t[0] == "name" and v == "end":
                if depth == 0:
                    break
                depth -= 1
            elif t[0] == "name" and v in ("else", "elseif"):
                if depth == 0:
                    break
            elif t[0] == "name" and v == "until":
                if depth == 0:
                    break
            self.next()
        leaf = Node("leaf")
        leaf.body = self.toks[start:self.pos]
        return leaf

    def parse_cond(self):
        """Parse conditions on g: g>=X / g<X / g~=X / g==X possibly combined."""
        conds = []
        while True:
            t = self.peek()
            if t is None:
                break
            if t[0] == "name" and t[1] in ("then", "do"):
                break
            if t[0] == "name" and t[1] == self.opname:
                self.next()
                op = self.next()
                val = self.next()
                v = parse_value(val)
                if v is not None:
                    conds.append((op[1], v))
                continue
            if t[0] == "name" and t[1] == "not":
                self.next()
                self.expect("(")
                t3 = self.peek()
                if t3 and t3[0] == "name" and t3[1] == self.opname:
                    # not(g<X) -> g>=X
                    self.next()  # g
                    op = self.next()
                    val = self.next()
                    v = parse_value(val)
                    self.expect(")")
                    if v is not None:
                        inv = {"<": ">=", ">": "<=", ">=": "<", "<=": ">",
                               "~=": "==", "==": "~="}
                        conds.append((inv.get(op[1], op[1]), v))
                    continue
                # runtime condition — skip balanced parens
                depth = 1
                while depth > 0 and self.pos < len(self.toks):
                    t4 = self.next()
                    if t4[1] == "(":
                        depth += 1
                    elif t4[1] == ")":
                        depth -= 1
                continue
            # anything else in the condition — skip token
            self.next()
        return conds


def walk(node, path, out):
    if node is None:
        return
    if node.kind == "leaf":
        text = " ".join(t[1] for t in (node.body or []))
        out.append((list(path), text))
        return
    invert = {"<": ">=", ">=": "<", ">": "<=", "<=": ">",
              "==": "~=", "~=": "=="}
    if node.cond:
        yes_conds = [c for c in node.cond
                     if isinstance(c, tuple) and len(c) == 2]
        for c in yes_conds:
            path.append(c)
    if node.yes is not None:
        walk(node.yes, path, out)
    if node.cond:
        for c in yes_conds:
            path.pop()
        # the no-branch takes the inverted constraints
        for op, v in yes_conds:
            path.append((invert.get(op, op), v))
    if node.no is not None:
        walk(node.no, path, out)
    if node.cond:
        for op, v in yes_conds:
            path.pop()


def main():
    src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    toks = tokenize(src)
    p = Parser(toks)
    tree = p.parse_if_chain()
    out = []
    walk(tree, [], out)
    print(f"leaves (handlers): {len(out)}")
    lines = []
    for path, text in out:
        rng = " & ".join(f"g{op}{v}" for op, v in path)
        lines.append(f"OPCODE {rng}\n  {text}")
    text = "\n".join(lines)
    if len(sys.argv) > 3 and sys.argv[2] == "-o":
        open(sys.argv[3], "w", encoding="utf-8").write(text + "\n")
        print("->", sys.argv[3])
    else:
        print(text[:3000])


if __name__ == "__main__":
    main()
