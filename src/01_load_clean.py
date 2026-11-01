"""Step 1: load the UCI Online Retail II data, clean it, and save the clean
sales lines to SQLite (data/clean/retail.db, table sales_lines)."""
from pathlib import Path
import sqlite3
import urllib.request
import zipfile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
RAW.mkdir(parents=True, exist_ok=True)
CLEAN.mkdir(parents=True, exist_ok=True)
XLSX = RAW / "online_retail_II.xlsx"
URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

if not XLSX.exists():
    print("downloading from UCI ...")
    zpath = RAW / "online_retail_ii.zip"
    urllib.request.urlretrieve(URL, zpath)
    zipfile.ZipFile(zpath).extractall(RAW)
    zpath.unlink()

print("reading Excel (takes about a minute) ...")
sheets = pd.read_excel(XLSX, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
y1, y2 = sheets["Year 2009-2010"], sheets["Year 2010-2011"]
raw_rows = len(y1) + len(y2)

# The two sheets overlap on 1 to 9 Dec 2010. Sheet 1 already has those days, so take sheet 2 from 10 Dec.
y2 = y2[y2["InvoiceDate"] >= "2010-12-10"]
df = pd.concat([y1, y2], ignore_index=True)
overlap_removed = raw_rows - len(df)

df["StockCode"] = df["StockCode"].str.strip().str.upper()
df["is_cancellation"] = df["Invoice"].str.startswith("C").astype(int)

steps = {}
n = len(df)
df = df[df["StockCode"].str.match(r"^\d")]               # real products only: drops POST, DOT, M, fees, gift vouchers, ADJUST
steps["non product codes (postage, fees, manual)"] = n - len(df); n = len(df)
df = df[df["Price"] > 0]                                  # free lines and stock write offs
steps["price zero or below"] = n - len(df); n = len(df)
df = df[(df["is_cancellation"] == 1) | (df["Quantity"] > 0)]  # negative lines that are not cancellations (damages, lost stock)
steps["negative quantity, not a cancellation"] = n - len(df)

# Demand is NET: cancellations stay in as negative quantities, so an order placed and
# cancelled (for example the 74,215 unit order on 18 Jan 2011) cancels itself out.
df["week_start"] = (df["InvoiceDate"].dt.normalize()
                    - pd.to_timedelta(df["InvoiceDate"].dt.dayofweek, unit="D")).dt.date
out = df.rename(columns={"StockCode": "stock_code", "Description": "description",
                         "Quantity": "quantity", "Price": "price", "Invoice": "invoice",
                         "InvoiceDate": "invoice_date", "Country": "country"})
out = out[["invoice", "invoice_date", "week_start", "stock_code", "description",
           "quantity", "price", "country", "is_cancellation"]]
out["invoice_date"] = out["invoice_date"].astype(str)

with sqlite3.connect(CLEAN / "retail.db") as con:
    out.to_sql("sales_lines", con, if_exists="replace", index=False)

print(f"raw rows {raw_rows:,}; overlap rows removed {overlap_removed:,}")
for k, v in steps.items():
    print(f"removed {v:,}: {k}")
print(f"clean rows {len(out):,}, products {out['stock_code'].nunique():,}, "
      f"{out['invoice_date'].min()[:10]} to {out['invoice_date'].max()[:10]}")
