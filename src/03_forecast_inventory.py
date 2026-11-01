"""Step 3: forecast weekly demand with 3 methods, measure accuracy on an 8 week
holdout, pick the best method per product, forecast the next 8 weeks, and work out
safety stock, reorder point and stock risk. All results go to outputs/."""
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")      # statsmodels convergence chatter
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

# ---- Assumptions (stated in the README) ----
HORIZON = 8            # weeks to forecast, and weeks held back to test accuracy
SEASON = 52            # weeks in a year
MA_WINDOW = 8          # moving average looks at the last 8 weeks
SERVICE_LEVEL = 0.95   # want to avoid running out in 95% of lead times
Z = 1.645              # z score for 95%
LEAD_TIME = 2          # weeks from placing an order to receiving it
COVER_WEEKS = 3        # assumed stock on hand = 3 weeks of recent average demand (no stock data in the dataset)

wk = pd.read_csv(OUT / "weekly_demand.csv", parse_dates=["week_start"])
names = wk.drop_duplicates("stock_code").set_index("stock_code")["description"].str.strip()


def seasonal_naive(train, h):
    # same week last year
    return train[-SEASON:][:h]


def moving_average(train, h):
    # average of the last 8 weeks, flat
    return np.repeat(train[-MA_WINDOW:].mean(), h)


def holt_winters(train, h):
    # level + damped trend + yearly seasonality. The smoothing weights are estimated from the data.
    # With under two full years of training data statsmodels cannot work out the starting values
    # itself, so they are set from the first year: level = its average, season = each week minus it.
    first_year = train[:SEASON]
    fit = ExponentialSmoothing(train, trend="add", damped_trend=True, seasonal="add",
                               seasonal_periods=SEASON, initialization_method="known",
                               initial_level=first_year.mean(), initial_trend=0.0,
                               initial_seasonal=first_year - first_year.mean()).fit()
    return np.clip(fit.forecast(h), 0, None)


METHODS = {"Seasonal naive": seasonal_naive, "Moving average": moving_average, "Holt Winters": holt_winters}

holdout_rows, accuracy_rows, future_rows, inventory_rows = [], [], [], []
for code, g in wk.groupby("stock_code", sort=False):
    y = g["demand"].to_numpy(dtype=float)
    weeks = g["week_start"].to_numpy()
    train, test = y[:-HORIZON], y[-HORIZON:]

    best = None
    for method, fn in METHODS.items():
        fc = fn(train, HORIZON)
        nz = test > 0
        mape = np.mean(np.abs(test[nz] - fc[nz]) / test[nz]) * 100   # average % miss per week
        wmape = np.abs(test - fc).sum() / test.sum() * 100            # total miss / total demand (big weeks count more)
        bias = (fc.sum() - test.sum()) / test.sum() * 100            # + means over forecast
        rmse = np.sqrt(np.mean((test - fc) ** 2))
        accuracy_rows.append({"stock_code": code, "description": names[code], "method": method,
                              "mape_pct": round(mape, 1), "wmape_pct": round(wmape, 1), "bias_pct": round(bias, 1),
                              "rmse": round(rmse, 1), "actual_total": test.sum(),
                              "forecast_total": round(fc.sum(), 0)})
        for wkst, a, f in zip(weeks[-HORIZON:], test, fc):
            holdout_rows.append({"stock_code": code, "description": names[code], "week_start": wkst,
                                 "method": method, "actual": a, "forecast": round(f, 1)})
        if best is None or mape < best[1]:
            best = (method, mape, rmse)

    # Refit the best method on all 104 weeks and forecast the next 8
    method, _, rmse = best
    future = METHODS[method](y, HORIZON)
    future_weeks = pd.date_range(weeks[-1] + np.timedelta64(7, "D"), periods=HORIZON, freq="7D")
    for wkst, f in zip(future_weeks, future):
        future_rows.append({"stock_code": code, "description": names[code], "week_start": wkst.date(),
                            "method": method, "forecast": round(f, 1)})

    # Inventory: safety stock covers forecast error over the lead time
    safety_stock = Z * rmse * np.sqrt(LEAD_TIME)
    lead_time_demand = future[:LEAD_TIME].sum()
    reorder_point = lead_time_demand + safety_stock
    avg_recent = y[-HORIZON:].mean()
    on_hand = COVER_WEEKS * avg_recent
    cum = np.cumsum(future)
    stockout_week = int(np.argmax(cum > on_hand)) + 1 if (cum > on_hand).any() else None
    inventory_rows.append({
        "stock_code": code, "description": names[code], "best_method": method,
        "avg_weekly_demand_last8": round(avg_recent, 1),
        "forecast_rmse": round(rmse, 1),
        "safety_stock": round(safety_stock, 0),
        "lead_time_demand": round(lead_time_demand, 0),
        "reorder_point": round(reorder_point, 0),
        "assumed_on_hand": round(on_hand, 0),
        "below_reorder_point": int(on_hand < reorder_point),
        "weeks_until_stockout": stockout_week,
        "forecast_next8_total": round(future.sum(), 0),
    })

acc = pd.DataFrame(accuracy_rows)
best_idx = acc.groupby("stock_code", sort=False)["mape_pct"].idxmin()
acc["is_best"] = 0
acc.loc[best_idx, "is_best"] = 1
inv = pd.DataFrame(inventory_rows)
# At risk = the stock we hold is already below the reorder point, so an order is needed now
inv["at_risk"] = inv["below_reorder_point"]

# One chart ready table for Power BI: last 26 weeks of history, the 8 week holdout with
# each method's forecast, then the next 8 weeks from the best method.
hold = pd.DataFrame(holdout_rows).pivot_table(index=["stock_code", "week_start"], columns="method",
                                              values="forecast").reset_index()
hist = wk.groupby("stock_code", sort=False).tail(26 + HORIZON)[["stock_code", "week_start", "demand"]]
chart = hist.rename(columns={"demand": "actual"}).merge(hold, on=["stock_code", "week_start"], how="left")
chart["period"] = np.where(chart["Moving average"].notna(), "Holdout", "History")
fut = pd.DataFrame(future_rows).rename(columns={"forecast": "next8_forecast"})[["stock_code", "week_start", "next8_forecast"]]
fut["week_start"] = pd.to_datetime(fut["week_start"])
fut["period"] = "Next 8 weeks"
chart = pd.concat([chart, fut], ignore_index=True)
chart["description"] = chart["stock_code"].map(names)
# Sort by product and week so every column has numbers near the top of the file
# (Power BI guesses column types from the first rows).
chart = chart.sort_values(["stock_code", "week_start"]).reset_index(drop=True)
chart.to_csv(OUT / "forecast_chart.csv", index=False)

# Overall accuracy per method: average MAPE across products, and bias on total volume
overall = acc.groupby("method").apply(lambda d: pd.Series({
    "avg_mape_pct": round(d["mape_pct"].mean(), 1),
    "wmape_pct": round((d["wmape_pct"] * d["actual_total"]).sum() / d["actual_total"].sum(), 1),
    "bias_pct": round((d["forecast_total"].sum() - d["actual_total"].sum()) / d["actual_total"].sum() * 100, 1),
    "products_best": int(d["is_best"].sum()),
})).reset_index().sort_values("avg_mape_pct")
best_only = acc[acc["is_best"] == 1]
overall_best = pd.DataFrame([{"method": "Best per product",
    "avg_mape_pct": round(best_only["mape_pct"].mean(), 1),
    "wmape_pct": round((best_only["wmape_pct"] * best_only["actual_total"]).sum() / best_only["actual_total"].sum(), 1),
    "bias_pct": round((best_only["forecast_total"].sum() - best_only["actual_total"].sum())
                      / best_only["actual_total"].sum() * 100, 1),
    "products_best": len(best_only)}])
overall = pd.concat([overall, overall_best], ignore_index=True)

pd.DataFrame(holdout_rows).to_csv(OUT / "holdout_forecasts.csv", index=False)
acc.to_csv(OUT / "accuracy_by_product.csv", index=False)
overall.to_csv(OUT / "accuracy_overall.csv", index=False)
pd.DataFrame(future_rows).to_csv(OUT / "forecast_next8.csv", index=False)
inv.to_csv(OUT / "inventory_plan.csv", index=False)

print("== Overall accuracy on the 8 week holdout (10 Oct to 4 Dec 2011)")
print(overall.to_string(index=False))
print("\n== Best method per product")
print(best_only[["description", "method", "mape_pct", "wmape_pct", "bias_pct"]].to_string(index=False))
print(f"\n== Stock risk ({SERVICE_LEVEL:.0%} service level, {LEAD_TIME} week lead time, "
      f"{COVER_WEEKS} weeks assumed cover)")
print(inv[inv["at_risk"] == 1][["description", "assumed_on_hand", "reorder_point",
                                "safety_stock", "weeks_until_stockout"]].to_string(index=False))
print(f"\n{inv['at_risk'].sum()} of {len(inv)} products at risk")
