---
name: model-diagnostics
description: "模型评估诊断与自动返工闭环。在表格数据回归建模的评估阶段，读取 metrics.json、data_profile.json 与 test_predictions.csv，检测 R2/RMSE/MAE 指标异常和残差分布异常；异常时返回数据处理阶段，给出独热编码、频数编码、目标变换、缺失值与异常值处理等修正建议，并调用 $tabular-modeling 与 $math-modeling 重新建模、复诊和输出报告。Use when 用户要求诊断模型评估异常、发现 R2 过低或为负、RMSE/MAE 相对目标尺度偏大、残差非正态/异方差/存在离群点/自相关，或需要在评估后自动返回数据处理阶段并重新建模。"
---

# Model Diagnostics

## 目标

在模型评估阶段建立诊断与返工闭环：先量化评估指标和残差分布，发现异常后定位数据处理根因，修正预处理后重新调用建模技能，比较前后结果并给出可复核的结论。

## 合规门（必须先执行）

1. 读取并遵守当前项目 `AGENTS.md`。
2. 运行 `$project-compliance`：执行 `python scripts/audit_project.py <项目根目录>`，再按 `references/safety-policy.md` 做语义判断。
3. 调用 `$math-modeling` 的安全门，确认建模目标合法、数据来源与授权范围清晰；发现禁止项或不确定项时停止并询问。
4. 处理个人数据时最小化、匿名化，并确认告知同意。

## 输入

优先使用 `$tabular-modeling` 生成的建模输出目录，其中包含：

- `metrics.json`：编码决策、模型比较、最佳模型指标。
- `data_profile.json`：每列类型、缺失、唯一值、相关性、预处理决策。
- `test_predictions.csv`：测试集真实值与预测值。

## 工作流

### 1. 运行诊断脚本

```powershell
python scripts/run_diagnostics.py --output-dir <建模输出目录>
```

可选参数：

- `--r2-min 0.5`：R² 低于该值判为指标异常。
- `--nrmse-max 1.0`：RMSE / 目标标准差高于该值判为指标异常。
- `--data <原始数据路径>` `--target <目标列>`：同时读取原始数据，用于补充目标偏度和分类变量建议。
- `--diagnostics-out <路径>`：默认在输出目录写 `diagnostics.json` 与 `residual_plot.png`。

脚本会输出 `verdict`：

- `pass`：指标与残差分布均通过默认阈值。
- `review`：存在可疑信号，需人工复核。
- `remediate`：存在明显异常，必须返回数据处理阶段并重跑。

### 2. 若 `verdict` 为 pass

1. 继续调用 `$math-modeling`，用 `data_profile.json` 和 `metrics.json` 写正式模型文档。
2. 将结果、图表路径和不确定性写进最终报告，结束。

### 3. 若 `verdict` 为 review 或 remediate

1. 打开 `diagnostics.json` 与 `data_profile.json`，对照 `references/diagnostic-playbook.md` 定位根因。
2. 按以下优先级修改数据处理：

   - 对 `2 <= unique_count <= 20` 的分类变量，如果之前是频数编码或未编码，改为独热编码；若使用 `$tabular-modeling`，重跑时提高 `--cardinality-threshold` 至至少该列唯一值数。
   - 高基数分类变量保留频数编码或改用受监督编码，并说明选择依据。
   - 目标列明显右偏（`|skew| > 1`）时，考虑 `log1p` 或 Box-Cox 目标变换，并在反变换后重新计算 R²/RMSE/MAE。
   - 缺失值优先用训练集统计量填充；离群点采用 Winsorize 或稳健缩放，避免删除测试集样本。
   - 检查是否发生数据泄漏：预处理只能在训练集上拟合，再应用到验证集和测试集。
   - 检查残差与拟合值的结构：若存在曲线关系，增加非线性特征或换非线性模型。
3. 保存修改前的 `metrics.json`、`diagnostics.json` 与图表备份，便于前后对比。
4. 重新调用 `$tabular-modeling`：

   ```powershell
   python scripts/run_modeling.py --input <数据文件> --target <目标列> --output-dir <新输出目录> --cardinality-threshold <新阈值>
   ```

   如果是自定义建模流程，直接在数据处理阶段修改后再重跑。
5. 对新输出目录再次运行 `scripts/run_diagnostics.py`。
6. 最多迭代 3 次。若仍 `remediate` 或无法改善，停止自动返工并输出：

   - 已尝试的数据处理修改。
   - 每轮 R²/RMSE/MAE 与残差诊断结果。
   - 最可能的剩余根因与需要用户补充的数据、业务背景或建模约束。

### 4. 输出最终结果

按 `assets/report-template.md` 输出 Markdown 报告，至少包含：

- 结论：允许 / 需加保护措施 / 需修改后重审 / 禁止。
- 风险等级：低 / 中 / 高 / 极高。
- 每轮模型指标与残差诊断对比。
- 修改过的数据处理项及其依据。
- 最终最优模型、参数、测试集 R²/RMSE/MAE。
- 残差图路径与剩余不确定性。

## 规则

- 只用回归任务；目标列必须数值型且不能有缺失。
- 所有预处理决策和缩放器只能在训练集拟合，再应用到验证集和测试集。
- 不因返工修改测试集；测试集只用于最终评估。
- 默认最大返工 3 次，避免无限循环。
- 每次返工必须记录“原处理方式 -> 新处理方式 -> 原因 -> 效果对比”。
- 若用户没有明确授权重跑或数据敏感，先停止并询问，不自动发布或覆盖原始模型。

## 资源

- `scripts/run_diagnostics.py`：计算指标异常与残差分布异常。
- scripts/model_diagnostics.py：兼容旧调用的转发入口；新流程请直接使用 un_diagnostics.py。
- `references/diagnostic-playbook.md`：阈值、根因定位和处理修正映射。
- `assets/report-template.md`：最终诊断与返工报告模板。