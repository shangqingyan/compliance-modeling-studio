#!/usr/bin/env python3
"""Read-only static pre-scan for a project directory against hard-block term lists.

Usage:
  python audit_project.py <project_dir> [--skip PATH]...

Exit codes:
  0  PASS or REVIEW (no non-negated hard-block terms found)
  1  invalid input or missing project directory
  2  one or more non-negated hard-block terms found
"""

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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

TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv",
    ".html", ".htm", ".css", ".scss", ".less", ".xml", ".sql", ".sh", ".bash",
    ".ps1", ".bat", ".cmd", ".r", ".m", ".ipynb", ".java", ".go", ".rs", ".c",
    ".h", ".cpp", ".hpp", ".cc", ".cs", ".rb", ".php", ".swift", ".kt", ".kts",
    ".proto", ".graphql", ".vue", ".svelte",
}

TEXT_BASENAMES = {
    "AGENTS.md", "AGENTS.override.md", "SKILL.md", "Dockerfile", "Makefile",
    "LICENSE", "NOTICE", "README", "CONTRIBUTING", "CODEOWNERS",
}

SKIP_DIR_PARTS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
}

MAX_FILE_BYTES = 2 * 1024 * 1024


def is_text_path(path):
    if path.name in TEXT_BASENAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


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


def read_text_safe(path):
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def collect_text_files(root, skip_paths):
    root = root.resolve()
    skip_resolved = {Path(p).resolve() for p in skip_paths}
    files = []
    for path in sorted(root.rglob("*")):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        if path in skip_resolved or path.resolve() in skip_resolved:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        if not is_text_path(path):
            continue
        files.append(path)
    return files


def main(argv):
    if len(argv) < 2:
        print("Usage: python audit_project.py <project_dir> [--skip PATH]...")
        return 1

    project_dir = Path(argv[1])
    skip_paths = [Path(__file__).resolve()]
    if "--skip" in argv:
        idx = argv.index("--skip")
        skip_paths = [Path(p) for p in argv[idx + 1:]]

    if not project_dir.exists() or not project_dir.is_dir():
        print(f"[ERROR] project directory not found: {project_dir}")
        return 1

    files = collect_text_files(project_dir, skip_paths)
    print(f"[INFO] Auditing: {project_dir}")
    print(f"[INFO] text files scanned: {len(files)}")

    all_hits = []
    for file in files:
        text = read_text_safe(file)
        if text is None:
            print(f"  - [SKIP] binary or undecodable: {file.relative_to(project_dir)}")
            continue
        rel = str(file.relative_to(project_dir))
        all_hits.extend(scan_text(text, rel, include_block=True))

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
