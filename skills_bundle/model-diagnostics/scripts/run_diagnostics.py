#!/usr/bin/env python3
"""Model evaluation diagnostics for tabular regression outputs.

Reads a modeling output directory produced by tabular-modeling (metrics.json,
data_profile.json, test_predictions.csv), computes metric and residual-distribution
health checks, writes diagnostics.json, and optionally renders a residual plot.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def fail(msg: str, code: int = 2) -> None:
    print(f"[ERROR] {msg}")
    raise SystemExit(code)


def read_json(path: Path) -> dict:
    if not path.exists():
        fail(f"找不到文件：{path}", 2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        fail(f"JSON 解析失败：{path}", 2)
    return {}


def read_predictions(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if not path.exists():
        fail(f"找不到预测文件：{path}", 2)
    df = pd.read_csv(path)
    if "target" not in df.columns or "prediction" not in df.columns:
        fail(f"预测文件必须包含 target 和 prediction 两列：{path}", 2)
    y = pd.to_numeric(df["target"], errors="coerce").to_numpy(dtype=float)
    yhat = pd.to_numeric(df["prediction"], errors="coerce").to_numpy(dtype=float)
    mask = ~(np.isnan(y) | np.isnan(yhat))
    y = y[mask]
    yhat = yhat[mask]
    if len(y) < 5:
        fail(f"有效测试样本数不足：{len(y)}", 2)
    return y, yhat


def read_optional_data(path: Path | None, target: str | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if not path.exists():
        print(f"[WARN] 原始数据不存在，跳过补充建议：{path}")
        return None
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="gb18030")
    elif suffix == ".json":
        try:
            df = pd.read_json(path)
        except ValueError:
            df = pd.read_json(path, lines=True)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        print("[WARN] 仅支持 CSV/JSON/Excel 原始数据补充诊断。")
        return None
    if target and target not in df.columns:
        print(f"[WARN] 目标列 {target!r} 不在原始数据中，跳过补充建议。")
        return None
    return df


def safe_number(value: float | np.floating | None) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def nan_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def compute_diagnostics(y: np.ndarray, yhat: np.ndarray) -> dict:
    n = len(y)
    residual = y - yhat
    y_mean = float(np.mean(y))
    y_std = float(np.std(y, ddof=1)) if n > 1 else 1.0
    if y_std <= 1e-12:
        y_std = 1.0

    ss_res = float(np.sum(residual * residual))
    ss_tot = float(np.sum((y - y_mean) * (y - y_mean)))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else None
    rmse = float(np.sqrt(np.mean(residual * residual)))
    mae = float(np.mean(np.abs(residual)))
    nrmse = rmse / y_std
    mae_ratio = mae / y_std

    mean_resid = float(np.mean(residual))
    std_resid = float(np.std(residual, ddof=1)) if n > 1 else 0.0
    mean_resid_ratio = abs(mean_resid) / y_std

    skew = safe_number(stats.skew(residual))
    kurtosis = safe_number(stats.kurtosis(residual, fisher=True))
    target_skew = safe_number(stats.skew(y))

    if 8 <= n <= 5000:
        shapiro_w = safe_number(stats.shapiro(residual)[0])
        shapiro_p = safe_number(stats.shapiro(residual)[1])
    else:
        shapiro_w = None
        shapiro_p = None

    standardized = (residual - mean_resid) / std_resid if std_resid > 1e-12 else np.zeros(n)
    outlier_count = int(np.sum(np.abs(standardized) > 3))
    outlier_ratio = outlier_count / n

    hetero_rho = None
    hetero_p = None
    if n > 5 and np.std(np.abs(residual), ddof=1) > 1e-12 and np.std(yhat, ddof=1) > 1e-12:
        rho, p = stats.spearmanr(np.abs(residual), yhat)
        hetero_rho = safe_number(rho)
        hetero_p = safe_number(p)

    lag1_autocorr = None
    if n > 2 and np.std(residual[:-1], ddof=1) > 1e-12 and np.std(residual[1:], ddof=1) > 1e-12:
        lag1_autocorr = safe_number(np.corrcoef(residual[:-1], residual[1:])[0, 1])

    residual_slope = None
    if n > 2 and np.std(yhat, ddof=1) > 1e-12:
        try:
            residual_slope = safe_number(float(np.polyfit(yhat, residual, 1)[0]))
        except Exception:
            residual_slope = None

    return {
        "sample_size": n,
        "target_mean": safe_number(y_mean),
        "target_std": safe_number(y_std),
        "target_skew": target_skew,
        "r2": r2,
        "rmse": rmse,
        "mae": mae,
        "normalized_rmse": nrmse,
        "mae_ratio": mae_ratio,
        "mean_residual": mean_resid,
        "residual_std": std_resid,
        "mean_resid_ratio": mean_resid_ratio,
        "residual_skew": skew,
        "residual_kurtosis": kurtosis,
        "shapiro_w": shapiro_w,
        "shapiro_p": shapiro_p,
        "outlier_count": outlier_count,
        "outlier_ratio": outlier_ratio,
        "heteroscedastic_rho": hetero_rho,
        "heteroscedastic_p": hetero_p,
        "lag1_autocorr": lag1_autocorr,
        "residual_slope": residual_slope,
    }


def evaluate_flags(diag: dict, args: argparse.Namespace) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    severe: list[str] = []

    r2 = diag["r2"]
    nrmse = diag["normalized_rmse"]
    mae_ratio = diag["mae_ratio"]
    skew = diag["residual_skew"]
    kurtosis = diag["residual_kurtosis"]
    shapiro_p = diag["shapiro_p"]
    mean_resid_ratio = diag["mean_resid_ratio"]
    hetero_p = diag["heteroscedastic_p"]
    hetero_rho = diag["heteroscedastic_rho"]
    outlier_ratio = diag["outlier_ratio"]
    lag1 = diag["lag1_autocorr"]
    slope = diag["residual_slope"]

    if r2 is not None and r2 < args.r2_min:
        reasons.append(f"R2={r2:.4f} 低于阈值 {args.r2_min}")
        if r2 < 0:
            severe.append("R2 为负，模型差于均值模型")
    if nrmse > args.nrmse_max:
        reasons.append(f"标准化 RMSE={nrmse:.4f} 高于阈值 {args.nrmse_max}")
        if nrmse > 1.5:
            severe.append("标准化 RMSE 超过 1.5")
    if mae_ratio > 0.8:
        reasons.append(f"MAE/目标标准差={mae_ratio:.4f} 高于 0.8")
    if mean_resid_ratio > 0.5:
        reasons.append(f"残差均值相对目标标准差={mean_resid_ratio:.4f}，存在系统偏差")
    if shapiro_p is not None and shapiro_p < 0.05:
        reasons.append(f"Shapiro-Wilk p={shapiro_p:.4g}，残差显著偏离正态")
        if shapiro_p < 0.01:
            severe.append("残差严重偏离正态分布")
    if skew is not None and abs(skew) > 1.5:
        reasons.append(f"残差偏度={skew:.4f}，绝对值超过 1.5")
        if abs(skew) > 2.5:
            severe.append("残差偏度绝对值超过 2.5")
    if kurtosis is not None and abs(kurtosis) > 8:
        reasons.append(f"残差峰度={kurtosis:.4f}，绝对值超过 8")
    if hetero_p is not None and hetero_rho is not None and hetero_p < 0.05 and abs(hetero_rho) > 0.3:
        reasons.append(f"残差绝对值与拟合值 Spearman rho={hetero_rho:.4f}, p={hetero_p:.4g}，存在异方差信号")
        if abs(hetero_rho) > 0.6:
            severe.append("存在较强异方差")
    if outlier_ratio > 0.05:
        reasons.append(f"标准化残差离群点比例={outlier_ratio:.4f}，超过 0.05")
        if outlier_ratio > 0.15:
            severe.append("离群点比例过高")
    if lag1 is not None and abs(lag1) > 0.7:
        reasons.append(f"残差一阶自相关={lag1:.4f}，绝对值超过 0.7")
        severe.append("残差强自相关")
    if slope is not None and abs(slope) > 0.1:
        reasons.append(f"残差对拟合值斜率={slope:.4f}，模型结构可能不足")

    return reasons, severe


def build_suggestions(
    diag: dict,
    metrics: dict | None,
    profile: dict | None,
    data: pd.DataFrame | None,
    target: str | None,
    max_onehot_cardinality: int,
) -> list[str]:
    suggestions: list[str] = []
    suggested_cols: set[str] = set()
    one_hot = set(metrics.get("encoding", {}).get("one_hot_columns", [])) if metrics else set()
    freq = set(metrics.get("encoding", {}).get("frequency_encoded_columns", [])) if metrics else set()

    if profile and isinstance(profile.get("feature_profile"), list):
        for item in profile["feature_profile"]:
            col = item.get("column")
            dtype = str(item.get("dtype", "")).lower()
            unique = item.get("unique_count")
            decision = str(item.get("preprocessing_decision", ""))
            if not isinstance(col, str) or not isinstance(unique, (int, float)):
                continue
            unique = int(unique)
            is_categorical = any(part in dtype for part in ("object", "category", "bool", "str"))
            if is_categorical and 2 <= unique <= max_onehot_cardinality:
                if col in freq or "频数编码" in decision:
                    suggestions.append(
                        f"将分类列 {col} 从频数编码改为独热编码；唯一值 {unique} ≤ {max_onehot_cardinality}。"
                    )
                    suggested_cols.add(col)
                elif col not in one_hot and "独热编码" not in decision and "删除" not in decision:
                    suggestions.append(f"对分类列 {col} 应用独热编码（唯一值 {unique}）。")
                    suggested_cols.add(col)

    if data is not None and target is not None and target in data.columns:
        for col in data.columns:
            if col == target:
                continue
            if any(part in str(data[col].dtype).lower() for part in ("object", "category", "bool", "str")):
                unique = int(data[col].nunique(dropna=True))
                if 2 <= unique <= max_onehot_cardinality and col not in one_hot and col not in suggested_cols:
                    suggestions.append(f"原始数据中分类列 {col} 唯一值为 {unique}，建议独热编码。")
                    suggested_cols.add(col)

    if diag.get("target_skew") is not None and abs(float(diag["target_skew"])) > 1.0:
        suggestions.append(
            f"目标列偏度为 {diag['target_skew']:.4f}，考虑 log1p 或 Box-Cox 目标变换后重新建模。"
        )
    if diag.get("outlier_ratio", 0) > 0.05:
        suggestions.append("残差离群点比例偏高，检查原始数据异常值并考虑 Winsorize 或稳健缩放。")
    if diag.get("heteroscedastic_rho") is not None and diag.get("heteroscedastic_p", 1) < 0.05:
        suggestions.append("存在异方差信号，考虑对数目标、加权回归或广义线性模型。")
    if diag.get("lag1_autocorr") is not None and abs(float(diag["lag1_autocorr"])) > 0.7:
        suggestions.append("残差存在强自相关，检查时间顺序、滞后项和切分方式。")

    seen: set[str] = set()
    deduped: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def render_plot(y: np.ndarray, yhat: np.ndarray, out_path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("[WARN] matplotlib 不可用，跳过残差图。")
        return False

    residual = y - yhat
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    ax = axes[0, 0]
    ax.scatter(yhat, residual, alpha=0.6, s=20)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_xlabel("Prediction")
    ax.set_ylabel("Residual")
    ax.set_title("Residual vs Fitted")

    ax = axes[0, 1]
    ax.hist(residual, bins="auto", alpha=0.7, color="#3B82F6")
    ax.set_xlabel("Residual")
    ax.set_ylabel("Count")
    ax.set_title("Residual Histogram")

    ax = axes[1, 0]
    stats.probplot(residual, dist="norm", plot=ax)
    ax.set_title("Normal Q-Q Plot")

    ax = axes[1, 1]
    ax.scatter(y, yhat, alpha=0.6, s=20)
    limits = [min(float(np.min(y)), float(np.min(yhat))), max(float(np.max(y)), float(np.max(yhat)))]
    ax.plot(limits, limits, color="red", linewidth=1, linestyle="--")
    ax.set_xlabel("Target")
    ax.set_ylabel("Prediction")
    ax.set_title("Predicted vs Actual")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="模型评估诊断脚本")
    parser.add_argument("--output-dir", type=Path, help="建模输出目录，需包含 metrics.json、data_profile.json、test_predictions.csv")
    parser.add_argument("--metrics", type=Path, help="metrics.json 路径；未提供时从 --output-dir 读取")
    parser.add_argument("--predictions", type=Path, help="test_predictions.csv 路径；未提供时从 --output-dir 读取")
    parser.add_argument("--data", type=Path, help="原始数据 CSV/JSON/Excel 路径，用于补充编码与目标偏度建议")
    parser.add_argument("--target", type=str, help="目标列名，与 --data 配合使用")
    parser.add_argument("--diagnostics-out", type=Path, help="diagnostics.json 输出路径；默认与预测文件同目录")
    parser.add_argument("--r2-min", type=float, default=0.5, help="R2 指标异常阈值，默认 0.5")
    parser.add_argument("--nrmse-max", type=float, default=1.0, help="标准化 RMSE 指标异常阈值，默认 1.0")
    parser.add_argument("--max-onehot-cardinality", type=int, default=20, help="建议独热编码的最大唯一值数，默认 20")
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    metrics_path = args.metrics or (output_dir / "metrics.json" if output_dir else None)
    predictions_path = args.predictions or (output_dir / "test_predictions.csv" if output_dir else None)
    profile_path = output_dir / "data_profile.json" if output_dir else None

    if metrics_path is None or predictions_path is None:
        fail("必须提供 --output-dir，或同时提供 --metrics 和 --predictions。", 2)

    y, yhat = read_predictions(Path(predictions_path))
    diag = compute_diagnostics(y, yhat)

    metrics = read_json(Path(metrics_path)) if Path(metrics_path).exists() else None
    profile = read_json(Path(profile_path)) if profile_path and Path(profile_path).exists() else None
    data = read_optional_data(args.data, args.target)

    reasons, severe = evaluate_flags(diag, args)
    if severe:
        verdict = "remediate"
    elif reasons:
        verdict = "review"
    else:
        verdict = "pass"

    suggestions = build_suggestions(diag, metrics, profile, data, args.target, args.max_onehot_cardinality)

    diagnostics_out = args.diagnostics_out or (Path(predictions_path).parent / "diagnostics.json")
    diagnostics_out.parent.mkdir(parents=True, exist_ok=True)
    plot_out = diagnostics_out.parent / "residual_plot.png"
    plot_written = render_plot(y, yhat, plot_out)

    payload = {
        "verdict": verdict,
        "reasons": reasons,
        "severe_signals": severe,
        "diagnostics": diag,
        "suggestions": suggestions,
        "artifacts": {
            "metrics": str(metrics_path),
            "predictions": str(predictions_path),
            "data_profile": str(profile_path) if profile_path else None,
            "residual_plot": str(plot_out) if plot_written else None,
        },
    }
    diagnostics_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print("[OK] 模型评估诊断完成")
    print(f"[OK] 判定：{verdict}")
    if reasons:
        for r in reasons:
            print(f"  - {r}")
    else:
        print("  - 未发现异常信号")
    if suggestions:
        print("[OK] 返工建议：")
        for s in suggestions:
            print(f"  - {s}")
    print(f"[OK] 诊断结果：{diagnostics_out}")
    if plot_written:
        print(f"[OK] 残差图：{plot_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())