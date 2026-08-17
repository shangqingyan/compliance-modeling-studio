# Report Template

Use this structure for the final `report.md`. The script already generates a complete report; after invoking `$math-modeling`, ensure `math-model.md` exists and is linked.

```markdown
# 表格数据回归建模报告

- 目标列
- 样本数与特征数
- 候选模型与调参策略
- 切分数量：训练 60% / 验证 20% / 测试 20%

## 数据画像
- 每列类型、缺失数、唯一值数、与目标相关性、处理方式

## 模型比较（验证集）
- 模型、参数、验证 R2、RMSE、MAE

## 最优模型
- 模型名、参数、测试集 R2、RMSE、MAE

## 正式数学模型文档
- 链接到 `math-model.md`

## 产物清单
- best_model.joblib
- preprocessing_pipeline.joblib
- metrics.json
- model_comparison.csv
- test_predictions.csv
- data_profile.json
```

For `math-model.md`, follow the `math-modeling` skill's `assets/model-template.md`.
