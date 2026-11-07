#!/usr/bin/env python3
"""build.py - assemble ai-gateway.yaml (and the chat-ui example) from their .in templates.

A line holding only "@@FILE path@@" is replaced by that file's lines, indented like the marker. Includes may nest.
Usage: scripts/build.py            (writes ai-gateway.yaml)
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARK = re.compile(r"^(\s*)@@FILE (\S+)@@\s*$")


def expand(text: str, seen: tuple = ()) -> str:
    out = []
    for line in text.splitlines():
        m = MARK.match(line)
        if not m:
            out.append(line)
            continue
        indent, rel = m.groups()
        if rel in seen:
            sys.exit(f"include loop: {rel}")
        body = expand((ROOT / rel).read_text(), seen + (rel,))
        out.extend((indent + l) if l.strip() else l for l in body.splitlines())
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    for src, dst in (("ai-gateway.yaml.in", "ai-gateway.yaml"), ("examples/chat-ui/chat-ui.yaml.in", "examples/chat-ui/chat-ui.yaml")):
        (ROOT / dst).write_text(expand((ROOT / src).read_text()))
        print("wrote", dst)
