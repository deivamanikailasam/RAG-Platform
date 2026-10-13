# Sample tables (Step 35)

Small CSV files for **SQL RAG** (`pipeline: {use: sql}`): the `sql` architecture loads each table
listed under `tables:` into an in-memory SQLite database, describes only the tables the person may
see to the model, and runs the model's single `SELECT` under an SQLite authorizer that allows only
reads of those tables.

| File | Access in the example profile | Used by |
|---|---|---|
| `expense_limits.csv` | `internal`, group `all-staff` | `test_architectures.py`, the example profile in Step 35 |
| `salary_bands.csv` | `confidential`, group `hr` | the access tests: staff never see it described |

Header names become column names (lower-case, non-letters turned into `_`): `Limit (AUD)` becomes
`limit_aud`. The values are illustrative and match the handbook in `examples/corpus/handbook/`
(per diem 90 / 150 dollars, hotels up to 250 dollars a night, home office 500 dollars).
