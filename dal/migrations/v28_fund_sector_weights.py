"""
v28: Fund sector weights for look-through sector decomposition.

Provides per-fund sector breakdowns so the X-Ray allocation view can show
real industry exposure instead of "88% Blend".  Individual equities don't
need rows here — they fall through to ticker_metadata.sector.

Lifecycle funds (TSP_L2065, TSP_LINCOME) derive their sector exposure at
query time by chaining through fund_composition weights → constituent
fund → this table.  They have no direct rows here.

Fixed income funds (TSP_F, TSP_G) have no sector rows — they're excluded
from the sector chart entirely.

Weights are approximate 2025 allocations from fund provider fact sheets
(Vanguard, iShares, TSP.gov, Invesco).
"""

VERSION = 28

# ── Sector weight reference data ─────────────────────────────────────────
# (ticker, sector, weight, source)
# Weights per ticker must sum to ~1.0

_SECTOR_ROWS = [
    # TSP_C — tracks S&P 500 (same allocation as VOO)
    ("TSP_C", "Technology",            0.32, "tsp.gov"),
    ("TSP_C", "Financials",            0.13, "tsp.gov"),
    ("TSP_C", "Healthcare",            0.12, "tsp.gov"),
    ("TSP_C", "Consumer Discretionary",0.10, "tsp.gov"),
    ("TSP_C", "Communication Services",0.09, "tsp.gov"),
    ("TSP_C", "Industrials",           0.09, "tsp.gov"),
    ("TSP_C", "Consumer Staples",      0.06, "tsp.gov"),
    ("TSP_C", "Energy",                0.04, "tsp.gov"),
    ("TSP_C", "Utilities",             0.025,"tsp.gov"),
    ("TSP_C", "Real Estate",           0.02, "tsp.gov"),
    ("TSP_C", "Materials",             0.025,"tsp.gov"),

    # VOO — Vanguard S&P 500 ETF (mirrors TSP_C)
    ("VOO", "Technology",              0.32, "vanguard"),
    ("VOO", "Financials",              0.13, "vanguard"),
    ("VOO", "Healthcare",              0.12, "vanguard"),
    ("VOO", "Consumer Discretionary",  0.10, "vanguard"),
    ("VOO", "Communication Services",  0.09, "vanguard"),
    ("VOO", "Industrials",             0.09, "vanguard"),
    ("VOO", "Consumer Staples",        0.06, "vanguard"),
    ("VOO", "Energy",                  0.04, "vanguard"),
    ("VOO", "Utilities",               0.025,"vanguard"),
    ("VOO", "Real Estate",             0.02, "vanguard"),
    ("VOO", "Materials",               0.025,"vanguard"),

    # TSP_S — Dow Jones US Completion Total Stock Market Index
    ("TSP_S", "Industrials",           0.18, "tsp.gov"),
    ("TSP_S", "Financials",            0.15, "tsp.gov"),
    ("TSP_S", "Technology",            0.14, "tsp.gov"),
    ("TSP_S", "Healthcare",            0.13, "tsp.gov"),
    ("TSP_S", "Consumer Discretionary",0.12, "tsp.gov"),
    ("TSP_S", "Real Estate",           0.08, "tsp.gov"),
    ("TSP_S", "Energy",                0.05, "tsp.gov"),
    ("TSP_S", "Materials",             0.04, "tsp.gov"),
    ("TSP_S", "Utilities",             0.04, "tsp.gov"),
    ("TSP_S", "Communication Services",0.04, "tsp.gov"),
    ("TSP_S", "Consumer Staples",      0.03, "tsp.gov"),

    # TSP_I — MSCI EAFE (international developed)
    ("TSP_I", "Financials",            0.18, "tsp.gov"),
    ("TSP_I", "Industrials",           0.14, "tsp.gov"),
    ("TSP_I", "Technology",            0.12, "tsp.gov"),
    ("TSP_I", "Healthcare",            0.10, "tsp.gov"),
    ("TSP_I", "Consumer Discretionary",0.10, "tsp.gov"),
    ("TSP_I", "Consumer Staples",      0.08, "tsp.gov"),
    ("TSP_I", "Materials",             0.07, "tsp.gov"),
    ("TSP_I", "Energy",                0.06, "tsp.gov"),
    ("TSP_I", "Communication Services",0.05, "tsp.gov"),
    ("TSP_I", "Utilities",             0.04, "tsp.gov"),
    ("TSP_I", "Real Estate",           0.03, "tsp.gov"),

    # IXUS — iShares Core MSCI International (similar to TSP_I with EM)
    ("IXUS", "Financials",             0.18, "ishares"),
    ("IXUS", "Industrials",            0.14, "ishares"),
    ("IXUS", "Technology",             0.12, "ishares"),
    ("IXUS", "Healthcare",             0.10, "ishares"),
    ("IXUS", "Consumer Discretionary", 0.10, "ishares"),
    ("IXUS", "Consumer Staples",       0.08, "ishares"),
    ("IXUS", "Materials",              0.07, "ishares"),
    ("IXUS", "Energy",                 0.06, "ishares"),
    ("IXUS", "Communication Services", 0.05, "ishares"),
    ("IXUS", "Utilities",              0.04, "ishares"),
    ("IXUS", "Real Estate",            0.03, "ishares"),

    # IJH — iShares S&P MidCap 400
    ("IJH", "Industrials",             0.20, "ishares"),
    ("IJH", "Financials",              0.16, "ishares"),
    ("IJH", "Technology",              0.13, "ishares"),
    ("IJH", "Consumer Discretionary",  0.12, "ishares"),
    ("IJH", "Healthcare",              0.10, "ishares"),
    ("IJH", "Real Estate",             0.08, "ishares"),
    ("IJH", "Materials",               0.06, "ishares"),
    ("IJH", "Energy",                  0.05, "ishares"),
    ("IJH", "Utilities",               0.04, "ishares"),
    ("IJH", "Communication Services",  0.03, "ishares"),
    ("IJH", "Consumer Staples",        0.03, "ishares"),

    # IJR — iShares S&P SmallCap 600
    ("IJR", "Financials",              0.18, "ishares"),
    ("IJR", "Industrials",             0.17, "ishares"),
    ("IJR", "Healthcare",              0.13, "ishares"),
    ("IJR", "Consumer Discretionary",  0.12, "ishares"),
    ("IJR", "Technology",              0.11, "ishares"),
    ("IJR", "Real Estate",             0.08, "ishares"),
    ("IJR", "Energy",                  0.06, "ishares"),
    ("IJR", "Materials",               0.04, "ishares"),
    ("IJR", "Utilities",               0.04, "ishares"),
    ("IJR", "Communication Services",  0.03, "ishares"),
    ("IJR", "Consumer Staples",        0.04, "ishares"),

    # QQQM — Invesco Nasdaq-100 (tech-heavy)
    ("QQQM", "Technology",             0.50, "invesco"),
    ("QQQM", "Communication Services", 0.16, "invesco"),
    ("QQQM", "Consumer Discretionary", 0.14, "invesco"),
    ("QQQM", "Healthcare",             0.07, "invesco"),
    ("QQQM", "Consumer Staples",       0.05, "invesco"),
    ("QQQM", "Industrials",            0.04, "invesco"),
    ("QQQM", "Utilities",              0.02, "invesco"),
    ("QQQM", "Financials",             0.01, "invesco"),
    ("QQQM", "Energy",                 0.01, "invesco"),
]


def run(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_sector_weights (
            ticker  TEXT    NOT NULL,
            sector  TEXT    NOT NULL,
            weight  REAL    NOT NULL,
            source  TEXT    DEFAULT 'manual',
            as_of   TEXT    DEFAULT (date('now')),
            PRIMARY KEY (ticker, sector)
        )
    """)

    cur.executemany(
        """
        INSERT OR IGNORE INTO fund_sector_weights
            (ticker, sector, weight, source)
        VALUES (?, ?, ?, ?)
        """,
        _SECTOR_ROWS,
    )

    conn.commit()
