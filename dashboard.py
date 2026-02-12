"""
Project Antigravity — Interactive Personal Finance Dashboard
Built with Plotly Dash.  Run:  python dashboard.py
"""

import os, pathlib, warnings, re, json, logging

log = logging.getLogger("antigravity")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import dash
from dash import Dash, html, dcc, Input, Output, callback, dash_table, State
from config import cfg

warnings.filterwarnings("ignore")

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE = pathlib.Path(__file__).resolve().parent
CATEGORY_MAP_FILE = BASE / "category_map.json"

# ─── Persistence Helper ──────────────────────────────────────────────────────

def _load_category_map():
    if CATEGORY_MAP_FILE.exists():
        try:
            with open(CATEGORY_MAP_FILE, "r") as f:
                return json.load(f)
        except Exception:
            log.warning("Failed to load category_map.json, using empty map")
            return {}
    return {}

def _save_category_map(mapping):
    with open(CATEGORY_MAP_FILE, "w") as f:
        json.dump(mapping, f, indent=2)


# ─── Unified Loader ──────────────────────────────────────────────────────────

def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and stray quotes from column names."""
    df.columns = (
        df.columns.str.strip()
                  .str.strip("'\"")
                  .str.strip()
    )
    return df


def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first column name that exists (case-insensitive)."""
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def load_nfcu(path: pathlib.Path, institution: str, account: str) -> pd.DataFrame:
    df = _clean_columns(pd.read_csv(path))

    date_col = _find_col(df, "Posting Date")
    txn_date_col = _find_col(df, "Transaction Date")
    amount_col = _find_col(df, "Amount")
    dir_col = _find_col(df, "Credit Debit Indicator")
    desc_col = _find_col(df, "Description")
    cat_col = _find_col(df, "Category")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], format="mixed")
    out["txn_date"] = pd.to_datetime(df[txn_date_col] if txn_date_col else df[date_col], format="mixed")
    out["amount"] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)
    direction = df[dir_col].astype(str).str.strip().str.lower() if dir_col else "debit"
    out["signed_amount"] = out["amount"].where(direction == "credit", -out["amount"])
    out["direction"] = direction.str.title() if dir_col else "Debit"
    out["description"] = df[desc_col].astype(str) if desc_col else ""
    out["category"] = df[cat_col].astype(str) if cat_col else "Uncategorized"
    out["institution"] = institution
    out["account"] = account
    return out


def load_chase(path: pathlib.Path, institution: str, account: str) -> pd.DataFrame:
    df = _clean_columns(pd.read_csv(path))

    date_col = _find_col(df, "Posting Date", "Post Date")
    txn_date_col = _find_col(df, "Transaction Date") or date_col
    amount_col = _find_col(df, "Amount")
    desc_col = _find_col(df, "Description")
    type_col = _find_col(df, "Type")
    details_col = _find_col(df, "Details")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], format="mixed")
    out["txn_date"] = pd.to_datetime(df[txn_date_col], format="mixed")
    out["amount"] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)

    if details_col:
        # Chase Checking: amounts already signed (negative = debit)
        out["signed_amount"] = out["amount"]
    else:
        # Chase CC: amounts positive, "Payment" type → credit, else debit
        types = df[type_col].astype(str).str.strip().str.lower() if type_col else "sale"
        out["signed_amount"] = out["amount"].where(types == "payment", -out["amount"])

    out["amount"] = out["amount"].abs()
    out["direction"] = out["signed_amount"].apply(lambda x: "Credit" if x >= 0 else "Debit")
    out["description"] = df[desc_col].astype(str) if desc_col else ""
    out["category"] = out["description"].apply(_chase_categorize)
    out["institution"] = institution
    out["account"] = account
    return out


def _chase_categorize(desc: str) -> str:
    desc = str(desc).upper()
    for key, cat in cfg.chase_keyword_map.items():
        if key in desc:
            return cat
    return "General"


# ─── Load Everything ─────────────────────────────────────────────────────────

_LOADERS = {"nfcu": load_nfcu, "chase": load_chase}
CSV_MANIFEST = [
    (BASE / src["path"], src["institution"], src["account"], _LOADERS[src["loader"]])
    for src in cfg.data_sources
]

frames = []
for path, inst, acct, loader in CSV_MANIFEST:
    if not path.exists():
        print(f"  ⚠  Skipped (not found): {path.name}")
        continue
    try:
        frames.append(loader(path, inst, acct))
        print(f"  ✔  {path.name}  →  {len(frames[-1])} rows")
    except Exception as e:
        log.error("Failed to load %s: %s", path.name, e)

ALL = pd.concat(frames, ignore_index=True).sort_values("date")

# Apply Persistent Overrides
CAT_MAP = _load_category_map()
# Vectorized update: map description to category, fall back to original
overrides = ALL["description"].map(CAT_MAP)
ALL["category"] = overrides.fillna(ALL["category"])
ALL["month"] = ALL["date"].dt.to_period("M").astype(str)
ALL["week"] = ALL["date"].dt.to_period("W").apply(lambda p: p.start_time)

# ─── Colour Palette (from config) ───────────────────────────────────────────────────────────
DARK_BG = cfg.colors.dark_bg
CARD_BG = cfg.colors.card_bg
ACCENT  = cfg.colors.accent
ACCENT2 = cfg.colors.accent2
ACCENT3 = cfg.colors.accent3
TEXT    = cfg.colors.text
SUBTEXT = cfg.colors.subtext

CATEGORY_PALETTE = px.colors.qualitative.Pastel + px.colors.qualitative.Set3

# ─── KPI Helpers ─────────────────────────────────────────────────────────────

def kpi_card(title, value, subtitle="", color=ACCENT):
    return html.Div([
        html.P(title, style={"margin": "0", "fontSize": "0.75rem", "color": SUBTEXT,
                              "textTransform": "uppercase", "letterSpacing": "1px"}),
        html.H2(value, style={"margin": "4px 0", "color": color, "fontWeight": "700"}),
        html.P(subtitle, style={"margin": "0", "fontSize": "0.8rem", "color": SUBTEXT}),
    ], style={
        "background": CARD_BG, "borderRadius": "12px", "padding": "20px 24px",
        "flex": "1", "minWidth": "180px",
        "borderLeft": f"3px solid {color}",
    })


# ─── App Layout ──────────────────────────────────────────────────────────────

app = Dash(__name__)
app.title = "Project Antigravity — Finance Dashboard"

months_available = sorted(ALL["month"].unique())

app.layout = html.Div(style={
    "fontFamily": "'Inter', 'Segoe UI', sans-serif",
    "backgroundColor": DARK_BG, "color": TEXT,
    "minHeight": "100vh", "padding": "24px 32px",
}, children=[

    # ── Header ───────────────────────────────────────────────────────────────
    dcc.Store(id="refresh-trigger", data=0),     # Trigger for updates
    dcc.Store(id="new-cat-pending-row", data=None), # Store row info when adding new cat

    # ── Modal for New Category ───────────────────────────────────────────────
    html.Div(id="modal-container", children=[
        html.Div([
            html.H3("✨ Add New Category", style={"marginTop": "0", "color": TEXT}),
            dcc.Input(id="new-cat-name", type="text", placeholder="Enter category name...",
                      style={"width": "100%", "padding": "10px", "borderRadius": "5px",
                             "border": "none", "backgroundColor": "#2a2d3a", "color": "white",
                             "marginBottom": "20px"}),
            html.Div([
                html.Button("Cancel", id="modal-cancel", n_clicks=0,
                            style={"marginRight": "10px", "padding": "8px 16px",
                                   "backgroundColor": "transparent", "color": SUBTEXT,
                                   "border": f"1px solid {SUBTEXT}", "borderRadius": "5px",
                                   "cursor": "pointer"}),
                html.Button("Save Category", id="modal-save", n_clicks=0,
                            style={"padding": "8px 16px", "backgroundColor": ACCENT,
                                   "color": "white", "border": "none", "borderRadius": "5px",
                                   "cursor": "pointer"}),
            ], style={"display": "flex", "justifyContent": "flex-end"})
        ], style={
            "position": "fixed", "top": "50%", "left": "50%",
            "transform": "translate(-50%, -50%)",
            "backgroundColor": CARD_BG, "padding": "30px", "borderRadius": "12px",
            "boxShadow": "0 10px 30px rgba(0,0,0,0.5)",
            "zIndex": "1000", "width": "400px", "maxWidth": "90%"
        }),
        html.Div(style={ # Overlay
            "position": "fixed", "top": "0", "left": "0", "width": "100%", "height": "100%",
            "backgroundColor": "rgba(0,0,0,0.7)", "zIndex": "999"
        })
    ], style={"display": "none"}),  # Initially hidden

    html.Div([
        html.H1("🚀 Project Antigravity", style={
            "margin": "0", "fontSize": "1.8rem",
            "background": f"linear-gradient(135deg, {ACCENT}, {ACCENT2})",
            "-webkit-background-clip": "text", "-webkit-text-fill-color": "transparent",
        }),
        html.P("Personal Finance Command Center", style={
            "margin": "4px 0 0 0", "color": SUBTEXT, "fontSize": "0.9rem"}),
    ], style={"marginBottom": "24px"}),

    # ── Filters ──────────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Label("Date Range", style={"fontSize": "0.75rem", "color": SUBTEXT, "marginBottom": "4px"}),
            dcc.RangeSlider(
                id="month-slider",
                min=0, max=len(months_available) - 1,
                value=[0, len(months_available) - 1],
                marks={i: {"label": m, "style": {"color": SUBTEXT, "fontSize": "0.7rem"}}
                       for i, m in enumerate(months_available)},
                step=1,
            ),
        ], style={"flex": "3", "minWidth": "300px"}),

        html.Div([
            html.Label("Institution", style={"fontSize": "0.75rem", "color": SUBTEXT, "marginBottom": "4px"}),
            dcc.Dropdown(
                id="institution-filter",
                options=[{"label": "All Institutions", "value": "ALL"}] +
                        [{"label": i, "value": i} for i in sorted(ALL["institution"].unique())],
                value="ALL", clearable=False,
                style={"backgroundColor": CARD_BG, "color": "#000", "borderRadius": "8px"},
            ),
        ], style={"flex": "1", "minWidth": "180px"}),

        html.Div([
            html.Label("Account Type", style={"fontSize": "0.75rem", "color": SUBTEXT, "marginBottom": "4px"}),
            dcc.Dropdown(
                id="account-filter",
                options=[{"label": "All Accounts", "value": "ALL"}] +
                        [{"label": a, "value": a} for a in sorted(ALL["account"].unique())],
                value="ALL", clearable=False,
                style={"backgroundColor": CARD_BG, "color": "#000", "borderRadius": "8px"},
            ),
        ], style={"flex": "1", "minWidth": "180px"}),
    ], style={"display": "flex", "gap": "24px", "alignItems": "flex-end",
              "marginBottom": "24px", "flexWrap": "wrap"}),

    # ── KPI Row ──────────────────────────────────────────────────────────────
    html.Div(id="kpi-row", style={"display": "flex", "gap": "16px",
                                   "marginBottom": "24px", "flexWrap": "wrap"}),

    # ── Charts Row 1 ─────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            dcc.Graph(id="income-vs-expense", config={"displayModeBar": False}),
        ], style={"flex": "2", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
        html.Div([
            dcc.Graph(id="category-pie", config={"displayModeBar": False}),
        ], style={"flex": "1", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap"}),

    # ── Charts Row 2 ─────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            dcc.Graph(id="burn-rate-trend", config={"displayModeBar": False}),
        ], style={"flex": "1", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
        html.Div([
            dcc.Graph(id="officiating-income", config={"displayModeBar": False}),
        ], style={"flex": "1", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap"}),

    # ── Charts Row 3 ─────────────────────────────────────────────────────────
    html.Div([
        html.Div([
            dcc.Graph(id="subscription-bar", config={"displayModeBar": False}),
        ], style={"flex": "1", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
        html.Div([
            dcc.Graph(id="top-merchants", config={"displayModeBar": False}),
        ], style={"flex": "1", "background": CARD_BG, "borderRadius": "12px", "padding": "12px"}),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap"}),

    # ── Transaction Table ────────────────────────────────────────────────────
    # ── Transaction Table ────────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.H3("📋 Transaction Review", style={"margin": "0", "fontSize": "1rem"}),
        ]),
        html.Div([
            dcc.Dropdown(
                id="page-size-dropdown",
                options=[
                    {"label": "10 rows", "value": 10},
                    {"label": "15 rows", "value": 15},
                    {"label": "20 rows", "value": 20},
                    {"label": "50 rows", "value": 50},
                    {"label": "100 rows", "value": 100},
                ],
                value=15,
                clearable=False,
                searchable=False,
                style={"width": "110px", "color": "#000"},
            ),
            dcc.Dropdown(
                id="category-filter-dropdown",
                placeholder="Filter by Category...",
                multi=True,
                style={"width": "300px", "color": "#000"},
            ),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center"}),
    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "12px"}),
        
    html.Div([
        dash_table.DataTable(
            id="txn-table",
            columns=[
                {"name": "Date", "id": "date_str"},
                {"name": "Institution", "id": "institution"},
                {"name": "Account", "id": "account"},
                {"name": "Description", "id": "description"},
                {"name": "Category", "id": "category", "presentation": "dropdown", "editable": True},
                {"name": "Amount", "id": "amount_str"},
            ],
            style_as_list_view=True,
            page_size=15,
            sort_action="native",
            filter_action="native",
            style_header={
                "backgroundColor": CARD_BG,
                "color": SUBTEXT,
                "fontWeight": "bold",
                "borderBottom": f"1px solid {SUBTEXT}",
            },
            style_cell={
                "backgroundColor": DARK_BG,
                "color": TEXT,
                "border": "none",
                "padding": "10px",
                "fontSize": "0.85rem",
                "fontFamily": "'Inter', 'Segoe UI', sans-serif",
                "textAlign": "left",
            },
            style_data_conditional=[
                {
                    "if": {"row_index": "odd"},
                    "backgroundColor": "#13161f",  # Zebra striping
                },
                {
                    "if": {"filter_query": "{signed_amount} > 0", "column_id": "amount_str"},
                    "color": ACCENT2,
                    "fontWeight": "bold",
                },
                {
                    "if": {"filter_query": "{signed_amount} < 0", "column_id": "amount_str"},
                    "color": ACCENT3,
                    "fontWeight": "bold",
                },
            ],
            style_filter={
                "backgroundColor": CARD_BG,
                "color": TEXT,
                "border": f"1px solid {SUBTEXT}",
            },
        ),
    ], style={"background": CARD_BG, "borderRadius": "12px", "padding": "20px", "marginBottom": "24px"}),

])


# ─── Callbacks ───────────────────────────────────────────────────────────────

def filter_data(month_range, institution, account):
    """Apply all filters and return expenses/income DataFrames."""
    m_start = months_available[month_range[0]]
    m_end   = months_available[month_range[1]]
    mask = (ALL["month"] >= m_start) & (ALL["month"] <= m_end)
    if institution != "ALL":
        mask &= ALL["institution"] == institution
    if account != "ALL":
        mask &= ALL["account"] == account
    filtered = ALL[mask]
    
    # Exclude internal moves from "Income" and "Expense" to avoid double counting
    # logic: Income is money entering the system (Salary). Expense is money leaving (Bambu Lab).
    # Moving money (Checking -> Savings, or Checking -> CC Payment) is neutral.
    exc_cats = cfg.excluded_categories
    
    exp = filtered[(filtered["signed_amount"] < 0) & (~filtered["category"].isin(exc_cats))].copy()
    exp["abs_amount"] = exp["amount"]
    
    inc = filtered[(filtered["signed_amount"] > 0) & (~filtered["category"].isin(exc_cats))].copy()
    
    return filtered, exp, inc


@callback(
    Output("refresh-trigger", "data"),
    Output("modal-container", "style"),
    Output("new-cat-pending-row", "data"),
    Output("new-cat-name", "value"),
    Input("txn-table", "data_timestamp"),
    Input("modal-save", "n_clicks"),
    Input("modal-cancel", "n_clicks"),
    State("txn-table", "data"),
    State("txn-table", "data_previous"),
    State("refresh-trigger", "data"),
    State("new-cat-name", "value"),
    State("new-cat-pending-row", "data"),
    prevent_initial_call=True,
)
def manage_categories(timestamp, save_clicks, cancel_clicks, current, previous, trig, new_name, pending_row):
    ctx = [p["prop_id"] for p in dash.callback_context.triggered][0]
    
    # ── 1. Handle Modal Actions (Save/Cancel) ──────────────────────────────
    if "modal-save" in ctx:
        if new_name and pending_row:
            desc = pending_row["description"]
            # Save new category
            CAT_MAP[desc] = new_name
            _save_category_map(CAT_MAP)
            ALL.loc[ALL["description"] == desc, "category"] = new_name
            return (trig or 0) + 1, {"display": "none"}, None, ""
        return dash.no_update, {"display": "none"}, None, ""

    if "modal-cancel" in ctx:
        return dash.no_update, {"display": "none"}, None, ""

    # ── 2. Handle Table Edits ──────────────────────────────────────────────
    if not current or not previous:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    changes_found = False
    open_modal = False
    row_info = None

    for r_curr, r_prev in zip(current, previous):
        if r_curr["category"] != r_prev["category"]:
            new_cat = r_curr["category"]
            desc = r_curr["description"]
            
            if new_cat == "ADD_NEW":
                # Open Modal, don't save yet
                open_modal = True
                row_info = {"description": desc}
                # Revert change in UI? Hard to do without full refresh. 
                # We'll just leave it as "ADD_NEW" until save/refresh.
            else:
                # Regular save
                CAT_MAP[desc] = new_cat
                _save_category_map(CAT_MAP)
                ALL.loc[ALL["description"] == desc, "category"] = new_cat
                changes_found = True
            break
            
    if open_modal:
        return dash.no_update, {"display": "block"}, row_info, ""
    
    return (trig or 0) + 1 if changes_found else trig, {"display": "none"}, None, ""



@callback(
    Output("kpi-row", "children"),
    Output("income-vs-expense", "figure"),
    Output("category-pie", "figure"),
    Output("burn-rate-trend", "figure"),
    Output("officiating-income", "figure"),
    Output("subscription-bar", "figure"),
    Output("top-merchants", "figure"),
    Output("txn-table", "data"),
    Output("txn-table", "dropdown"),
    Output("category-filter-dropdown", "options"),
    Input("month-slider", "value"),
    Input("institution-filter", "value"),
    Input("account-filter", "value"),
    Input("category-filter-dropdown", "value"),
    Input("refresh-trigger", "data"),
)
def update_dashboard(month_range, institution, account, cat_filter, _):
    try:
        filtered, exp, inc = filter_data(month_range, institution, account)

        # ── KPIs ─────────────────────────────────────────────────────────────
        total_in  = inc["signed_amount"].sum()
        total_out = exp["abs_amount"].sum()
        net       = total_in - total_out
        n_months  = max(len(filtered["month"].unique()), 1)
        avg_burn  = total_out / n_months

        kpis = [
            kpi_card("Total Income", f"${total_in:,.0f}", f"{n_months} months", ACCENT2),
            kpi_card("Total Spending", f"${total_out:,.0f}", "excl. transfers", ACCENT3),
            kpi_card("Net Cash Flow", f"${net:,.0f}",
                     "surplus" if net >= 0 else "deficit",
                     ACCENT2 if net >= 0 else ACCENT3),
            kpi_card("Avg Monthly Burn", f"${avg_burn:,.0f}", "per month", ACCENT),
        ]

        # ── Chart template ───────────────────────────────────────────────────
        def dark_layout(title=""):
            return dict(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                title=dict(text=title, font=dict(size=14, color=TEXT)),
                margin=dict(l=40, r=20, t=40, b=40),
                font=dict(family="Inter, Segoe UI, sans-serif", color=TEXT),
            )

        # ── 1. Income vs Expense by Month ────────────────────────────────────
        inc_by_month = inc.groupby("month")["signed_amount"].sum().reset_index(name="Income")
        exp_by_month = exp.groupby("month")["abs_amount"].sum().reset_index(name="Spending")
        merged = pd.merge(inc_by_month, exp_by_month, on="month", how="outer").fillna(0).sort_values("month")
        merged["Net"] = merged["Income"] - merged["Spending"]

        fig_ie = go.Figure()
        fig_ie.add_bar(x=merged["month"], y=merged["Income"], name="Income",
                       marker_color=ACCENT2, marker_cornerradius=6)
        fig_ie.add_bar(x=merged["month"], y=merged["Spending"], name="Spending",
                       marker_color=ACCENT3, marker_cornerradius=6)
        fig_ie.add_scatter(x=merged["month"], y=merged["Net"], name="Net",
                           mode="lines+markers", line=dict(color=ACCENT, width=2))
        fig_ie.update_layout(**dark_layout("Income vs Spending by Month"), barmode="group",
                             legend=dict(orientation="h", y=-0.15))

        # ── 2. Category Donut ────────────────────────────────────────────────
        cat_totals = exp.groupby("category")["abs_amount"].sum().sort_values(ascending=False).head(12)
        fig_pie = go.Figure(go.Pie(
            labels=cat_totals.index, values=cat_totals.values,
            hole=0.55, textinfo="label+percent", textposition="outside",
            marker=dict(colors=CATEGORY_PALETTE),
        ))
        
        pie_layout = dark_layout("Spending by Category")
        pie_layout.update({
            "showlegend": False,
            "margin": dict(l=20, r=20, t=40, b=20)
        })
        fig_pie.update_layout(pie_layout)

        # ── 3. Weekly Burn Rate Trend ────────────────────────────────────────
        weekly_burn = exp.groupby("week")["abs_amount"].sum().reset_index()
        weekly_burn.columns = ["week", "amount"]
        fig_burn = go.Figure()
        fig_burn.add_scatter(x=weekly_burn["week"], y=weekly_burn["amount"],
                             mode="lines+markers", fill="tozeroy",
                             line=dict(color=ACCENT3, width=2),
                             fillcolor="rgba(255,107,107,0.15)",
                             marker=dict(size=5))
        fig_burn.update_layout(**dark_layout("Weekly Burn Rate"))

        # ── 4. Officiating Income ────────────────────────────────────────────
        off_mask = inc["description"].str.contains(
            cfg.officiating_pattern, case=False, na=False
        )
        off = inc[off_mask].copy()
        off_monthly = off.groupby("month")["signed_amount"].sum().reset_index()
        off_monthly.columns = ["month", "amount"]
        off_monthly["cumulative"] = off_monthly["amount"].cumsum()

        fig_off = go.Figure()
        fig_off.add_bar(x=off_monthly["month"], y=off_monthly["amount"],
                        name="Monthly", marker_color=ACCENT, marker_cornerradius=6)
        fig_off.add_scatter(x=off_monthly["month"], y=off_monthly["cumulative"],
                            name="Cumulative", mode="lines+markers", yaxis="y2",
                            line=dict(color=ACCENT2, width=2))
        fig_off.update_layout(
            **dark_layout("🏀 Officiating Income (Hustle P&L)"),
            yaxis2=dict(overlaying="y", side="right", showgrid=False,
                        title="Cumulative $", color=ACCENT2),
            legend=dict(orientation="h", y=-0.15),
        )

        # ── 5. Subscription / Recurring Charges ──────────────────────────────
        recurring_keywords = cfg.subscription_keywords
        sub_mask = exp["description"].str.contains("|".join(recurring_keywords), case=False, na=False)
        subs = exp[sub_mask].copy()
        sub_monthly = subs.groupby("description")["abs_amount"].sum().sort_values(ascending=True).tail(14)

        fig_sub = go.Figure(go.Bar(
            y=sub_monthly.index, x=sub_monthly.values,
            orientation="h", marker_color=ACCENT,
            marker_cornerradius=6,
        ))
        fig_sub.update_layout(**dark_layout("💳 Subscription & Recurring (Period Total)"))

        # ── 6. Top Merchants ─────────────────────────────────────────────────
        merchant_totals = exp.groupby("description")["abs_amount"].sum().sort_values(ascending=True).tail(15)
        fig_merch = go.Figure(go.Bar(
            y=merchant_totals.index, x=merchant_totals.values,
            orientation="h",
            marker=dict(color=merchant_totals.values, colorscale="Viridis"),
            marker_cornerradius=6,
        ))
        fig_merch.update_layout(**dark_layout("🏪 Top Merchants by Spend"))

        # ── Transaction Table (Full) ─────────────────────────────────────────
        # Prepare data for DataTable
        table_df = filtered.sort_values("date", ascending=False).copy()
        
        # Apply Category Filter if present
        if cat_filter:
            table_df = table_df[table_df["category"].isin(cat_filter)]
            
        table_df["date_str"] = table_df["date"].dt.strftime("%Y-%m-%d")
        table_df["amount_str"] = table_df["signed_amount"].apply(lambda x: f"${x:,.2f}")
        
        table_data = table_df.to_dict("records")
        
        # Build Dropdown Options
        unique_cats = sorted(ALL["category"].dropna().unique())
        if "Uncategorized" in unique_cats:
            unique_cats.remove("Uncategorized")
            unique_cats = ["Uncategorized"] + unique_cats
            
        dropdown_options = {
            "category": {
                "options": [
                    {"label": "✨ Add New...", "value": "ADD_NEW"}
                ] + [{"label": c, "value": c} for c in unique_cats]
            }
        }
        
        filter_opts = [{"label": c, "value": c} for c in unique_cats]

        return kpis, fig_ie, fig_pie, fig_burn, fig_off, fig_sub, fig_merch, table_data, dropdown_options, filter_opts
    except Exception:
        log.exception("Error in update_dashboard callback")
        return [], go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure(), [], {}, []


# ─── Separate Callbacks ──────────────────────────────────────────────────────

@callback(
    Output("txn-table", "page_size"),
    Input("page-size-dropdown", "value")
)
def update_page_size(size):
    try:
        if not size: return 15
        return int(size)
    except Exception:
        log.warning("Invalid page size, defaulting to 15")
        return 15


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  🚀  Project Antigravity Dashboard")
    print(f"  📊  Loaded {len(ALL):,} transactions across {ALL['institution'].nunique()} institutions")
    print(f"  📅  Date range: {ALL['date'].min().date()} → {ALL['date'].max().date()}")
    print(f"  🌐  Open http://127.0.0.1:8050 in your browser\n")
    app.run(debug=cfg.server_debug, port=cfg.server_port)
