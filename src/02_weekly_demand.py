"""Step 2: run sql/weekly_demand.sql and save outputs/weekly_demand.csv."""
from pathlib import Path
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "outputs").mkdir(exist_ok=True)
with sqlite3.connect(ROOT / "data" / "clean" / "retail.db") as con:
    wk = pd.read_sql((ROOT / "sql" / "weekly_demand.sql").read_text(), con)

assert wk["stock_code"].nunique() == 25 and len(wk) == 25 * 104, "expected 25 products x 104 weeks"
wk.to_csv(ROOT / "outputs" / "weekly_demand.csv", index=False)
summary = wk.groupby(["stock_code", "description"], sort=False)["demand"].agg(["sum", "mean"]).round(1)
print(summary.to_string())
print(f"\n{wk['stock_code'].nunique()} products x {wk['week_start'].nunique()} weeks "
      f"({wk['week_start'].min()} to {wk['week_start'].max()})")
