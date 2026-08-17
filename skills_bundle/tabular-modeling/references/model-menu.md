# Candidate Model Menu

Default candidates, in run order:

| model | estimator | hyperparameter grid |
| --- | --- | --- |
| linear | LinearRegression | `{}` |
| ridge | Ridge | `alpha ∈ {0.1, 1.0, 10.0, 100.0}` |
| lasso | Lasso(max_iter=10000) | `alpha ∈ {0.001, 0.01, 0.1, 1.0}` |
| decision_tree | DecisionTreeRegressor(random_state=42) | `max_depth ∈ {3, 5, 7, None}` |
| random_forest | RandomForestRegressor(random_state=42, n_jobs=-1) | `n_estimators ∈ {100, 200}`, `max_depth ∈ {None, 5, 10}` |
| gradient_boosting | GradientBoostingRegressor(random_state=42) | `n_estimators ∈ {100, 200}`, `learning_rate ∈ {0.05, 0.1}` |
| svr | SVR | `C ∈ {0.1, 1.0, 10.0}`, `kernel ∈ {rbf, linear}` |

- Pass a comma-separated subset with `--models`.
- Pass `--skip-tuning` to use only the first parameter set for each model.
- Supported metric keys: `r2`, `rmse`, `mae`.
- Validation R2 is the primary selection metric.
