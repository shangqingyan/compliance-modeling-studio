# 合规建模智能网页

本地深色科技风 Web 应用，用于上传 CSV/Excel 数据、执行表格回归建模、诊断与可视化、接收用户反馈并触发重建，并将技能学习、技能评估、项目合规与 Sunny 监督纳入闭环。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。

## 功能模块

- 数据建模：上传 CSV/Excel/JSON，选择目标列，启动建模。
- 诊断与可视化：模型对比、预测 vs 实际、残差图、数学文档、优秀模型规律。
- 反馈重建：1–5 星评分 + 文字反馈，低分或勾选重建会创建新任务。
- 技能迭代学习：查看已安装技能、查找新技能、生成学习草稿、批准安装/删除。
- 技能权重评估：执行 `skill-review` dry-run，查看权重与删除候选，批准后删除。
- 合规审计日志：运行并查看 `project-compliance` 与 `sunny` 的固定审计结论。

## 关键路径

- `app.py`：FastAPI 路由、文件上传、任务创建、静态资源挂载。
- `orchestrator.py`：建模/诊断/返工编排、技能学习与评估、合规审计、模式登记。
- `frontend/index.html`：单页前端。
- `data/`：运行时任务、反馈、技能状态、审计日志（不纳入 Git）。
