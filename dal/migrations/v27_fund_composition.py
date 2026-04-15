"""
v27: Fund composition reference table for look-through allocation.

Maps fund/ETF tickers to their underlying asset-class exposures so the
allocation view can merge TSP_C + VOO into a single "US Large Cap Equity"
bucket.  Individual equities (AAPL, MSFT, etc.) have no rows — absence
signals a terminal holding that falls through to ticker_metadata.

This is pure reference data, not account-specific or synthetic.  The same
mappings apply whether holdings are seeded or scraped from tsp.gov.
"""

VERSION = 27


# ── Base reference rows (INSERT OR IGNORE) ─────────────────────────────
# Weights from TSP.gov fund sheets and ETF provider fact sheets as of
# 2025-Q1.  L2065 glide-path snapshot; update annually after TSP publishes
# new allocations.

_COMPOSITION_ROWS = [
    # TSP core funds
    ("TSP_C",     "US Large Cap Equity",      1.00, "US",              "Large Cap",     "tsp.gov"),
    # TSP_S tracks the Dow Jones US Completion TSM Index — approx 60% small / 40% mid
    ("TSP_S",     "US Small Cap Equity",       0.60, "US",              "Small Cap",     "tsp.gov"),
    ("TSP_S",     "US Mid Cap Equity",         0.40, "US",              "Mid Cap",       "tsp.gov"),
    ("TSP_I",     "Intl Developed Equity",     1.00, "Developed Intl",  "Large Cap",     "tsp.gov"),  # MSCI EAFE ~85% large cap
    ("TSP_F",     "US Fixed Income",           1.00, "US",              "Fixed Income",  "tsp.gov"),
    ("TSP_G",     "US Government Securities",  1.00, "US",              "Fixed Income",  "tsp.gov"),
    # TSP lifecycle 2065 (approximate 2025 allocation)
    ("TSP_L2065", "US Large Cap Equity",       0.52, "US",              "Large Cap",     "tsp.gov"),
    # L2065's small/mid allocation mirrors the S Fund split (60/40 small/mid)
    ("TSP_L2065", "US Small Cap Equity",       0.09, "US",              "Small Cap",     "tsp.gov"),
    ("TSP_L2065", "US Mid Cap Equity",         0.06, "US",              "Mid Cap",       "tsp.gov"),
    ("TSP_L2065", "Intl Developed Equity",     0.16, "Developed Intl",  "Large Cap",     "tsp.gov"),
    ("TSP_L2065", "Emerging Markets Equity",   0.07, "Emerging Markets", "Large Cap",    "tsp.gov"),
    ("TSP_L2065", "US Fixed Income",           0.10, "US",              "Fixed Income",  "tsp.gov"),
    # TSP L Income (conservative)
    ("TSP_LINCOME", "US Large Cap Equity",     0.12, "US",              "Large Cap",     "tsp.gov"),
    ("TSP_LINCOME", "US Small Cap Equity",     0.018, "US",             "Small Cap",     "tsp.gov"),
    ("TSP_LINCOME", "US Mid Cap Equity",       0.012, "US",             "Mid Cap",       "tsp.gov"),
    ("TSP_LINCOME", "Intl Developed Equity",   0.05, "Developed Intl",  "Large Cap",     "tsp.gov"),
    ("TSP_LINCOME", "US Fixed Income",         0.24, "US",              "Fixed Income",  "tsp.gov"),
    ("TSP_LINCOME", "US Government Securities",0.56, "US",              "Fixed Income",  "tsp.gov"),
    # Common ETFs (Acorns portfolio + Fidelity)
    ("VOO",  "US Large Cap Equity",      1.00, "US",              "Large Cap",     "vanguard"),
    ("IJH",  "US Mid Cap Equity",        1.00, "US",              "Mid Cap",       "ishares"),
    ("IJR",  "US Small Cap Equity",      1.00, "US",              "Small Cap",     "ishares"),
    ("IXUS", "Intl Developed Equity",    0.80, "Developed Intl",  "Large Cap",     "ishares"),
    ("IXUS", "Emerging Markets Equity",  0.20, "Emerging Markets", "Large Cap",    "ishares"),
    ("QQQM", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "invesco"),
    # Individual equities — terminal holdings that still need proper asset class
    # labels so X-Ray mode classifies them alongside fund decompositions.
    # All US Large Cap unless otherwise noted.
    ("AAPL", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
    ("MSFT", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
    ("AMZN", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
    ("GOOG", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
    ("SPG",  "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),  # S&P 500 REIT
    ("TGT",  "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
    ("SBUX", "US Large Cap Equity",      1.00, "US",              "Large Cap",     "manual"),
]


def run(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_composition (
            ticker      TEXT    NOT NULL,
            asset_class TEXT    NOT NULL,
            weight      REAL    NOT NULL,
            geography   TEXT,
            cap_class   TEXT,
            source      TEXT    DEFAULT 'manual',
            as_of       TEXT    DEFAULT (date('now')),
            PRIMARY KEY (ticker, asset_class)
        )
    """)

    cur.executemany(
        """
        INSERT OR IGNORE INTO fund_composition
            (ticker, asset_class, weight, geography, cap_class, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        _COMPOSITION_ROWS,
    )

    conn.commit()
