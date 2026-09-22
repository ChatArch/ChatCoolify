#!/usr/bin/env python3
"""Reject environment-specific deployment details from public documentation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "DEVELOP.md",
    *sorted((ROOT / "docs").glob("*.md")),
]
FORBIDDEN = (
    "coolify.public.wzhecnu.cn",
    "coolify.local.wzhecnu.cn",
    "/home/",
    "/Users/",
    "zhihong.oray",
    "recall.cube",
    "rexwzh@",
)

violations: list[str] = []
for path in PUBLIC_FILES:
    text = path.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        if needle in text:
            violations.append(f"{path.relative_to(ROOT)}:{needle}")

if violations:
    raise SystemExit("Environment-specific public documentation: " + ", ".join(violations))
print("public-doc-sanitization=passed")
