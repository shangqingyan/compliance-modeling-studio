---
name: model-pattern-miner
description: Record, normalize, summarize, and mine reusable patterns from excellent predictive models created on an online modeling platform; recommend patterns for new modeling goals and maintain user preferences. Use when the user asks to register/coordinate/summarize past models, identify excellent models by configurable metrics such as test R2 at least 0.9, discover general modeling patterns, analyze when and why a pattern applies, or recommend modeling approaches. Do not use for generating or training new models.
---

# Model Pattern Miner

## Safety Gate

Run this gate before any file read/write or platform access.

- Use only user-authorized exported files or the official API. Do not scrape, crawl, or bypass the platform's authentication or terms of service.
- Do not collect personal data. Store only model metadata needed for registry, patterns, and recommendations; anonymize or omit any personal identifiers.
- Respect rate limits, robots rules, and applicable privacy law.
- If a request is illegal, harmful, or uncertain, stop and ask the user for legitimate scope before continuing.

## Overview

Maintain a persistent, configurable registry of predictive models created on an online modeling platform, classify each model against configurable excellence thresholds, and turn the excellent subset into reusable patterns. Output is record, summarize, recommend, and preference only. Never train or generate a new model from this skill.

## Data And Config Locations

- Skill folder: `C:\Users\OseasyVM\.codex\skills\model-pattern-miner`
- Data root default: `C:\Users\OseasyVM\.codex\model-patterns`; override with environment variable `MODEL_PATTERN_DATA_DIR`.
- Data files: `registry.json`, `patterns.json`, `preferences.json`, `snapshots/`, `reports/`.
- Platform adapter: `config/platform.yaml`.
- Excellence thresholds: `config/thresholds.yaml`.
- Canonical data contract: `references/schema.md`.

## Workflow

1. Run the Safety Gate above and the project compliance skill before creating or updating files.
2. Search for an existing skill with `find-skills` before duplicating a registry/pattern-mining skill.
3. Inspect `config/platform.yaml`; fill `endpoint`, `token_env`, and `field_map` only when the user authorizes a real platform connection.
4. Import with dry-run first:
   `python "C:\Users\OseasyVM\.codex\skills\model-pattern-miner\scripts\ingest.py" --source <file-or-url> --format csv|json|api`
   Review the normalized records. Then commit:
   `python "C:\Users\OseasyVM\.codex\skills\model-pattern-miner\scripts\ingest.py" --source <file-or-url> --commit`
5. Apply excellence rules:
   `python "C:\Users\OseasyVM\.codex\skills\model-pattern-miner\scripts\analyze.py"`
   This writes `evaluation` into `registry.json`, creates `excellent_models.json`, `patterns.json`, and `reports/`.
6. For a new modeling goal, recommend only patterns:
   `python "C:\Users\OseasyVM\.codex\skills\model-pattern-miner\scripts\recommend.py" --goal "..." --target-variable "..." --dataset "..." --sample-size 1000`
7. After the user accepts or rejects a recommendation, record the preference in `preferences.json` using `vote: 1` for useful or `vote: -1` for not useful, then rerun recommendation so the preference weight is used.
8. Keep every generated pattern evidence-based. Each pattern must state `applies_when`, `does_not_apply_when`, `rationale`, and `risks`.

## Commands

- Import: `scripts/ingest.py --source <file|url> [--format csv|json|api|auto] [--mapping config/platform.yaml] [--commit]`
- Analyze: `scripts/analyze.py [--registry <path>] [--thresholds config/thresholds.yaml] [--data-root <path>]`
- Recommend: `scripts/recommend.py --goal <text> [--target-variable <text>] [--dataset <text>] [--sample-size <n>] [--top-k <n>]`
- Validate skill: `python "C:\Users\OseasyVM\.codex\skills\.system\skill-creator\scripts\quick_validate.py" "C:\Users\OseasyVM\.codex\skills\model-pattern-miner"`

## Compliance Output

After each run, report the fixed conclusion format: conclusion (allowed / needs safeguards / revise-and-review / prohibited), risk level (low / medium / high / critical), findings, basis, required changes, alternatives, and escalation decision.

## Resources

- `references/schema.md`: canonical record, pattern, and preference schemas, plus field-mapping examples.
- `scripts/ingest.py`: authorized CSV/JSON/API import and normalization.
- `scripts/analyze.py`: excellence classification and pattern mining.
- `scripts/recommend.py`: pattern recommendation with preference weighting.
- `config/platform.yaml`: platform source and field mapping template.
- `config/thresholds.yaml`: excellence thresholds and analysis settings.

