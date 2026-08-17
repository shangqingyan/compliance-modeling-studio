import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from common import (
    CONFIG_DIR,
    ensure_dirs,
    get_data_root,
    get_path,
    load_json,
    load_yaml,
    now_iso,
    save_json,
    split_list,
    to_float,
    to_int,
    to_str,
)


def infer_format(source, requested):
    if requested and requested != "auto":
        return requested
    lower = source.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return "api"
    if lower.endswith(".csv"):
        return "csv"
    return "json"


def load_api_json(source, source_cfg):
    token_env = source_cfg.get("token_env") or "MODEL_PATTERN_API_TOKEN"
    token = os.environ.get(token_env, "")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(source, headers=headers)
    timeout = float(source_cfg.get("timeout_seconds", 30))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    time.sleep(1.0 / max(float(source_cfg.get("rate_limit_per_second", 1)), 0.1))
    return json.loads(payload)


def load_file_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def load_file_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def as_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("models", "data", "items", "records", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return []


def load_source(source, fmt, source_cfg):
    if fmt == "api":
        return as_records(load_api_json(source, source_cfg))
    if fmt == "csv":
        return load_file_csv(source)
    return as_records(load_file_json(source))


def normalize_metrics(raw_metrics, source_record, metric_map):
    metrics = {"train": {}, "test": {}, "cv": {}}
    if isinstance(raw_metrics, dict):
        for key, value in raw_metrics.items():
            if key in metrics and isinstance(value, dict):
                metrics[key].update(value)
                continue
            bucket = "test"
            metric_name = key
            if key.startswith("train_"):
                bucket = "train"
                metric_name = key[6:]
            elif key.startswith("test_"):
                bucket = "test"
                metric_name = key[5:]
            elif key.startswith("cv_"):
                bucket = "cv"
                metric_name = key[3:]
            number = to_float(value)
            metrics[bucket][metric_name] = number if number is not None else to_str(value)

    for metric_name, source_path in (metric_map or {}).items():
        value = get_path(source_record, source_path)
        if value is None and isinstance(source_path, str) and source_path in source_record:
            value = source_record[source_path]
        if value is None:
            continue
        number = to_float(value)
        bucket = "test"
        normalized_name = metric_name
        if metric_name.startswith("train_"):
            bucket = "train"
            normalized_name = metric_name[6:]
        elif metric_name.startswith("test_"):
            bucket = "test"
            normalized_name = metric_name[5:]
        elif metric_name.startswith("cv_"):
            bucket = "cv"
            normalized_name = metric_name[3:]
        metrics[bucket][normalized_name] = number if number is not None else to_str(value)
    return metrics


def coerce_mapping(value):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("{") or value.startswith("["):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
    if isinstance(value, dict):
        return value
    return value or {}


def normalize_record(source_record, field_map, metric_map, platform_name, source):
    canonical_source = {}
    for canonical_name, source_path in (field_map or {}).items():
        value = get_path(source_record, source_path)
        if value is None and isinstance(source_path, str) and source_path in source_record:
            value = source_record[source_path]
        if value is not None:
            canonical_source[canonical_name] = value

    for key, value in source_record.items():
        if key not in canonical_source and value is not None:
            canonical_source[key] = value

    raw_id = canonical_source.get("id")
    raw_source_id = canonical_source.get("source_id")
    for candidate in ("model_id", "source_id", "id"):
        if raw_source_id in (None, ""):
            raw_source_id = canonical_source.get(candidate)
    if raw_source_id in (None, ""):
        raw_source_id = raw_id
    if raw_id in (None, ""):
        raw_id = raw_source_id
    name = to_str(canonical_source.get("name"))
    if name == "":
        name = to_str(canonical_source.get("model_name"))
    if raw_source_id in (None, "") and name == "":
        raise ValueError("record is missing both source_id/id and name")

    raw_metrics = canonical_source.get("metrics")
    metrics = normalize_metrics(raw_metrics, source_record, metric_map)

    split = coerce_mapping(canonical_source.get("split"))
    hyperparameters = coerce_mapping(canonical_source.get("hyperparameters"))
    stability = coerce_mapping(canonical_source.get("stability"))

    return {
        "id": to_str(raw_id),
        "source_id": to_str(raw_source_id),
        "name": name,
        "platform": to_str(canonical_source.get("platform")) or platform_name,
        "objective": to_str(canonical_source.get("objective")),
        "target_variable": to_str(canonical_source.get("target_variable")),
        "dataset": to_str(canonical_source.get("dataset")),
        "features": split_list(canonical_source.get("features")),
        "algorithm": to_str(canonical_source.get("algorithm")),
        "hyperparameters": hyperparameters if isinstance(hyperparameters, dict) else {},
        "sample_size": to_int(canonical_source.get("sample_size")),
        "split": split if isinstance(split, dict) else {},
        "metrics": metrics,
        "stability": stability if isinstance(stability, dict) else {},
        "created_at": to_str(canonical_source.get("created_at")),
        "artifacts": split_list(canonical_source.get("artifacts")),
        "tags": split_list(canonical_source.get("tags")),
        "notes": to_str(canonical_source.get("notes")),
        "source": source,
        "imported_at": now_iso(),
    }


def upsert(registry, record):
    key = record.get("source_id") or record.get("id")
    for index, existing in enumerate(registry):
        existing_key = existing.get("source_id") or existing.get("id")
        if existing_key and existing_key == key:
            registry[index] = record
            return registry, False
    registry.append(record)
    return registry, True


def main():
    parser = argparse.ArgumentParser(description="Import model records from an authorized CSV/JSON file or API.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--format", choices=["auto", "csv", "json", "api"], default="auto")
    parser.add_argument("--mapping", default=str(CONFIG_DIR / "platform.yaml"))
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--commit", action="store_true", help="Write to registry; default is dry-run")
    args = parser.parse_args()

    fmt = infer_format(args.source, args.format)
    config = load_yaml(args.mapping)
    source_cfg = config.get("source", {})
    field_map = config.get("field_map", {})
    metric_map = config.get("metric_map", {})
    platform_name = str(config.get("platform", {}).get("name", "generic-online-modeling-platform"))

    raw_records = load_source(args.source, fmt, source_cfg)
    if not raw_records:
        print("[ERROR] no records found in source", file=sys.stderr)
        return 2

    normalized = []
    errors = []
    for index, raw in enumerate(raw_records):
        try:
            normalized.append(normalize_record(raw, field_map, metric_map, platform_name, args.source))
        except Exception as exc:
            errors.append({"index": index, "error": str(exc), "record": raw})

    payload = {
        "dry_run": not args.commit,
        "source": args.source,
        "format": fmt,
        "normalized_count": len(normalized),
        "error_count": len(errors),
        "records": normalized,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.commit:
        data_root = ensure_dirs(args.data_root)
        registry_path = data_root / "registry.json"
        registry = load_json(registry_path, [])
        added = 0
        updated = 0
        for record in normalized:
            registry, was_added = upsert(registry, record)
            if was_added:
                added += 1
            else:
                updated += 1
        save_json(registry_path, registry)
        snapshot = save_json(data_root / "snapshots" / f"import-{now_iso().replace(':', '-')}.json", payload)
        print(f"[OK] registry written: {registry_path}")
        print(f"[OK] snapshot written: {snapshot}")
        print(f"[OK] added={added} updated={updated}")

    if errors:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


