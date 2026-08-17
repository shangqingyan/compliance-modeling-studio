# Model Pattern Miner Data Contract

## Data Root

Default `C:\Users\OseasyVM\.codex\model-patterns`. Override with `MODEL_PATTERN_DATA_DIR`.

Files:
- `registry.json`: list of normalized model records.
- `excellent_models.json`: records classified as excellent by the latest analysis.
- `patterns.json`: mined patterns.
- `preferences.json`: user feedback on patterns.
- `snapshots/`: timestamped import snapshots for audit.
- `reports/patterns.md` and `reports/excellent_models.md`: human-readable reports.

## Canonical ModelRecord

```json
{
  "id": "string",
  "source_id": "string",
  "name": "string",
  "platform": "string",
  "objective": "string",
  "target_variable": "string",
  "dataset": "string",
  "features": ["string"],
  "algorithm": "string",
  "hyperparameters": {},
  "sample_size": 0,
  "split": {},
  "metrics": {
    "train": {"r2": 0, "rmse": 0, "mae": 0},
    "test": {"r2": 0, "rmse": 0, "mae": 0},
    "cv": {"r2_mean": 0, "r2_std": 0}
  },
  "stability": {"overfit_gap": 0},
  "created_at": "string",
  "artifacts": ["string"],
  "tags": ["string"],
  "notes": "string",
  "evaluation": {"status": "excellent|below_threshold|incomplete", "warnings": ["string"]}
}
```

Required fields for import: `source_id` (or `id`) and `name`. Missing `metrics.test.r2` is allowed but produces `incomplete`.

## Excellence Rules

Read `config/thresholds.yaml`. The only hard gate enabled by default is `metrics.test.r2 >= 0.90`. Optional quality gates such as `test_rmse.max`, `test_mae.max`, `min_sample_size`, `max_overfit_gap`, `cv_r2_min`, and `cv_r2_std_max` are warnings only unless their value is set and the corresponding condition fails. They do not change the excellence status.

## Pattern Schema

```json
{
  "pattern_id": "string",
  "type": "algorithm|feature|hyperparameter|sample_size|overfit_gap",
  "statement": "string",
  "supporting_models": ["string"],
  "applies_when": ["string"],
  "does_not_apply_when": ["string"],
  "confidence": 0.0,
  "evidence": "string",
  "rationale": "string",
  "risks": ["string"],
  "last_updated": "string"
}
```

## Preference Schema

```json
{
  "pattern_id": "string",
  "vote": 1,
  "context": "string",
  "timestamp": "string"
}
```

## Field Mapping Example

`config/platform.yaml` maps canonical fields to source keys. A source row can be flat CSV or nested JSON.

CSV columns:
`model_id,name,algorithm,test_r2,train_r2,sample_size,features`

Field map:
`source_id: model_id`, `name: name`, `algorithm: algorithm`, `sample_size: sample_size`, `features: features`

Metric map:
`test_r2: test_r2`, `train_r2: train_r2`

The importer builds `metrics.test.r2` and `metrics.train.r2` from flat columns.
