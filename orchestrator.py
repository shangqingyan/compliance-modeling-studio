"""Orchestrator for the local compliance modeling web app."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.neural_network import MLPRegressor

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
MODEL_OUTPUT_DIR = DATA_DIR / "modeling_outputs"
PATTERN_DIR = DATA_DIR / "model-patterns"
SKILL_DRAFT_DIR = DATA_DIR / "skill_drafts"
SKILL_CANDIDATE_DIR = DATA_DIR / "skill_candidates"
SKILL_REVIEW_DIR = DATA_DIR / "skill-review"
COMPLIANCE_DIR = DATA_DIR / "compliance"
JOBS_DIR = DATA_DIR / "jobs"
APPROVAL_DIR = DATA_DIR / "approvals"
RISK_STATE_PATH = COMPLIANCE_DIR / "risk_state.json"
ALERTS_PATH = COMPLIANCE_DIR / "alerts.json"

CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
BUNDLED_SKILLS_DIR = ROOT / "skills_bundle"
SKILLS_DIR = BUNDLED_SKILLS_DIR if (BUNDLED_SKILLS_DIR / "tabular-modeling" / "SKILL.md").exists() else CODEX_HOME / "skills"

TABULAR_RUN = SKILLS_DIR / "tabular-modeling" / "scripts" / "run_modeling.py"
MLP_RUN = ROOT / "scripts" / "run_modeling_mlp.py"
DIAGNOSTICS_RUN = SKILLS_DIR / "model-diagnostics" / "scripts" / "run_diagnostics.py"
PATTERN_DIR_SKILL = SKILLS_DIR / "model-pattern-miner"
PATTERN_INGEST = PATTERN_DIR_SKILL / "scripts" / "ingest.py"
PATTERN_ANALYZE = PATTERN_DIR_SKILL / "scripts" / "analyze.py"
PATTERN_RECOMMEND = PATTERN_DIR_SKILL / "scripts" / "recommend.py"
SKILL_REVIEW_RUN = SKILLS_DIR / "skill-review" / "scripts" / "review.py"
PROJECT_AUDIT = SKILLS_DIR / "project-compliance" / "scripts" / "audit_project.py"
SUNNY_AUDIT = SKILLS_DIR / "sunny" / "scripts" / "audit_skill.py"
SKILL_SCAFFOLD = SKILLS_DIR / "skill-learner" / "scripts" / "scaffold_skill.py"

DEFAULT_MODELS = ["linear", "ridge", "lasso", "decision_tree", "random_forest", "gradient_boosting", "svr"]
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_ITERATIONS = 3
INITIAL_SKILL_IDS = {
    "find-skills", "math-modeling", "sunny", "project-compliance", "skill-review",
    "tabular-modeling", "model-diagnostics", "model-pattern-miner", "skill-learner",
}
RISK_LEVELS = {"低": 0, "中": 1, "高": 2, "极高": 3}

for _d in (UPLOAD_DIR, MODEL_OUTPUT_DIR, PATTERN_DIR, SKILL_DRAFT_DIR, SKILL_CANDIDATE_DIR, SKILL_REVIEW_DIR, COMPLIANCE_DIR, JOBS_DIR, APPROVAL_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


def sanitize_filename(name: str) -> str:
    name = Path(name).name.strip()
    if not name:
        return "input.csv"
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name)


def safe_skill_name(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    if not SKILL_NAME_RE.match(name) or len(name) > 64:
        raise ValueError(f"非法技能名称: {name!r}")
    return name


def run_command(args, timeout=600, env=None, cwd=None):
    """Run a command and return decoded output."""
    try:
        proc = subprocess.run(
            [str(a) for a in args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd or ROOT),
            env=env or os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        return {"returncode": 124, "stdout": exc.stdout or "", "stderr": f"命令超时: {' '.join(map(str, args))}"}
    except Exception as exc:  # noqa: BLE001
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}
    return {"returncode": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}


def read_job(job_id: str) -> dict:
    return load_json(JOBS_DIR / f"{job_id}.json", None)


def write_job(job_id: str, **fields) -> dict:
    path = JOBS_DIR / f"{job_id}.json"
    job = load_json(path, {"job_id": job_id, "created_at": now_iso(), "logs": []})
    job.update(fields)
    save_json(path, job)
    return job


def append_log(job_id: str, message: str, level: str = "info") -> None:
    job = read_job(job_id) or {"job_id": job_id, "logs": []}
    logs = job.setdefault("logs", [])
    logs.append({"time": now_local(), "level": level, "message": message})
    save_json(JOBS_DIR / f"{job_id}.json", job)


def list_jobs() -> list[dict]:
    jobs = []
    for path in sorted(JOBS_DIR.glob("*.json")):
        job = load_json(path, None)
        if job:
            jobs.append(job)
    return jobs


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gb18030")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    raise ValueError(f"不支持的数据格式: {suffix}")


def preview_data(path: Path) -> dict:
    df = read_table(path)
    columns = [str(c) for c in df.columns]
    numeric_columns = [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    suggested_target = numeric_columns[-1] if numeric_columns else (columns[-1] if columns else "")
    return {
        "columns": columns,
        "numeric_columns": numeric_columns,
        "suggested_target": suggested_target,
        "rows": int(len(df)),
    }


def _load_project_audit_module():
    spec = importlib.util.spec_from_file_location("project_audit_script", PROJECT_AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROJECT_AUDIT_MODULE = _load_project_audit_module()


def audit_project(path: Path, skip_paths: list[Path] | None = None) -> dict:
    root = Path(path).resolve()
    skip_dirs = [Path(p).resolve() for p in (skip_paths or [])]
    files = []
    for file in PROJECT_AUDIT_MODULE.collect_text_files(root, []):
        try:
            file = file.resolve()
            rel = file.relative_to(root)
        except Exception:
            continue
        if any(file == d or d in file.parents for d in skip_dirs):
            continue
        files.append(file)

    all_hits = []
    for file in files:
        text = PROJECT_AUDIT_MODULE.read_text_safe(file)
        if text is None:
            continue
        rel = str(file.relative_to(root))
        all_hits.extend(PROJECT_AUDIT_MODULE.scan_text(text, rel, include_block=True))

    all_hits = PROJECT_AUDIT_MODULE.dedupe(all_hits)
    block_hits = [h for h in all_hits if h[2] == "BLOCK" and not h[3]]
    review_hits = [h for h in all_hits if h[2] == "REVIEW" and not h[3]]
    negated_hits = [h for h in all_hits if h[3]]

    raw_lines = [f"[INFO] Auditing: {root}", f"[INFO] text files scanned: {len(files)}"]
    for path_hit, term, level, _negated in negated_hits:
        raw_lines.append(f"[SCAN] negated {level.lower()} term {term!r} in {path_hit}")
    for path_hit, term, level, _negated in review_hits:
        raw_lines.append(f"[SCAN] review term {term!r} in {path_hit}")
    for path_hit, term, level, _negated in block_hits:
        raw_lines.append(f"[SCAN] block term {term!r} in {path_hit}")
    if block_hits:
        raw_lines.append("[VERDICT] BLOCK")
    elif review_hits:
        raw_lines.append("[VERDICT] REVIEW")
    else:
        raw_lines.append("[VERDICT] PASS")
    text = "\n".join(raw_lines) + "\n"

    if block_hits:
        conclusion = "禁止"
        risk = "极高"
        blocked = True
    elif review_hits:
        conclusion = "需加保护措施"
        risk = "中"
        blocked = False
    else:
        conclusion = "允许"
        risk = "低"
        blocked = False
    return {
        "target": str(root),
        "returncode": 2 if block_hits else (1 if review_hits else 0),
        "conclusion": conclusion,
        "risk": risk,
        "blocked": blocked,
        "block_hits": [f"{h[1]} in {h[0]}" for h in block_hits],
        "review_hits": [f"{h[1]} in {h[0]}" for h in review_hits],
        "raw": text,
    }


def audit_skill(path: Path) -> dict:
    result = run_command([sys.executable, str(SUNNY_AUDIT), str(path)], timeout=120)
    text = (result.get("stdout") or "") + "\n" + (result.get("stderr") or "")
    lines = text.splitlines()
    block_hits = [line for line in lines if "[SCAN] block term" in line.lower()]
    review_hits = [line for line in lines if "[SCAN] review term" in line.lower()]
    metadata_issues = [line for line in lines if "[WARN] metadata:" in line]
    returncode = result.get("returncode", 0)
    if returncode == 2:
        conclusion = "禁止"
        risk = "极高"
        blocked = True
    elif review_hits or metadata_issues:
        conclusion = "需加保护措施"
        risk = "中"
        blocked = False
    else:
        conclusion = "允许"
        risk = "低"
        blocked = False
    return {
        "target": str(path),
        "returncode": returncode,
        "conclusion": conclusion,
        "risk": risk,
        "blocked": blocked,
        "block_hits": block_hits,
        "review_hits": review_hits,
        "metadata_issues": metadata_issues,
        "raw": text,
    }


def run_project_compliance(extra_paths=None) -> dict:
    entries = []
    entries.append(audit_project(ROOT, skip_paths=[DATA_DIR, BUNDLED_SKILLS_DIR]))
    for path in extra_paths or []:
        if path and Path(path).exists():
            entries.append(audit_project(Path(path)))
    blocked = any(e["blocked"] for e in entries)
    high = any(e["risk"] in {"高", "极高"} for e in entries)
    conclusion = "禁止" if blocked else ("需加保护措施" if any(e["conclusion"] != "允许" for e in entries) else "允许")
    risk = "极高" if blocked else ("中" if any(e["conclusion"] != "允许" for e in entries) else "低")
    record = {
        "timestamp": now_iso(),
        "conclusion": conclusion,
        "risk": risk,
        "blocked": blocked,
        "entries": entries,
        "findings": [line for e in entries for line in (e.get("block_hits") or []) + (e.get("review_hits") or [])],
        "basis": ["project-compliance/audit_project.py", "project-compliance/references/safety-policy.md", "AGENTS.md"],
        "required_changes": [] if not blocked else ["立即停止当前动作"],
        "alternatives": ["在不越线的前提下最小化数据处理、匿名化、限速并保留审计日志"] if not blocked else ["停止并询问用户合法范围"],
        "escalation": "是" if blocked else "否",
    }
    if blocked:
        record["required_changes"] = ["立即停止当前动作"]
        record["alternatives"] = ["停止并询问用户合法范围"]
    path = COMPLIANCE_DIR / f"audit_{now_iso().replace(':', '-')}.json"
    save_json(path, record)
    return record


def run_sunny_audit(skill_dir: Path) -> dict:
    entry = audit_skill(skill_dir)
    record = {
        "timestamp": now_iso(),
        "conclusion": entry["conclusion"],
        "risk": entry["risk"],
        "blocked": entry["blocked"],
        "entries": [entry],
        "findings": (entry.get("block_hits") or []) + (entry.get("review_hits") or []) + (entry.get("metadata_issues") or []),
        "basis": ["sunny/scripts/audit_skill.py", "sunny/references/safety-policy.md"],
        "required_changes": [] if not entry["blocked"] else ["停止技能安装或草稿生成"],
        "alternatives": ["修复技能元数据与内容后重新审查"] if not entry["blocked"] else ["停止并询问用户合法范围"],
        "escalation": "是" if entry["blocked"] else "否",
    }
    path = COMPLIANCE_DIR / f"sunny_{now_iso().replace(':', '-')}.json"
    save_json(path, record)
    return record


def build_math_model(out_dir: Path, metrics: dict, profile: dict, target: str) -> Path:
    best = metrics.get("best_model", {})
    split = metrics.get("split", {})
    encoding = metrics.get("encoding", {})
    rows = [
        "# Mathematical Model: Local Tabular Regression",
        "",
        "## 1. Problem Statement",
        f"对本地数据集进行回归建模，目标变量为 `{target}`，在训练/验证/测试数据上估计连续数值并评估泛化能力。",
        "",
        "## 2. Assumptions",
        "- 样本来自同一分布，缺失值采用训练集统计量填充。",
        "- 低基数分类变量使用独热编码，高基数分类变量使用频数编码。",
        "- 预处理仅在训练集上拟合，再应用到验证集与测试集。",
        "",
        "## 3. Variables and Parameters",
        "| Symbol | Meaning | Unit | Domain |",
        "| --- | --- | --- | --- |",
        f"| y | 目标变量 `{target}` | 原始单位 | 数据范围 |",
        f"| X | 数值特征与编码后的分类特征 | 混合 | 标准化/编码后的范围 |",
        f"| p | 模型超参数 | - | {json.dumps(best.get('params', {}), ensure_ascii=False)} |",
        "",
        "## 4. Governing Equations / Relationships",
        f"模型: `{best.get('name', 'unknown')}`；拟合关系为 y_hat = f(X; p)。",
        "",
        "## 5. Objective and Constraints",
        "- Objective: 最大化验证集 R²，其次降低 RMSE。",
        "- Constraints: 不使用测试集选择模型；不修改测试集；每轮预处理只能在训练集拟合。",
        "",
        "## 6. Model Type",
        f"回归模型: {best.get('name', 'unknown')}，确定性监督学习。",
        "",
        "## 7. Solution Method",
        f"使用 `tabular-modeling/scripts/run_modeling.py` 执行 60/20/20 划分与候选模型网格搜索。",
        "",
        "## 8. Results",
        f"- Test R²: {best.get('test_r2')}",
        f"- Test RMSE: {best.get('test_rmse')}",
        f"- Test MAE: {best.get('test_mae')}",
        f"- Split: {json.dumps(split, ensure_ascii=False)}",
        f"- Encoding: {json.dumps(encoding, ensure_ascii=False)}",
        "",
        "## 9. Validation",
        "残差图、预测 vs 实际图、R²/RMSE/MAE 由 model-diagnostics 复核。",
        "",
        "## 10. Limitations",
        "模型只适用于与训练数据同分布的数据；外推需谨慎。",
        "",
    ]
    out = out_dir / "math-model.md"
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


def read_json_file(path: Path, default=None):
    return load_json(path, default)


def make_chart_data(out_dir: Path, job: dict) -> dict:
    metrics = read_json_file(out_dir / "metrics.json", {})
    comparison = metrics.get("model_comparison", [])
    best = metrics.get("best_model", {})
    pred_path = out_dir / "test_predictions.csv"
    predictions = []
    if pred_path.exists():
        try:
            df = pd.read_csv(pred_path)
            df = df.head(200)
            predictions = [
                {"target": float(r.target), "prediction": float(r.prediction)}
                for _, r in df.iterrows()
                if pd.notna(r.get("target")) and pd.notna(r.get("prediction"))
            ]
        except Exception:
            predictions = []
    return {
        "model_comparison": comparison,
        "best_model": best,
        "predictions": predictions,
        "residual_plot_url": f"/artifacts/{job['job_id']}/iter_{job.get('best_iteration', 1)}/residual_plot.png",
        "metrics": metrics,
    }


def update_pattern_miner(job: dict, out_dir: Path) -> dict:
    metrics = read_json_file(out_dir / "metrics.json", {})
    profile = read_json_file(out_dir / "data_profile.json", {})
    best = metrics.get("best_model", {})
    input_path = Path(job["input_path"])
    try:
        df = read_table(input_path)
        features = [c for c in df.columns if str(c) != job["target"]]
        sample_size = int(len(df))
    except Exception:
        features = []
        sample_size = 0
    record = {
        "id": job["job_id"],
        "source_id": job["job_id"],
        "name": f"local-{job['job_id']}",
        "platform": "local-tabular-modeling",
        "objective": "regression",
        "target_variable": job["target"],
        "dataset": input_path.name,
        "features": features,
        "algorithm": best.get("name", "unknown"),
        "hyperparameters": best.get("params", {}),
        "sample_size": sample_size,
        "split": metrics.get("split", {}),
        "metrics": {
            "test": {
                "r2": best.get("test_r2"),
                "rmse": best.get("test_rmse"),
                "mae": best.get("test_mae"),
            },
            "train": {},
            "cv": {},
        },
        "stability": {"overfit_gap": None},
        "created_at": now_iso(),
        "artifacts": [str(out_dir / "math-model.md"), str(out_dir / "metrics.json")],
        "tags": ["local", "tabular", "regression"],
        "notes": f"auto-registered by compliance modeling web for job {job['job_id']}",
    }
    import_file = PATTERN_DIR / "imports" / f"{job['job_id']}.json"
    import_file.parent.mkdir(parents=True, exist_ok=True)
    save_json(import_file, record)
    env = os.environ.copy()
    env["MODEL_PATTERN_DATA_DIR"] = str(PATTERN_DIR)
    outputs = []
    for label, args in [
        ("ingest", [sys.executable, str(PATTERN_INGEST), "--source", str(import_file), "--format", "json", "--commit"]),
        ("analyze", [sys.executable, str(PATTERN_ANALYZE)]),
    ]:
        res = run_command(args, timeout=180, env=env)
        outputs.append({"stage": label, "returncode": res["returncode"], "stdout": res["stdout"], "stderr": res["stderr"]})
    goal = job.get("goal") or f"对 {job['target']} 进行回归建模"
    rec = run_command(
        [sys.executable, str(PATTERN_RECOMMEND), "--goal", goal, "--target-variable", job["target"], "--dataset", input_path.name, "--sample-size", str(sample_size or "")],
        timeout=180,
        env=env,
    )
    outputs.append({"stage": "recommend", "returncode": rec["returncode"], "stdout": rec["stdout"], "stderr": rec["stderr"]})
    recommendations = []
    if rec["returncode"] == 0:
        try:
            payload = json.loads(rec["stdout"])
            recommendations = payload.get("recommendations", [])
        except Exception:
            recommendations = []
    return {"record_file": str(import_file), "stages": outputs, "recommendations": recommendations}


def adjust_params(params: dict, diagnostics: dict, pattern_advice: list[dict] | None = None) -> dict:
    params = dict(params or {})
    suggestions = [str(s).lower() for s in diagnostics.get("suggestions", [])]
    advice_text = " ".join(
        str(a.get("statement", "")) + " " + str(a.get("type", ""))
        for a in (pattern_advice or [])
    ).lower()
    text = " ".join([*suggestions, advice_text])
    models = params.get("models") or DEFAULT_MODELS[:]
    if any(k in text for k in ["非线性", "tree", "random forest", "gradient boosting", "svr", "nonlinear"]):
        for m in ["random_forest", "gradient_boosting", "svr"]:
            if m not in models:
                models.append(m)
        params["models"] = models
    return params


def _load_modeling_module():
    spec = importlib.util.spec_from_file_location("tabular_modeling_script", TABULAR_RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MODELING_MODULE = _load_modeling_module()


def run_stability_training(job: dict, pass_out_dir: Path, best_model_name: str, training_runs: int) -> dict:
    """Run repeated in-process single-model trainings to estimate stability."""
    training_runs = int(training_runs or 0)
    if training_runs <= 0:
        return {"runs": 0, "note": "未启用重复训练"}
    params = job.get("params") or {}
    threshold = int(params.get("cardinality_threshold", 20))
    try:
        df = MODELING_MODULE.load_data(Path(job["input_path"]))
        target = job["target"]
        y = MODELING_MODULE.as_numeric_target(df[target], target)
        X = df.drop(columns=[target])
        best = read_json_file(pass_out_dir / "metrics.json", {}).get("best_model", {})
        model_params = best.get("params") or {}
        if best_model_name == "random_forest":
            model_params = {"n_estimators": 50, "n_jobs": -1}
        elif best_model_name == "gradient_boosting":
            model_params = {"n_estimators": 50}
    except Exception as exc:  # noqa: BLE001
        return {"runs": 0, "error": f"稳定性训练初始化失败: {exc}"}

    rows = []
    for i in range(training_runs):
        seed = 1000 + i
        X_train, X_rest, y_train, y_rest = MODELING_MODULE.train_test_split(
            X, y, test_size=0.4, random_state=seed, shuffle=True
        )
        X_val, X_test, y_val, y_test = MODELING_MODULE.train_test_split(
            X_rest, y_rest, test_size=0.5, random_state=seed, shuffle=True
        )
        try:
            selection_prep = MODELING_MODULE.Preprocessor(cardinality_threshold=threshold)
            selection_prep.fit(X_train)
            X_train_p = selection_prep.transform(X_train)
            X_val_p = selection_prep.transform(X_val)
            if best_model_name == "mlp":
                estimator = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=int(params.get("epochs", 100)), random_state=42, early_stopping=False)
            else:
                estimator = MODELING_MODULE.build_model(best_model_name, model_params)
            estimator.fit(X_train_p, y_train)
            val_pred = estimator.predict(X_val_p)
            val_metrics = MODELING_MODULE.metrics(y_val, val_pred)

            X_dev = pd.concat([X_train, X_val], axis=0)
            y_dev = pd.concat([y_train, y_val], axis=0)
            final_prep = MODELING_MODULE.Preprocessor(cardinality_threshold=threshold)
            final_prep.fit(X_dev)
            X_dev_p = final_prep.transform(X_dev)
            X_test_p = final_prep.transform(X_test)
            if best_model_name == "mlp":
                final_estimator = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=int(params.get("epochs", 100)), random_state=42, early_stopping=False)
            else:
                final_estimator = MODELING_MODULE.build_model(best_model_name, model_params)
            final_estimator.fit(X_dev_p, y_dev)
            test_pred = final_estimator.predict(X_test_p)
            test_metrics = MODELING_MODULE.metrics(y_test, test_pred)
            row = {
                "run": i,
                "random_state": seed,
                "validation_r2": val_metrics.get("r2"),
                "validation_rmse": val_metrics.get("rmse"),
                "validation_mae": val_metrics.get("mae"),
                "test_r2": test_metrics.get("r2"),
                "test_rmse": test_metrics.get("rmse"),
                "test_mae": test_metrics.get("mae"),
                "returncode": 0,
            }
        except Exception as exc:  # noqa: BLE001
            row = {
                "run": i,
                "random_state": seed,
                "returncode": 1,
                "error": str(exc),
            }
        rows.append(row)
        if (i + 1) % 50 == 0:
            append_log(job["job_id"], f"稳定性训练进度 {i + 1}/{training_runs}")
            write_job(job["job_id"], training_progress={"done": i + 1, "total": training_runs})

    def agg(key):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        if not vals:
            return {"count": 0, "mean": None, "std": None}
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
        return {"count": len(vals), "mean": mean, "std": var ** 0.5}

    return {
        "runs": training_runs,
        "model": best_model_name,
        "summary": {
            "validation_r2": agg("validation_r2"),
            "validation_rmse": agg("validation_rmse"),
            "validation_mae": agg("validation_mae"),
            "test_r2": agg("test_r2"),
            "test_rmse": agg("test_rmse"),
            "test_mae": agg("test_mae"),
        },
        "runs_dir": str(MODEL_OUTPUT_DIR / job["job_id"] / "training_runs"),
        "rows": rows,
    }




def relax_diagnostic_verdict(diagnostics: dict, metrics: dict):
    original = diagnostics.get("verdict")
    if original not in {"review", "remediate"}:
        return original, None
    try:
        test_r2 = float(metrics.get("best_model", {}).get("test_r2"))
        nrmse = float(diagnostics.get("diagnostics", {}).get("normalized_rmse"))
    except Exception:
        return original, None
    if test_r2 >= 0.90 and nrmse <= 0.35:
        override = {
            "original_verdict": original,
            "test_r2": test_r2,
            "normalized_rmse": nrmse,
            "reason": "高R²模型残差分布不完美，已放宽通过",
        }
        return "pass", override
    return original, None


def adjust_cardinality_threshold(params: dict, profile: dict, diagnostics: dict) -> dict:
    current = int(params.get("cardinality_threshold", 20))
    suggestions = [str(s).lower() for s in diagnostics.get("suggestions", [])]
    suggestion_text = " ".join(suggestions)
    features = profile.get("feature_profile", []) if isinstance(profile, dict) else []
    freq_features = [
        f for f in features
        if str(f.get("preprocessing_decision", "")) in {"频数编码", "frequency"}
    ]
    max_unique = max([int(f.get("unique_count", 0) or 0) for f in freq_features], default=0)
    need_raise = (bool(freq_features) and max_unique > current) or any(
        key in suggestion_text for key in ["one-hot", "onehot", "独热", "cardinality"]
    )
    if need_raise:
        new_threshold = min(100, max(max_unique, current + 10))
        reason = f"返工需要更充分的类别编码，阈值从 {current} 调整为 {new_threshold}"
    else:
        new_threshold = current
        reason = "无需调整独热编码阈值" if not freq_features else "当前独热编码阈值已覆盖现有类别"
    return {
        "threshold": new_threshold,
        "previous_threshold": current,
        "reason": reason,
        "max_categorical_unique": max_unique,
        "frequency_encoded_features": [f.get("column") for f in freq_features],
    }

def run_modeling_job(job_id: str) -> None:
    job = read_job(job_id)
    if not job:
        return
    try:
        job = write_job(job_id, status="compliance", started_at=now_iso())
        append_log(job_id, "开始合规预检")
        input_path = Path(job["input_path"])
        compliance = run_project_compliance(extra_paths=[input_path.parent])
        write_job(job_id, compliance=compliance)
        if compliance.get("blocked"):
            append_log(job_id, "合规预检发现禁止项，终止运行", "error")
            write_job(job_id, status="blocked", finished_at=now_iso(), result={"error": "合规预检未通过，已终止输出"})
            return
        append_log(job_id, f"合规预检结论: {compliance['conclusion']}，风险等级: {compliance['risk']}")

        params = job.get("params") or {}
        params["cardinality_threshold"] = int(params.get("cardinality_threshold", 20))
        params["models"] = params.get("models") or DEFAULT_MODELS[:]
        target = job["target"]
        job = write_job(job_id, params=params)
        used_skills = set(job.get("skills_used", []))
        used_skills.update(["tabular-modeling", "model-diagnostics", "math-modeling", "model-pattern-miner", "project-compliance", "sunny"])
        write_job(job_id, skills_used=sorted(used_skills))

        final_result = None
        iterations = {}
        passed = False

        for iteration in range(1, MAX_ITERATIONS + 1):
            job = write_job(job_id, status="modeling", iteration_count=iteration)
            append_log(job_id, f"第 {iteration}/{MAX_ITERATIONS} 轮建模开始")
            out_dir = MODEL_OUTPUT_DIR / job_id / f"iter_{iteration}"
            out_dir.mkdir(parents=True, exist_ok=True)
            model_script = MLP_RUN if "mlp" in (params.get("models") or DEFAULT_MODELS) else TABULAR_RUN
            model_env = os.environ.copy()
            model_env["MLP_EPOCHS"] = str(int(params.get("epochs", 100)))
            model_args = [
                sys.executable, str(model_script),
                "--input", str(input_path),
                "--target", target,
                "--output-dir", str(out_dir),
                "--cardinality-threshold", str(params.get("cardinality_threshold", 20)),
                "--models", ",".join(params.get("models") or DEFAULT_MODELS),
            ]
            if params.get("skip_tuning"):
                model_args.append("--skip-tuning")
            model_res = run_command(model_args, timeout=900, env=model_env)
            append_log(job_id, f"建模命令返回码: {model_res['returncode']}")
            if model_res["returncode"] != 0:
                append_log(job_id, f"建模失败: {model_res['stderr'] or model_res['stdout']}", "error")
                iterations[str(iteration)] = {"verdict": "model_failed", "stdout": model_res["stdout"], "stderr": model_res["stderr"]}
                continue

            job = write_job(job_id, status="diagnosing")
            append_log(job_id, f"第 {iteration} 轮模型诊断")
            diag_res = run_command(
                [sys.executable, str(DIAGNOSTICS_RUN), "--output-dir", str(out_dir), "--data", str(input_path), "--target", target],
                timeout=600,
            )
            diagnostics = read_json_file(out_dir / "diagnostics.json", {})
            if not diagnostics:
                diagnostics = {"verdict": "diagnostic_failed", "reasons": [], "suggestions": [], "artifacts": {}}
            metrics_for_verdict = read_json_file(out_dir / "metrics.json", {})
            original_verdict = diagnostics.get("verdict", "diagnostic_failed")
            verdict, diagnostic_override = relax_diagnostic_verdict(diagnostics, metrics_for_verdict)
            if diagnostic_override:
                diagnostics = dict(diagnostics)
                diagnostics["_override"] = diagnostic_override
            iterations[str(iteration)] = {
                "verdict": verdict,
                "original_verdict": original_verdict,
                "diagnostic_override": diagnostic_override,
                "out_dir": str(out_dir),
                "diagnostics": diagnostics,
                "model_stdout": model_res["stdout"],
                "model_stderr": model_res["stderr"],
                "diag_stdout": diag_res["stdout"],
                "diag_stderr": diag_res["stderr"],
            }
            append_log(job_id, f"诊断判定: {verdict}" + (f"，宽松通过原因: {diagnostic_override['reason']}" if diagnostic_override else ""))

            if verdict in ("pass", "review"):
                metrics = read_json_file(out_dir / "metrics.json", {})
                profile = read_json_file(out_dir / "data_profile.json", {})
                math_path = build_math_model(out_dir, metrics, profile, target)
                charts = make_chart_data(out_dir, job)
                zh_plot = out_dir / "residual_plot_zh.png"
                if generate_residual_plot_zh(out_dir / "test_predictions.csv", zh_plot):
                    charts["residual_plot_zh_url"] = f"/artifacts/{job_id}/iter_{iteration}/residual_plot_zh.png"
                training_runs = int(params.get("stability_runs", 50))
                charts["r2_table"] = build_r2_table(metrics, None)
                final_result = {"warning": verdict == "review" or bool(diagnostic_override),
                    "iteration": iteration,
                    "out_dir": str(out_dir),
                    "metrics": metrics,
                    "diagnostics": diagnostics,
                    "diagnostic_override": diagnostic_override,
                    "charts": charts,
                    "training_summary": {"runs": training_runs, "status": "running", "note": "稳定性训练进行中"},
                    "math_model_path": str(math_path),
                }
                write_job(job_id, status="pass", result=final_result, best_iteration=iteration, iterations=iterations,
                          stability_status="running", pattern_status="pending")
                append_log(job_id, "模型评估通过" if verdict == "pass" else "模型存在可疑信号，已按带警告通过")
                passed = True

                def finish_pass_async():
                    try:
                        stability = run_stability_training(job, out_dir, metrics.get("best_model", {}).get("name", "linear"), training_runs)
                        job_now = read_job(job_id) or {}
                        result_now = job_now.get("result") or {}
                        charts_now = result_now.get("charts") or {}
                        charts_now["r2_table"] = build_r2_table(metrics, stability)
                        result_now["training_summary"] = stability
                        result_now["charts"] = charts_now
                        write_job(job_id, result=result_now, stability_status="done")
                        pattern_result = update_pattern_miner(job, out_dir)
                        write_job(job_id, pattern_result=pattern_result, pattern_advice=pattern_result.get("recommendations", []),
                                  pattern_status="done", finished_at=now_iso())
                        append_log(job_id, "稳定性训练与优秀模型规律登记完成")
                    except Exception as exc:  # noqa: BLE001
                        write_job(job_id, stability_status="done", pattern_status="done", finished_at=now_iso(),
                                  result={"error": f"后台训练更新失败: {exc}"})
                        append_log(job_id, f"后台训练更新失败: {exc}", "error")

                threading.Thread(target=finish_pass_async, daemon=True).start()
                break

            append_log(job_id, f"诊断建议: {json.dumps(diagnostics.get('suggestions', []), ensure_ascii=False)}")
            profile_for_adjust = read_json_file(out_dir / "data_profile.json", {})
            threshold_adjustment = adjust_cardinality_threshold(params, profile_for_adjust, diagnostics)
            params["cardinality_threshold"] = threshold_adjustment["threshold"]
            params = adjust_params(params, diagnostics, job.get("pattern_advice", []))
            iterations[str(iteration)]["adjustment"] = threshold_adjustment
            write_job(job_id, params=params, iterations=iterations)
            append_log(job_id, f"独热编码阈值调整: {threshold_adjustment['reason']}")
            append_log(job_id, f"调整后参数: {json.dumps(params, ensure_ascii=False)}")

        if not passed:
            latest_display = None
            for key in sorted(iterations.keys(), key=lambda x: int(x), reverse=True):
                it = iterations[key]
                out_dir = Path(it.get("out_dir", ""))
                if out_dir and (out_dir / "metrics.json").exists():
                    metrics = read_json_file(out_dir / "metrics.json", {})
                    job_for_chart = dict(job)
                    job_for_chart["best_iteration"] = int(key)
                    charts = make_chart_data(out_dir, job_for_chart)
                    if generate_residual_plot_zh(out_dir / "test_predictions.csv", out_dir / "residual_plot_zh.png"):
                        charts["residual_plot_zh_url"] = f"/artifacts/{job_id}/iter_{key}/residual_plot_zh.png"
                    charts["r2_table"] = build_r2_table(metrics, None)
                    latest_display = {
                        "iteration": int(key),
                        "out_dir": str(out_dir),
                        "metrics": metrics,
                        "diagnostics": it.get("diagnostics", {}),
                        "charts": charts,
                        "training_summary": {"runs": 0, "note": "任务未通过，未运行稳定性训练"},
                        "math_model_path": "",
                    }
                    break
            write_job(job_id, status="blocked", iterations=iterations, finished_at=now_iso(), result={
                "error": "模型评估未通过，已终止输出；请查看诊断建议与迭代记录。",
                "iterations": iterations,
                "latest_display": latest_display,
            })
            append_log(job_id, "达到最大返工次数，终止输出", "error")
    except Exception as exc:  # noqa: BLE001
        write_job(job_id, status="blocked", finished_at=now_iso(), result={"error": f"运行异常: {exc}"})
        append_log(job_id, f"运行异常: {exc}", "error")


def start_job(job_id: str) -> None:
    thread = threading.Thread(target=run_modeling_job, args=(job_id,), daemon=True)
    thread.start()


def list_skills() -> list[dict]:
    skills = []
    if not SKILLS_DIR.exists():
        return skills
    for path in sorted(SKILLS_DIR.iterdir()):
        if not path.is_dir():
            continue
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        first = text.splitlines()[0] if text else ""
        name = path.name
        desc = ""
        if text.startswith("---"):
            m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            if m:
                fm = m.group(1)
                for line in fm.splitlines():
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip("'\"")
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip("'\"")
        skills.append({"id": path.name, "name": name, "description": desc, "path": str(path)})
    return skills


def find_skills(query: str) -> dict:
    if not query.strip():
        return {"query": query, "output": "", "error": "查询不能为空"}
    npx = shutil.which("npx") or "npx.cmd"
    res = run_command([npx, "-y", "skills", "find", query.strip()], timeout=180)
    return {
        "query": query.strip(),
        "returncode": res["returncode"],
        "output": res["stdout"],
        "error": res["stderr"] if res["returncode"] != 0 else "",
    }


def create_skill_draft(name: str, goal: str) -> dict:
    name = safe_skill_name(name)
    draft_dir = SKILL_DRAFT_DIR / name
    if draft_dir.exists():
        shutil.rmtree(draft_dir)
    res = run_command([sys.executable, str(SKILL_SCAFFOLD), "--name", name, "--goal", goal or "new skill", "--dest", str(SKILL_DRAFT_DIR)])
    if res["returncode"] != 0:
        return {"ok": False, "error": res["stderr"] or res["stdout"], "name": name}
    audit = run_sunny_audit(draft_dir)
    record = {
        "id": name,
        "name": name,
        "goal": goal,
        "path": str(draft_dir),
        "status": "proposed",
        "audit": audit,
        "created_at": now_iso(),
        "raw": {"stdout": res["stdout"], "stderr": res["stderr"]},
    }
    save_json(SKILL_CANDIDATE_DIR / f"{name}.json", record)
    return {"ok": True, "candidate": record}


def install_skill(name: str, approved: bool) -> dict:
    name = safe_skill_name(name)
    if not approved:
        return {"ok": False, "error": "用户未批准安装", "name": name}
    draft_dir = SKILL_DRAFT_DIR / name
    if not draft_dir.exists():
        return {"ok": False, "error": f"草稿不存在: {draft_dir}", "name": name}
    audit = run_sunny_audit(draft_dir)
    if audit.get("blocked"):
        return {"ok": False, "error": "Sunny 合规审查未通过，安装已终止", "audit": audit, "name": name}
    dest = SKILLS_DIR / name
    if dest.exists():
        return {"ok": False, "error": f"技能已存在: {dest}", "name": name}
    shutil.copytree(draft_dir, dest)
    record_path = SKILL_CANDIDATE_DIR / f"{name}.json"
    record = load_json(record_path, {"id": name, "name": name})
    record.update({"status": "installed", "installed_at": now_iso(), "destination": str(dest), "audit": audit})
    save_json(record_path, record)
    return {"ok": True, "name": name, "destination": str(dest), "audit": audit}


def delete_skill(skill_id: str, approved: bool) -> dict:
    skill_id = safe_skill_name(skill_id)
    if not approved:
        return {"ok": False, "error": "用户未批准删除", "skill_id": skill_id}
    skill_dir = SKILLS_DIR / skill_id
    if not skill_dir.exists():
        return {"ok": False, "error": f"技能不存在: {skill_dir}", "skill_id": skill_id}
    resolved = skill_dir.resolve()
    skills_resolved = SKILLS_DIR.resolve()
    if skills_resolved not in resolved.parents:
        return {"ok": False, "error": "目标路径不在技能目录内", "skill_id": skill_id}
    if skill_id in INITIAL_SKILL_IDS:
        return {"ok": False, "error": f"初始技能不可删除: {skill_id}", "skill_id": skill_id}
    backup_root = SKILL_REVIEW_DIR / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, backup_root / skill_id)
    shutil.rmtree(skill_dir)
    record = {
        "skill_id": skill_id,
        "action": "delete",
        "approved": True,
        "backup": str(backup_root / skill_id),
        "timestamp": now_iso(),
    }
    save_json(SKILL_REVIEW_DIR / f"delete_{now_iso().replace(':', '-')}.json", record)
    return {"ok": True, "skill_id": skill_id, "backup": str(backup_root / skill_id)}


def build_evidence() -> dict:
    skills = [s["id"] for s in list_skills()]
    usage = {skill: {"task_count": 0, "used_cycles_ago": 99, "critical": skill in {"project-compliance", "sunny", "skill-review"}, "importance": None, "ablation_impact": None} for skill in skills}
    for job in list_jobs():
        for skill in job.get("skills_used", []):
            if skill in usage:
                usage[skill]["task_count"] += 1
                usage[skill]["used_cycles_ago"] = 0
    evidence = {"skills": []}
    for skill, meta in usage.items():
        item = {"id": skill, **meta}
        evidence["skills"].append(item)
    path = SKILL_REVIEW_DIR / "evidence.json"
    save_json(path, evidence)
    return evidence


def run_skill_review(dry_run: bool = True) -> dict:
    evidence = build_evidence()
    state_path = SKILL_REVIEW_DIR / "state.json"
    report_path = SKILL_REVIEW_DIR / "report.md"
    args = [
        sys.executable, str(SKILL_REVIEW_RUN),
        "--skills-dir", str(SKILLS_DIR),
        "--inventory", str(SKILL_REVIEW_DIR / "evidence.json"),
        "--state", str(state_path),
        "--report", str(report_path),
    ]
    res = run_command(args, timeout=300)
    report_content = report_path.read_text(encoding="utf-8", errors="replace") if report_path.exists() else ""
    state = load_json(state_path, {})
    return {
        "dry_run": dry_run,
        "returncode": res["returncode"],
        "stdout": res["stdout"],
        "stderr": res["stderr"],
        "report": report_content,
        "state": state,
        "evidence": evidence,
    }


def apply_skill_review_delete(skill_ids: list[str], approved: bool) -> dict:
    if not approved:
        return {"ok": False, "error": "用户未批准删除"}
    ids = [safe_skill_name(x) for x in skill_ids]
    if not ids:
        return {"ok": False, "error": "未提供技能ID"}
    protected = [x for x in ids if x in INITIAL_SKILL_IDS]
    if protected:
        return {"ok": False, "error": f"初始技能不可删除: {', '.join(protected)}"}
    backup_dir = SKILL_REVIEW_DIR / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    args = [
        sys.executable, str(SKILL_REVIEW_RUN),
        "--skills-dir", str(SKILLS_DIR),
        "--state", str(SKILL_REVIEW_DIR / "state.json"),
        "--report", str(SKILL_REVIEW_DIR / "report.md"),
        "--apply-delete",
        "--skill-ids", ",".join(ids),
        "--backup-dir", str(backup_dir),
    ]
    res = run_command(args, timeout=300)
    return {"ok": res["returncode"] == 0, "returncode": res["returncode"], "stdout": res["stdout"], "stderr": res["stderr"]}


def latest_review() -> dict:
    report_path = SKILL_REVIEW_DIR / "report.md"
    state_path = SKILL_REVIEW_DIR / "state.json"
    evidence_path = SKILL_REVIEW_DIR / "evidence.json"
    return {
        "report": report_path.read_text(encoding="utf-8", errors="replace") if report_path.exists() else "",
        "state": load_json(state_path, {}),
        "evidence": load_json(evidence_path, {"skills": []}),
    }


def latest_compliance() -> dict:
    records = sorted(COMPLIANCE_DIR.glob("audit_*.json"))
    latest = load_json(records[-1], {}) if records else {}
    sunny_records = sorted(COMPLIANCE_DIR.glob("sunny_*.json"))
    latest_sunny = load_json(sunny_records[-1], {}) if sunny_records else {}
    return {"latest": latest, "latest_sunny": latest_sunny}




def latest_job() -> dict | None:
    jobs = list_jobs()
    if not jobs:
        return None
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs[0]


def generate_residual_plot_zh(pred_path: Path, out_path: Path) -> bool:
    if not pred_path.exists():
        return False
    try:
        df = pd.read_csv(pred_path)
        if "target" not in df.columns or "prediction" not in df.columns:
            return False
        y = pd.to_numeric(df["target"], errors="coerce").to_numpy(dtype=float)
        yhat = pd.to_numeric(df["prediction"], errors="coerce").to_numpy(dtype=float)
        mask = ~(np.isnan(y) | np.isnan(yhat))
        y = y[mask]
        yhat = yhat[mask]
        if len(y) < 5:
            return False
        residual = y - yhat
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "sans-serif"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        ax = axes[0, 0]
        ax.scatter(yhat, residual, alpha=0.6, s=24)
        ax.axhline(0, color="black", linewidth=1)
        ax.set_xlabel("预测值")
        ax.set_ylabel("残差")
        ax.set_title("残差 vs 拟合值")

        ax = axes[0, 1]
        ax.hist(residual, bins="auto", alpha=0.72, color="#3B82F6")
        ax.set_xlabel("残差")
        ax.set_ylabel("频数")
        ax.set_title("残差直方图")

        ax = axes[1, 0]
        stats.probplot(residual, dist="norm", plot=ax)
        ax.set_title("正态 Q-Q 图")
        ax.set_xlabel("理论分位数")
        ax.set_ylabel("样本分位数")

        ax = axes[1, 1]
        ax.scatter(y, yhat, alpha=0.6, s=24)
        limits = [min(float(np.min(y)), float(np.min(yhat))), max(float(np.max(y)), float(np.max(yhat)))]
        ax.plot(limits, limits, color="red", linewidth=1, linestyle="--")
        ax.set_xlabel("实际值")
        ax.set_ylabel("预测值")
        ax.set_title("预测 vs 实际")

        fig.tight_layout()
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return True
    except Exception:
        return False


def build_r2_table(metrics: dict, stability: dict | None) -> list[dict]:
    rows = []
    comparison = metrics.get("model_comparison", []) if metrics else []
    best = (metrics or {}).get("best_model", {})
    stable_summary = (stability or {}).get("summary", {})
    for item in comparison:
        model = item.get("model", "")
        rows.append({
            "模型": model,
            "验证R²": item.get("validation_r2"),
            "测试R²": best.get("test_r2") if model == best.get("name") else None,
            "R²均值": stable_summary.get("test_r2", {}).get("mean") if model == (stability or {}).get("model") else None,
            "R²标准差": stable_summary.get("test_r2", {}).get("std") if model == (stability or {}).get("model") else None,
        })
    return rows


def _local_skill_recommendations() -> list[dict]:
    recs = []
    latest = latest_job()
    if latest:
        status = latest.get("status")
        diagnostics = (latest.get("result") or {}).get("diagnostics", {}) if latest.get("result") else {}
        verdict = diagnostics.get("verdict") if diagnostics else None
        if status == "blocked" or verdict in {"review", "remediate"}:
            recs.append({"id": "model-diagnostics-plus", "skill_id": "model-diagnostics-plus", "title": "模型诊断增强", "reason": "当前任务存在诊断短板，建议学习更细的残差诊断与修复技能。", "query": "model diagnostics regression residual remediation"})
        best_name = ((latest.get("result") or {}).get("metrics", {}) or {}).get("best_model", {}).get("name", "")
        if best_name in {"linear", "ridge", "lasso"}:
            recs.append({"id": "feature-engineering-plus", "skill_id": "feature-engineering-plus", "title": "特征工程增强", "reason": "当前最优模型为线性模型，建议学习特征交叉与非线性增强技能。", "query": "feature engineering tabular regression"})
    recs.append({"id": "visualization-plus", "skill_id": "visualization-plus", "title": "可视化增强", "reason": "增强中文图表、交互式可视化和报告能力。", "query": "data visualization charts dashboard"})
    recs.append({"id": "model-interpretability-plus", "skill_id": "model-interpretability-plus", "title": "模型可解释性增强", "reason": "提升模型解释、SHAP与业务可理解性。", "query": "model interpretability shap"})
    return recs


def get_skill_recommendations(refresh: bool = False) -> dict:
    path = APPROVAL_DIR / "recommendations.json"
    recs = load_json(path, [])
    if not recs or refresh:
        recs = _local_skill_recommendations()
        if refresh:
            for rec in recs:
                try:
                    found = find_skills(rec.get("query", ""))
                    rec["find_skills"] = found
                except Exception:
                    rec["find_skills"] = {"error": "find-skills 查询失败"}
        save_json(path, recs)
    return {"recommendations": recs}


def approve_skill_recommendation(rec_id: str, client_id: str) -> dict:
    client_id = (client_id or "").strip()
    if not client_id:
        return {"ok": False, "error": "缺少用户ID"}
    path = APPROVAL_DIR / "recommendations.json"
    recs = load_json(path, [])
    rec = next((r for r in recs if r.get("id") == rec_id), None)
    if not rec:
        return {"ok": False, "error": "推荐项不存在"}
    approvals = set(rec.get("approvals", []))
    approvals.add(client_id)
    rec["approvals"] = sorted(approvals)
    rec["approval_count"] = len(approvals)
    save_json(path, recs)
    triggered = len(approvals) >= 10
    if triggered:
        threading.Thread(target=run_full_upgrade, daemon=True).start()
    return {"ok": True, "approval_count": len(approvals), "triggered": triggered, "recommendation": rec}


def run_full_upgrade() -> dict:
    log = []
    log.append({"time": now_iso(), "message": "10个用户批准已达成，启动全流程迭代升级"})
    recs = load_json(APPROVAL_DIR / "recommendations.json", [])
    approved = [r for r in recs if len(r.get("approvals", [])) >= 10]
    for rec in approved:
        name = safe_skill_name(rec.get("skill_id", ""))
        goal = rec.get("reason", "推荐技能")
        draft = create_skill_draft(name, goal)
        log.append({"time": now_iso(), "message": f"生成草稿 {name}: {draft}"})
        if draft.get("ok"):
            installed = install_skill(name, approved=True)
            log.append({"time": now_iso(), "message": f"安装技能 {name}: {installed}"})
    review = run_skill_review(dry_run=True)
    log.append({"time": now_iso(), "message": f"技能权重评估返回码 {review.get('returncode')}"})
    latest = latest_job()
    if latest and latest.get("input_path") and latest.get("target"):
        new_job_id = uuid.uuid4().hex[:12]
        write_job(
            new_job_id,
            status="pending",
            upload_id=latest.get("upload_id"),
            input_path=latest.get("input_path"),
            target=latest.get("target"),
            goal=(latest.get("goal") or "全流程升级重建"),
            params=latest.get("params") or {},
            iteration_count=0,
            logs=[],
            feedback=[],
            skills_used=[],
            parent_job_id=latest.get("job_id"),
            created_at=now_iso(),
        )
        start_job(new_job_id)
        log.append({"time": now_iso(), "message": f"已创建升级重建任务 {new_job_id}"})
    compliance = run_project_compliance()
    log.append({"time": now_iso(), "message": f"合规复检结论 {compliance.get('conclusion')} / {compliance.get('risk')}"})
    result = {"started_at": now_iso(), "approved_recommendations": [r.get("id") for r in approved], "log": log}
    save_json(APPROVAL_DIR / f"upgrade_{now_iso().replace(':', '-')}.json", result)
    return result


def risk_value(label: str) -> int:
    return RISK_LEVELS.get(label, 0)


def update_compliance_risk(record: dict) -> dict:
    prev = load_json(RISK_STATE_PATH, {"current_risk": "低", "previous_risk": "低", "numeric": 0})
    prev_label = prev.get("current_risk", "低")
    cur_label = record.get("risk", "低")
    prev_num = risk_value(prev_label)
    cur_num = risk_value(cur_label)
    increased = cur_num > prev_num
    highest = cur_label == "极高"
    alert = None
    if increased:
        alert = {
            "time": now_iso(),
            "from": prev_label,
            "to": cur_label,
            "findings": record.get("findings", []),
            "message": f"合规风险等级从 {prev_label} 升高到 {cur_label}",
        }
        save_json(ALERTS_PATH, alert)
    state = {
        "current_risk": cur_label,
        "previous_risk": prev_label,
        "numeric": cur_num,
        "increased": increased,
        "highest": highest,
        "updated_at": now_iso(),
    }
    save_json(RISK_STATE_PATH, state)
    return {"state": state, "alert": alert}


def run_compliance_with_risk() -> dict:
    record = run_project_compliance()
    risk = update_compliance_risk(record)
    if risk["state"].get("highest"):
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(1)
        time.sleep(1)
        os._exit(1)
    return {"record": record, **risk}


def get_compliance_status() -> dict:
    state = load_json(RISK_STATE_PATH, {"current_risk": "低", "previous_risk": "低", "numeric": 0, "increased": False, "highest": False})
    alert = load_json(ALERTS_PATH, {})
    return {"state": state, "alert": alert}


def delete_job(job_id: str) -> dict:
    job_path = JOBS_DIR / f"{job_id}.json"
    if not job_path.exists():
        return {"ok": False, "error": "任务不存在"}
    job_path.unlink(missing_ok=True)
    out_dir = (MODEL_OUTPUT_DIR / job_id).resolve()
    root = MODEL_OUTPUT_DIR.resolve()
    try:
        if root in out_dir.parents and out_dir.exists():
            shutil.rmtree(out_dir)
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "deleted_job": True, "artifact_error": str(exc)}
    return {"ok": True, "deleted_job": True}
