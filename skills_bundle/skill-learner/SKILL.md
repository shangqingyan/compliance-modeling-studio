---
name: skill-learner
description: Autonomously learn, model, and build reusable Codex skills from a user-provided goal, with mandatory safety, legality, and human-values alignment gates. Use when the user asks to learn a skill for a goal, build, model, generate, teach, or extend an agent skill, evolve a skill from feedback, or turn a task into a reusable skill; also use when asked to autonomously extend agent capabilities.
---

# Skill Learner

## Safety Gate (run first, always)

Read `references/safety-guidelines.md` and apply its screening to the goal before any modeling or building.

- If the goal is prohibited (illegal activity, network/social security harm, malware, unauthorized access, credential/data exfiltration, disinformation at scale, surveillance or harassment, safety-system bypass, exploitative content), stop and decline. Do not model, scaffold, or write anything.
- If uncertain, ask the user for legitimate scope and intent clarification; keep any output minimal, defensive, and reviewable.
- Re-run the gate after modeling and again before publishing a skill. Never remove or weaken it.

## Workflow

1. Restate the goal and success criteria. Confirm audience, in/out of scope, and constraints. Ask only for genuinely ambiguous, high-impact details.
2. Search for an existing skill first (use the `find-skills` skill, `npx skills find <query>`, or skills.sh) and reuse it instead of duplicating it.
3. Model the skill before writing it by filling the Skill Model fields below.
4. Apply the Safety Gate to the model: goals, steps, resources, and outputs.
5. Implement the skill under `$CODEX_HOME/skills/<skill-name>` (default `~/.codex/skills`): write SKILL.md with `name` and `description` frontmatter plus an imperative body, and add only the resources the workflow actually needs.
6. Validate frontmatter and naming, then run any available skill validator.
7. Report the skill name, location, and that it becomes available on the next turn.
8. On failure or user feedback, update the Skill Model and SKILL.md; keep the Safety Gate intact.

## Skill Model

For each goal, produce and keep a short model:

- Goal: one-sentence objective and success criteria.
- Triggers: what a user would say to invoke the skill.
- Inputs/Outputs.
- Workflow: numbered steps.
- Knowledge: domain facts the skill must encode.
- Resources: `scripts/`, `references/`, `assets/` actually required.
- Safety: assessed risk level (allowed / allowed-with-care / prohibited) and mitigation.

## Implementation Rules

- Name skills with lowercase letters, digits, and single hyphens, under 64 characters; normalize user titles to hyphen-case.
- Keep SKILL.md lean; move detailed policy, schemas, and examples into `references/`.
- Include only scripts, references, and assets that directly support the skill.
- Use `scripts/scaffold_skill.py` in this skill to create a starter directory, then complete it.

## Bundled Resources

- `references/safety-guidelines.md`: read first; defines the prohibition and value-alignment policy.
- `scripts/scaffold_skill.py`: create a starter skill directory with a safety-gated SKILL.md template.
