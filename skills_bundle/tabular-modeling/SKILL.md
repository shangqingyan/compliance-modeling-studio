---
name: tabular-modeling
description: "Analyze tabular data, decide one-hot vs frequency encoding, build linear/nonlinear regression models, split data 60/20/20 into train/validation/test, compare models, evaluate with R2/RMSE/MAE, save the best model, and produce a formal math model via $math-modeling. Use when the user asks to model, preprocess, standardize, encode, train, evaluate, or select a regression model from CSV/JSON/Excel data."
---

# Tabular Modeling

## Compliance Gate (run first, always)

Read and follow the current project `AGENTS.md` and run `project-compliance` before creating, reading, or publishing any artifact. Apply the `$math-modeling` safety gate before and after modeling. Decline prohibited tasks and ask for clarification when uncertain.

## Workflow

1. Locate the user-provided data file and confirm its path.
2. Run `scripts/run_modeling.py` to perform data diagnosis, preprocessing, 60/20/20 splitting, candidate model training, validation-based selection, and test evaluation.
3. Review the generated `data_profile.json` and `metrics.json`.
4. Invoke `$math-modeling` with the data profile and best-model metrics. Follow its safety gate and `assets/model-template.md` to write `math-model.md` in the output directory.
5. Confirm `report.md` references `math-model.md`, then return the output directory path, best model name/parameters, and test R2/RMSE/MAE to the user.

## CLI

```bash
python scripts/run_modeling.py --input <file> [--target <column>] [--output-dir <dir>] [--random-state 42] [--cardinality-threshold 20] [--models linear,ridge,lasso,decision_tree,random_forest,gradient_boosting,svr] [--skip-tuning]
```

- `--input`: CSV, JSON, or Excel path. CSV tries UTF-8 then GB18030. Excel requires openpyxl.
- `--target`: optional target column; defaults to the last column.
- `--output-dir`: optional output directory; defaults to `modeling_outputs/<timestamp>`.
- `--models`: optional comma-separated candidate models; defaults to all supported regression models.
- `--skip-tuning`: use default parameters only.

## Rules

- Use regression only. The target must be numeric and must not contain missing values.
- Fit all preprocessing decisions and scalers on training data only; apply them to validation and test.
- Use exactly 60% train, 20% validation, 20% test with a deterministic shuffle.
- Select the best model by validation R2; retrain it on train+validation; evaluate only once on test.
- Do not edit test data and do not use test metrics to select the model.

## Resources

- `references/pipeline.md`: detailed pipeline decisions and failure handling.
- `references/model-menu.md`: candidate models and hyperparameter grids.
- `assets/report-template.md`: report structure for `report.md` and `math-model.md`.
- `scripts/run_modeling.py`: deterministic executable pipeline.
