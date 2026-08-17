#!/usr/bin/env python3
"""Read-only static pre-scan for a Codex skill directory.

Usage:
  python audit_skill.py <skill_dir>

Exit codes:
  0  no non-negated hard-block terms in SKILL.md
  1  invalid input or missing SKILL.md
  2  one or more non-negated hard-block terms found in SKILL.md
"""

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Action-oriented phrases that indicate an instruction to do harm. Bare policy
# nouns such as "malware" or "phishing" are treated as REVIEW, not BLOCK.
BLOCK_TERMS = [
    "create malware", "write malware", "develop malware", "deploy malware", "make malware",
    "build a botnet", "create a botnet",
    "launch a denial-of-service", "launch denial-of-service", "run a denial-of-service",
    "steal credentials", "steal passwords", "steal data", "exfiltrate credentials", "exfiltrate data",
    "create a phishing page", "make a phishing page", "phishing page",
    "weaponize vulnerability", "weaponize a vulnerability",
    "bypass authentication", "bypass safety", "jailbreak the model", "jailbreak this model",
    "non-consensual intimate imagery", "child sexual abuse material", "produce child sexual abuse",
    "doxx someone", "stalk someone", "harass someone",
    "create disinformation at scale", "spread disinformation at scale",
    "编写恶意软件", "制作钓鱼页面", "创建钓鱼页面", "窃取凭据", "窃取密码", "外泄数据", "窃取数据",
    "武器化漏洞", "绕过认证", "绕过安全系统", "越狱模型",
    "制作非自愿私密影像", "制作儿童性虐待材料",
    "人肉搜索某人", "骚扰某人", "跟踪某人",
    "制造大规模虚假信息", "传播大规模虚假信息", "实施协同虚假行为",
]

REVIEW_TERMS = [
    "malware", "ransomware", "botnet", "denial-of-service", "unauthorized access",
    "credential theft", "phishing", "social engineering", "data exfiltration",
    "safety-system bypass", "jailbreak", "disinformation", "surveillance",
    "web scraping", "scrape", "crawler", "automation", "personal data",
    "biometric", "intellectual property", "account creation", "rate limit",
    "恶意软件", "勒索软件", "僵尸网络", "拒绝服务攻击", "未授权访问", "凭据窃取",
    "钓鱼", "社会工程", "数据外泄", "安全系统绕过", "越狱", "虚假信息", "监控",
    "网页抓取", "爬虫", "自动化", "个人信息", "生物识别", "知识产权", "账号创建", "限速",
]

NEGATION_MARKERS = [
    "do not", "don't", "never", "avoid", "decline", "prohibit", "prohibited",
    "forbidden", "prevent", "illegal", "不得", "禁止", "不要", "避免", "拒绝", "防止",
]


def parse_frontmatter(text):
    """Return (metadata_dict, issues)."""
    if not text.startswith("---"):
        return {}, ["SKILL.md does not start with YAML frontmatter"]
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}, ["invalid frontmatter format"]
    raw = match.group(1)
    meta = {}
    for line in raw.splitlines():
        pair = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if pair:
            key = pair.group(1)
            value = pair.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            meta[key] = value
    return meta, []


def validate_metadata(meta):
    issues = []
    if "name" not in meta:
        issues.append("missing 'name'")
    else:
        name = str(meta["name"]).strip()
        if not NAME_RE.match(name) or len(name) > MAX_NAME_LEN:
            issues.append(f"invalid name: {name!r}")
    if "description" not in meta:
        issues.append("missing 'description'")
    else:
        desc = str(meta["description"]).strip()
        if len(desc) > MAX_DESC_LEN:
            issues.append(f"description too long ({len(desc)})")
        if "<" in desc or ">" in desc:
            issues.append("description contains angle brackets")
    return issues


def is_negated(text, start):
    before = text[max(0, start - 100):start].lower()
    return any(marker in before for marker in NEGATION_MARKERS)


def scan_text(text, path, include_block=True):
    hits = []
    lowered = text.lower()
    if include_block:
        for term in BLOCK_TERMS:
            needle = term.lower()
            for match in re.finditer(re.escape(needle), lowered):
                hits.append((path, term, "BLOCK", is_negated(text, match.start())))
    for term in REVIEW_TERMS:
        needle = term.lower()
        for match in re.finditer(re.escape(needle), lowered):
            hits.append((path, term, "REVIEW", is_negated(text, match.start())))
    return hits


def dedupe(hits):
    seen = set()
    result = []
    for hit in hits:
        key = (hit[0], hit[1], hit[2], hit[3])
        if key not in seen:
            seen.add(key)
            result.append(hit)
    return result


def main(argv):
    if len(argv) != 2:
        print("Usage: python audit_skill.py <skill_dir>")
        return 1

    skill_dir = Path(argv[1])
    if not skill_dir.exists() or not skill_dir.is_dir():
        print(f"[ERROR] skill directory not found: {skill_dir}")
        return 1

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"[ERROR] SKILL.md not found: {skill_md}")
        return 1

    text = skill_md.read_text(encoding="utf-8")
    meta, parse_issues = parse_frontmatter(text)
    issues = parse_issues + validate_metadata(meta)

    print(f"[INFO] Auditing: {skill_dir}")
    if issues:
        for issue in issues:
            print(f"[WARN] metadata: {issue}")
    else:
        print("[INFO] metadata: valid")

    resources = []
    for sub in ("scripts", "references", "assets"):
        sub_dir = skill_dir / sub
        if sub_dir.is_dir():
            for file in sorted(p for p in sub_dir.rglob("*") if p.is_file()):
                resources.append(str(file.relative_to(skill_dir)))
    print(f"[INFO] resources: {len(resources)}")
    for resource in resources:
        print(f"  - {resource}")

    all_hits = scan_text(text, "SKILL.md", include_block=True)
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        for file in sorted(ref_dir.glob("*.md")):
            ref_text = file.read_text(encoding="utf-8")
            all_hits.extend(scan_text(ref_text, str(file.relative_to(skill_dir)), include_block=False))

    all_hits = dedupe(all_hits)
    block_hits = [h for h in all_hits if h[2] == "BLOCK" and not h[3]]
    review_hits = [h for h in all_hits if h[2] == "REVIEW" and not h[3]]
    negated_hits = [h for h in all_hits if h[3]]

    for path, term, level, _negated in negated_hits:
        print(f"[SCAN] negated {level.lower()} term {term!r} in {path}")
    for path, term, level, _negated in review_hits:
        print(f"[SCAN] review term {term!r} in {path}")
    for path, term, level, _negated in block_hits:
        print(f"[SCAN] block term {term!r} in {path}")

    if block_hits:
        print("[VERDICT] BLOCK")
        return 2
    if review_hits:
        print("[VERDICT] REVIEW")
    else:
        print("[VERDICT] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))