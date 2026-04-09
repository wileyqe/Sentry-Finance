"""
dal/parsers/eventlink.py — Eventlink officiating payment history parser.
"""

import csv
import io
import json
import logging
import sqlite3
import re
from datetime import datetime, timezone

from dal.parsers.base import DocumentParser, ParseResult

log = logging.getLogger("sentry.parsers.eventlink")


class EventlinkParser(DocumentParser):
    @property
    def parser_type(self) -> str:
        return "eventlink"

    def can_parse(self, filename: str, content_bytes: bytes) -> bool:
        """Detect Eventlink exports by filename pattern or content markers."""
        name = filename.lower()
        if "eventlink" in name or "payment_history" in name:
            return True
            
        try:
            # Check content for Eventlink headers
            text = content_bytes.decode("utf-8", errors="ignore")[:2000]
            markers = ["Game Date", "Pay Rate", "Assignor", "Official", "Pay Date"]
            return sum(1 for m in markers if m.lower() in text.lower()) >= 2
        except Exception:
            try:
                # Might be binary XLSX
                if content_bytes.startswith(b"PK"):
                    if "payment" in name or "export" in name:
                        # Need openpyxl to be sure, but filename hinting + PK ZIP header is a good proxy 
                        # for Excel if we assume reasonable constraint.
                        return True
            except Exception:
                pass
            return False

    def parse(self, content_bytes: bytes) -> ParseResult:
        """Parse the export file into structured payment records."""
        # Try XLSX first, fallback to CSV
        try:
            if content_bytes.startswith(b"PK\x03\x04"):
                return self._parse_xlsx(content_bytes)
        except Exception:
            pass
            
        return self._parse_csv(content_bytes)

    def _parse_xlsx(self, file_bytes: bytes) -> ParseResult:
        """Parse XLSX format using openpyxl."""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportError("openpyxl is required to parse Eventlink XLSX files. Please install it.")
            
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        
        headers = []
        payments = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(cell).strip().lower() if cell is not None else "" for cell in row]
                continue
            
            row_dict = dict(zip(headers, row))
            if any(v is not None for v in row_dict.values()):
                payments.append(self._process_row(row_dict))
                
        return self._build_result(payments)

    def _parse_csv(self, file_bytes: bytes) -> ParseResult:
        """Parse CSV format."""
        content_str = file_bytes.decode("utf-8", errors="ignore")
        # Try standard parsing first
        try:
            reader = csv.DictReader(content_str.splitlines())
            rows = list(reader)
        except Exception:
            # Fallback for weird newlines in unquoted fields
            reader = csv.DictReader(content_str.splitlines(), quoting=csv.QUOTE_NONE)
            rows = list(reader)
        
        payments = []
        for row in rows:
            clean_row = {k.strip().lower(): v for k, v in row.items() if k}
            if any(clean_row.values()):
                payments.append(self._process_row(clean_row))
                
        return self._build_result(payments)
        
    def _process_row(self, row: dict) -> dict:
        """Extract needed fields flexibly given varying column names."""
        pay = {}
        # Date processing
        game_date = row.get("game date") or row.get("date") or ""
        pay_date = row.get("pay date") or row.get("payment date") or row.get("date") or ""
        
        # Format string dates to YYYY-MM-DD
        pay["game_date"] = self._format_date(game_date)
        pay["pay_date"] = self._format_date(pay_date) or pay["game_date"]
        
        # Amount
        amt_str = str(row.get("amount", row.get("total", row.get("pay rate", "0"))))
        amt_str = amt_str.replace('$', '').replace(',', '').strip()
        try:
            pay["amount"] = float(amt_str)
        except ValueError:
            pay["amount"] = 0.0
            
        # Details
        pay["sport"] = row.get("sport", row.get("event", ""))
        pay["level"] = row.get("level", row.get("game", ""))
        pay["role"] = row.get("role", row.get("position", ""))
        pay["raw_line"] = json.dumps(row)
        
        return pay
        
    def _format_date(self, dt) -> str:
        if not dt:
            return ""
        if hasattr(dt, 'strftime'):
            return dt.strftime("%Y-%m-%d")
        
        dt_str = str(dt).strip()
        m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})", dt_str)
        if m:
            mm, dd, yy = m.groups()
            if len(yy) == 2:
                yy = "20" + yy
            return f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
        return dt_str
        
    def _build_result(self, payments: list[dict]) -> ParseResult:
        valid_payments = [p for p in payments if p["amount"] > 0]
        
        total_amount = sum(p["amount"] for p in valid_payments)
        preview = {
            "Total Games": len(valid_payments),
            "Total Earned": f"${total_amount:,.2f}"
        }
        
        if valid_payments:
            dates = [p["game_date"] for p in valid_payments if p["game_date"]]
            if dates:
                preview["Date Range"] = f"{min(dates)} to {max(dates)}"
                
        warnings = []
        can_commit = True
        if not valid_payments:
            warnings.append(
                "⚠ BLOCK: Recognized as an Eventlink export but no "
                "valid payments > $0 were extracted. The file format "
                "may have changed, or the export is empty."
            )
            can_commit = False

        return ParseResult(
            parser_type=self.parser_type,
            preview=preview,
            data={"payments": valid_payments},
            warnings=warnings,
            can_commit=can_commit,
        )

    def commit(self, conn: sqlite3.Connection, result: ParseResult) -> dict:
        """Write parsed data to the transactions table. Deduplicates based on 7-day window."""
        payments = result.data.get("payments", [])
        
        if not payments:
            return {"inserted": 0, "duplicates": 0, "total_value": 0}
            
        inserted = 0
        duplicates = 0
        total_value = 0.0
        
        now = datetime.now(timezone.utc).isoformat()
        acct_id = "eventlink_manual"
        
        conn.execute(
            "INSERT OR IGNORE INTO accounts (id, name, type, subtype, institution_name) VALUES (?, ?, 'depository', 'cash', 'Eventlink')",
            (acct_id, 'Eventlink Payouts')
        )
        
        for i, pay in enumerate(payments):
            amt = pay["amount"]
            pay_date = pay["pay_date"]
            
            parts = [p for p in [pay['sport'], pay['level'], pay['role']] if p]
            desc = f"Officiating: {' '.join(parts)}" if parts else "Eventlink Officiating"
            
            # Check for duplicate: Date within 7 days, exact amount, and Officiating Income category
            dup_row = conn.execute("""
                SELECT id FROM transactions 
                WHERE category = 'Officiating Income'
                  AND amount = ? 
                  AND abs(julianday(posting_date) - julianday(?)) <= 7
                LIMIT 1
            """, (amt, pay_date)).fetchone()
            
            if dup_row:
                duplicates += 1
                continue
                
            txn_id = f"evl_{pay_date.replace('-', '')}_{int(amt*100)}_{i}_{now[-4:]}"
            
            conn.execute("""
                INSERT INTO transactions (
                    id, account_id, posting_date, transaction_date,
                    amount, signed_amount, direction, 
                    description, raw_description, merchant_name,
                    category, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'credit', ?, ?, 'Eventlink', 'Officiating Income', ?)
            """, (
                txn_id, acct_id, pay_date, pay["game_date"],
                amt, amt, desc, pay["raw_line"], now
            ))
            
            inserted += 1
            total_value += amt
            
        return {
            "inserted": inserted,
            "duplicates_skipped": duplicates,
            "total_earned": total_value
        }
