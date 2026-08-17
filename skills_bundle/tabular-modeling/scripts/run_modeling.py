#!/usr/bin/env python3
"""Deterministic tabular regression modeling CLI for the tabular-modeling skill.

Pipeline:
  load -> basic validation -> 60/20/20 split -> fit preprocessor on train only
  -> grid-search candidates on train and validation -> retrain best on train+val
  -> evaluate on test -> save artifacts and report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

DEFAULT_MODELS = [
    "linear",
    "ridge",
    "lasso",
    "decision_tree",
    "random_forest",
    "gradient_boosting",
    "svr",
]

MODEL_SPECS = {
    "linear": {
        "factory": lambda: LinearRegression(),
        "params": [{}],
    },
    "ridge": {
        "factory": lambda: Ridge(),
        "params": [{"alpha": a} for a in (0.1, 1.0, 10.0, 100.0)],
    },
    "lasso": {
        "factory": lambda: Lasso(max_iter=10000),
        "params": [{"alpha": a} for a in (0.001, 0.01, 0.1, 1.0)],
    },
    "decision_tree": {
        "factory": lambda: DecisionTreeRegressor(random_state=42),
        "params": [{"max_depth": d} for d in (3, 5, 7, None)],
    },
    "random_forest": {
        "factory": lambda: RandomForestRegressor(random_state=42, n_jobs=-1),
        "params": [
            {"n_estimators": n, "max_depth": d}
            for n in (100, 200)
            for d in (None, 5, 10)
        ],
    },
    "gradient_boosting": {
        "factory": lambda: GradientBoostingRegressor(random_state=42),
        "params": [
            {"n_estimators": n, "learning_rate": lr}
            for n in (100, 200)
            for lr in (0.05, 0.1)
        ],
    },
    "svr": {
        "factory": lambda: SVR(),
        "params": [
            {"C": c, "kernel": k}
            for c in (0.1, 1.0, 10.0)
            for k in ("rbf", "linear")
        ],
    },
}


def fail(message: str, code: int = 1) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(code)


class Preprocessor:
    """Fit preprocessing decisions on train data only, then transform new splits."""

    def __init__(self, cardinality_threshold: int = 20) -> None:
        self.cardinality_threshold = cardinality_threshold

    def fit(self, X: pd.DataFrame) -> "Preprocessor":
        self.drop_cols_ = [
            c
            for c in X.columns
            if X[c].isna().all() or X[c].nunique(dropna=True) <= 1
        ]
        X_keep = X.drop(columns=self.drop_cols_)

        self.num_cols_ = [
            c for c in X_keep.columns if pd.api.types.is_numeric_dtype(X_keep[c])
        ]
        self.cat_cols_ = [c for c in X_keep.columns if c not in self.num_cols_]

        self.num_imputer_ = SimpleImputer(strategy="median")
        if self.num_cols_:
            self.num_imputer_.fit(X_keep[self.num_cols_].astype(float))

        self.cat_imputer_ = SimpleImputer(strategy="most_frequent")
        if self.cat_cols_:
            self.cat_imputer_.fit(X_keep[self.cat_cols_].astype(object))

        if self.cat_cols_:
            cat_imputed = pd.DataFrame(
                self.cat_imputer_.transform(X_keep[self.cat_cols_].astype(object)),
                columns=self.cat_cols_,
                index=X_keep.index,
            ).astype(str)
            self.onehot_cols_ = [
                c
                for c in self.cat_cols_
                if cat_imputed[c].nunique(dropna=False) <= self.cardinality_threshold
            ]
            self.freq_cols_ = [
                c for c in self.cat_cols_ if c not in self.onehot_cols_
            ]
            self.freq_maps_ = {
                c: cat_imputed[c].value_counts(normalize=True).to_dict()
                for c in self.freq_cols_
            }
        else:
            self.onehot_cols_ = []
            self.freq_cols_ = []
            self.freq_maps_ = {}

        self.ohe_ = OneHotEncoder(drop="first", handle_unknown="ignore", sparse_output=False)
        if self.onehot_cols_:
            cat_imputed = pd.DataFrame(
                self.cat_imputer_.transform(X_keep[self.cat_cols_].astype(object)),
                columns=self.cat_cols_,
                index=X_keep.index,
            ).astype(str)
            self.ohe_.fit(cat_imputed[self.onehot_cols_])

        self.scaler_ = StandardScaler()
        if self.num_cols_:
            num_imputed = pd.DataFrame(
                self.num_imputer_.transform(X_keep[self.num_cols_].astype(float)),
                columns=self.num_cols_,
                index=X_keep.index,
            )
            self.scaler_.fit(num_imputed)

        if not self.num_cols_ and not self.cat_cols_:
            raise ValueError("没有可用于建模的特征列。")

        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X_keep = X.drop(columns=self.drop_cols_, errors="ignore")
        parts: list[pd.DataFrame] = []

        if self.num_cols_:
            num_imputed = pd.DataFrame(
                self.num_imputer_.transform(X_keep[self.num_cols_].astype(float)),
                columns=self.num_cols_,
                index=X_keep.index,
            )
            scaled = self.scaler_.transform(num_imputed)
            parts.append(
                pd.DataFrame(scaled, columns=self.num_cols_, index=X_keep.index)
            )

        if self.cat_cols_:
            cat_imputed = pd.DataFrame(
                self.cat_imputer_.transform(X_keep[self.cat_cols_].astype(object)),
                columns=self.cat_cols_,
                index=X_keep.index,
            ).astype(str)
            if self.onehot_cols_:
                ohe = self.ohe_.transform(cat_imputed[self.onehot_cols_])
                ohe_names = list(self.ohe_.get_feature_names_out(self.onehot_cols_))
                parts.append(
                    pd.DataFrame(ohe, columns=ohe_names, index=X_keep.index)
                )
            for col in self.freq_cols_:
                vals = cat_imputed[col].map(self.freq_maps_).fillna(0.0).astype(float)
                parts.append(pd.DataFrame({f"freq_{col}": vals}, index=X_keep.index))

        if not parts:
            raise ValueError("预处理后没有可用特征。")

        return pd.concat(parts, axis=1)

    def decision_for(self, column: str) -> str:
        if column in self.drop_cols_:
            return "删除（全空或常量）"
        if column in self.onehot_cols_:
            return "独热编码"
        if column in self.freq_cols_:
            return "频数编码"
        if column in self.num_cols_:
            return "标准化"
        return "未使用"


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"输入文件不存在：{path}", 2)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return pd.read_csv(path, encoding="gb18030")
            except Exception as exc:  # noqa: BLE001
                fail(f"CSV 读取失败：{exc}", 2)
        except Exception as exc:  # noqa: BLE001
            fail(f"CSV 读取失败：{exc}", 2)

    if suffix == ".json":
        try:
            return pd.read_json(path)
        except Exception:  # noqa: BLE001
            try:
                return pd.read_json(path, lines=True)
            except Exception as exc:  # noqa: BLE001
                fail(f"JSON 读取失败：{exc}", 2)

    if suffix in {".xlsx", ".xls"}:
        try:
            return pd.read_excel(path)
        except ImportError:
            fail("读取 Excel 需要 openpyxl；请先运行：python -m pip install openpyxl", 2)
        except Exception as exc:  # noqa: BLE001
            fail(f"Excel 读取失败：{exc}", 2)

    fail(f"不支持的输入格式：{suffix or '无扩展名'}", 2)
    raise AssertionError("unreachable")


def as_numeric_target(series: pd.Series, target: str) -> pd.Series:
    if not pd.api.types.is_numeric_dtype(series):
        converted = pd.to_numeric(series, errors="coerce")
        if converted.isna().any():
            fail(f"目标列 '{target}' 不是有效数值列，或包含无法转换为数字的值。", 2)
        return converted
    return series


def metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "rmse": float(mean_squared_error(y_true, y_pred) ** 0.5),
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }


def build_model(model_name: str, params: dict):
    spec = MODEL_SPECS[model_name]
    estimator = spec["factory"]()
    estimator.set_params(**params)
    return estimator


def build_profile(df: pd.DataFrame, target: str, preprocessor: Preprocessor) -> dict:
    columns = []
    for col in df.columns:
        if col == target:
            continue
        corr = None
        if pd.api.types.is_numeric_dtype(df[col]):
            try:
                corr = float(df[col].corr(pd.to_numeric(df[target], errors="coerce")))
            except Exception:  # noqa: BLE001
                corr = None
        columns.append(
            {
                "column": col,
                "dtype": str(df[col].dtype),
                "missing_count": int(df[col].isna().sum()),
                "missing_ratio": float(df[col].isna().mean()),
                "unique_count": int(df[col].nunique(dropna=True)),
                "correlation_with_target": corr,
                "preprocessing_decision": preprocessor.decision_for(col),
            }
        )
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "target": target,
        "feature_count": int(df.shape[1] - 1),
        "feature_profile": columns,
    }


def generate_report(
    output_dir: Path,
    data_profile: dict,
    target: str,
    split_sizes: dict[str, int],
    comparison_rows: list[dict],
    best: dict,
    test_metrics: dict,
    model_names: list[str],
    skip_tuning: bool,
    cardinality_threshold: int,
) -> None:
    lines = [
        "# 表格数据回归建模报告",
        "",
        f"- 目标列：`{target}`",
        f"- 样本数：{data_profile['rows']}",
        f"- 特征数：{data_profile['columns'] - 1}",
        f"- 候选模型：{', '.join(model_names)}",
        f"- 调参：{'关闭' if skip_tuning else '基础网格搜索'}",
        f"- 分类独热阈值：≤ {cardinality_threshold}",
        f"- 切分：训练 {split_sizes['train']} / 验证 {split_sizes['validation']} / 测试 {split_sizes['test']}",
        "",
        "## 数据画像",
        "",
        "| 列 | 类型 | 缺失数 | 缺失率 | 唯一值 | 与目标相关 | 处理方式 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in data_profile["feature_profile"]:
        corr = (
            f"{item['correlation_with_target']:.4f}"
            if item["correlation_with_target"] is not None
            else "-"
        )
        lines.append(
            f"| {item['column']} | {item['dtype']} | {item['missing_count']} "
            f"| {item['missing_ratio']:.3%} | {item['unique_count']} | {corr} | {item['preprocessing_decision']} |"
        )

    lines += [
        "",
        "## 模型比较（验证集）",
        "",
        "| 模型 | 参数 | R² | RMSE | MAE |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in comparison_rows:
        lines.append(
            f"| {row['model']} | {json.dumps(row['params'], ensure_ascii=False)} "
            f"| {row['validation_r2']:.6f} | {row['validation_rmse']:.6f} | {row['validation_mae']:.6f} |"
        )

    lines += [
        "",
        "## 最优模型",
        "",
        f"- 模型：`{best['model']}`",
        f"- 参数：`{json.dumps(best['params'], ensure_ascii=False)}`",
        "",
        "### 测试集最终评估（20% 留出集）",
        "",
        f"- R²：{test_metrics['r2']:.6f}",
        f"- RMSE：{test_metrics['rmse']:.6f}",
        f"- MAE：{test_metrics['mae']:.6f}",
        "",
        "## 正式数学模型文档",
        "",
        "见 `math-model.md`（由 `$math-modeling` 按安全门与模板生成）。",
        "",
        "## 产物清单",
        "",
        "- `best_model.joblib`：最优模型",
        "- `preprocessing_pipeline.joblib`：预处理流水线",
        "- `metrics.json`：指标与比较",
        "- `model_comparison.csv`：候选模型比较",
        "- `test_predictions.csv`：测试集真实值与预测值",
        "- `data_profile.json`：数据画像与编码决策",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="表格数据回归建模流水线")
    parser.add_argument("--input", required=True, help="输入 CSV/JSON/Excel 文件路径")
    parser.add_argument("--target", default=None, help="目标列名；默认最后一列")
    parser.add_argument("--output-dir", default=None, help="输出目录；默认 modeling_outputs/<时间戳>")
    parser.add_argument("--random-state", type=int, default=42, help="随机种子，默认 42")
    parser.add_argument("--cardinality-threshold", type=int, default=20, help="独热编码最大分类数，默认 20")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS), help="逗号分隔候选模型，默认全部")
    parser.add_argument("--skip-tuning", action="store_true", help="关闭基础调参，仅使用默认参数")
    args = parser.parse_args(argv)

    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_names:
        fail("--models 不能为空。", 2)
    for name in model_names:
        if name not in MODEL_SPECS:
            fail(f"未知模型 '{name}'。可用模型：{', '.join(MODEL_SPECS)}", 2)

    df = load_data(Path(args.input))
    if df.empty:
        fail("输入数据为空。", 2)
    if df.shape[0] < 5:
        fail("样本数过少，至少需要 5 行以满足 60/20/20 切分。", 2)

    target = args.target if args.target is not None else df.columns[-1]
    if target not in df.columns:
        fail(f"目标列 '{target}' 不存在。可用列：{list(df.columns)}", 2)

    target_series = as_numeric_target(df[target], target)
    if target_series.isna().any():
        fail(f"目标列 '{target}' 存在缺失值，请先处理目标列。", 2)

    feature_df = df.drop(columns=[target])
    if feature_df.shape[1] == 0:
        fail("没有可用于建模的特征列。", 2)

    # 60/20/20 split, shuffle deterministic.
    X_train, X_rest, y_train, y_rest = train_test_split(
        feature_df,
        target_series,
        test_size=0.4,
        random_state=args.random_state,
        shuffle=True,
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_rest,
        y_rest,
        test_size=0.5,
        random_state=args.random_state,
        shuffle=True,
    )

    # Selection preprocessor fit on train only.
    selection_preprocessor = Preprocessor(cardinality_threshold=args.cardinality_threshold)
    selection_preprocessor.fit(X_train)
    X_train_pp = selection_preprocessor.transform(X_train)
    X_val_pp = selection_preprocessor.transform(X_val)

    comparison_rows: list[dict] = []
    best_record: dict | None = None
    for model_name in model_names:
        spec = MODEL_SPECS[model_name]
        param_sets = spec["params"] if not args.skip_tuning else spec["params"][:1]
        for params in param_sets:
            estimator = build_model(model_name, params)
            try:
                estimator.fit(X_train_pp, y_train)
                pred_val = estimator.predict(X_val_pp)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 模型 {model_name} 参数 {params} 训练失败：{exc}", file=sys.stderr)
                continue
            m = metrics(y_val, pred_val)
            comparison_rows.append(
                {
                    "model": model_name,
                    "params": params,
                    "validation_r2": m["r2"],
                    "validation_rmse": m["rmse"],
                    "validation_mae": m["mae"],
                }
            )
            if best_record is None or (
                m["r2"],
                -m["rmse"],
            ) > (
                best_record["validation_r2"],
                -best_record["validation_rmse"],
            ):
                best_record = {
                    "model": model_name,
                    "params": params,
                    "validation_r2": m["r2"],
                    "validation_rmse": m["rmse"],
                    "validation_mae": m["mae"],
                }

    if not comparison_rows or best_record is None:
        fail("没有模型训练成功，无法选择最优模型。", 3)

    # Final retrain on train+validation with a freshly fit preprocessor.
    X_dev = pd.concat([X_train, X_val], axis=0)
    y_dev = pd.concat([y_train, y_val], axis=0)
    final_preprocessor = Preprocessor(cardinality_threshold=args.cardinality_threshold)
    final_preprocessor.fit(X_dev)
    X_dev_pp = final_preprocessor.transform(X_dev)
    X_test_pp = final_preprocessor.transform(X_test)

    best_estimator = build_model(best_record["model"], best_record["params"])
    best_estimator.fit(X_dev_pp, y_dev)
    pred_test = best_estimator.predict(X_test_pp)
    test_metrics = metrics(y_test, pred_test)

    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd() / "modeling_outputs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(best_estimator, output_dir / "best_model.joblib")
    joblib.dump(final_preprocessor, output_dir / "preprocessing_pipeline.joblib")

    data_profile = build_profile(df, target, final_preprocessor)
    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df.to_csv(output_dir / "model_comparison.csv", index=False, encoding="utf-8-sig")

    test_predictions = pd.DataFrame({"target": y_test.values, "prediction": pred_test})
    test_predictions.to_csv(output_dir / "test_predictions.csv", index=False, encoding="utf-8-sig")

    metrics_payload = {
        "target": target,
        "split": {
            "train": int(len(X_train)),
            "validation": int(len(X_val)),
            "test": int(len(X_test)),
        },
        "encoding": {
            "one_hot_columns": list(final_preprocessor.onehot_cols_),
            "frequency_encoded_columns": list(final_preprocessor.freq_cols_),
            "scaled_numeric_columns": list(final_preprocessor.num_cols_),
            "dropped_columns": list(final_preprocessor.drop_cols_),
        },
        "model_comparison": comparison_rows,
        "best_model": {
            "name": best_record["model"],
            "params": best_record["params"],
            "validation_r2": best_record["validation_r2"],
            "validation_rmse": best_record["validation_rmse"],
            "validation_mae": best_record["validation_mae"],
            "test_r2": test_metrics["r2"],
            "test_rmse": test_metrics["rmse"],
            "test_mae": test_metrics["mae"],
        },
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "data_profile.json").write_text(
        json.dumps(data_profile, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    generate_report(
        output_dir=output_dir,
        data_profile=data_profile,
        target=target,
        split_sizes=metrics_payload["split"],
        comparison_rows=comparison_rows,
        best=best_record,
        test_metrics=test_metrics,
        model_names=model_names,
        skip_tuning=args.skip_tuning,
        cardinality_threshold=args.cardinality_threshold,
    )

    print(f"[OK] 最优模型：{best_record['model']}")
    print(f"[OK] 测试集 R2={test_metrics['r2']:.6f}, RMSE={test_metrics['rmse']:.6f}, MAE={test_metrics['mae']:.6f}")
    print(f"[OK] 输出目录：{output_dir}")
    print("[OK] 请调用 $math-modeling，使用 data_profile.json 与 metrics.json 生成 math-model.md。")


if __name__ == "__main__":
    main()
