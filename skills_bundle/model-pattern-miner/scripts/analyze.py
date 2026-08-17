import argparse
import json
import statistics
from pathlib import Path

from common import (
    CONFIG_DIR,
    ensure_dirs,
    load_json,
    load_yaml,
    now_iso,
    save_json,
    to_float,
)


def metric_number(record, bucket, name):
    return to_float(record.get("metrics", {}).get(bucket, {}).get(name))


def evaluate(record, thresholds):
    excellent_cfg = thresholds.get("excellent", {})
    test_r2_min = to_float(excellent_cfg.get("test_r2", {}).get("min", 0.90))
    if test_r2_min is None:
        test_r2_min = 0.90

    test_r2 = metric_number(record, "test", "r2")
    if test_r2 is None:
        return {"status": "incomplete", "warnings": []}

    warnings = []
    train_r2 = metric_number(record, "train", "r2")
    if train_r2 is not None:
        max_gap = to_float(excellent_cfg.get("max_overfit_gap"))
        if max_gap is not None and (train_r2 - test_r2) > max_gap:
            warnings.append(f"train-test R2 gap {train_r2 - test_r2:.4f} exceeds {max_gap}")

    sample_size = to_float(record.get("sample_size"))
    min_sample = to_float(excellent_cfg.get("min_sample_size"))
    if min_sample is not None and sample_size is not None and sample_size < min_sample:
        warnings.append(f"sample_size {sample_size:.0f} below {min_sample:.0f}")

    test_rmse = metric_number(record, "test", "rmse")
    max_rmse = to_float(excellent_cfg.get("test_rmse", {}).get("max"))
    if max_rmse is not None and test_rmse is not None and test_rmse > max_rmse:
        warnings.append(f"test RMSE {test_rmse:.4f} exceeds {max_rmse}")

    test_mae = metric_number(record, "test", "mae")
    max_mae = to_float(excellent_cfg.get("test_mae", {}).get("max"))
    if max_mae is not None and test_mae is not None and test_mae > max_mae:
        warnings.append(f"test MAE {test_mae:.4f} exceeds {max_mae}")

    cv_r2_mean = metric_number(record, "cv", "r2_mean")
    cv_r2_min = to_float(excellent_cfg.get("cv_r2_min"))
    if cv_r2_min is not None and cv_r2_mean is not None and cv_r2_mean < cv_r2_min:
        warnings.append(f"CV R2 mean {cv_r2_mean:.4f} below {cv_r2_min}")

    cv_r2_std = metric_number(record, "cv", "r2_std")
    cv_r2_std_max = to_float(excellent_cfg.get("cv_r2_std_max"))
    if cv_r2_std_max is not None and cv_r2_std is not None and cv_r2_std > cv_r2_std_max:
        warnings.append(f"CV R2 std {cv_r2_std:.4f} exceeds {cv_r2_std_max}")

    if test_r2 < test_r2_min:
        return {"status": "below_threshold", "warnings": warnings}
    return {"status": "excellent", "warnings": warnings}


def add_pattern(patterns, pattern_type, statement, supporting, evidence, applies, does_not, rationale, risks, confidence):
    if not supporting:
        return
    pattern_id = f"{pattern_type}-{len(patterns) + 1:03d}"
    patterns.append({
        "pattern_id": pattern_id,
        "type": pattern_type,
        "statement": statement,
        "supporting_models": supporting,
        "applies_when": applies,
        "does_not_apply_when": does_not,
        "confidence": round(confidence, 3),
        "evidence": evidence,
        "rationale": rationale,
        "risks": risks,
        "last_updated": now_iso(),
    })


def median(values):
    values = sorted(float(v) for v in values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.median(values)


def mine_patterns(excellent_records, config):
    min_support = max(int(config.get("pattern_mining", {}).get("min_support", 2)), 1)
    total = len(excellent_records)
    patterns = []

    algorithm_counts = {}
    for record in excellent_records:
        algorithm = str(record.get("algorithm") or "").strip()
        if algorithm:
            algorithm_counts.setdefault(algorithm, []).append(record)

    for algorithm, records in sorted(algorithm_counts.items(), key=lambda item: -len(item[1])):
        if len(records) < min_support:
            continue
        names = [str(record.get("name") or record.get("source_id")) for record in records]
        objectives = sorted({str(record.get("objective") or "").strip() for record in records if str(record.get("objective") or "").strip()})
        applies = ["New objective is similar to historical excellent-model objectives."]
        if objectives:
            applies.append("Historical objectives include: " + "; ".join(objectives[:5]))
        add_pattern(
            patterns,
            "algorithm",
            f"Algorithm '{algorithm}' appears in {len(records)}/{total} excellent models.",
            names,
            f"{len(records)} excellent models use this algorithm.",
            applies,
            ["Dataset, target, or objective differs materially from the supporting models."],
            "Repeated success across similar models is observational evidence, not proof of causation.",
            ["Correlation is not causation.", "Selection bias may overstate the algorithm's generality."],
            len(records) / total if total else 0.0,
        )

    feature_counts = {}
    for record in excellent_records:
        for feature in record.get("features", []):
            feature_counts.setdefault(feature, []).append(record)

    for feature, records in sorted(feature_counts.items(), key=lambda item: -len(item[1])):
        if len(records) < min_support:
            continue
        names = [str(record.get("name") or record.get("source_id")) for record in records]
        add_pattern(
            patterns,
            "feature",
            f"Feature '{feature}' is used in {len(records)}/{total} excellent models.",
            names,
            f"{len(records)} excellent models include this feature.",
            ["The new task has a comparable data source and target semantics."],
            ["The feature is unavailable, unstable, or has different semantics in the new dataset."],
            "Feature reuse is most reliable when the data generation process and target are comparable.",
            ["Leakage or drift can make a historically useful feature harmful."],
            len(records) / total if total else 0.0,
        )

    param_values = {}
    for record in excellent_records:
        algorithm = str(record.get("algorithm") or "").strip()
        params = record.get("hyperparameters", {})
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            number = to_float(value)
            if number is not None:
                param_values.setdefault((algorithm, key), []).append(number)

    for (algorithm, key), values in sorted(param_values.items(), key=lambda item: -len(item[1])):
        if len(values) < min_support:
            continue
        med = median(values)
        supports = []
        for record in excellent_records:
            params = record.get("hyperparameters", {})
            if isinstance(params, dict) and key in params and to_float(params[key]) is not None:
                supports.append(str(record.get("name") or record.get("source_id")))
        statement = f"Hyperparameter '{key}' for algorithm '{algorithm}' ranges {min(values):g} to {max(values):g} (median {med:g})."
        add_pattern(
            patterns,
            "hyperparameter",
            statement,
            supports,
            f"{len(values)} numeric observations for this hyperparameter.",
            [f"Use only when algorithm is '{algorithm}' and the data/target are comparable."],
            ["Different algorithm, target, or data distribution."],
            "Reported ranges are empirical starting points, not guaranteed optima.",
            ["Small sample size.", "Hyperparameters may be sensitive to data scale and objective."],
            len(values) / total if total else 0.0,
        )

    sample_sizes = [to_float(record.get("sample_size")) for record in excellent_records if to_float(record.get("sample_size")) is not None]
    if len(sample_sizes) >= min_support:
        med = median(sample_sizes)
        supports = [str(record.get("name") or record.get("source_id")) for record in excellent_records if to_float(record.get("sample_size")) is not None]
        add_pattern(
            patterns,
            "sample_size",
            f"Excellent models commonly use sample_size {min(sample_sizes):g} to {max(sample_sizes):g} (median {med:g}).",
            supports,
            f"{len(sample_sizes)} excellent models report sample size.",
            ["The new dataset is of a similar scale and task type."],
            ["Very different data volume, class balance, or signal-to-noise ratio."],
            "Sample-size ranges are descriptive and task-dependent.",
            ["Confounded with task complexity."],
            len(sample_sizes) / total if total else 0.0,
        )

    gaps = []
    for record in excellent_records:
        train_r2 = metric_number(record, "train", "r2")
        test_r2 = metric_number(record, "test", "r2")
        if train_r2 is not None and test_r2 is not None:
            gaps.append(train_r2 - test_r2)
    if len(gaps) >= min_support:
        med = median(gaps)
        supports = []
        for record in excellent_records:
            train_r2 = metric_number(record, "train", "r2")
            test_r2 = metric_number(record, "test", "r2")
            if train_r2 is not None and test_r2 is not None:
                supports.append(str(record.get("name") or record.get("source_id")))
        add_pattern(
            patterns,
            "overfit_gap",
            f"Excellent models show train-test R2 gap {min(gaps):.3f} to {max(gaps):.3f} (median {med:.3f}).",
            supports,
            f"{len(gaps)} models report both train and test R2.",
            ["Both train and test metrics are available."],
            ["Metrics are missing or defined differently."],
            "Small train-test gaps are a useful stability signal.",
            ["Different train/test splits make gaps hard to compare."],
            len(gaps) / total if total else 0.0,
        )

    return patterns


def main():
    parser = argparse.ArgumentParser(description="Classify models and mine reusable patterns.")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--thresholds", default=str(CONFIG_DIR / "thresholds.yaml"))
    parser.add_argument("--registry", default=None)
    args = parser.parse_args()

    data_root = ensure_dirs(args.data_root)
    thresholds = load_yaml(args.thresholds)
    registry_path = Path(args.registry) if args.registry else data_root / "registry.json"
    registry = load_json(registry_path, [])
    if not registry:
        print("[WARN] registry is empty; nothing to analyze")
        return 0

    counts = {"excellent": 0, "below_threshold": 0, "incomplete": 0}
    for record in registry:
        evaluation = evaluate(record, thresholds)
        record["evaluation"] = evaluation
        counts[evaluation["status"]] = counts.get(evaluation["status"], 0) + 1

    save_json(registry_path, registry)
    excellent = [record for record in registry if record.get("evaluation", {}).get("status") == "excellent"]
    save_json(data_root / "excellent_models.json", excellent)

    patterns = mine_patterns(excellent, thresholds)
    save_json(data_root / "patterns.json", patterns)

    report_lines = [
        "# Model Pattern Report",
        "",
        f"- analyzed: {now_iso()}",
        f"- total records: {len(registry)}",
        f"- excellent: {counts.get('excellent', 0)}",
        f"- below threshold: {counts.get('below_threshold', 0)}",
        f"- incomplete: {counts.get('incomplete', 0)}",
        "",
        "## Excellent Models",
        "",
    ]
    if excellent:
        report_lines.extend(["| name | algorithm | test R2 |", "| --- | --- | --- |"])
        for record in excellent:
            test_r2 = metric_number(record, "test", "r2")
            report_lines.append(f"| {record.get('name', record.get('source_id'))} | {record.get('algorithm', '')} | {test_r2 if test_r2 is not None else ''} |")
    else:
        report_lines.append("No excellent models found.")
    report_lines.extend(["", "## Patterns", ""])
    if patterns:
        for pattern in patterns:
            report_lines.extend([
                f"### {pattern['pattern_id']}: {pattern['statement']}",
                "",
                f"- type: {pattern['type']}",
                f"- confidence: {pattern['confidence']}",
                f"- supporting models: {', '.join(pattern['supporting_models'])}",
                f"- applies when: {'; '.join(pattern['applies_when'])}",
                f"- does not apply when: {'; '.join(pattern['does_not_apply_when'])}",
                f"- rationale: {pattern['rationale']}",
                f"- risks: {'; '.join(pattern['risks'])}",
                "",
            ])
    else:
        report_lines.append("Not enough excellent models to mine patterns at the configured support threshold.")
    report_lines.append("")
    (data_root / "reports" / "patterns.md").write_text("\n".join(report_lines), encoding="utf-8")
    (data_root / "reports" / "excellent_models.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps({"counts": counts, "patterns": len(patterns), "data_root": str(data_root)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
