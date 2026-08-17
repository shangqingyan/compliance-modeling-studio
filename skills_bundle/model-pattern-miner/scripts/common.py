from pathlib import Path
import datetime
import json
import os
import re

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency guard
    yaml = None


SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = SKILL_DIR / "config"


def get_data_root():
    env = os.environ.get("MODEL_PATTERN_DATA_DIR")
    if env:
        return Path(env)
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "model-patterns"
    return Path.home() / ".codex" / "model-patterns"


def ensure_dirs(root=None):
    root = Path(root) if root else get_data_root()
    for sub in ("snapshots", "reports"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def load_yaml(path):
    if yaml is None:
        raise RuntimeError("PyYAML is required; install it before using this skill")
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_path(data, path):
    if path in (None, ""):
        return None
    if not isinstance(path, str):
        parts = [str(p) for p in path]
    else:
        parts = [p for p in path.split(".") if p != ""]
    cur = data
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"nan", "null", "none", "na", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value):
    number = to_float(value)
    if number is None:
        return None
    return int(number)


def to_str(value):
    if value is None:
        return ""
    return str(value)


def split_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, (dict, int, float)):
        return [str(value)]
    return [item.strip() for item in re.split(r"[,;|]", str(value)) if item.strip()]

