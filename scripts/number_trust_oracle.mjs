#!/usr/bin/env node

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import initSqlJs from "../frontend/node_modules/sql.js/dist/sql-wasm.js";

const require = createRequire(import.meta.url);
const YAML = require("../frontend/node_modules/yaml");

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

const ORACLE_VERSION = "node-sqljs-oracle-v1";

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

function round1(value) {
  return Math.round(Number(value || 0) * 10) / 10;
}

function round2(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

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

  checks() {
    const referenceDate = this.manifest.reference_date;
    const { start, end } = monthBounds(referenceDate);
    const checks = [];

    for (const viewState of this.registryViewStates()) {
      const ownerId = viewState.owner_id ?? null;
      const summary = this.reportSummary(start, end, ownerId);
      const cashout = this.cashoutPeriod(start, end, ownerId);

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
  const SQL = await initSqlJs({
    locateFile: (file) => path.join(SQL_JS_DIST, file),
  });
  const dbBuffer = readFileSync(path.resolve(args.db));
  const db = new SQL.Database(dbBuffer);
  try {
    const oracleDb = new OracleDb(db);
    const registry = YAML.parse(readFileSync(path.resolve(args.registry), "utf8"));
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

main().catch((error) => {
  console.error(error?.stack || String(error));
  process.exit(1);
});
