---
name: skill-review
description: Periodically audit, rank, prune, and pin installed Codex skills using an ablation-based importance model with cumulative normalized weights. Use when the user asks to 梳理、归纳、复盘、清理、删除、排序、加权、固定 skills, to review installed skills, to decide whether removing a skill would hurt task completion, or to maintain a weighted skill memory across review cycles.
---

# Skill Review

## Overview

Use this skill to review installed Codex skills on a recurring basis, decide which skills are worth keeping, and produce a stable weighted ranking that carries over between review cycles. The default behavior is analysis only; never delete a skill without explicit user confirmation.

## Workflow

1. **Scan** the target skills directory for immediate child directories containing `SKILL.md`.
2. **Load previous state** (`cumulative_weight`, `normalized_weight`, `pinned`) if it exists. Pinned skills are re-inspected but never proposed for deletion.
3. **Score each non-pinned skill** with two quantities:
   - `importance S` in `[0,1]`: task coverage, uniqueness, recency, and explicit critical flags.
   - `ablation_impact A` in `[0,1]`: estimated harm from removing the skill.
4. **Classify** each skill:
   - `PINNED`: permanently retained; skip deletion checks.
   - `DELETE_CANDIDATE`: not pinned, low `S`, and low `A`.
   - `KEEP`: everything else.
5. **Accumulate weights** for kept and pinned skills:
   - New cumulative weight = previous cumulative weight + weighted importance/ablation score.
6. **Normalize** cumulative weights across all kept and pinned skills so they sum to `1`.
7. **Pin** a skill when its normalized weight and consecutive high-importance rounds exceed thresholds.
8. **Write state and report**, ordered by normalized weight descending. Present deletion candidates for human confirmation; do not auto-delete.

## Run the script

```powershell
python scripts/review.py --skills-dir C:\Users\OseasyVM\.codex\skills --state skill-review-state.json --report skill-review-report.md
```

Optional evidence and thresholds:

```powershell
python scripts/review.py --skills-dir C:\Users\OseasyVM\.codex\skills --inventory evidence.json --state skill-review-state.json --report skill-review-report.md
```

Deletion is available only with an explicit whitelist and backup:

```powershell
python scripts/review.py --skills-dir C:\Users\OseasyVM\.codex\skills --state skill-review-state.json --apply-delete --skill-ids skill-a,skill-b --backup-dir _skill-review-backup
```

Use `python scripts/review.py --help` for all options.

## Inventory evidence format

`--inventory` accepts JSON:

```json
{
  "skills": [
    {
      "id": "example-skill",
      "task_count": 12,
      "used_cycles_ago": 1,
      "critical": false,
      "importance": null,
      "ablation_impact": null
    }
  ]
}
```

- `task_count`: number of recent tasks that depend on the skill.
- `used_cycles_ago`: cycles since the skill was last used.
- `critical`: true for skills that must never be auto-removed.
- `importance`: optional manual override in `[0,1]`; use sparingly.
- `ablation_impact`: optional label `none`, `low`, `medium`, or `high`.

## Safety rules

- Dry-run is the default. Actual deletion requires `--apply-delete` plus an explicit `--skill-ids` list.
- Never delete pinned skills, `skill-review` itself, or paths outside the scanned skills directory.
- Back up moved skills before deletion and record the backup path in the report.
- Before any destructive action, re-run the project compliance skill and confirm the path is inside the intended skills directory.
- Treat all deletion candidates as recommendations until a human approves them.

## Reference

See `references/model.md` for the full mathematical model and threshold defaults.