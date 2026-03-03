"""
scripts/chart_acorns_performance.py — Acorns portfolio value chart.

Reads positions_ledger from the DB, fetches historical prices via yfinance,
and generates a cumulative portfolio value chart.
"""

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import pandas as pd
import yfinance as yf

# Ensure the root project directory is in the path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Connect to database
db_path = BASE_DIR / "data" / "sentry.db"
if not db_path.exists():
    print(f"Database not found at {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)

# Query the fractional shares running totals
query = """
    SELECT timestamp, ticker, new_total_shares 
    FROM positions_ledger 
    WHERE account_id = 'acorns_0000'
    ORDER BY timestamp ASC
"""
df = pd.read_sql_query(query, conn)
conn.close()

if df.empty:
    print("No data found in positions_ledger for acorns_0000")
    sys.exit(1)

# Convert timestamp to datetime and normalize to date
df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.normalize()

# Pivot: dates as index, tickers as columns, last share count per day
pivot_df = df.pivot_table(
    index="timestamp", columns="ticker", values="new_total_shares", aggfunc="last"
)

# Create a complete daily date range and forward-fill share counts
date_range = pd.date_range(start=pivot_df.index.min(), end=pivot_df.index.max())
pivot_df = pivot_df.reindex(date_range).ffill().fillna(0)

# Fetch historical closing prices from yfinance
tickers = pivot_df.columns.tolist()
start_date = pivot_df.index.min().strftime("%Y-%m-%d")
end_date = (pivot_df.index.max() + timedelta(days=2)).strftime("%Y-%m-%d")

print(
    f"Fetching historical prices from yfinance for {tickers} between {start_date} and {end_date}..."
)
yf_data = yf.download(tickers, start=start_date, end=end_date)["Close"]
yf_data = yf_data.reindex(date_range).ffill().bfill()

# Calculate daily monetary value per holding
value_df = pivot_df * yf_data
value_df["Total"] = value_df.sum(axis=1)

# ---- Chart ----
fig, ax = plt.subplots(figsize=(14, 7))
fig.patch.set_facecolor("#121212")
ax.set_facecolor("#1a1a2e")

# Total portfolio value (primary line)
ax.plot(
    value_df.index,
    value_df["Total"],
    label="Total Portfolio Value",
    linewidth=2.5,
    color="#00e676",
    zorder=5,
)
ax.fill_between(
    value_df.index,
    value_df["Total"],
    color="#00e676",
    alpha=0.08,
)

# Individual holdings (dashed)
colors = {"IJH": "#2979ff", "IJR": "#ff3d00", "IXUS": "#ffea00", "VOO": "#d500f9"}
for ticker in tickers:
    ax.plot(
        value_df.index,
        value_df[ticker],
        label=ticker,
        linewidth=1.2,
        color=colors.get(ticker, "#aaa"),
        linestyle="--",
        alpha=0.7,
    )

# Annotate key events
# Find the withdrawal dip
jul_data = value_df.loc["2024-07-20":"2024-08-05", "Total"]
if not jul_data.empty:
    min_idx = jul_data.idxmin()
    min_val = jul_data.min()
    ax.annotate(
        f"Withdrawal\n${min_val:,.0f}",
        xy=(min_idx, min_val),
        xytext=(min_idx + timedelta(days=30), min_val + 500),
        arrowprops=dict(arrowstyle="->", color="#ff3d00", lw=1.5),
        fontsize=9,
        color="#ff3d00",
        ha="center",
    )

# Annotate start and end values
start_val = value_df["Total"].iloc[0]
end_val = value_df["Total"].iloc[-1]
ax.annotate(
    f"${start_val:,.0f}",
    xy=(value_df.index[0], start_val),
    xytext=(10, 10),
    textcoords="offset points",
    fontsize=9,
    color="#aaa",
)
ax.annotate(
    f"${end_val:,.0f}",
    xy=(value_df.index[-1], end_val),
    xytext=(-50, 10),
    textcoords="offset points",
    fontsize=9,
    color="#00e676",
    fontweight="bold",
)

# Formatting
ax.set_title(
    "Acorns Portfolio — Cumulative Value (24 Months)",
    fontsize=16,
    pad=20,
    color="white",
    fontweight="bold",
)
ax.set_xlabel("Date", fontsize=11, color="lightgray")
ax.set_ylabel("Market Value", fontsize=11, color="lightgray")

# Y-axis: start at $0, format as currency
ax.set_ylim(bottom=0)
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

# X-axis: monthly ticks
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

# Grid and legend
ax.grid(True, linestyle="-", alpha=0.15)
ax.legend(
    loc="upper left",
    frameon=True,
    facecolor="#1e1e1e",
    edgecolor="#333",
    fontsize=9,
)

ax.tick_params(colors="lightgray")
for spine in ax.spines.values():
    spine.set_color("#333")

plt.tight_layout()

# Save
output_path = Path(
    r"C:\Users\chang\.gemini\antigravity\brain\7cc08689-e7d0-42ea-a94d-2ed0eba56ffe\acorns_performance.png"
)
plt.savefig(output_path, dpi=300, facecolor="#121212")
print(f"Chart successfully saved to: {output_path}")
