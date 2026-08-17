#!/usr/bin/env python3
"""Create a starter Codex skill directory with a safety-gated SKILL.md template.

Usage:
  python scaffold_skill.py --name <skill-name> --goal "<goal>" [--dest <skills-dir>] [--resources scripts,references,assets]
"""

import argparse
import os
import re
import sys
from pathlib import Path

MAX_NAME_LENGTH = 64
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

TEMPLATE = """---
name: {name}
description: [TODO: Explain what this skill does and when to use it. Include concrete triggers and contexts.]
---

# {title}

## Safety Gate

Before acting, screen the task against legality, network and social security safety, and human-values alignment. If the task is prohibited or harmful, stop and decline.

## Overview

{overview}

## Workflow

1. [TODO: first step]
2. [TODO: next step]

## Resources

[TODO: list only files actually created under scripts/, references/, or assets/.]
"""


def normalize_name(raw):
    name = raw.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return name


def default_dest():
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return os.path.join(home, "skills")


def title_case(name):
    return " ".join(word.capitalize() for word in name.split("-") if word)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Skill name")
    parser.add_argument("--goal", default="", help="One-sentence goal to prefill in the overview")
    parser.add_argument("--dest", default=None, help="Destination skills directory")
    parser.add_argument("--resources", default="", help="Comma-separated: scripts,references,assets")
    args = parser.parse_args()

    name = normalize_name(args.name)
    if not NAME_RE.match(name) or len(name) > MAX_NAME_LENGTH:
        print(
            "[ERROR] Invalid skill name. Use lowercase letters, digits, and single "
            f"hyphens, max {MAX_NAME_LENGTH} chars. Got: {name!r}"
        )
        return 1

    dest = Path(args.dest or default_dest())
    skill_dir = dest / name
    if skill_dir.exists():
        print(f"[ERROR] Destination already exists: {skill_dir}")
        return 1

    resources = {r for r in args.resources.split(",") if r}
    unknown = resources - ALLOWED_RESOURCES
    if unknown:
        print(f"[ERROR] Unknown resources: {', '.join(sorted(unknown))}. Allowed: scripts,references,assets")
        return 1

    skill_dir.mkdir(parents=True, exist_ok=False)
    for res in sorted(resources):
        (skill_dir / res).mkdir(exist_ok=True)

    overview = "[TODO: 1-2 sentences on what this skill enables.]"
    if args.goal:
        overview = f"Enable: {args.goal}"

    content = TEMPLATE.format(name=name, title=title_case(name), overview=overview)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    print(f"[OK] Created {skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
