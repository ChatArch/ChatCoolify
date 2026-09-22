#!/usr/bin/env python3
"""Fail when repository text appears to contain a real Coolify API token."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "build", "dist", "site", "__pycache__", ".pytest_cache", "chatcoolify.egg-info"}
TOKEN_PATTERNS = [
    re.compile(r"(?:Bearer\s+|COOLIFY_API_TOKEN\s*=\s*[\"']?)(\d+\|[A-Za-z0-9_-]{20,})"),
]

violations: list[str] = []
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in SKIP for part in path.parts):
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        violations.append(str(path.relative_to(ROOT)))

if violations:
    raise SystemExit("Potential Coolify token found in: " + ", ".join(violations))
print("secret-scan=passed")
