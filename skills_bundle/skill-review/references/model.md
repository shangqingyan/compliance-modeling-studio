# Skill Review Mathematical Model

## Notation

- `N`: set of scanned skills.
- `P_t`: set of pinned skills at cycle `t`.
- `S_i(t)`: importance score for skill `i` at cycle `t`, in `[0,1]`.
- `A_i(t)`: ablation impact for skill `i` at cycle `t`, in `[0,1]`.
- `C_i(t)`: cumulative (pre-normalization) weight at end of cycle `t`.
- `W_i(t)`: normalized weight at end of cycle `t`, in `[0,1]`.
- `W_i(t-1)` is loaded from the previous review state.

## Importance score

Compute each feature from the inventory evidence and scanned `SKILL.md` descriptions.

- Coverage: `c_i(t) = task_count_i / max(1, total_task_count)`. If no task evidence exists, use a neutral value `c_i(t) = 0.5`.
- Uniqueness: `u_i(t) = 1 - max_{j != i} J(desc_i, desc_j)`, where `J` is token-level Jaccard similarity over the skill descriptions.
- Recency: `r_i(t) = exp(-lambda_rec * used_cycles_ago_i)` with default `lambda_rec = 0.25`.
- Critical flag: `q_i(t) = 1` if explicitly marked critical, else `0`.

Combine:

```text
S_i(t) = clip(w_cov*c_i + w_uniq*u_i + w_rec*r_i + w_crit*q_i, 0, 1)
```

Default weights: `w_cov=0.35`, `w_uniq=0.35`, `w_rec=0.20`, `w_crit=0.10`.

If an explicit `importance` override is supplied, use it as `S_i(t)`.

## Ablation impact

If an explicit `ablation_impact` label is supplied, map it to:

```text
none=0.00, low=0.25, medium=0.60, high=0.95
```

Otherwise infer it from deletion impact:

```text
A_i(t) = clip(b_uniq*u_i + b_cov*c_i, 0, 1)
```

Default weights: `b_uniq=0.60`, `b_cov=0.40`.

## Deletion candidate

A non-pinned skill is a `DELETE_CANDIDATE` when both hold:

```text
S_i(t) < theta_s
A_i(t) < theta_a
```

Defaults: `theta_s = 0.20`, `theta_a = 0.25`.

A candidate is only a recommendation. The script does not delete it unless the user explicitly confirms a whitelist.

## Weight accumulation

For each `KEEP` or `PINNED` skill:

```text
delta_i(t) = alpha*S_i(t) + (1-alpha)*A_i(t)
C_i(t) = rho * C_i(t-1) + delta_i(t)
```

- `alpha = 0.60` by default.
- `rho = 1.0` by default: previous importance is fully retained, so a skill that remains important accumulates weight.
- A newly seen skill starts with `C_i(t-1)=0`.
- Delete candidates do not accumulate and are excluded from normalization.

## Normalization

```text
W_i(t) = C_i(t) / sum_{j in Active(t)} C_j(t)
```

`Active(t)` contains all `KEEP` and `PINNED` skills for the current cycle.

## Pinning

A non-pinned skill becomes pinned when all of the following hold:

```text
W_i(t) >= theta_pin
S_i(t) >= theta_pin_s
high_rounds_i(t) >= r_pin
```

- `high_rounds_i(t)` is the number of consecutive cycles in which the first two conditions held.
- Defaults: `theta_pin = 0.25`, `theta_pin_s = 0.50`, `r_pin = 2`.
- Once pinned, the skill is never proposed for deletion in later cycles. It stays in normalization and ranking but is exempt from deletion checks.
- Manual unpinning requires an explicit user request.

## Memory ordering

Sort active skills by `W_i(t)` descending. Higher-ranked skills are treated as more important in subsequent review memory. In the next cycle, load state first and re-evaluate previously high-weight skills before lower-weight skills.