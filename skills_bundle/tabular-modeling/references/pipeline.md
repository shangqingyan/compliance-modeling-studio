# Pipeline Details

## Input loading
- `.csv`: `pd.read_csv` with UTF-8 first, then GB18030.
- `.json`: `pd.read_json` first, then `lines=True`.
- `.xlsx/.xls`: `pd.read_excel`; if openpyxl is missing, exit with the command `python -m pip install openpyxl`.

## Validation before modeling
- Input file must exist and contain at least 5 rows.
- `--target` defaults to the last column.
- Target must be numeric or fully convertible to numeric.
- Target must not contain missing values.
- At least one non-target feature column must remain.

## Data split
- Split the full dataset deterministically with `random_state`:
  - first split: 60% train, 40% rest
  - second split: rest divided equally into 20% validation and 20% test
- No stratification; the task is regression.

## Preprocessing
- All decisions are fitted on the training split only.
- Drop columns that are all-missing or constant on the training split.
- Impute numeric columns with the median and categorical columns with the most frequent value.
- Classify columns:
  - numeric dtype -> numeric
  - object/category/bool or other non-numeric dtype -> categorical
- Low-cardinality categorical columns (unique count <= `--cardinality-threshold`, default 20):
  - one-hot encoding with `drop='first'` and `handle_unknown='ignore'`
- High-cardinality categorical columns (unique count > threshold):
  - frequency encoding from training frequencies; unseen categories map to 0
- Scale numeric columns with `StandardScaler` fitted on the training split only.

## Candidate training and selection
- Each candidate model and each hyperparameter combination is fitted on the 60% training split.
- Validation split is used only to record validation R2, RMSE, and MAE.
- Best model = highest validation R2; tie-break by lower validation RMSE.
- `--skip-tuning` limits each model to its first/default parameter set.

## Final evaluation
- After selection, refit a fresh preprocessing pipeline and the best estimator on train + validation (80%).
- Transform and evaluate only once on the 20% test split.
- Save all artifacts to the output directory.

## Error handling
- Exit code 2: input, target, or preprocessing validation error.
- Exit code 3: no candidate model trained successfully.
- Exit code 1: unexpected runtime error.

## Reproducibility
- Use the same `--random-state` to reproduce the same split and model-selection sequence.
- Tree, forest, and gradient-boosting estimators use `random_state=42` internally.
