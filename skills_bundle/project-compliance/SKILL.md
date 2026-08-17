---
name: project-compliance
description: "Enforces legal compliance and human-values alignment for every file and action in the current project. Use before, during, or after creating, modifying, deleting, or publishing any project file (code, data, model, config, script, document, media, commit), and when auditing or reviewing the repository for legal, safety, privacy, or values-compliance risks."
---

# Project Compliance

对本项目的一切文件和实施动作做法律合规与人类价值观对齐检查。与项目根目录 `AGENTS.md` 配合使用：`AGENTS.md` 是始终生效的总规范，本技能提供可复用的审查流程、政策基准和静态扫描工具。

## 适用范围

- 覆盖本项目内所有文件与动作：代码、数据、模型、配置、脚本、文档、图片、音视频、提交信息、发布内容等。
- 覆盖实施全过程：创建、修改、删除、发布、自动化执行、依赖引入。

## 审查流程

1. 识别对象与风险面：文件路径、任务目标、计划动作、产出物；是否涉及个人数据、网络发布、自动化、知识产权、安全测试或第三方权益。
2. 运行静态初筛：`python scripts/audit_project.py <项目根目录>`。无论脚本结果如何，都继续做语义判断。
3. 对照 `references/safety-policy.md` 将风险分为四类：允许 / 需加保护措施 / 需修改后重审 / 禁止。
4. 对“禁止”或高风险事项：停止继续，说明违反的法律或价值观依据，给出不越线的替代做法；仅在用户明确确认后继续。
5. 输出固定结论。

## 硬性规则

- 对明确有害请求直接拒绝，不提供部分绕过方案。
- 发现个人数据处理、网络发布、自动化操作、安全研究、知识产权等高敏感事项时，要求确认授权、范围和最小化原则。
- 审查以现行官方法律文本和已确认事实为准；无法确认时，先停止并询问用户。

## 输出格式

```text
结论: 允许 / 需加保护措施 / 需修改后重审 / 禁止
风险等级: 低 / 中 / 高 / 极高
发现项:
- ...
依据:
- ...
必要修改:
- ...
替代方案:
- ...
升级处理: 是 / 否
说明: ...
```
