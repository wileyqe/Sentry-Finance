#!/usr/bin/env node

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SQL_JS_DIST = path.join(ROOT, "frontend", "node_modules", "sql.js", "dist");
const DEFAULT_REGISTRY = path.join(
  ROOT,
  "docs",
  "audits",
  "number-trust",
  "ui-number-registry.yaml",
);
const DEFAULT_VOCABULARY = path.join(
  ROOT,
  "docs",
  "audits",
  "number-trust",
  "oracle-vocabulary.json",
);
const ACCOUNTS_CONFIG_PATH = path.join(ROOT, "accounts.yaml");
const OWNER_CONFIG_PATH = path.join(ROOT, "config", "owner_config.yaml");

const ORACLE_VERSION = "node-sqljs-oracle-v1";
const INVESTMENT_CASH_EQUIVALENTS = new Set(["SPAXX", "FDRXX"]);

function parseArgs(argv) {
  const args = {
    db: null,
    registry: DEFAULT_REGISTRY,
    vocabulary: DEFAULT_VOCABULARY,
    pretty: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--db") {
      args.db = argv[++i];
    } else if (arg === "--registry") {
      args.registry = argv[++i];
    } else if (arg === "--vocabulary") {
      args.vocabulary = argv[++i];
    } else if (arg === "--pretty") {
      args.pretty = true;
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  if (!args.db) {
    throw new Error("--db is required");
  }
  return args;
}

function cents(value) {
  return Math.round(Number(value || 0) * 100);
}

function decimalPlaces(value) {
  const text = String(value);
  if (!text.includes(".")) return 0;
  return text.length - text.indexOf(".") - 1;
}

function roundHalfEvenUnits(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (fraction < 0.5) return lower;
  if (fraction > 0.5) return lower + 1;
  return lower % 2 === 0 ? lower : lower + 1;
}

function roundToDisplayPrecision(value, displayPrecision) {
  if (value == null) return null;
  const numeric = Number(value);
  const precision = Number(displayPrecision);
  if (!Number.isFinite(numeric) || !Number.isFinite(precision) || precision <= 0) {
    return numeric;
  }
  const rounded = roundHalfEvenUnits(numeric / precision) * precision;
  const places = decimalPlaces(precision);
  return places ? Number(rounded.toFixed(places)) : Math.round(rounded);
}

function round1(value) {
  return roundToDisplayPrecision(Number(value || 0), 0.1);
}

function round2(value) {
  return roundToDisplayPrecision(Number(value || 0), 0.01);
}

export { roundToDisplayPrecision };

function monthBounds(referenceDate) {
  const [yearText, monthText] = referenceDate.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return {
    start: `${yearText}-${monthText}-01`,
    end: `${yearText}-${monthText}-${String(last).padStart(2, "0")}`,
  };
}

function addMonths(isoDate, delta) {
  const [yearText, monthText] = isoDate.slice(0, 7).split("-");
  const monthIndex = Number(yearText) * 12 + Number(monthText) - 1 + delta;
  const year = Math.floor(monthIndex / 12);
  const month = (monthIndex % 12) + 1;
  return `${year}-${String(month).padStart(2, "0")}-01`;
}

function monthEnd(year, month) {
  const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function monthSeries(referenceDate, months) {
  const start = addMonths(`${referenceDate.slice(0, 7)}-01`, -(months - 1));
  const out = [];
  for (let i = 0; i < months; i += 1) {
    out.push(addMonths(start, i));
  }
  return out;
}

function periodMonthCount(start, end) {
  const [sy, sm] = start.slice(0, 7).split("-").map(Number);
  const [ey, em] = end.slice(0, 7).split("-").map(Number);
  if (!sy || !sm || !ey || !em) return 1;
  return Math.max(1, (ey * 12 + em) - (sy * 12 + sm) + 1);
}

function previousMonthStart(referenceDate, delta) {
  const [yearText, monthText] = referenceDate.split("-");
  const monthIndex = Number(yearText) * 12 + Number(monthText) - 1 + delta;
  const year = Math.floor(monthIndex / 12);
  const month = (monthIndex % 12) + 1;
  return `${year}-${String(month).padStart(2, "0")}-01`;
}

function monthKey(value) {
  return String(value || "").slice(0, 7);
}

function placeholders(values) {
  return values.map(() => "?").join(",");
}

class OracleDb {
  constructor(db) {
    this.db = db;
  }

  all(sql, params = []) {
    const stmt = this.db.prepare(sql);
    try {
      stmt.bind(params);
      const rows = [];
      while (stmt.step()) {
        rows.push(stmt.getAsObject());
      }
      return rows;
    } finally {
      stmt.free();
    }
  }

  one(sql, params = []) {
    return this.all(sql, params)[0] || null;
  }

  scalar(sql, params = []) {
    const row = this.one(sql, params);
    if (!row) return null;
    return Object.values(row)[0];
  }
}

class NumberTrustOracle {
  constructor(db, registry, vocabulary, manifest) {
    this.db = db;
    this.registry = registry;
    this.vocabulary = vocabulary;
    this.manifest = manifest;
    this.ownerAccountCache = new Map();
  }

  registryViewStates() {
    return (this.registry.view_states || []).map((state) => ({
      id: state.id,
      view: state.view,
      owner_id: state.owner_id ?? null,
      expected_state: state.expected_state,
    }));
  }

  scopedId(baseId, viewState) {
    return `${baseId}@${viewState.id}`;
  }

  ownerAccountIds(ownerId) {
    if (ownerId == null) return null;
    const cacheKey = ownerId.toLowerCase();
    if (this.ownerAccountCache.has(cacheKey)) {
      return this.ownerAccountCache.get(cacheKey);
    }
    const owner = this.db.one(
      "SELECT id FROM owners WHERE LOWER(id) = LOWER(?)",
      [ownerId],
    );
    if (!owner) {
      this.ownerAccountCache.set(cacheKey, []);
      return [];
    }
    const rows = this.db.all(
      `
      SELECT id
        FROM accounts
       WHERE is_active = 1
         AND (LOWER(owner_id) = LOWER(?) OR owner_id IS NULL)
       ORDER BY id
      `,
      [ownerId],
    );
    const ids = rows.map((row) => row.id);
    this.ownerAccountCache.set(cacheKey, ids);
    return ids;
  }

  accountScope(ownerId, column = "account_id") {
    const accountIds = this.ownerAccountIds(ownerId);
    if (accountIds == null) return { sql: "", params: [] };
    if (accountIds.length === 0) return { sql: " AND 1=0", params: [] };
    return {
      sql: ` AND ${column} IN (${placeholders(accountIds)})`,
      params: accountIds,
    };
  }

  manifestPayload() {
    const row = this.db.one(
      "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'",
    );
    if (!row) {
      throw new Error("trusted seed manifest not found in app_settings");
    }
    return JSON.parse(row.value);
  }

  latestNetWorth(referenceDate, ownerId) {
    const { end: monthEnd } = monthBounds(referenceDate);
    const accountScope = this.accountScope(ownerId, "id");
    const accounts = this.db.all(
      `SELECT id, type, is_active FROM accounts WHERE 1=1${accountScope.sql}`,
      accountScope.params,
    );
    if (accounts.length === 0) return null;

    let banking = 0;
    let liabilities = 0;
    for (const account of accounts) {
      const balance = this.db.one(
        `
        SELECT balance FROM balance_snapshots
         WHERE account_id = ? AND as_of <= ?
         ORDER BY as_of DESC LIMIT 1
        `,
        [account.id, monthEnd],
      );
      if (!balance) continue;
      if (["checking", "savings"].includes(account.type)) {
        banking += Number(balance.balance || 0);
      } else if (
        ["credit_card", "loan", "bnpl", "mortgage"].includes(account.type)
        && Number(account.is_active || 0) === 1
      ) {
        liabilities += Number(balance.balance || 0);
      }
    }

    const portfolioScope = this.accountScope(ownerId, "id");
    const investmentAccounts = this.db.all(
      `
      SELECT id
        FROM accounts
       WHERE type IN ('investment', 'retirement')
         ${portfolioScope.sql}
      `,
      portfolioScope.params,
    );
    let portfolio = 0;
    for (const account of investmentAccounts) {
      const row = this.db.one(
        `
        SELECT total_account_value FROM portfolio_snapshots
         WHERE account_id = ? AND timestamp < date(?, '+1 month')
         ORDER BY timestamp DESC LIMIT 1
        `,
        [account.id, `${monthEnd.slice(0, 7)}-01`],
      );
      if (row) portfolio += Number(row.total_account_value || 0);
    }

    let realEstateSql = `
      SELECT name, estimated_value FROM real_estate r
       WHERE name NOT LIKE '%[%'
         AND as_of = (
           SELECT MAX(as_of) FROM real_estate r2
            WHERE r2.name = r.name AND r2.as_of <= ?
         )
    `;
    const realEstateParams = [monthEnd];
    if (ownerId) {
      realEstateSql += " AND LOWER(owner_id) = LOWER(?)";
      realEstateParams.push(ownerId);
    }
    const realEstate = this.db
      .all(realEstateSql, realEstateParams)
      .reduce((total, row) => total + Number(row.estimated_value || 0), 0);

    let vehicleSql = `
      SELECT vehicle_id, estimated_value FROM vehicle_valuations vv
       WHERE valuation_date = (
         SELECT MAX(valuation_date) FROM vehicle_valuations vv2
          WHERE vv2.vehicle_id = vv.vehicle_id AND vv2.valuation_date <= ?
       )
    `;
    const vehicleParams = [monthEnd];
    if (ownerId) {
      vehicleSql += `
        AND EXISTS (
          SELECT 1 FROM vehicle_assets va
           WHERE va.id = vv.vehicle_id
             AND LOWER(va.owner_id) = LOWER(?)
        )
      `;
      vehicleParams.push(ownerId);
    }
    const vehicles = this.db
      .all(vehicleSql, vehicleParams)
      .reduce((total, row) => total + Number(row.estimated_value || 0), 0);

    const assets = round2(banking + portfolio + realEstate + vehicles);
    return {
      month: monthEnd.slice(0, 7),
      assets,
      liabilities: round2(liabilities),
      net_worth: round2(assets + liabilities),
    };
  }

  payrollAdjustment(start, end, ownerId) {
    const startEm = monthKey(start);
    const endEm = monthKey(end);
    let payrollSql = `
      SELECT * FROM payroll_snapshots
       WHERE pay_period BETWEEN ? AND ?
    `;
    const payrollParams = [startEm, endEm];
    if (ownerId) {
      payrollSql += " AND LOWER(owner_id) = LOWER(?)";
      payrollParams.push(ownerId);
    }
    payrollSql += " ORDER BY pay_period ASC, id ASC";

    const rows = this.db.all(payrollSql, payrollParams);
    const matchScope = this.accountScope(ownerId, "account_id");
    let withholdingCents = 0;
    let withholdingCount = 0;
    const excludedTxIds = new Set();
    const incomeCategories = [];

    for (const row of rows) {
      const gross = cents(row.gross_pay);
      for (const col of [
        "federal_tax",
        "state_tax",
        "sbp_premium",
        "health_insurance",
        "dental_vision",
        "other_deductions",
      ]) {
        const amount = cents(row[col]);
        if (amount) {
          withholdingCents += amount;
          withholdingCount += 1;
        }
      }

      const source = String(row.source || "").trim().toLowerCase();
      let match = null;
      if (source.length >= 3) {
        const pattern = `%${source}%`;
        match = this.db.one(
          `
          SELECT id FROM transactions
           WHERE status = 'posted'
             AND signed_amount > 0
             AND transfer_tag IS NULL
             AND substr(COALESCE(effective_month, strftime('%Y-%m', posting_date)), 1, 7) = ?
             ${matchScope.sql}
             AND (LOWER(COALESCE(merchant, '')) LIKE ?
                  OR LOWER(COALESCE(description, '')) LIKE ?)
           ORDER BY signed_amount DESC, id ASC LIMIT 1
          `,
          [row.pay_period, ...matchScope.params, pattern, pattern],
        );
      }

      const label = match && !excludedTxIds.has(match.id)
        ? "Paycheck (gross)"
        : "Paycheck (no deposit matched)";
      if (match && !excludedTxIds.has(match.id)) {
        excludedTxIds.add(match.id);
      }
      if (gross > 0) {
        incomeCategories.push({
          category: label,
          total_cents: gross,
          count: 1,
        });
      }
    }

    return {
      withholdingCents,
      withholdingCount,
      excludedTxIds,
      incomeCategories,
    };
  }

  cashoutPeriod(start, end, ownerId) {
    const startEm = monthKey(start);
    const endEm = monthKey(end);
    const payroll = this.payrollAdjustment(start, end, ownerId);
    const accountScope = this.accountScope(ownerId, "account_id");
    const accountScopeT = this.accountScope(ownerId, "t.account_id");

    const excludedIds = Array.from(payroll.excludedTxIds).sort();
    const excludedClause = excludedIds.length
      ? `AND id NOT IN (${placeholders(excludedIds)})`
      : "";
    const incomeExcl = this.vocabulary.income_excl_from_inc;
    const incomeRows = this.db.all(
      `
      SELECT COALESCE(category, 'Other Income') AS category,
             COALESCE(SUM(signed_amount), 0) AS total,
             COUNT(*) AS count
        FROM transactions
       WHERE status = 'posted'
         AND signed_amount > 0
         AND transfer_tag IS NULL
         AND COALESCE(category, 'Other Income') NOT IN (${placeholders(incomeExcl)})
         ${excludedClause}
         AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) BETWEEN ? AND ?
         ${accountScope.sql}
       GROUP BY category
      `,
      [
        ...incomeExcl,
        ...excludedIds,
        startEm,
        endEm,
        ...accountScope.params,
      ],
    );

    const incomeCategories = incomeRows.map((row) => ({
      category: row.category,
      total_cents: cents(row.total),
      count: row.count,
    }));
    incomeCategories.push(...payroll.incomeCategories);
    incomeCategories.sort((a, b) => b.total_cents - a.total_cents);
    const incomeCents = incomeCategories.reduce((total, row) => total + row.total_cents, 0);

    const cashTypes = this.vocabulary.cash_account_types;
    const spendExclude = this.vocabulary.cashout_spend_exclude;
    const spendRows = this.db.all(
      `
      SELECT COALESCE(t.category, 'Uncategorized') AS category,
             SUM(-t.signed_amount) AS total,
             COUNT(*) AS count
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
       WHERE t.status = 'posted'
         AND t.signed_amount < 0
         AND t.transfer_tag IS NULL
         AND a.type IN (${placeholders(cashTypes)})
         AND COALESCE(t.category, 'Uncategorized') NOT IN (${placeholders(spendExclude)})
         AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
         ${accountScopeT.sql}
       GROUP BY category
      `,
      [...cashTypes, ...spendExclude, startEm, endEm, ...accountScopeT.params],
    );

    const spendingCategories = spendRows.map((row) => ({
      category: row.category,
      total_cents: cents(row.total),
      count: row.count,
    }));
    const ordinarySpendCents = spendRows.reduce((total, row) => total + cents(row.total), 0);
    const debtCashCategories = new Set(this.vocabulary.debt_cash_categories);
    const rawDebtCashCents = spendRows
      .filter((row) => debtCashCategories.has(row.category))
      .reduce((total, row) => total + cents(row.total), 0);

    const mortgageRows = this.db.all(
      `
      SELECT t.id, t.signed_amount, s.principal_cents, s.interest_cents, s.escrow_cents
        FROM transactions t
        LEFT JOIN loan_payment_splits s ON s.transaction_id = t.id
       WHERE t.status = 'posted'
         AND t.signed_amount < 0
         AND t.transfer_tag IS NULL
         AND t.category IN ('Mortgage', 'Mortgages')
         AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
         ${accountScopeT.sql}
      `,
      [startEm, endEm, ...accountScopeT.params],
    );
    let mortgageConsumedCents = 0;
    let mortgagePrincipalCents = 0;
    for (const row of mortgageRows) {
      const total = cents(Math.abs(Number(row.signed_amount || 0)));
      if (row.principal_cents == null) {
        mortgageConsumedCents += total;
      } else {
        mortgagePrincipalCents += Number(row.principal_cents || 0);
        mortgageConsumedCents += Number(row.interest_cents || 0) + Number(row.escrow_cents || 0);
      }
    }

    const transferRows = this.db.all(
      `
      SELECT t.id, t.transfer_tag, t.account_id, t.signed_amount
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
       WHERE t.status = 'posted'
         AND t.signed_amount < 0
         AND t.transfer_tag IS NOT NULL
         AND a.type IN ('checking', 'savings', 'money_market')
         AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
         ${accountScopeT.sql}
      `,
      [startEm, endEm, ...accountScopeT.params],
    );
    let transferToLiabilityCents = 0;
    let ccPaymentCents = 0;
    let ccPaymentCount = 0;
    let loanPaymentViaTransferCents = 0;
    let loanPaymentViaTransferCount = 0;
    const liabilityTypes = new Set(this.vocabulary.liability_types);
    for (const row of transferRows) {
      const peer = this.db.one(
        `
        SELECT a.type FROM transactions p
          JOIN accounts a ON a.id = p.account_id
         WHERE p.transfer_tag = ?
           AND p.id != ?
           AND p.signed_amount > 0
         ORDER BY p.posting_date LIMIT 1
        `,
        [row.transfer_tag, row.id],
      );
      const peerType = String(peer?.type || "").toLowerCase();
      if (liabilityTypes.has(peerType)) {
        const amount = cents(Math.abs(Number(row.signed_amount || 0)));
        transferToLiabilityCents += amount;
        if (["credit_card", "credit", "bnpl"].includes(peerType)) {
          ccPaymentCents += amount;
          ccPaymentCount += 1;
        } else if (["loan", "mortgage"].includes(peerType)) {
          loanPaymentViaTransferCents += amount;
          loanPaymentViaTransferCount += 1;
        }
      }
    }

    const debtAccumulatedExcl = this.vocabulary.debt_accumulated_exclude;
    const debtAccumulatedRow = this.db.one(
      `
      SELECT COALESCE(SUM(-t.signed_amount), 0) AS total
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
       WHERE t.status = 'posted'
         AND t.signed_amount < 0
         AND t.transfer_tag IS NULL
         AND a.type IN ('credit_card', 'credit', 'bnpl')
         AND COALESCE(t.category, '') NOT IN (${placeholders(debtAccumulatedExcl)})
         AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
         ${accountScopeT.sql}
      `,
      [...debtAccumulatedExcl, startEm, endEm, ...accountScopeT.params],
    );
    const debtAccumulatedCents = cents(debtAccumulatedRow?.total);

    if (mortgageConsumedCents > 0) {
      spendingCategories.push({
        category: "Mortgage Interest & Escrow",
        total_cents: mortgageConsumedCents,
        count: mortgageRows.length,
      });
    }
    if (ccPaymentCents > 0) {
      spendingCategories.push({
        category: "Credit Card Payments",
        total_cents: ccPaymentCents,
        count: ccPaymentCount,
      });
    }
    if (loanPaymentViaTransferCents > 0) {
      spendingCategories.push({
        category: "Loan / Mortgage Transfers",
        total_cents: loanPaymentViaTransferCents,
        count: loanPaymentViaTransferCount,
      });
    }
    if (payroll.withholdingCents > 0) {
      spendingCategories.push({
        category: "Taxes & Withholdings",
        total_cents: payroll.withholdingCents,
        count: payroll.withholdingCount,
      });
    }
    spendingCategories.sort((a, b) => b.total_cents - a.total_cents);

    const spendingCents = ordinarySpendCents
      + payroll.withholdingCents
      + mortgageConsumedCents
      + transferToLiabilityCents;
    const debtServiceCents = mortgageConsumedCents + transferToLiabilityCents + rawDebtCashCents;
    const debtPaidDownCents = mortgagePrincipalCents + transferToLiabilityCents + rawDebtCashCents;
    const netCents = incomeCents - spendingCents;
    const savingsRate = incomeCents ? round1((netCents / incomeCents) * 100) : 0;

    const toBreakdown = (rows, totalCents) => rows
      .filter((row) => row.total_cents > 0)
      .map((row) => ({
        category: row.category,
        total: round2(row.total_cents / 100),
        count: row.count,
        pct: totalCents ? round1((row.total_cents / totalCents) * 100) : 0,
      }));

    return {
      income: round2(incomeCents / 100),
      spending: round2(spendingCents / 100),
      net: round2(netCents / 100),
      savings_rate: savingsRate,
      debt_service: round2(debtServiceCents / 100),
      debt_accumulated: round2(debtAccumulatedCents / 100),
      debt_paid_down: round2(debtPaidDownCents / 100),
      net_debt_change: round2((debtAccumulatedCents - debtPaidDownCents) / 100),
      income_categories: toBreakdown(incomeCategories, incomeCents),
      spending_categories: toBreakdown(spendingCategories, spendingCents),
    };
  }

  reportSummary(start, end, ownerId) {
    const cashout = this.cashoutPeriod(start, end, ownerId);
    return {
      total_income: cashout.income,
      total_spending: cashout.spending,
      net: cashout.net,
      savings_rate: cashout.savings_rate,
      debt_service: cashout.debt_service,
      debt_accumulated: cashout.debt_accumulated,
      debt_paid_down: cashout.debt_paid_down,
      net_debt_change: cashout.net_debt_change,
      definition: "cash_out_grossup",
      top_categories: cashout.spending_categories.slice(0, 3).map((row) => ({
        category: row.category,
        total_spent: row.total,
        transaction_count: row.count,
        pct_of_total: row.pct,
      })),
      categories_with_spend: cashout.spending_categories.length,
    };
  }

  emergencyFund(referenceDate, ownerId) {
    const accountScopeA = this.accountScope(ownerId, "a.id");
    const accountScopeTx = this.accountScope(ownerId, "account_id");
    const liquid = this.db.scalar(
      `
      SELECT COALESCE(SUM(latest.balance), 0) AS total
        FROM accounts a
        JOIN (
          SELECT bs.account_id, bs.balance
            FROM balance_snapshots bs
            JOIN (
              SELECT account_id, MAX(as_of) AS max_as_of
                FROM balance_snapshots GROUP BY account_id
            ) mx ON mx.account_id = bs.account_id AND mx.max_as_of = bs.as_of
        ) latest ON latest.account_id = a.id
       WHERE a.type IN ('checking', 'savings') AND a.is_active = 1
         ${accountScopeA.sql}
      `,
      accountScopeA.params,
    );

    const start = previousMonthStart(referenceDate, -6);
    const end = `${referenceDate.slice(0, 7)}-01`;
    const exclusions = this.vocabulary.all_excl_from_spend;
    const rows = this.db.all(
      `
      SELECT COALESCE(effective_month, strftime('%Y-%m', posting_date)) AS month,
             SUM(-signed_amount) AS total
        FROM transactions
       WHERE status = 'posted'
         AND signed_amount < 0
         AND transfer_tag IS NULL
         ${accountScopeTx.sql}
         AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})
         AND posting_date >= ?
         AND posting_date < ?
       GROUP BY month
      `,
      [...accountScopeTx.params, ...exclusions, start, end],
    );
    const avg = rows.length
      ? rows.reduce((total, row) => total + Number(row.total || 0), 0) / rows.length
      : 0;
    return {
      liquid_balance: round2(liquid),
      avg_monthly_spending: round2(avg),
      months_of_runway: avg ? round1(Number(liquid || 0) / avg) : null,
    };
  }

  latestCreditScores(ownerId) {
    let inner = "";
    let outer = "";
    const params = [];
    if (ownerId) {
      inner = "WHERE LOWER(owner_id) = LOWER(?)";
      outer = "WHERE LOWER(cs.owner_id) = LOWER(?)";
      params.push(ownerId, ownerId);
    }
    return this.db.all(
      `
      SELECT cs.score, cs.score_type, cs.source, cs.institution_id,
             cs.score_date, cs.owner_id
        FROM credit_scores cs
        JOIN (
          SELECT owner_id, institution_id, source, MAX(score_date) AS max_date
            FROM credit_scores
           ${inner}
           GROUP BY owner_id, institution_id, source
        ) latest ON cs.owner_id IS latest.owner_id
                 AND cs.institution_id = latest.institution_id
                 AND cs.source = latest.source
                 AND cs.score_date = latest.max_date
       ${outer}
       ORDER BY cs.owner_id, cs.score_date DESC
      `,
      params,
    ).map((row) => ({
      score: row.score,
      score_type: row.score_type,
      source: row.source,
      institution_id: row.institution_id,
      score_date: row.score_date,
      owner_id: row.owner_id,
      factors: [],
    }));
  }

  freshness(referenceDate, ownerId) {
    const accountScope = this.accountScope(ownerId, "id");
    const accountScopeA = this.accountScope(ownerId, "a.id");
    const activeRows = this.db.all(
      `SELECT DISTINCT institution_id FROM accounts WHERE is_active = 1${accountScope.sql}`,
      accountScope.params,
    );
    const institutions = new Set(activeRows.map((row) => row.institution_id));
    institutions.add("tsp");
    institutions.add("mypay");
    try {
      for (const row of this.db.all("SELECT institution_id FROM institution_refresh_status")) {
        institutions.add(row.institution_id);
      }
    } catch {
      // The table exists in canonical seed; keep this independent oracle tolerant.
    }

    const refreshLast = new Map();
    try {
      for (const row of this.db.all(
        "SELECT institution_id, last_success FROM institution_refresh_status",
      )) {
        if (row.last_success) refreshLast.set(row.institution_id, row.last_success);
      }
    } catch {
      // Ignore pre-upgrade databases.
    }

    const groupedLatest = (sql) => {
      const map = new Map();
      for (const row of this.db.all(sql, accountScopeA.params)) {
        if (row.latest) map.set(row.institution_id, row.latest);
      }
      return map;
    };

    const balanceLast = groupedLatest(`
      SELECT a.institution_id, MAX(bs.as_of) AS latest
        FROM balance_snapshots bs
        JOIN accounts a ON a.id = bs.account_id
       WHERE 1=1
         ${accountScopeA.sql}
       GROUP BY a.institution_id
    `);
    const portfolioLast = groupedLatest(`
      SELECT a.institution_id, MAX(ps.timestamp) AS latest
        FROM portfolio_snapshots ps
        JOIN accounts a ON a.id = ps.account_id
       WHERE 1=1
         ${accountScopeA.sql}
       GROUP BY a.institution_id
    `);
    let apyLast = new Map();
    try {
      apyLast = groupedLatest(`
        SELECT a.institution_id, MAX(ah.as_of) AS latest
          FROM apy_history ah
          JOIN accounts a ON a.id = ah.account_id
         WHERE 1=1
           ${accountScopeA.sql}
         GROUP BY a.institution_id
      `);
    } catch {
      apyLast = new Map();
    }

    const referenceMidnight = Date.parse(`${referenceDate}T00:00:00Z`);
    const rows = [];
    for (const inst of institutions) {
      const candidates = [
        refreshLast.get(inst),
        balanceLast.get(inst),
        portfolioLast.get(inst),
        apyLast.get(inst),
      ].filter(Boolean);
      const tsRaw = candidates.length ? candidates.sort().at(-1) : null;
      const expectedHours = ["tsp", "mypay"].includes(inst) ? 720 : 24;
      let staleness = "no_data";
      if (tsRaw) {
        let parsed;
        if (!String(tsRaw).includes("T") && !String(tsRaw).includes(" ")) {
          parsed = Date.parse(`${String(tsRaw).slice(0, 10)}T23:59:59Z`);
        } else {
          const iso = String(tsRaw).replace("Z", "+00:00");
          parsed = Date.parse(iso.includes("+") ? iso : `${iso}Z`);
        }
        const hoursSince = Math.max((referenceMidnight - parsed) / 3600000, 0);
        if (hoursSince <= expectedHours) {
          staleness = "fresh";
        } else if (hoursSince <= expectedHours * 3) {
          staleness = "stale";
        } else {
          staleness = "critical";
        }
      }
      rows.push({ institution_id: inst, staleness });
    }
    return rows.sort((a, b) => a.institution_id.localeCompare(b.institution_id));
  }

  netWorthHistory(referenceDate, months, ownerId) {
    return monthSeries(referenceDate, months)
      .map((monthStart) => this.latestNetWorth(monthStart, ownerId))
      .filter(Boolean);
  }

  netWorthVelocity(referenceDate, ownerId) {
    const history = this.netWorthHistory(referenceDate, 24, ownerId);
    const velocityHistory = history.map((item, index) => {
      const row = {
        month: item.month,
        net_worth: item.net_worth,
        mom_change: null,
        mom_pct: null,
      };
      if (index > 0) {
        const previous = history[index - 1].net_worth;
        const change = round2(item.net_worth - previous);
        row.mom_change = change;
        if (previous !== 0) row.mom_pct = round1((change / Math.abs(previous)) * 100);
      }
      return row;
    });
    const current = velocityHistory.length ? velocityHistory.at(-1).net_worth : 0;
    const momChange = velocityHistory.length ? velocityHistory.at(-1).mom_change : null;
    const momPct = velocityHistory.length ? velocityHistory.at(-1).mom_pct : null;
    let rolling3Change = null;
    let rolling3Avg = null;
    let rolling12Change = null;
    let rolling12Avg = null;
    if (velocityHistory.length >= 4) {
      rolling3Change = round2(current - velocityHistory.at(-4).net_worth);
      rolling3Avg = round2(rolling3Change / 3);
    }
    if (velocityHistory.length >= 13) {
      rolling12Change = round2(current - velocityHistory.at(-13).net_worth);
      rolling12Avg = round2(rolling12Change / 12);
    }
    let trend = "insufficient_data";
    if (rolling3Avg != null) {
      if (rolling3Avg < 0) {
        trend = "declining";
      } else if (rolling12Avg != null) {
        if (rolling3Avg > 0 && rolling12Avg > 0) {
          const lower = rolling12Avg * 0.8;
          const upper = rolling12Avg * 1.2;
          if (rolling3Avg > upper) trend = "accelerating";
          else if (rolling3Avg < lower) trend = "decelerating";
          else trend = "steady";
        } else {
          trend = rolling3Avg > rolling12Avg ? "accelerating" : "decelerating";
        }
      }
    }
    return {
      current_net_worth: round2(current),
      mom_change: momChange,
      mom_pct: momPct,
      rolling_3m_change: rolling3Change,
      rolling_3m_monthly_avg: rolling3Avg,
      rolling_12m_change: rolling12Change,
      rolling_12m_monthly_avg: rolling12Avg,
      trend,
      history: velocityHistory,
    };
  }

  dashboardNetWorthDetails(referenceDate, ownerId) {
    const history = this.netWorthHistory(referenceDate, 6, ownerId);
    if (!history.length) {
      return {
        assets: 0,
        liabilities: 0,
        delta_amount: 0,
        delta_percent: 0,
        velocity_amount: 0,
      };
    }
    const first = history[0].net_worth;
    const latest = history.at(-1);
    const delta = round2(latest.net_worth - first);
    const months = Math.max(1, history.length - 1);
    return {
      assets: latest.assets,
      liabilities: latest.liabilities,
      delta_amount: delta,
      delta_percent: first ? round1((delta / first) * 100) : 0,
      velocity_amount: round2(delta / months),
    };
  }

  dtiSeries(referenceDate, months, ownerId) {
    const incomeCats = this.vocabulary.income_categories;
    const debtCats = ["Mortgages", "Loan Payments", "Credit Card Payments", "BNPL Payments"];
    const accountScope = this.accountScope(ownerId, "t.account_id");
    const currentMonth = `${referenceDate.slice(0, 7)}-01`;
    const windowStart = addMonths(currentMonth, -months);
    const rows = this.db.all(
      `
      SELECT COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) AS month,
             SUM(CASE
               WHEN t.transfer_tag IS NULL
                AND t.signed_amount > 0
                AND COALESCE(t.category, 'Other Income') IN (${placeholders(incomeCats)})
               THEN t.signed_amount ELSE 0 END) AS gross_income,
             SUM(CASE
               WHEN t.signed_amount < 0
                AND a.type IN ('checking', 'savings')
                AND COALESCE(t.category, '') IN (${placeholders(debtCats)})
               THEN ABS(t.signed_amount) ELSE 0 END) AS debt_payments
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
       WHERE t.status = 'posted'
         AND t.posting_date >= ?
         AND t.posting_date < ?
         ${accountScope.sql}
       GROUP BY month
       ORDER BY month ASC
      `,
      [...incomeCats, ...debtCats, windowStart, currentMonth, ...accountScope.params],
    );
    return rows.map((row) => {
      const income = round2(row.gross_income);
      const debt = round2(row.debt_payments);
      const dti = income ? round1((debt / income) * 100) : null;
      let status = null;
      if (dti != null) {
        if (dti <= 28) status = "healthy";
        else if (dti <= 36) status = "moderate";
        else if (dti <= 43) status = "high";
        else status = "critical";
      }
      return {
        month: row.month,
        debt_payments: debt,
        gross_income: income,
        dti_ratio: dti,
        status,
      };
    });
  }

  spendingComparison(referenceDate, ownerId) {
    const [yearText, monthText, dayText] = referenceDate.split("-");
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    const thisStart = `${yearText}-${monthText}-01`;
    const thisEnd = monthEnd(year, month);
    const prevStart = addMonths(thisStart, -1);
    const [py, pm] = prevStart.slice(0, 7).split("-").map(Number);
    const prevEnd = monthEnd(py, pm);
    const maxDays = Math.max(Number(thisEnd.slice(8)), Number(prevEnd.slice(8)), 31);
    const accountScope = this.accountScope(ownerId, "account_id");
    const exclusions = this.vocabulary.all_excl_from_spend;
    const daily = (start, end) => {
      const rows = this.db.all(
        `
        SELECT CAST(strftime('%d', posting_date) AS INTEGER) AS day,
               SUM(-signed_amount) AS daily_spent
          FROM transactions
         WHERE status = 'posted'
           AND signed_amount < 0
           AND transfer_tag IS NULL
           AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})
           AND posting_date >= ?
           AND posting_date <= ?
           ${accountScope.sql}
         GROUP BY day
        `,
        [...exclusions, start, end, ...accountScope.params],
      );
      return new Map(rows.map((row) => [Number(row.day), Number(row.daily_spent || 0)]));
    };
    const current = daily(thisStart, thisEnd);
    const previous = daily(prevStart, prevEnd);
    let cumCurrent = 0;
    let cumPrevious = 0;
    const rows = [];
    const prevLast = Number(prevEnd.slice(8));
    const currentLast = Number(thisEnd.slice(8));
    for (let d = 1; d <= maxDays; d += 1) {
      if (d <= prevLast) cumPrevious += previous.get(d) || 0;
      const item = { period: `Day ${d}`, Previous: round2(cumPrevious) };
      if (d <= day && d <= currentLast) {
        cumCurrent += current.get(d) || 0;
        item.Current = round2(cumCurrent);
      }
      rows.push(item);
    }
    return rows;
  }

  dashboardSpending(referenceDate, totalSpending, ownerId) {
    const comparison = this.spendingComparison(referenceDate, ownerId);
    let prevTotal = 0;
    for (let i = comparison.length - 1; i >= 0; i -= 1) {
      const value = comparison[i].Previous;
      if (value != null && value > 0) {
        prevTotal = value;
        break;
      }
    }
    const day = Number(referenceDate.slice(8));
    const [, monthText] = referenceDate.split("-");
    const lastDay = Number(monthEnd(Number(referenceDate.slice(0, 4)), Number(monthText)).slice(8));
    const delta = round2(totalSpending - prevTotal);
    const perDay = day ? totalSpending / day : 0;
    return {
      current_month_total: round2(totalSpending),
      previous_total: round2(prevTotal),
      delta_amount: delta,
      delta_percent: prevTotal ? round1((delta / prevTotal) * 100) : 0,
      per_day: round2(perDay),
      projected_eom: round2(perDay * lastDay),
      comparison,
    };
  }

  budgetSummary(month) {
    const targetRows = this.db.all(
      "SELECT category, target_amount FROM budgets WHERE month = ? AND owner_id IS NULL",
      [month],
    );
    const targets = new Map(targetRows.map((row) => [row.category, Number(row.target_amount || 0)]));
    const exclusions = this.vocabulary.all_excl_from_spend;
    const actualRows = this.db.all(
      `
      SELECT COALESCE(category, 'Uncategorized') AS category,
             SUM(-signed_amount) AS spending
        FROM transactions
       WHERE status = 'posted'
         AND signed_amount < 0
         AND transfer_tag IS NULL
         AND COALESCE(effective_month, strftime('%Y-%m', posting_date)) = ?
         AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})
       GROUP BY category
      `,
      [month, ...exclusions],
    );
    const actuals = new Map(actualRows.map((row) => [row.category, Number(row.spending || 0)]));
    const cats = Array.from(new Set([...targets.keys(), ...actuals.keys()])).sort();
    const categories = cats.map((category) => {
      const target = targets.get(category) || 0;
      const actual = actuals.get(category) || 0;
      const pctUsed = target > 0 ? (actual / target) * 100 : (actual > 0 ? 100 : 0);
      let status = "under";
      if (pctUsed >= 100) status = "over";
      else if (pctUsed >= 80) status = "warning";
      else if (pctUsed >= 50) status = "on_track";
      return {
        category,
        target: round2(target),
        target_amount: round2(target),
        actual: round2(actual),
        spent: round2(actual),
        remaining: round2(target - actual),
        pct_used: round1(pctUsed),
        status,
      };
    }).sort((a, b) => b.pct_used - a.pct_used);
    const totalBudget = round2(categories.reduce((sum, row) => sum + row.target, 0));
    const totalSpent = round2(categories.reduce((sum, row) => sum + row.actual, 0));
    return {
      month,
      total_budget: totalBudget,
      total_budgeted: totalBudget,
      total_spent: totalSpent,
      total_remaining: round2(totalBudget - totalSpent),
      pct_used: totalBudget ? round1((totalSpent / totalBudget) * 100) : 0,
      over_budget_count: categories.filter((row) => row.status === "over").length,
      categories_tracked: categories.length,
      categories,
    };
  }

  budgetsPage(referenceDate) {
    const month = referenceDate.slice(0, 7);
    const summary = this.budgetSummary(month);
    const visible = (summary.categories || [])
      .filter((cat) => Number(cat.target ?? cat.target_amount ?? 0) > 0
        || Number(cat.actual ?? 0) > 0)
      .sort((a, b) => Number(b.actual ?? 0) - Number(a.actual ?? 0));

    const totalAssigned = round2(visible.reduce(
      (sum, cat) => sum + Number(cat.target ?? cat.target_amount ?? 0),
      0,
    ));
    const totalSpent = round2(visible.reduce(
      (sum, cat) => sum + Number(cat.actual ?? 0),
      0,
    ));
    const remaining = round2(totalAssigned - totalSpent);
    const pctUsed = totalAssigned ? round1((totalSpent / totalAssigned) * 100) : 0;

    const [yearText, monthText] = month.split("-");
    const year = Number(yearText);
    const monthInt = Number(monthText);
    const daysInMonth = new Date(Date.UTC(year, monthInt, 0)).getUTCDate();
    const refYear = Number(referenceDate.slice(0, 4));
    const refMonth = Number(referenceDate.slice(5, 7));
    const refDay = Number(referenceDate.slice(8, 10));
    const sameMonth = refYear === year && refMonth === monthInt;
    const currentDay = sameMonth ? refDay : daysInMonth;
    const daysLeft = Math.max(0, daysInMonth - currentDay);
    const dailyAllowance = daysLeft > 0
      ? round2(Math.max(0, remaining) / daysLeft)
      : 0;

    return {
      month,
      total_assigned: totalAssigned,
      total_spent: totalSpent,
      total_remaining: remaining,
      pct_used: pctUsed,
      days_in_month: daysInMonth,
      days_left: daysLeft,
      daily_allowance: dailyAllowance,
      active_count: visible.length,
      categories: visible.map((cat) => ({
        category: cat.category,
        target: round2(cat.target ?? cat.target_amount ?? 0),
        actual: round2(cat.actual ?? 0),
        remaining: round2(cat.remaining ?? 0),
        status: cat.status,
      })),
    };
  }

  recurringDashboard(ownerId) {
    const accountScope = this.accountScope(ownerId, "account_id");
    const rows = this.db.all(
      `
      SELECT id, merchant, frequency, expected_amount, last_amount
        FROM recurring_transactions
       WHERE status = 'active'
         ${accountScope.sql}
       ORDER BY frequency, merchant
      `,
      accountScope.params,
    );
    const bills = rows.filter((row) => Number(row.expected_amount ?? row.last_amount ?? 0) < 0);
    const divisors = {
      monthly: 1,
      weekly: 1 / 4.33,
      biweekly: 1 / 2.17,
      quarterly: 3,
      "semi-annual": 6,
      annual: 12,
      yearly: 12,
    };
    let monthly = 0;
    for (const row of bills) {
      const raw = Number(row.expected_amount ?? row.last_amount ?? 0);
      const divisor = divisors[String(row.frequency || "monthly").toLowerCase()] ?? 1;
      monthly += Math.abs(raw) / divisor;
    }
    return {
      monthly_total: Math.round(monthly),
      item_amounts: bills.slice(0, 5).map((row) => round2(row.expected_amount ?? row.last_amount ?? 0)),
      item_ids: bills.slice(0, 5).map((row) => row.id),
      count: rows.length,
    };
  }

  transactionsPage(ownerId, { limit = 1000, startDate = null, endDate = null, excludeTransfers = false } = {}) {
    const clauses = ["1=1"];
    const params = [];
    if (startDate) {
      clauses.push("posting_date >= ?");
      params.push(startDate);
    }
    if (endDate) {
      clauses.push("posting_date <= ?");
      params.push(endDate);
    }
    if (excludeTransfers) {
      const exclusions = this.vocabulary.excluded_from_spend || [];
      clauses.push(`COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})`);
      params.push(...exclusions);
      clauses.push("transfer_tag IS NULL");
    }
    const accountScope = this.accountScope(ownerId, "account_id");
    const where = `${clauses.join(" AND ")}${accountScope.sql}`;
    const allParams = [...params, ...accountScope.params];
    const total = this.db.scalar(`SELECT COUNT(*) AS count FROM transactions WHERE ${where}`, allParams);
    const rows = this.db.all(
      `
      SELECT id, posting_date, signed_amount, amount, category, account_id, transfer_tag
        FROM transactions
       WHERE ${where}
       ORDER BY posting_date DESC
       LIMIT ? OFFSET 0
      `,
      [...allParams, limit],
    );
    const page = rows.slice(0, 25);
    const amount = (tx) => round2(tx.signed_amount ?? tx.amount ?? 0);
    return {
      row_amounts: page.map(amount),
      row_dates: page.map((tx) => tx.posting_date),
      filtered_count: rows.length,
      total_count: total,
      range_start: page.length ? 1 : 0,
      range_end: Math.min(25, rows.length),
      active_filter_count: 0,
      recent_amounts: rows.map(amount),
    };
  }

  cashoutRolling(referenceDate, ownerId, months = 18) {
    return monthSeries(referenceDate, months).map((monthStart) => {
      const [year, month] = monthStart.slice(0, 7).split("-").map(Number);
      const detail = this.cashoutPeriod(monthStart, monthEnd(year, month), ownerId);
      return {
        year,
        month,
        label: `${["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month]} '${String(year % 100).padStart(2, "0")}`,
        income: detail.income,
        spending: detail.spending,
        net: detail.net,
        savings_rate: detail.savings_rate,
        debt_service: detail.debt_service,
        debt_accumulated: detail.debt_accumulated,
        debt_paid_down: detail.debt_paid_down,
        net_debt_change: detail.net_debt_change,
      };
    });
  }

  bypassFlows(start, end, ownerId) {
    let sql = `
      SELECT id, display_label, owner_id, tax_treatment, match_rule_json
        FROM income_sources
       WHERE active = 1
         AND bypass_cash_routing = 1
    `;
    const params = [];
    if (ownerId) {
      sql += " AND LOWER(owner_id) = LOWER(?)";
      params.push(ownerId);
    }
    const months = periodMonthCount(start, end);
    return this.db.all(sql, params).flatMap((row) => {
      let rule;
      try {
        rule = JSON.parse(row.match_rule_json || "{}");
      } catch {
        return [];
      }
      const monthly = Number.parseInt(rule.monthly_amount_cents || 0, 10);
      if (monthly <= 0) return [];
      return [{
        source_id: row.id,
        display_label: row.display_label,
        owner_id: row.owner_id,
        tax_treatment: row.tax_treatment,
        monthly_amount_cents: monthly,
        months,
        amount_cents: monthly * months,
        bucket: "STORED_ILLIQUID",
      }];
    });
  }

  investmentTransferCents(start, end, ownerId) {
    const startEm = monthKey(start);
    const endEm = monthKey(end);
    const t1Scope = this.accountScope(ownerId, "t1.account_id");
    const tScope = this.accountScope(ownerId, "t.account_id");
    const row = this.db.one(
      `
      SELECT COALESCE(SUM(amount), 0) AS total FROM (
          SELECT t1.id, ABS(t1.signed_amount) AS amount
            FROM transactions t1
            JOIN transactions t2
                 ON t1.transfer_tag = t2.transfer_tag AND t1.id != t2.id
            JOIN accounts a2 ON a2.id = t2.account_id
           WHERE t1.status = 'posted'
             AND t1.signed_amount < 0
             AND t1.transfer_tag IS NOT NULL
             AND a2.type IN ('investment', 'brokerage', 'retirement', 'hsa')
             AND COALESCE(t1.effective_month, strftime('%Y-%m', t1.posting_date)) BETWEEN ? AND ?
             ${t1Scope.sql}
          UNION
          SELECT t.id, ABS(t.signed_amount) AS amount
            FROM transactions t
            JOIN positions_ledger pl ON pl.bank_txn_id = t.id
           WHERE t.status = 'posted'
             AND t.signed_amount < 0
             AND COALESCE(t.effective_month, strftime('%Y-%m', t.posting_date)) BETWEEN ? AND ?
             ${tScope.sql}
      )
      `,
      [startEm, endEm, ...t1Scope.params, startEm, endEm, ...tScope.params],
    );
    return cents(row?.total);
  }

  reportsFlow(start, end, ownerId) {
    const cashout = this.cashoutPeriod(start, end, ownerId);
    const bypass = this.bypassFlows(start, end, ownerId);
    const bypassCents = bypass.reduce((sum, row) => sum + Number(row.amount_cents || 0), 0);
    const investmentTransferCents = this.investmentTransferCents(start, end, ownerId);
    const consumed = cents(cashout.spending);
    const illiquid = investmentTransferCents + bypassCents;
    const totalInflow = cents(cashout.income) + bypassCents;
    const liquid = totalInflow - consumed - illiquid;
    const bucketTotalsCents = {
      CONSUMED: consumed,
      STORED_LIQUID: liquid,
      STORED_ILLIQUID: illiquid,
    };
    const bucketTotal = Object.values(bucketTotalsCents).reduce((sum, value) => sum + value, 0);
    return {
      total_income: cashout.income,
      total_spending: cashout.spending,
      net: cashout.net,
      savings_rate: cashout.savings_rate,
      bucket_totals: Object.fromEntries(
        Object.entries(bucketTotalsCents).map(([key, value]) => [key, round2(value / 100)]),
      ),
      bucket_totals_cents: bucketTotalsCents,
      bucket_percents: Object.fromEntries(
        Object.entries(bucketTotalsCents).map(([key, value]) => [
          key,
          bucketTotal ? round1((value / bucketTotal) * 100) : 0,
        ]),
      ),
      total_inflow_cents: totalInflow,
      bucket_invariant_drift_cents: Object.values(bucketTotalsCents).reduce((sum, value) => sum + value, 0) - totalInflow,
      bypass_flows: bypass,
      debt_service: cashout.debt_service,
      debt_accumulated: cashout.debt_accumulated,
      debt_paid_down: cashout.debt_paid_down,
      net_debt_change: cashout.net_debt_change,
    };
  }

  netWorthAtDate(asOf, ownerId) {
    const accountScope = this.accountScope(ownerId, "a.id");
    const balance = this.db.one(
      `
      WITH latest_bal AS (
          SELECT a.id, a.type, a.is_active,
                 (SELECT bs.balance FROM balance_snapshots bs
                   WHERE bs.account_id = a.id
                     AND date(bs.as_of) <= date(?)
                   ORDER BY bs.as_of DESC LIMIT 1) AS balance
            FROM accounts a
           WHERE 1=1 ${accountScope.sql}
      )
      SELECT SUM(CASE WHEN type IN ('checking','savings') THEN balance ELSE 0 END) AS banking,
             SUM(CASE WHEN type IN ('credit_card','loan','bnpl','mortgage')
                       AND is_active = 1 THEN balance ELSE 0 END) AS liabilities
        FROM latest_bal
       WHERE balance IS NOT NULL
      `,
      [asOf, ...accountScope.params],
    );
    const port = this.db.one(
      `
      WITH latest_port AS (
          SELECT a.id,
                 (SELECT ps.total_account_value FROM portfolio_snapshots ps
                   WHERE ps.account_id = a.id
                     AND date(ps.timestamp) <= date(?)
                   ORDER BY ps.timestamp DESC LIMIT 1) AS total
            FROM accounts a
           WHERE a.type IN ('investment','retirement')
             ${accountScope.sql}
      )
      SELECT SUM(total) AS portfolio FROM latest_port WHERE total IS NOT NULL
      `,
      [asOf, ...accountScope.params],
    );
    let reSql = `
      SELECT estimated_value FROM (
          SELECT estimated_value,
                 ROW_NUMBER() OVER (PARTITION BY name ORDER BY as_of DESC, rowid DESC) AS rn
            FROM real_estate
           WHERE name NOT LIKE '%[%'
             AND date(as_of) <= date(?)
    `;
    const reParams = [asOf];
    if (ownerId) {
      reSql += " AND LOWER(owner_id) = LOWER(?)";
      reParams.push(ownerId);
    }
    reSql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL";
    const realEstate = this.db.all(reSql, reParams).reduce((sum, row) => sum + cents(row.estimated_value), 0);
    let vehSql = `
      SELECT estimated_value FROM (
          SELECT vv.estimated_value,
                 ROW_NUMBER() OVER (
                   PARTITION BY vv.vehicle_id
                   ORDER BY vv.valuation_date DESC, vv.id DESC
                 ) AS rn
            FROM vehicle_valuations vv
    `;
    const vehParams = [asOf];
    if (ownerId) {
      vehSql += `
            JOIN vehicle_assets va ON va.id = vv.vehicle_id
           WHERE date(vv.valuation_date) <= date(?)
             AND LOWER(va.owner_id) = LOWER(?)
      `;
      vehParams.push(ownerId);
    } else {
      vehSql += " WHERE date(vv.valuation_date) <= date(?)";
    }
    vehSql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL";
    const vehicle = this.db.all(vehSql, vehParams).reduce((sum, row) => sum + cents(row.estimated_value), 0);
    const banking = cents(balance?.banking);
    const investment = cents(port?.portfolio);
    const liabilities = cents(balance?.liabilities);
    return {
      banking_cents: banking,
      investment_cents: investment,
      real_estate_cents: realEstate,
      vehicle_cents: vehicle,
      liabilities_cents: liabilities,
      net_worth_cents: banking + investment + realEstate + vehicle + liabilities,
    };
  }

  accountability(start, end, ownerId) {
    const nwStart = this.netWorthAtDate(start, ownerId);
    const nwEnd = this.netWorthAtDate(end, ownerId);
    const flow = this.reportsFlow(start, end, ownerId);
    const accountScope = this.accountScope(ownerId, "account_id");
    const capex = this.db.one(
      `
      SELECT COALESCE(SUM(-signed_amount), 0) AS capex
        FROM transactions
       WHERE status = 'posted'
         AND signed_amount < 0
         AND transfer_tag IS NULL
         AND category = 'Home Improvement'
         AND date(posting_date) >= date(?)
         AND date(posting_date) <= date(?)
         ${accountScope.sql}
      `,
      [start, end, ...accountScope.params],
    );
    const userContrib = this.investmentTransferCents(start, end, ownerId);
    const netWorthDelta = nwEnd.net_worth_cents - nwStart.net_worth_cents;
    const marketDelta = nwEnd.investment_cents - nwStart.investment_cents - userContrib;
    const realEstateDelta = nwEnd.real_estate_cents - nwStart.real_estate_cents - cents(capex?.capex);
    const vehicleDelta = nwEnd.vehicle_cents - nwStart.vehicle_cents;
    const dollarsIn = flow.total_inflow_cents;
    const dollarsSpent = flow.bucket_totals_cents.CONSUMED;
    const accounted = dollarsIn - dollarsSpent + marketDelta + realEstateDelta + vehicleDelta;
    const unexplained = netWorthDelta - accounted;
    const accountedPct = netWorthDelta === 0
      ? 1
      : Math.max(0, 1 - Math.abs(unexplained) / Math.abs(netWorthDelta));
    let reClause = "";
    const reParams = [];
    if (ownerId) {
      reClause = "AND LOWER(owner_id) = LOWER(?)";
      reParams.push(ownerId);
    }
    const stale = Number(this.db.scalar(
      `
      SELECT COUNT(*) AS n FROM (
          SELECT name, MAX(date(as_of)) AS latest
            FROM real_estate
           WHERE name NOT LIKE '%[%'
             AND source != '[source]'
             ${reClause}
           GROUP BY name
          HAVING latest < date(?, '-90 days')
      )
      `,
      [...reParams, end],
    ) || 0);
    const interp = Number(this.db.scalar(
      `
      SELECT COUNT(*) AS n FROM (
          SELECT name, COUNT(*) AS valuations
            FROM real_estate
           WHERE name NOT LIKE '%[%'
             AND source != '[source]'
             ${reClause}
           GROUP BY name
          HAVING valuations < 2
      )
      `,
      reParams,
    ) || 0);
    return {
      start_date: start,
      end_date: end,
      net_worth_start_cents: nwStart.net_worth_cents,
      net_worth_end_cents: nwEnd.net_worth_cents,
      net_worth_delta_cents: netWorthDelta,
      identity_terms: {
        dollars_in_cents: dollarsIn,
        dollars_spent_cents: dollarsSpent,
        market_value_delta_cents: marketDelta,
        real_estate_delta_cents: realEstateDelta,
        vehicle_delta_cents: vehicleDelta,
      },
      unexplained_cents: unexplained,
      accounted_for_pct: Math.round(accountedPct * 10000) / 10000,
      drift_source_count: stale + interp + (stale ? stale : 0),
    };
  }

  accountsSnapshot(referenceDate, ownerId) {
    const accountScope = this.accountScope(ownerId, "id");
    const accounts = this.db.all(
      `
      SELECT id, institution_id, name, last4, type, owner_id, closed_at, is_synthetic
        FROM accounts
       WHERE is_active = 1
         AND id IN (
           SELECT DISTINCT account_id FROM balance_snapshots
           UNION
           SELECT DISTINCT account_id FROM transactions
         )
         ${accountScope.sql}
      `,
      accountScope.params,
    );
    const latestBalances = new Map(this.db.all(
      `
      SELECT bs.account_id, bs.balance, bs.as_of
        FROM balance_snapshots bs
       WHERE bs.id = (
         SELECT id FROM balance_snapshots b2
          WHERE b2.account_id = bs.account_id
          ORDER BY b2.as_of DESC LIMIT 1
       )
      `,
    ).map((row) => [row.account_id, row]));
    const loanDetails = new Map(this.db.all(
      `
      WITH latest AS (
          SELECT ld.account_id, ld.field_name, ld.field_value
            FROM loan_details ld
           WHERE ld.as_of = (
             SELECT MAX(ld2.as_of)
               FROM loan_details ld2
              WHERE ld2.account_id = ld.account_id
                AND ld2.field_name = ld.field_name
           )
      )
      SELECT account_id,
             MAX(CASE WHEN field_name='purchase_price' THEN CAST(field_value AS REAL) END) AS purchase_price,
             MAX(CASE WHEN field_name='interest_rate' THEN CAST(field_value AS REAL) END) AS interest_rate,
             MAX(CASE WHEN field_name='minimum_payment' THEN CAST(field_value AS REAL) END) AS minimum_payment,
             MAX(CASE WHEN field_name='term_months' THEN CAST(field_value AS INTEGER) END) AS term_months,
             MAX(CASE WHEN field_name='origination_date' THEN field_value END) AS origination_date,
             MAX(CASE WHEN field_name='credit_limit' THEN CAST(field_value AS REAL) END) AS credit_limit,
             MAX(CASE WHEN field_name='rewards_points' THEN field_value END) AS rewards_points
        FROM latest
       GROUP BY account_id
      `,
    ).map((row) => [row.account_id, row]));
    const enriched = accounts.map((account) => {
      const acct = { ...account };
      const balance = latestBalances.get(acct.id);
      acct.balance = balance ? balance.balance : null;
      acct.balance_as_of = balance ? balance.as_of : null;
      if (["investment", "retirement"].includes(acct.type)) {
        const snap = this.db.one(
          "SELECT total_account_value, cash_balance FROM portfolio_snapshots WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1",
          [acct.id],
        );
        const total = Number(snap?.total_account_value || 0);
        const cash = Number(snap?.cash_balance || 0);
        acct.holdings_value = round2(total - cash);
        acct.investment_cash = round2(cash);
        if ((acct.balance || 0) === 0 || total > (acct.balance || 0)) acct.balance = round2(total);
      }
      if (loanDetails.has(acct.id)) Object.assign(acct, loanDetails.get(acct.id));
      if (acct.closed_at) acct.status = "closed";
      else if (["loan", "mortgage", "bnpl"].includes(acct.type)) {
        acct.status = acct.balance != null && acct.balance >= 0 ? "paid_off" : "active";
      } else {
        acct.status = "active";
      }
      return acct;
    });
    let reSql = `
      WITH latest AS (
          SELECT id, name, estimated_value, linked_loan_id, source, as_of, owner_id,
                 ROW_NUMBER() OVER (PARTITION BY name ORDER BY as_of DESC, id DESC) AS rn
            FROM real_estate
           WHERE source != '[source]'
    `;
    const reParams = [];
    if (ownerId) {
      reSql += " AND LOWER(owner_id) = LOWER(?)";
      reParams.push(ownerId);
    }
    reSql += `
      )
      SELECT id, name, estimated_value, as_of, source, linked_loan_id, owner_id
        FROM latest
       WHERE rn = 1
       ORDER BY name
    `;
    const realEstate = this.db.all(reSql, reParams);
    let vehSql = "SELECT id, make, model, year, purchase_date, purchase_price FROM vehicle_assets";
    const vehParams = [];
    if (ownerId) {
      vehSql += " WHERE LOWER(owner_id) = LOWER(?)";
      vehParams.push(ownerId);
    }
    const vehicles = this.db.all(vehSql, vehParams).map((vehicle) => {
      const latest = this.db.one(
        "SELECT valuation_date, estimated_value, source, source_url FROM vehicle_valuations WHERE vehicle_id = ? ORDER BY valuation_date DESC LIMIT 1",
        [vehicle.id],
      );
      return {
        ...vehicle,
        latest_value: latest ? latest.estimated_value : null,
        latest_value_as_of: latest ? latest.valuation_date : null,
        latest_value_source: latest ? latest.source : null,
      };
    });
    const display = [...enriched];
    for (const row of realEstate) {
      display.push({
        id: `manual:re:${row.id}`,
        institution_id: "manual",
        name: row.name,
        type: "real_estate",
        balance: row.estimated_value || 0,
        balance_as_of: row.as_of,
        status: "active",
      });
    }
    for (const row of vehicles) {
      display.push({
        id: `manual:veh:${row.id}`,
        institution_id: "manual",
        name: `${row.year} ${row.make} ${row.model}`,
        type: "vehicle",
        balance: row.latest_value || 0,
        balance_as_of: row.latest_value_as_of,
        status: "active",
      });
    }
    const filter = (types) => display.filter((row) => types.includes(row.type));
    const sum = (rows) => round2(rows.reduce((total, row) => total + Number(row.balance || 0), 0));
    const groups = {
      "Credit cards": filter(["credit_card", "credit"]),
      Loans: filter(["loan", "bnpl", "mortgage"]),
      Cash: filter(["checking", "savings"]),
      "Real Estate": filter(["real_estate", "property"]),
      Vehicles: filter(["vehicle"]),
      Investments: filter(["investment", "retirement"]),
    };
    const groupTotals = Object.fromEntries(
      Object.entries(groups).filter(([, rows]) => rows.length).map(([key, rows]) => [key, sum(rows)]),
    );
    const assetBucketsRaw = {
      "Real Estate": groups["Real Estate"].filter((row) => (row.balance || 0) >= 0),
      Vehicles: groups.Vehicles.filter((row) => (row.balance || 0) >= 0),
      Investments: groups.Investments.filter((row) => (row.balance || 0) >= 0),
      Cash: groups.Cash.filter((row) => (row.balance || 0) >= 0),
    };
    const assetBuckets = Object.fromEntries(
      Object.entries(assetBucketsRaw)
        .map(([key, rows]) => [key, sum(rows)])
        .filter(([, value]) => value > 0),
    );
    const liabilities = {
      "Credit Cards": round2(Math.abs(sum(groups["Credit cards"]))),
      BNPL: round2(Math.abs(sum(display.filter((row) => row.type === "bnpl")))),
      Loans: round2(Math.abs(sum(display.filter((row) => ["loan", "mortgage"].includes(row.type))))),
    };
    const liabilityBuckets = Object.fromEntries(Object.entries(liabilities).filter(([, value]) => value > 0));
    const assetsTotal = round2(Object.values(assetBuckets).reduce((total, value) => total + value, 0));
    const liabilitiesTotal = round2(Object.values(liabilityBuckets).reduce((total, value) => total + value, 0));
    const bucketTotals = { ...assetBuckets, ...liabilityBuckets };
    const bucketPercents = {
      ...Object.fromEntries(
        Object.entries(assetBuckets).map(([key, value]) => [
          key,
          assetsTotal ? round1((value / assetsTotal) * 100) : 0,
        ]),
      ),
      ...Object.fromEntries(
        Object.entries(liabilityBuckets).map(([key, value]) => [
          key,
          liabilitiesTotal ? round1((value / liabilitiesTotal) * 100) : 0,
        ]),
      ),
    };
    const history = this.netWorthHistory(referenceDate, 6, ownerId);
    const displayTotal = history.length ? history.at(-1).net_worth : 0;
    const trendPercent = history.length >= 2 && history[0].net_worth
      ? round1(((history.at(-1).net_worth - history[0].net_worth) / Math.abs(history[0].net_worth)) * 100)
      : 0;
    const visibleRows = [
      ...groups["Credit cards"],
      ...groups.Loans,
      ...groups.Cash,
      ...groups["Real Estate"],
      ...groups.Vehicles,
      ...groups.Investments,
    ].filter((row) => row.status === "active");
    return {
      display_total: displayTotal,
      trend_percent: trendPercent,
      data_through: null,
      group_totals: groupTotals,
      row_balances: visibleRows.map((row) => round2(row.balance || 0)),
      row_balance_as_of: visibleRows.map((row) => row.balance_as_of ?? null),
      apr: visibleRows.filter((row) => row.interest_rate).map((row) => row.interest_rate),
      rewards_points: visibleRows
        .filter((row) => row.rewards_points && String(row.rewards_points).replace(/,/g, "").match(/^\d+$/))
        .map((row) => Number.parseInt(String(row.rewards_points).replace(/,/g, ""), 10)),
      installment_paid_percent: visibleRows
        .filter((row) => row.purchase_price && row.purchase_price > 0)
        .map((row) => Math.max(0, Math.min(100, Math.round(((row.purchase_price + (row.balance || 0)) / row.purchase_price) * 100)))),
      credit_utilization_percent: visibleRows
        .filter((row) => row.credit_limit && row.credit_limit > 0 && !row.purchase_price)
        .map((row) => Math.max(0, Math.min(100, Math.round((Math.abs(row.balance || 0) / row.credit_limit) * 100)))),
      summary: {
        assets_total: assetsTotal,
        liabilities_total: liabilitiesTotal,
        bucket_totals: bucketTotals,
        bucket_percents: bucketPercents,
      },
    };
  }

  investmentAccountRows(ownerId) {
    const scope = this.accountScope(ownerId, "a.id");
    return this.db.all(
      `
      SELECT a.id, a.name, a.institution_id, a.type, a.is_synthetic,
             a.tax_status
        FROM accounts a
       WHERE a.type IN ('investment', 'retirement')
         AND a.is_active = 1
         ${scope.sql}
       ORDER BY a.name
      `,
      scope.params,
    );
  }

  investmentHoldingRows(ownerId) {
    const rows = [];
    for (const account of this.investmentAccountRows(ownerId)) {
      const latest = this.db.scalar(
        "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
        [account.id],
      );
      const holdings = [];
      let totalEquity = 0;
      let cashBalance = 0;

      if (latest) {
        const holdingRows = this.db.all(
          `
          SELECT ih.ticker, ih.shares, ih.close_price, ih.market_value,
                 ih.cost_basis, tm.sector, tm.asset_class
            FROM investment_holdings ih
            LEFT JOIN ticker_metadata tm ON tm.ticker = ih.ticker
           WHERE ih.account_id = ? AND ih.date = ?
           ORDER BY ih.market_value DESC
          `,
          [account.id, latest],
        );
        for (const holding of holdingRows) {
          const marketValue = Number(holding.market_value || 0);
          if (INVESTMENT_CASH_EQUIVALENTS.has(holding.ticker)) {
            cashBalance += marketValue;
            continue;
          }
          totalEquity += marketValue;
          holdings.push({
            ticker: holding.ticker,
            account: account.name,
            account_id: account.id,
            tax_status: account.tax_status,
            price: round2(holding.close_price),
            quantity: Math.round(Number(holding.shares || 0) * 100000) / 100000,
            value: round2(marketValue),
            sector: holding.sector,
            asset_class: holding.asset_class,
          });
        }
      }

      if (cashBalance === 0) {
        const snap = this.db.one(
          "SELECT cash_balance FROM portfolio_snapshots WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1",
          [account.id],
        );
        cashBalance = Number(snap?.cash_balance || 0);
      }

      const totalValue = totalEquity + cashBalance;
      if (totalValue > 0) {
        for (const holding of holdings) {
          holding.portfolio_pct = round1((Number(holding.value || 0) / totalValue) * 100);
        }
      }
      if (cashBalance > 0) {
        holdings.push({
          ticker: "Cash",
          account: account.name,
          account_id: account.id,
          tax_status: account.tax_status,
          price: 1,
          quantity: Math.round(cashBalance * 100000) / 100000,
          value: round2(cashBalance),
          portfolio_pct: totalValue ? round1((cashBalance / totalValue) * 100) : 0,
          sector: "Cash",
          asset_class: "Cash / Equivalents",
        });
      }
      rows.push(...holdings);
    }
    return rows.sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
  }

  investmentHoldings(ownerId) {
    const rows = this.investmentHoldingRows(ownerId);
    return {
      prices: rows.map((row) => round2(row.price)),
      quantities: rows.map((row) => Math.round(Number(row.quantity || 0) * 100000) / 100000),
      values: rows.map((row) => round2(row.value)),
      portfolio_pcts: rows.map((row) => round1(row.portfolio_pct)),
      empty: rows.length === 0,
    };
  }

  investmentPerformanceAll(ownerId) {
    const scope = this.accountScope(ownerId, "a.id");
    const ihAccountSql = `
      ih.account_id IN (
        SELECT a.id FROM accounts a
         WHERE a.type IN ('investment', 'retirement')
           AND a.is_active = 1
           ${scope.sql}
      )
    `;
    const psAccountSql = `
      ps.account_id IN (
        SELECT a.id FROM accounts a
         WHERE a.type IN ('investment', 'retirement')
           AND a.is_active = 1
           ${scope.sql}
      )
    `;
    const holdingRows = this.db.all(
      `
      SELECT ih.date AS date, SUM(ih.market_value) AS holdings_value
        FROM investment_holdings ih
       WHERE ${ihAccountSql}
         AND ih.date >= ?
       GROUP BY ih.date
       ORDER BY ih.date
      `,
      [...scope.params, "2000-01-01"],
    );
    if (!holdingRows.length) return [];

    const cashRows = this.db.all(
      `
      SELECT substr(ps.timestamp, 1, 10) AS snap_date,
             SUM(ps.cash_balance) AS cash_balance
        FROM portfolio_snapshots ps
       WHERE ${psAccountSql}
         AND ps.timestamp >= ?
       GROUP BY snap_date
       ORDER BY snap_date
      `,
      [...scope.params, "2000-01-01"],
    );
    const cashByDate = new Map(
      cashRows.map((row) => [row.snap_date, Number(row.cash_balance || 0)]),
    );
    const cashDates = Array.from(cashByDate.keys()).sort();
    const daily = holdingRows.map((row) => {
      let cash = 0;
      for (const cashDate of cashDates) {
        if (cashDate <= row.date) cash = cashByDate.get(cashDate) || 0;
        else break;
      }
      return {
        date: row.date,
        total_value: round2(Number(row.holdings_value || 0) + cash),
      };
    });

    const monthlyByKey = new Map();
    for (const row of daily) {
      monthlyByKey.set(row.date.slice(0, 7), row);
    }
    const contribRows = this.db.all(
      `
      SELECT strftime('%Y-%m', posting_date) AS month,
             SUM(amount) AS total_contrib
        FROM transactions
       WHERE transfer_tag LIKE 'invest:%'
         AND direction = 'Debit'
       GROUP BY month
      `,
    );
    const contribs = new Map(
      contribRows.map((row) => [row.month, Number(row.total_contrib || 0)]),
    );
    let prevValue = 0;
    return Array.from(monthlyByKey.keys()).sort().map((month) => {
      const row = monthlyByKey.get(month);
      const totalValue = Number(row.total_value || 0);
      const contributions = contribs.get(month) || 0;
      const out = {
        date: row.date,
        month,
        total_value: round2(totalValue),
        contributions: round2(contributions),
        gain_loss: round2(totalValue - prevValue - contributions),
      };
      prevValue = totalValue;
      return out;
    });
  }

  investmentAllocation(ownerId) {
    const scope = this.accountScope(ownerId, "a.id");
    const rows = this.db.all(
      `
      SELECT ih.ticker, ih.market_value, tm.sector, tm.asset_class
        FROM investment_holdings ih
        JOIN accounts a ON a.id = ih.account_id
        LEFT JOIN ticker_metadata tm ON tm.ticker = ih.ticker
       WHERE a.type IN ('investment', 'retirement')
         AND a.is_active = 1
         ${scope.sql}
         AND ih.date = (
             SELECT MAX(ih2.date)
               FROM investment_holdings ih2
              WHERE ih2.account_id = ih.account_id
         )
       ORDER BY ih.market_value DESC
      `,
      scope.params,
    );
    const cashRows = this.db.all(
      `
      SELECT ps.cash_balance
        FROM portfolio_snapshots ps
        JOIN accounts a ON a.id = ps.account_id
       WHERE a.type IN ('investment', 'retirement')
         AND a.is_active = 1
         ${scope.sql}
         AND ps.timestamp = (
             SELECT MAX(ps2.timestamp)
               FROM portfolio_snapshots ps2
              WHERE ps2.account_id = ps.account_id
         )
      `,
      scope.params,
    );
    const totalCash = cashRows.reduce((sum, row) => sum + Number(row.cash_balance || 0), 0);
    const totalValue = rows
      .filter((row) => !INVESTMENT_CASH_EQUIVALENTS.has(row.ticker))
      .reduce((sum, row) => sum + Number(row.market_value || 0), 0) + totalCash;
    if (totalValue <= 0) {
      return {
        total_value: 0,
        asset_class_amounts: [],
        asset_class_pcts: [],
        sector_amounts: [],
        sector_pcts: [],
        geography_amounts: [],
        geography_pcts: [],
        market_cap_amounts: [],
        market_cap_pcts: [],
        empty: true,
      };
    }

    const addToMap = (map, key, value) => {
      map.set(key, (map.get(key) || 0) + value);
    };
    const bucketPayload = (map) => Array.from(map.entries())
      .map(([name, amount]) => ({
        name,
        amount: round2(amount),
        pct: round1((amount / totalValue) * 100),
      }))
      .sort((a, b) => b.pct - a.pct);

    const sectorMap = new Map();
    const classMap = new Map();
    for (const row of rows) {
      if (INVESTMENT_CASH_EQUIVALENTS.has(row.ticker)) continue;
      const value = Number(row.market_value || 0);
      addToMap(sectorMap, row.sector || "Unknown", value);
      addToMap(classMap, row.asset_class || "Unknown", value);
    }
    if (totalCash > 0) addToMap(classMap, "Cash / Equivalents", totalCash);

    const capByTicker = new Map();
    for (const row of this.db.all(
      "SELECT ticker, cap_class FROM fund_composition WHERE cap_class IS NOT NULL",
    )) {
      if (!capByTicker.has(row.ticker)) capByTicker.set(row.ticker, row.cap_class);
    }
    const capMap = new Map();
    for (const row of rows) {
      if (INVESTMENT_CASH_EQUIVALENTS.has(row.ticker)) continue;
      addToMap(capMap, capByTicker.get(row.ticker) || "Large Cap", Number(row.market_value || 0));
    }

    const geoByTicker = new Map();
    for (const row of this.db.all(
      "SELECT ticker, geography, weight FROM fund_composition WHERE geography IS NOT NULL",
    )) {
      if (!geoByTicker.has(row.ticker)) geoByTicker.set(row.ticker, []);
      geoByTicker.get(row.ticker).push([row.geography, Number(row.weight || 0)]);
    }
    const geoLabels = new Map([
      ["US", "United States"],
      ["Developed Intl", "Developed Int'l"],
      ["Emerging Markets", "Emerging Markets"],
    ]);
    const geoMap = new Map();
    for (const row of rows) {
      if (INVESTMENT_CASH_EQUIVALENTS.has(row.ticker)) continue;
      const entries = geoByTicker.get(row.ticker);
      const value = Number(row.market_value || 0);
      if (entries && entries.length) {
        for (const [rawGeo, weight] of entries) {
          addToMap(geoMap, geoLabels.get(rawGeo) || rawGeo, value * weight);
        }
      } else {
        addToMap(geoMap, "United States", value);
      }
    }
    if (totalCash > 0) addToMap(geoMap, "United States", totalCash);

    const assetClasses = bucketPayload(classMap);
    const sectors = bucketPayload(sectorMap);
    const geographies = bucketPayload(geoMap);
    const marketCaps = bucketPayload(capMap);
    return {
      total_value: round2(totalValue),
      asset_class_amounts: assetClasses.map((row) => row.amount),
      asset_class_pcts: assetClasses.map((row) => row.pct),
      sector_amounts: sectors.map((row) => row.amount),
      sector_pcts: sectors.map((row) => row.pct),
      geography_amounts: geographies.map((row) => row.amount),
      geography_pcts: geographies.map((row) => row.pct),
      market_cap_amounts: marketCaps.map((row) => row.amount),
      market_cap_pcts: marketCaps.map((row) => row.pct),
      empty: false,
    };
  }

  investmentTaxSummary(ownerId) {
    const scope = this.accountScope(ownerId, "a.id");
    const accounts = this.db.all(
      `
      SELECT a.id, a.tax_status
        FROM accounts a
       WHERE a.type IN ('investment', 'retirement')
         AND a.is_active = 1
         AND a.tax_status IS NOT NULL
         ${scope.sql}
      `,
      scope.params,
    );
    const buckets = new Map([
      ["Tax-Deferred", 0],
      ["Tax-Free", 0],
      ["Taxable", 0],
    ]);
    const addBucket = (name, amount) => {
      buckets.set(name, (buckets.get(name) || 0) + amount);
    };
    for (const account of accounts) {
      const snap = this.db.one(
        "SELECT total_account_value FROM portfolio_snapshots WHERE account_id = ? ORDER BY timestamp DESC LIMIT 1",
        [account.id],
      );
      let accountValue = Number(snap?.total_account_value || 0);
      if (!accountValue) {
        const latest = this.db.scalar(
          "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
          [account.id],
        );
        if (latest) {
          const row = this.db.one(
            "SELECT SUM(market_value) AS mv FROM investment_holdings WHERE account_id = ? AND date = ?",
            [account.id, latest],
          );
          accountValue = Number(row?.mv || 0);
        }
      }
      if (account.tax_status === "mixed") {
        const taxRows = this.db.all(
          `
          SELECT bucket_type, balance
            FROM tax_buckets
           WHERE account_id = ?
             AND as_of = (
                 SELECT MAX(as_of) FROM tax_buckets WHERE account_id = ?
             )
          `,
          [account.id, account.id],
        );
        if (taxRows.length) {
          for (const row of taxRows) {
            addBucket(row.bucket_type === "traditional" ? "Tax-Deferred" : "Tax-Free", Number(row.balance || 0) / 100);
          }
        } else {
          addBucket("Tax-Deferred", accountValue);
        }
      } else if (account.tax_status === "traditional") {
        addBucket("Tax-Deferred", accountValue);
      } else if (["roth", "hsa"].includes(account.tax_status)) {
        addBucket("Tax-Free", accountValue);
      } else if (account.tax_status === "taxable") {
        addBucket("Taxable", accountValue);
      }
    }
    const total = Array.from(buckets.values()).reduce((sum, value) => sum + value, 0);
    const rows = Array.from(buckets.entries())
      .filter(([, amount]) => amount > 0)
      .map(([name, amount]) => ({
        name,
        amount: round2(amount),
        pct: total > 0 ? round1((amount / total) * 100) : 0,
      }));
    return {
      total: round2(total),
      amounts: rows.map((row) => row.amount),
      pcts: rows.map((row) => row.pct),
    };
  }

  investmentsOverview(ownerId) {
    const performance = this.investmentPerformanceAll(ownerId);
    const holdings = this.investmentHoldings(ownerId);
    const allocation = this.investmentAllocation(ownerId);
    const taxSummary = this.investmentTaxSummary(ownerId);
    const fallbackTotal = holdings.values.reduce((sum, value) => sum + Number(value || 0), 0);
    const firstValue = performance.length > 1 ? Number(performance[0].total_value || 0) : 0;
    const lastValue = performance.length ? Number(performance.at(-1).total_value || 0) : fallbackTotal;
    const changeAbs = round2(lastValue - firstValue);
    return {
      total_value: round2(lastValue || fallbackTotal),
      change_abs: changeAbs,
      change_pct: firstValue > 0 ? round1((changeAbs / firstValue) * 100) : 0,
      asset_class_count: allocation.asset_class_amounts.length,
      asset_class_amounts: allocation.asset_class_amounts,
      asset_class_pcts: allocation.asset_class_pcts,
      tax_treatment_amounts: taxSummary.amounts,
      tax_treatment_pcts: taxSummary.pcts,
      performance_empty: performance.length === 0,
    };
  }

  netWorthMonth(year, month, ownerId) {
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const asOf = `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
    const accountScope = this.accountScope(ownerId, "id");
    const accounts = this.db.all(
      `SELECT id, type, is_active FROM accounts WHERE 1=1${accountScope.sql}`,
      accountScope.params,
    );
    if (!accounts.length) return null;
    let banking = 0;
    let liabilities = 0;
    for (const account of accounts) {
      const balance = this.db.one(
        `
        SELECT balance FROM balance_snapshots
         WHERE account_id = ? AND date(as_of) <= date(?)
         ORDER BY as_of DESC LIMIT 1
        `,
        [account.id, asOf],
      );
      if (!balance) continue;
      if (["checking", "savings"].includes(account.type)) {
        banking += Number(balance.balance || 0);
      } else if (
        ["credit_card", "loan", "bnpl", "mortgage"].includes(account.type)
        && Number(account.is_active || 0) === 1
      ) {
        liabilities += Number(balance.balance || 0);
      }
    }

    const portfolioScope = this.accountScope(ownerId, "id");
    const investmentAccounts = this.db.all(
      `
      SELECT id FROM accounts
       WHERE type IN ('investment', 'retirement')
         ${portfolioScope.sql}
      `,
      portfolioScope.params,
    );
    let portfolio = 0;
    for (const account of investmentAccounts) {
      const row = this.db.one(
        `
        SELECT total_account_value FROM portfolio_snapshots
         WHERE account_id = ? AND date(timestamp) <= date(?)
         ORDER BY timestamp DESC LIMIT 1
        `,
        [account.id, asOf],
      );
      if (row) portfolio += Number(row.total_account_value || 0);
    }

    let reSql = `
      SELECT estimated_value FROM (
          SELECT estimated_value,
                 ROW_NUMBER() OVER (PARTITION BY name ORDER BY as_of DESC, rowid DESC) AS rn
            FROM real_estate
           WHERE name NOT LIKE '%[%'
             AND date(as_of) <= date(?)
    `;
    const reParams = [asOf];
    if (ownerId) {
      reSql += " AND LOWER(owner_id) = LOWER(?)";
      reParams.push(ownerId);
    }
    reSql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL";
    const realEstate = this.db
      .all(reSql, reParams)
      .reduce((total, row) => total + Number(row.estimated_value || 0), 0);

    let vehSql = `
      SELECT estimated_value FROM (
          SELECT vv.estimated_value,
                 ROW_NUMBER() OVER (
                   PARTITION BY vv.vehicle_id
                   ORDER BY vv.valuation_date DESC, vv.id DESC
                 ) AS rn
            FROM vehicle_valuations vv
    `;
    const vehParams = [asOf];
    if (ownerId) {
      vehSql += `
            JOIN vehicle_assets va ON va.id = vv.vehicle_id
           WHERE date(vv.valuation_date) <= date(?)
             AND LOWER(va.owner_id) = LOWER(?)
      `;
      vehParams.push(ownerId);
    } else {
      vehSql += " WHERE date(vv.valuation_date) <= date(?)";
    }
    vehSql += ") ranked WHERE rn = 1 AND estimated_value IS NOT NULL";
    const vehicles = this.db
      .all(vehSql, vehParams)
      .reduce((total, row) => total + Number(row.estimated_value || 0), 0);

    const assets = round2(banking + portfolio + realEstate + vehicles);
    return {
      month: `${year}-${String(month).padStart(2, "0")}`,
      assets,
      liabilities: round2(liabilities),
      net_worth: round2(assets + liabilities),
    };
  }

  budgetCategories(month) {
    const summary = this.budgetSummary(month);
    return summary.categories || [];
  }

  monthlyReview(year, month, ownerId) {
    const monthStr = `${year}-${String(month).padStart(2, "0")}`;
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const monthStart = `${monthStr}-01`;
    const monthEnd = `${monthStr}-${String(lastDay).padStart(2, "0")}`;
    const incomeCats = this.vocabulary.income_categories;
    const exclusions = this.vocabulary.all_excl_from_spend;
    const accountScope = this.accountScope(ownerId, "account_id");

    const incRow = this.db.one(
      `
      SELECT COALESCE(SUM(signed_amount), 0) AS total
        FROM transactions
       WHERE status = 'posted' AND transfer_tag IS NULL
         AND signed_amount > 0
         AND category IN (${placeholders(incomeCats)})
         AND posting_date >= ? AND posting_date <= ?
         ${accountScope.sql}
      `,
      [...incomeCats, monthStart, monthEnd, ...accountScope.params],
    );
    const incomeTotal = round2(incRow?.total || 0);

    const spRow = this.db.one(
      `
      SELECT COALESCE(SUM(-signed_amount), 0) AS total
        FROM transactions
       WHERE status = 'posted' AND transfer_tag IS NULL
         AND signed_amount < 0
         AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})
         AND posting_date >= ? AND posting_date <= ?
         ${accountScope.sql}
      `,
      [...exclusions, monthStart, monthEnd, ...accountScope.params],
    );
    const spendingTotal = round2(spRow?.total || 0);
    const savingsRate = incomeTotal > 0
      ? round1(((incomeTotal - spendingTotal) / incomeTotal) * 100)
      : 0;
    const cashSurplus = round2(incomeTotal - spendingTotal);

    const nwCurr = this.netWorthMonth(year, month, ownerId);
    const priorYear = month === 1 ? year - 1 : year;
    const priorMonth = month === 1 ? 12 : month - 1;
    const nwPrior = this.netWorthMonth(priorYear, priorMonth, ownerId);
    let netWorthDelta = { amount: 0, pct: 0, direction: "flat" };
    if (nwCurr && nwPrior && Number(nwPrior.net_worth || 0) !== 0) {
      const change = round2(nwCurr.net_worth - nwPrior.net_worth);
      const pct = round1((change / Math.abs(nwPrior.net_worth)) * 100);
      const direction = change > 0 ? "up" : (change < 0 ? "down" : "flat");
      netWorthDelta = { amount: change, pct, direction };
    }

    const ucRow = this.db.one(
      `
      SELECT COUNT(*) AS cnt
        FROM transactions
       WHERE status = 'posted'
         AND posting_date >= ? AND posting_date <= ?
         AND COALESCE(category, 'Uncategorized') = 'Uncategorized'
         AND transfer_tag IS NULL
         ${accountScope.sql}
      `,
      [monthStart, monthEnd, ...accountScope.params],
    );
    const uncategorizedCount = Number(ucRow?.cnt || 0);

    // Mirror dal/payroll.get_gross_income_for_month: pick the most recent
    // single snapshot, do NOT sum across owners. Household view returns one
    // owner's snapshot rather than a household total.
    let payrollSql = `
      SELECT COALESCE(gross_pay, 0) AS gross_pay,
             COALESCE(federal_tax, 0) AS federal_tax,
             COALESCE(state_tax, 0) AS state_tax,
             COALESCE(sbp_premium, 0) + COALESCE(health_insurance, 0)
               + COALESCE(dental_vision, 0) + COALESCE(other_deductions, 0)
               AS deductions,
             COALESCE(net_pay, 0) AS net_pay
        FROM payroll_snapshots
       WHERE pay_period = ?
    `;
    const payrollParams = [monthStr];
    if (ownerId) {
      payrollSql += " AND LOWER(owner_id) = LOWER(?)";
      payrollParams.push(ownerId);
    }
    payrollSql += " ORDER BY id DESC LIMIT 1";
    const pRow = this.db.one(payrollSql, payrollParams);
    let preTax = null;
    if (pRow && Number(pRow.gross_pay || 0) > 0) {
      const gross = Number(pRow.gross_pay);
      const fed = Number(pRow.federal_tax);
      const state = Number(pRow.state_tax);
      const deductions = Number(pRow.deductions);
      const net = Number(pRow.net_pay);
      const taxWithheld = fed + state;
      const savingsRatePct = gross > 0
        ? round1(((gross - taxWithheld - spendingTotal) / gross) * 100)
        : 0;
      preTax = {
        gross_income: gross,
        federal_tax: fed,
        state_tax: state,
        deductions,
        net_pay: net,
        savings_rate_pct: savingsRatePct,
      };
    }

    const bvaCategories = this.budgetCategories(monthStr);
    const overBudget = bvaCategories
      .filter((cat) => cat.actual > cat.target && cat.target > 0)
      .map((cat) => ({
        category: cat.category,
        actual: cat.actual,
        target: cat.target,
        variance: round2(cat.actual - cat.target),
      }))
      .sort((a, b) => b.variance - a.variance);
    const improved = bvaCategories
      .filter((cat) => cat.actual <= cat.target && cat.target > 0)
      .map((cat) => ({
        category: cat.category,
        actual: cat.actual,
        target: cat.target,
        variance: round2(cat.actual - cat.target),
      }))
      .sort((a, b) => a.variance - b.variance);
    const budgetHighlights = [...overBudget.slice(0, 5), ...improved.slice(0, 3)];
    const budgetHighlightActuals = budgetHighlights.map((b) => round2(b.actual));

    const NOTABLE_THRESHOLD = 1000;
    const notableRows = this.db.all(
      `
      SELECT -signed_amount AS amount
        FROM transactions
       WHERE status = 'posted'
         AND posting_date >= ? AND posting_date <= ?
         AND transfer_tag IS NULL
         AND signed_amount < 0
         ${accountScope.sql}
         AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(incomeCats)})
         AND ABS(signed_amount) >= ${NOTABLE_THRESHOLD}
       ORDER BY ABS(signed_amount) DESC
       LIMIT 5
      `,
      [monthStart, monthEnd, ...accountScope.params, ...incomeCats],
    );
    const notableTransactionAmounts = notableRows.map((r) => round2(r.amount || 0));

    return {
      month: monthStr,
      income_total: incomeTotal,
      spending_total: spendingTotal,
      savings_rate: savingsRate,
      net_worth_delta: netWorthDelta,
      cash_surplus: cashSurplus,
      uncategorized_count: uncategorizedCount,
      pre_tax: preTax,
      budget_highlight_actuals: budgetHighlightActuals,
      notable_transaction_amounts: notableTransactionAmounts,
    };
  }

  expectedTaxDocs(ownerId) {
    const docs = [
      { parser_type: "dfas_1099r", scope: "primary" },
      { parser_type: "fidelity_1099", scope: "primary" },
      { parser_type: "acorns_1099", scope: "primary" },
      { parser_type: "affirm_1099int", scope: "primary" },
      { parser_type: "nfcu_1098", scope: "household" },
    ];
    if (ownerId == null) return docs;
    let primary = "quintin";
    try {
      const config = YAML.parse(readFileSync(OWNER_CONFIG_PATH, "utf8")) || {};
      if (config.primary_owner) primary = String(config.primary_owner).toLowerCase();
    } catch {
      // fall back to default
    }
    if (String(ownerId).toLowerCase() === primary) return docs;
    return docs.filter((doc) => doc.scope === "household");
  }

  taxDocReceivedCount(year, ownerId) {
    const docs = this.expectedTaxDocs(ownerId);
    let received = 0;
    for (const { parser_type: parserType, scope } of docs) {
      let ownerClause = "";
      const params = [];
      if (ownerId == null) {
        ownerClause = "";
      } else if (scope === "household") {
        ownerClause = "AND owner_id IS NULL";
      } else {
        ownerClause = "AND LOWER(owner_id) = ?";
        params.push(String(ownerId).toLowerCase());
      }
      const row = this.db.one(
        `
        SELECT 1 FROM document_drops
         WHERE parser_type = ?
           AND json_extract(summary_json, '$.tax_year') = ?
           AND committed_at IS NOT NULL
           ${ownerClause}
         LIMIT 1
        `,
        [parserType, String(year), ...params],
      );
      if (row) received += 1;
    }
    return received;
  }

  hysaAccountId() {
    try {
      const config = YAML.parse(readFileSync(ACCOUNTS_CONFIG_PATH, "utf8")) || {};
      const accounts = config.affirm;
      if (Array.isArray(accounts)) {
        for (const account of accounts) {
          if (!account || account.type !== "savings") continue;
          const id = String(account.id || "").trim();
          if (id) return id;
        }
      }
    } catch {
      // Match dal.accounts_config.get_account_id() miss behavior.
    }
    return "affirm_XXXX";
  }

  yearlyInterestCost(year, ownerId) {
    const currentYear = String(Math.trunc(Number(year))).padStart(4, "0");
    const liabilityScope = this.accountScope(ownerId, "id");
    const liabilityAccounts = this.db.all(
      `
      SELECT id, name, type
        FROM accounts
       WHERE is_active = 1
         AND type IN ('credit_card', 'loan', 'bnpl', 'mortgage')
         AND id IN (
             SELECT DISTINCT account_id FROM balance_snapshots
             UNION
             SELECT DISTINCT account_id FROM transactions
             UNION
             SELECT DISTINCT account_id FROM loan_details
         )
         ${liabilityScope.sql}
      `,
      liabilityScope.params,
    );

    const accountIds = liabilityAccounts.map((account) => account.id);
    const loanDetailsByAccount = new Map();
    const transactionTotalsByAccount = new Map();
    if (accountIds.length) {
      for (const row of this.db.all(
        `
        SELECT account_id, field_value FROM (
            SELECT account_id, field_value,
                   ROW_NUMBER() OVER (
                     PARTITION BY account_id ORDER BY as_of DESC
                   ) AS rn
              FROM loan_details
             WHERE account_id IN (${placeholders(accountIds)})
               AND (LOWER(field_name) LIKE '%interest%ytd%'
                    OR LOWER(field_name) IN ('ytd_interest', 'interest paid ytd', 'ytd interest paid'))
               AND strftime('%Y', as_of) = ?
        ) ranked
         WHERE rn = 1
           AND field_value IS NOT NULL
        `,
        [...accountIds, currentYear],
      )) {
        loanDetailsByAccount.set(row.account_id, row.field_value);
      }

      for (const row of this.db.all(
        `
        SELECT account_id, SUM(ABS(signed_amount)) AS total
          FROM transactions
         WHERE account_id IN (${placeholders(accountIds)})
           AND status = 'posted'
           AND (LOWER(category) LIKE '%interest%' OR LOWER(category) LIKE '%finance charge%')
           AND strftime('%Y', posting_date) = ?
         GROUP BY account_id
        `,
        [...accountIds, currentYear],
      )) {
        if (row.total != null) {
          transactionTotalsByAccount.set(row.account_id, Number(row.total));
        }
      }
    }

    let interestPaid = 0;
    for (const account of liabilityAccounts) {
      let ytdValue = 0;
      let source = null;
      const loanDetailValue = loanDetailsByAccount.get(account.id);
      if (loanDetailValue) {
        const cleaned = String(loanDetailValue).replace(/[$,%]/g, "").trim();
        const parsed = Number.parseFloat(cleaned);
        if (!Number.isNaN(parsed)) {
          ytdValue = parsed;
          source = "loan_details";
        }
      }
      if (source == null) {
        ytdValue = transactionTotalsByAccount.get(account.id) || 0;
      }
      interestPaid += round2(ytdValue);
    }

    const hysaId = this.hysaAccountId();
    const earnedScope = this.accountScope(ownerId, "account_id");
    const earnedRow = ownerId == null
      ? this.db.one(
        `
        SELECT COALESCE(SUM(signed_amount), 0) AS total
          FROM transactions
         WHERE (account_id = ? OR LOWER(category) LIKE '%interest%' OR LOWER(description) = 'interest')
           AND signed_amount > 0
           AND status = 'posted'
           AND strftime('%Y', posting_date) = ?
        `,
        [hysaId, currentYear],
      )
      : this.db.one(
        `
        SELECT COALESCE(SUM(signed_amount), 0) AS total
          FROM transactions
         WHERE signed_amount > 0
           AND status = 'posted'
           AND strftime('%Y', posting_date) = ?
           AND (account_id = ? OR LOWER(category) LIKE '%interest%' OR LOWER(description) = 'interest')
           ${earnedScope.sql}
        `,
        [currentYear, hysaId, ...earnedScope.params],
      );

    interestPaid = round2(interestPaid);
    const interestEarned = round2(earnedRow?.total || 0);
    return {
      interest_paid: interestPaid,
      interest_earned: interestEarned,
      interest_net_cost: round2(interestPaid - interestEarned),
    };
  }

  yearlyWrapup(year, ownerId) {
    const yearStart = `${year}-01-01`;
    const yearEnd = `${year}-12-31`;
    const accountScope = this.accountScope(ownerId, "account_id");
    const incomeCats = [...this.vocabulary.income_categories].sort();
    const exclusions = this.vocabulary.all_excl_from_spend;

    const incomeByStream = [];
    for (const stream of incomeCats) {
      const row = this.db.one(
        `
        SELECT COALESCE(SUM(signed_amount), 0) AS total
          FROM transactions
         WHERE status = 'posted' AND transfer_tag IS NULL
           AND signed_amount > 0
           AND category = ?
           AND posting_date >= ? AND posting_date <= ?
           ${accountScope.sql}
        `,
        [stream, yearStart, yearEnd, ...accountScope.params],
      );
      incomeByStream.push({ stream, total: round2(row?.total || 0) });
    }
    const totalIncome = round2(incomeByStream.reduce((sum, s) => sum + s.total, 0));

    const spendRows = this.db.all(
      `
      SELECT COALESCE(category, 'Uncategorized') AS cat,
             SUM(-signed_amount) AS total
        FROM transactions
       WHERE status = 'posted' AND transfer_tag IS NULL
         AND signed_amount < 0
         AND posting_date >= ? AND posting_date <= ?
         AND COALESCE(category, 'Uncategorized') NOT IN (${placeholders(exclusions)})
         ${accountScope.sql}
       GROUP BY cat
       ORDER BY total DESC
      `,
      [yearStart, yearEnd, ...exclusions, ...accountScope.params],
    );
    const spendingByCategory = spendRows.map((r) => ({
      category: r.cat,
      total: round2(r.total || 0),
    }));
    const totalSpending = round2(spendingByCategory.reduce((sum, c) => sum + c.total, 0));
    const savingsRate = totalIncome > 0
      ? round1(((totalIncome - totalSpending) / totalIncome) * 100)
      : 0;

    let payrollSql = `
      SELECT pay_period,
             COALESCE(gross_pay, 0) AS gross_pay,
             COALESCE(federal_tax, 0) AS federal_tax,
             COALESCE(state_tax, 0) AS state_tax
        FROM payroll_snapshots
       WHERE substr(pay_period, 1, 4) = ?
    `;
    const payrollParams = [String(year)];
    if (ownerId) {
      payrollSql += " AND LOWER(owner_id) = LOWER(?)";
      payrollParams.push(ownerId);
    }
    const pRows = this.db.all(payrollSql, payrollParams);
    const monthsCovered = new Set(pRows.map((r) => r.pay_period)).size;
    let effectiveTax = null;
    if (pRows.length && monthsCovered > 0) {
      const gross = pRows.reduce((sum, r) => sum + Number(r.gross_pay || 0), 0);
      const fed = pRows.reduce((sum, r) => sum + Number(r.federal_tax || 0), 0);
      const state = pRows.reduce((sum, r) => sum + Number(r.state_tax || 0), 0);
      const effRate = gross > 0 ? round1(((fed + state) / gross) * 100) : 0;
      // Match dal/payroll.get_effective_tax_rate — no `net_pay` field.
      effectiveTax = {
        gross_income: round2(gross),
        federal_tax: round2(fed),
        state_tax: round2(state),
        effective_rate_pct: effRate,
        months_covered: monthsCovered,
        data_quality: monthsCovered === 12 ? "complete" : "partial",
      };
    }

    const expectedDocs = this.expectedTaxDocs(ownerId);
    const received = this.taxDocReceivedCount(year, ownerId);
    const expectedCount = expectedDocs.length;
    let status = "preliminary";
    if (expectedCount > 0 && received >= expectedCount) status = "final";
    else if (received > 0) status = "revised";

    const interest = this.yearlyInterestCost(year, ownerId);

    return {
      year,
      status,
      total_income: totalIncome,
      total_spending: totalSpending,
      savings_rate: savingsRate,
      tax_doc_received: received,
      tax_doc_expected: expectedCount,
      effective_tax: effectiveTax,
      interest_paid: interest.interest_paid,
      interest_earned: interest.interest_earned,
      interest_net_cost: interest.interest_net_cost,
      income_by_stream_amounts: incomeByStream
        .filter((s) => s.total > 0)
        .map((s) => s.total),
      spending_by_category_amounts: spendingByCategory.slice(0, 12).map((c) => c.total),
    };
  }

  checks() {
    const referenceDate = this.manifest.reference_date;
    const { start, end } = monthBounds(referenceDate);
    const reportsStart = start;
    const reportsEnd = referenceDate;
    const checks = [];

    for (const viewState of this.registryViewStates()) {
      const ownerId = viewState.owner_id ?? null;
      const summary = this.reportSummary(start, end, ownerId);
      const cashout = this.cashoutPeriod(start, end, ownerId);
      const dti = this.dtiSeries(referenceDate, 12, ownerId);

      checks.push({
        id: this.scopedId("dashboard.net_worth.latest", viewState),
        view_state: viewState,
        expected: this.latestNetWorth(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.monthly_net_flow", viewState),
        view_state: viewState,
        expected: summary,
      });
      checks.push({
        id: this.scopedId("dashboard.emergency_runway", viewState),
        view_state: viewState,
        expected: this.emergencyFund(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.credit_scores.latest", viewState),
        view_state: viewState,
        expected: this.latestCreditScores(ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.freshness.state_labels", viewState),
        view_state: viewState,
        expected: this.freshness(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.net_worth.details", viewState),
        view_state: viewState,
        expected: this.dashboardNetWorthDetails(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.net_worth.velocity", viewState),
        view_state: viewState,
        expected: this.netWorthVelocity(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("cash_flow.dti.latest", viewState),
        view_state: viewState,
        expected: dti.length ? dti.at(-1) : null,
      });
      checks.push({
        id: this.scopedId("dashboard.spending.hero", viewState),
        view_state: viewState,
        expected: this.dashboardSpending(referenceDate, summary.total_spending, ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.budget.summary", viewState),
        view_state: viewState,
        expected: this.budgetSummary(referenceDate.slice(0, 7)),
      });
      const budgetsPagePayload = this.budgetsPage(referenceDate);
      const { categories: _budgetsPageCategories, ...budgetsPageSummary } = budgetsPagePayload;
      checks.push({
        id: this.scopedId("budgets.page.summary", viewState),
        view_state: viewState,
        expected: budgetsPageSummary,
      });
      checks.push({
        id: this.scopedId("budgets.page.categories", viewState),
        view_state: viewState,
        expected: budgetsPagePayload.categories,
      });
      checks.push({
        id: this.scopedId("dashboard.recurring.summary", viewState),
        view_state: viewState,
        expected: this.recurringDashboard(ownerId),
      });
      checks.push({
        id: this.scopedId("dashboard.recent_transactions", viewState),
        view_state: viewState,
        expected: this.transactionsPage(ownerId, { limit: 8, excludeTransfers: true }).recent_amounts.slice(0, 8),
      });
      checks.push({
        id: this.scopedId("cash_flow.current_month", viewState),
        view_state: viewState,
        expected: cashout,
      });
      checks.push({
        id: this.scopedId("cash_flow.rolling.latest_month", viewState),
        view_state: viewState,
        expected: {
          income: cashout.income,
          spending: cashout.spending,
          net: cashout.net,
          savings_rate: cashout.savings_rate,
          debt_service: cashout.debt_service,
          debt_accumulated: cashout.debt_accumulated,
          debt_paid_down: cashout.debt_paid_down,
          net_debt_change: cashout.net_debt_change,
        },
      });
      checks.push({
        id: this.scopedId("cash_flow.chart.monthly_points", viewState),
        view_state: viewState,
        expected: this.cashoutRolling(referenceDate, ownerId, 18),
      });
      checks.push({
        id: this.scopedId("transactions.table", viewState),
        view_state: viewState,
        expected: this.transactionsPage(ownerId, { limit: 1000 }),
      });
      checks.push({
        id: this.scopedId("reports.flow", viewState),
        view_state: viewState,
        expected: this.reportsFlow(reportsStart, reportsEnd, ownerId),
      });
      checks.push({
        id: this.scopedId("reports.accountability", viewState),
        view_state: viewState,
        expected: this.accountability(reportsStart, reportsEnd, ownerId),
      });
      checks.push({
        id: this.scopedId("reports.transactions.visible", viewState),
        view_state: viewState,
        expected: this.transactionsPage(ownerId, {
          limit: 1000,
          startDate: reportsStart,
          endDate: reportsEnd,
        }).recent_amounts,
      });
      checks.push({
        id: this.scopedId("accounts.snapshot", viewState),
        view_state: viewState,
        expected: this.accountsSnapshot(referenceDate, ownerId),
      });
      checks.push({
        id: this.scopedId("investments.holdings", viewState),
        view_state: viewState,
        expected: this.investmentHoldings(ownerId),
      });
      checks.push({
        id: this.scopedId("investments.allocation", viewState),
        view_state: viewState,
        expected: this.investmentAllocation(ownerId),
      });
      checks.push({
        id: this.scopedId("investments.overview", viewState),
        view_state: viewState,
        expected: this.investmentsOverview(ownerId),
      });

      const refYear = Number(referenceDate.slice(0, 4));
      const refMonth = Number(referenceDate.slice(5, 7));
      const reviewYear = refMonth === 1 ? refYear - 1 : refYear;
      const reviewMonth = refMonth === 1 ? 12 : refMonth - 1;
      checks.push({
        id: this.scopedId("review.monthly", viewState),
        view_state: viewState,
        expected: this.monthlyReview(reviewYear, reviewMonth, ownerId),
      });
      checks.push({
        id: this.scopedId("review.yearly", viewState),
        view_state: viewState,
        expected: this.yearlyWrapup(refYear - 1, ownerId),
      });
    }

    return checks;
  }

  report(dbPath, registryPath, vocabularyPath) {
    const checks = this.checks();
    return {
      oracle_version: ORACLE_VERSION,
      language: "javascript",
      runtime: `node ${process.version}`,
      sqlite_reader: "sql.js",
      db_path: path.resolve(dbPath),
      registry_path: path.resolve(registryPath),
      vocabulary_path: path.resolve(vocabularyPath),
      seed_version: this.manifest.seed_version,
      reference_date: this.manifest.reference_date,
      database_fingerprint: this.manifest.database_fingerprint,
      check_count: checks.length,
      checks,
    };
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const YAML = require("../frontend/node_modules/yaml");
  const { default: initSqlJs } = await import("../frontend/node_modules/sql.js/dist/sql-wasm.js");
  const SQL = await initSqlJs({
    locateFile: (file) => path.join(SQL_JS_DIST, file),
  });
  const dbBuffer = readFileSync(path.resolve(args.db));
  const db = new SQL.Database(dbBuffer);
  try {
    const oracleDb = new OracleDb(db);
    // The registry uses a `*all_views` alias once per registered value;
    // each new surface multiplies the alias count, so the YAML parser's
    // "excessive alias" guard trips well below our actual size. Disable
    // the check (`maxAliasCount: -1`) — the file is committed source,
    // not adversarial input.
    const registry = YAML.parse(
      readFileSync(path.resolve(args.registry), "utf8"),
      { maxAliasCount: -1 },
    );
    const vocabulary = JSON.parse(readFileSync(path.resolve(args.vocabulary), "utf8"));
    const manifestRow = oracleDb.one(
      "SELECT value FROM app_settings WHERE key = 'trusted_seed_manifest'",
    );
    if (!manifestRow) {
      throw new Error("trusted seed manifest not found in app_settings");
    }
    const manifest = JSON.parse(manifestRow.value);
    const oracle = new NumberTrustOracle(oracleDb, registry, vocabulary, manifest);
    const report = oracle.report(args.db, args.registry, args.vocabulary);
    process.stdout.write(JSON.stringify(report, null, args.pretty ? 2 : 0));
    process.stdout.write("\n");
  } finally {
    db.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error?.stack || String(error));
    process.exit(1);
  });
}
