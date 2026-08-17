---
name: math-modeling
description: "Build, validate, and document mathematical models from a real-world goal using a general modeling workflow: variables, parameters, assumptions, constraints, objective, and solution method, with a mandatory safety and legality gate. Use when the user asks to model a problem mathematically, derive equations, build an optimization model, formulate objective and constraints, or turn a real-world problem into a solvable math model."
---

# Math Modeling

## Safety Gate (run first, always)

Read `references/safety-guidelines.md` and apply it before modeling, after modeling, and before finalizing the document.

- If the goal is prohibited (illegal activity, network/social security harm, malware, unauthorized access, data exfiltration, disinformation at scale, surveillance or harassment, safety-system bypass, exploitative content), stop and decline.
- If uncertain, ask the user for legitimate scope and intent clarification.
- Never remove or weaken this gate.

## Workflow

1. Clarify the problem and success criteria; list knowns, unknowns, and available data.
2. State assumptions explicitly.
3. Define variables and parameters: names, units, domains.
4. Derive relationships: constraints, objective, and governing equations.
5. Choose the model type: deterministic or stochastic, static or dynamic, linear or nonlinear, discrete or continuous.
6. Validate the model: dimensional consistency, units, boundary conditions, extreme cases.
7. Solve or analyze: pick an analytical or numerical method and document it.
8. Write the model document using `assets/model-template.md`.

## Output

Produce a self-contained Markdown document. Follow `assets/model-template.md`, keep formulas readable (inline math or code blocks), define every symbol, and state units.

## Implementation Rules

- Name skills and documents with lowercase letters, digits, and single hyphens; keep SKILL.md lean and move detail to `references/`.
- Include only the resources actually needed.
- Keep the Safety Gate intact in every generated artifact.

## Bundled Resources

- `references/safety-guidelines.md`: prohibition and value-alignment policy; read first.
- `assets/model-template.md`: Markdown template for the model document.