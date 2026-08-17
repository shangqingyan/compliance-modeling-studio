#!/usr/bin/env python3
"""Periodic skill review: score, rank, prune, and pin Codex skills."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - fallback parser below
    yaml = None


DEFAULTS = {
    "lambda_rec": 0.25,
    "w_cov": 0.35,
    "w_uniq": 0.35,
    "w_rec": 0.20,
    "w_crit": 0.10,
    "b_uniq": 0.60,
    "b_cov": 0.40,
    "alpha": 0.60,
    "rho": 1.0,
    "theta_s": 0.20,
    "theta_a": 0.25,
    "theta_pin": 0.25,
    "theta_pin_s": 0.50,
    "r_pin": 2,
    "neutral_coverage": 0.50,
}

ABLATION_MAP = {
    "none": 0.00,
    "low": 0.25,
    "medium": 0.60,
    "high": 0.95,
}


def clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def tokenize(text: str) -> set[str]:
    text = text.lower()
    latin = re.findall(r"[a-z0-9_]+", text)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    cjk_bigrams = {a + b for a, b in zip(cjk_chars, cjk_chars[1:])}
    return set(latin) | set(cjk_chars) | cjk_bigrams


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def read_frontmatter_text(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not match:
        return None
    return match.group(1)


def read_skill_metadata(skill_dir: Path) -> dict | None:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8")
    frontmatter_text = read_frontmatter_text(text)
    name = skill_dir.name
    description = ""
    if frontmatter_text:
        if yaml is not None:
            try:
                frontmatter = yaml.safe_load(frontmatter_text)
                if isinstance(frontmatter, dict):
                    name = frontmatter.get("name") or name
                    raw_description = frontmatter.get("description") or ""
                    description = raw_description if isinstance(raw_description, str) else json.dumps(raw_description, ensure_ascii=False)
            except Exception:
                pass
        if not description:
            name_match = re.search(r"^name:\s*[\"']?([^\"'\n]+)[\"']?\s*$", frontmatter_text, re.MULTILINE)
            desc_match = re.search(r"^description:\s*[\"']?(.+?)[\"']?\s*$", frontmatter_text, re.MULTILINE)
            if name_match:
                name = name_match.group(1).strip()
            if desc_match:
                description = desc_match.group(1).strip()
    return {
        "id": str(name).strip() or skill_dir.name,
        "name": str(name).strip() or skill_dir.name,
        "description": description,
        "path": str(skill_dir.resolve()),
    }


def scan_skills(skills_dir: Path) -> list[dict]:
    if not skills_dir.exists():
        raise FileNotFoundError(f"Skills directory not found: {skills_dir}")
    skills = []
    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        meta = read_skill_metadata(child)
        if meta:
            skills.append(meta)
    return skills


def load_json(path: Path | None, default=None):
    if path is None or not Path(path).exists():
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON file {path}: {exc}") from exc


def merge_config(base: dict, updates: dict | None) -> dict:
    if not updates:
        return dict(base)
    merged = dict(base)
    merged.update({k: v for k, v in updates.items() if k in base})
    return merged


def merge_inventory(skills: list[dict], inventory: dict | None) -> list[dict]:
    if not inventory:
        return skills
    by_id = {}
    for item in inventory.get("skills", []):
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    for skill in skills:
        ev = by_id.get(skill["id"], {})
        if not ev:
            continue
        for key in (
            "task_count",
            "used_cycles_ago",
            "critical",
            "importance",
            "ablation_impact",
            "pinned",
            "delete_candidate",
        ):
            if key in ev:
                skill[key] = ev[key]
    return skills


def compute_unique_scores(skills: list[dict]) -> list[float]:
    tokens = [tokenize(s.get("description", "")) for s in skills]
    scores = []
    for i in range(len(skills)):
        if len(skills) <= 1:
            scores.append(1.0)
            continue
        max_sim = 0.0
        for j in range(len(skills)):
            if i == j:
                continue
            max_sim = max(max_sim, jaccard(tokens[i], tokens[j]))
        scores.append(1.0 - max_sim)
    return scores


def status_for(skill: dict, pinned: bool, cfg: dict, importance: float, ablation: float) -> str:
    if pinned:
        return "PINNED"
    if skill.get("delete_candidate"):
        return "DELETE_CANDIDATE"
    if importance < cfg["theta_s"] and ablation < cfg["theta_a"]:
        return "DELETE_CANDIDATE"
    return "KEEP"


def run_review(skills_dir: Path, inventory: dict | None, state_path: Path, cfg: dict) -> dict:
    state = load_json(state_path, default={"version": 1, "cycle": 0, "skills": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "cycle": 0, "skills": {}}
    state.setdefault("skills", {})
    previous_cycle = int(state.get("cycle", 0))
    cycle = previous_cycle + 1

    skills = merge_inventory(scan_skills(skills_dir), inventory)
    if not skills:
        raise ValueError("No skills found. Check --skills-dir and ensure it contains SKILL.md folders.")

    unique_scores = compute_unique_scores(skills)
    total_tasks = sum(int(s.get("task_count", 0) or 0) for s in skills)

    active = {}
    results = []

    for idx, skill in enumerate(skills):
        skill_id = skill["id"]
        prev = state["skills"].get(skill_id, {})
        prev_pinned = bool(prev.get("pinned")) or bool(skill.get("pinned"))
        task_count = int(skill.get("task_count", 0) or 0)
        coverage = (task_count / total_tasks) if total_tasks > 0 else float(cfg["neutral_coverage"])
        coverage = clip(coverage)

        used_cycles_ago = int(skill.get("used_cycles_ago", 0) or 0)
        recency = math.exp(-float(cfg["lambda_rec"]) * used_cycles_ago)
        critical = 1.0 if skill.get("critical") else 0.0

        explicit_importance = skill.get("importance")
        if explicit_importance is not None:
            importance = clip(float(explicit_importance))
        else:
            importance = clip(
                float(cfg["w_cov"]) * coverage
                + float(cfg["w_uniq"]) * unique_scores[idx]
                + float(cfg["w_rec"]) * recency
                + float(cfg["w_crit"]) * critical
            )

        explicit_ablation = skill.get("ablation_impact")
        if explicit_ablation is not None:
            key = str(explicit_ablation).strip().lower()
            if key in ABLATION_MAP:
                ablation = ABLATION_MAP[key]
            else:
                ablation = clip(float(explicit_ablation))
        else:
            ablation = clip(
                float(cfg["b_uniq"]) * unique_scores[idx]
                + float(cfg["b_cov"]) * coverage
            )

        status = status_for(skill, prev_pinned, cfg, importance, ablation)

        prev_cumulative = float(prev.get("cumulative_weight", 0.0) or 0.0)
        if status != "DELETE_CANDIDATE":
            delta = float(cfg["alpha"]) * importance + (1.0 - float(cfg["alpha"])) * ablation
            cumulative = float(cfg["rho"]) * prev_cumulative + delta
            active[skill_id] = cumulative
        else:
            cumulative = prev_cumulative

        high_rounds = int(prev.get("high_rounds", 0) or 0)
        results.append(
            {
                "id": skill_id,
                "name": skill.get("name", skill_id),
                "path": skill.get("path", ""),
                "importance": round(importance, 6),
                "ablation": round(ablation, 6),
                "cumulative_weight": round(cumulative, 6),
                "normalized_weight": 0.0,
                "status": status,
                "pinned": prev_pinned,
                "high_rounds": high_rounds,
            }
        )

    total_weight = sum(active.values())
    if total_weight <= 0:
        total_weight = 1.0

    newly_pinned = []
    for result in results:
        if result["status"] == "DELETE_CANDIDATE":
            continue
        result["normalized_weight"] = active[result["id"]] / total_weight
        norm = result["normalized_weight"]
        importance = result["importance"]
        if result["pinned"]:
            continue
        if norm >= float(cfg["theta_pin"]) and importance >= float(cfg["theta_pin_s"]):
            result["high_rounds"] += 1
        else:
            result["high_rounds"] = 0
        if result["high_rounds"] >= int(cfg["r_pin"]):
            result["pinned"] = True
            result["status"] = "PINNED"
            newly_pinned.append(result["id"])

    new_state_skills = {}
    for result in results:
        skill_id = result["id"]
        new_state_skills[skill_id] = {
            "cumulative_weight": result["cumulative_weight"],
            "normalized_weight": result["normalized_weight"],
            "pinned": result["pinned"],
            "high_rounds": result["high_rounds"],
            "last_importance": result["importance"],
            "last_ablation": result["ablation"],
        }

    new_state = {
        "version": 1,
        "cycle": cycle,
        "skills": new_state_skills,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")

    results.sort(key=lambda r: (r["pinned"], r["normalized_weight"]), reverse=True)
    for rank, result in enumerate(results, 1):
        result["rank"] = rank

    return {
        "cycle": cycle,
        "total_skills": len(results),
        "keep_count": sum(1 for r in results if r["status"] == "KEEP"),
        "pinned_count": sum(1 for r in results if r["pinned"]),
        "delete_candidate_count": sum(1 for r in results if r["status"] == "DELETE_CANDIDATE"),
        "newly_pinned": newly_pinned,
        "skills": results,
    }


def render_markdown(report: dict, scanned_dir: str, state_path: str) -> str:
    lines = [
        f"# Skill Review Report - Cycle {report['cycle']}",
        "",
        f"- Scanned directory: `{scanned_dir}`",
        f"- State file: `{state_path}`",
        f"- Total skills: {report['total_skills']}",
        f"- Keep: {report['keep_count']}",
        f"- Pinned: {report['pinned_count']}",
        f"- Delete candidates: {report['delete_candidate_count']}",
        "",
    ]
    if report["newly_pinned"]:
        lines.append(f"- Newly pinned: {', '.join(report['newly_pinned'])}")
        lines.append("")
    lines.extend(
        [
            "## Ranking",
            "",
            "| Rank | Skill | Normalized weight | Importance | Ablation | Status |",
            "| ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in report["skills"]:
        lines.append(
            f"| {item['rank']} | {item['id']} | {item['normalized_weight']:.4f} "
            f"| {item['importance']:.4f} | {item['ablation']:.4f} | {item['status']} |"
        )
    lines.append("")
    lines.append("## Deletion candidates")
    candidates = [r for r in report["skills"] if r["status"] == "DELETE_CANDIDATE"]
    if candidates:
        for item in candidates:
            lines.append(f"- `{item['id']}` (importance={item['importance']:.4f}, ablation={item['ablation']:.4f})")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("> Deletion candidates are recommendations only. Run with `--apply-delete` and an explicit `--skill-ids` list after human confirmation.")
    return "\n".join(lines) + "\n"


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def apply_deletions(report: dict, skills_dir: Path, skill_ids: list[str], backup_dir: Path) -> list[dict]:
    by_id = {r["id"]: r for r in report["skills"]}
    root = skills_dir.resolve()
    backup_root = backup_dir.resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / timestamp
    destination.mkdir(parents=True, exist_ok=False)
    log = []

    for skill_id in skill_ids:
        item = by_id.get(skill_id)
        if item is None:
            log.append({"id": skill_id, "status": "NOT_FOUND"})
            continue
        if skill_id == "skill-review":
            log.append({"id": skill_id, "status": "PROTECTED_SELF"})
            continue
        if item["pinned"] or item["status"] == "PINNED":
            log.append({"id": skill_id, "status": "PINNED_SKIPPED"})
            continue
        if item["status"] != "DELETE_CANDIDATE":
            log.append({"id": skill_id, "status": "NOT_CANDIDATE_SKIPPED"})
            continue
        skill_path = Path(item["path"]).resolve()
        if not is_relative_to(skill_path, root):
            log.append({"id": skill_id, "status": "OUTSIDE_ROOT_SKIPPED", "path": str(skill_path)})
            continue
        if skill_path.name != skill_id:
            log.append({"id": skill_id, "status": "NAME_MISMATCH_SKIPPED", "path": str(skill_path)})
            continue
        target = destination / skill_path.name
        shutil.move(str(skill_path), str(target))
        log.append({"id": skill_id, "status": "MOVED_TO_BACKUP", "backup": str(target)})

    return log


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review, rank, prune, and pin Codex skills.")
    parser.add_argument("--skills-dir", required=True, help="Directory containing installed skills.")
    parser.add_argument("--state", default="skill-review-state.json", help="Path to persistent JSON state.")
    parser.add_argument("--report", default="skill-review-report.md", help="Path for Markdown or .json report.")
    parser.add_argument("--inventory", help="Optional JSON evidence file.")
    parser.add_argument("--config", help="Optional JSON config overrides.")
    parser.add_argument("--apply-delete", action="store_true", help="Move confirmed deletion candidates to backup.")
    parser.add_argument("--skill-ids", default="", help="Comma-separated skill ids to delete when --apply-delete is set.")
    parser.add_argument("--backup-dir", default="_skill-review-backup", help="Backup directory for moved skills.")
    args = parser.parse_args(argv)

    cfg = merge_config(DEFAULTS, load_json(Path(args.config) if args.config else None, default={}))
    inventory = load_json(Path(args.inventory) if args.inventory else None, default={"skills": []})

    report = run_review(Path(args.skills_dir), inventory, Path(args.state), cfg)

    if args.report.lower().endswith(".json"):
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            render_markdown(report, str(Path(args.skills_dir).resolve()), str(Path(args.state).resolve())),
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.apply_delete:
        skill_ids = [x.strip() for x in args.skill_ids.split(",") if x.strip()]
        if not skill_ids:
            print("ERROR: --apply-delete requires --skill-ids.", file=sys.stderr)
            return 2
        log = apply_deletions(report, Path(args.skills_dir), skill_ids, Path(args.backup_dir))
        print("Deletion log:")
        print(json.dumps(log, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())