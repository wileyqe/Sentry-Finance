"""pii_scan.py — Repository PII scanner.

Scans tracked / staged files for leaked PII before commit or on-demand.

Usage:
  python scripts/pii_scan.py                     # scan staged files (hook mode)
  python scripts/pii_scan.py --all-tracked       # scan every tracked file
  python scripts/pii_scan.py --files a.py b.md   # scan specific files

Exits non-zero on any hit (blocks the commit when wired to pre-commit).

Real account last-4s are sourced from a gitignored `accounts.yaml` at
repo root. If the file is absent, that category is skipped silently —
new contributors without the yaml still get SSN / card / location
coverage.

Allowlisted files (known to carry adversarial fixtures) are skipped:
  - tests/test_failure_modes.py   (defensive PII-scrubber assertions)
  - scripts/pii_scan.py           (this file, contains the patterns)
  - docs/prompts/P0-SEC_pii-security-gate.md  (audit narrative)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_YAML = REPO_ROOT / "accounts.yaml"

ALLOWLIST = {
    "tests/test_failure_modes.py",
    "scripts/pii_scan.py",
    "docs/prompts/P0-SEC_pii-security-gate.md",
    "accounts.yaml.example",
    "config/categories.user.yaml.example",
}

# Files that are allowed to carry a VIN-shape literal. The synthetic
# vehicle's VIN lives in dummy_data/vehicle_assets.json and (until PR2's
# composer lands) the seeder. The details-panel invariant test seeds
# its own synthetic vehicle for assertions. A VIN appearing anywhere
# else — extractors, backend, frontend, prompts — is a leak.
VIN_ALLOWED_FILES = {
    "dummy_data/vehicle_assets.json",
    "scripts/seed_dummy_data.py",
    "tests/test_details_panel_invariants.py",
    # 2026-04-27: VIN regex fixture pinning the NFCU auto-loan
    # field-pattern, and the link_vehicle_to_loan_by_vin DAL helper.
    "tests/test_nfcu_extractor.py",
    "tests/test_dal_vehicles.py",
}

# Files + suffixes that are known to contain arbitrary digit strings
# (SVG path coords, pip wheel hashes, lockfile integrity hashes).
# We skip the Luhn-card check on these; static SSN/phone/location still run.
LUHN_SKIP_SUFFIXES = {".svg", ".lock", ".min.js", ".woff", ".woff2"}
LUHN_SKIP_FILES = {
    "requirements.txt",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "frontend/package-lock.json",
}

# Static patterns (run on every file not in the allowlist).
# Tuples of (label, compiled regex).
STATIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN (\\d{3}-\\d{2}-\\d{4})", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("US phone (\\d{3}-\\d{3}-\\d{4})", re.compile(r"\b\d{3}-\d{3}-\d{4}\b")),
    # Merchant customer-service format on bank statements (e.g. NETFLIX.COM
    # 866-XXXXXXX CA) — same 10 digits but different grouping than US phone.
    ("Merchant phone (\\d{3}-\\d{7})", re.compile(r"\b\d{3}-\d{7}\b")),
    ("Bloomington literal", re.compile(r"\bBloomington\b", re.I)),
    ("Indiana literal", re.compile(r"\bIndiana\b", re.I)),
]

# VIN-shape: 17 alphanumerics, no I/O/Q (per ISO 3779). Run only on
# files NOT in VIN_ALLOWED_FILES — see Apr 2026 leak where a real Kia
# VIN was committed into seed_dummy_data.py disguised as "dummy data".
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")

# Python-only: flag log.* calls that interpolate an unredacted account
# identifier. The P0 audit found five such leaks in backend/result_writer
# and seven more across extractors/*. Any new regression gets caught here
# at commit time instead of leaking real last-4s into log files.
_LOG_CALL_RE = re.compile(
    r"\blog\.(info|warning|warn|error|exception|debug)\b"
)
# Must appear as an ARGUMENT (preceded by comma or open-paren, followed by
# comma/close-paren) so format-string literals like
# ``"rewrote %d account_id(s)"`` are not false-positives.
_PII_ARG_RE = re.compile(
    r"[,(]\s*(account_id|account_ids|acct\.last4|acct\.last_4)\s*[,)]"
)
_REDACT_WRAP_RE = re.compile(
    r"(redact_account_id_for_logs|_redact_account_id|redact_last4|mask_account_id)\s*\("
)


def check_unredacted_pii_in_log_call(line: str) -> str | None:
    # Returns a label if this single line is a log call whose arg list
    # contains an unredacted account identifier, else None.
    if not _LOG_CALL_RE.search(line):
        return None
    if not _PII_ARG_RE.search(line):
        return None
    if _REDACT_WRAP_RE.search(line):
        return None
    return "unredacted account identifier in log call"


def load_real_last4s() -> list[str]:
    """Read real last-4 digits from gitignored accounts.yaml. Returns [] if missing."""
    if not ACCOUNTS_YAML.exists():
        return []
    try:
        import yaml
    except ImportError:
        return []
    with open(ACCOUNTS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    last4s: set[str] = set()
    for _institution, accounts in data.items():
        if not isinstance(accounts, list):
            continue
        for acct in accounts:
            # Skip accounts explicitly marked synthetic (dummy UI/UX test
            # accounts whose last-4 is not PII).
            if acct.get("synthetic") is True:
                continue
            last4 = str(acct.get("last4", "")).strip()
            # Only numeric last-4s are leakable; labels like "HYSA" or "BNPL"
            # are not PII and may also false-positive against legit content.
            if re.fullmatch(r"\d{4}", last4):
                last4s.add(last4)
    return sorted(last4s)


def luhn_check(digits: str) -> bool:
    """Return True if the digit string passes the Luhn checksum."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def iter_target_files(args: argparse.Namespace) -> list[Path]:
    """Resolve files to scan based on CLI args."""
    if args.files:
        return [Path(f).resolve() for f in args.files]
    if args.all_tracked:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        )
        return [REPO_ROOT / line for line in out.splitlines() if line.strip()]
    # Default: staged files (pre-commit hook mode)
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def scan_file(path: Path, last4s: list[str]) -> list[tuple[int, str, str]]:
    """Scan a single file. Returns list of (line_no, pattern_label, snippet)."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel in ALLOWLIST:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    hits: list[tuple[int, str, str]] = []

    is_python = path.suffix == ".py"
    vin_check_active = rel not in VIN_ALLOWED_FILES

    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pat in STATIC_PATTERNS:
            if pat.search(line):
                hits.append((line_no, label, line.strip()[:120]))

        if vin_check_active:
            for m in _VIN_RE.finditer(line):
                # Filter out clearly-non-VIN false positives: pure-digit
                # strings (e.g. "12345678901234567" — happens in lock
                # files, hashes) and strings with no letters.
                vin = m.group(0)
                if not any(c.isalpha() for c in vin):
                    continue
                hits.append((line_no, "VIN-shape (17-char alnum)", vin))

        if is_python:
            log_hit = check_unredacted_pii_in_log_call(line)
            if log_hit:
                hits.append((line_no, log_hit, line.strip()[:120]))

        for last4 in last4s:
            # Require the match to NOT be preceded by a decimal point
            # (filters out float literals like 0.0001) or by alphanumeric
            # content (filters out hex hashes and identifiers).
            for m in re.finditer(rf"\b{last4}\b", line):
                before = line[m.start() - 1] if m.start() > 0 else ""
                if before in (".", "_"):
                    continue
                hits.append((line_no, f"real last-4 ({last4})", line.strip()[:120]))
                break  # one hit per line per last-4 is enough

        # Luhn-valid 13–16 digit sequences (potential card number).
        skip_luhn = (
            path.suffix in LUHN_SKIP_SUFFIXES or rel in LUHN_SKIP_FILES
        )
        if not skip_luhn:
            for m in re.finditer(r"(?<!\d)(\d{13,16})(?!\d)", line):
                digits = m.group(1)
                if luhn_check(digits):
                    hits.append(
                        (line_no, "Luhn-valid card-like digit string", digits[:4] + "…")
                    )

    return hits


def warn_staged_sensitive_files(staged: Iterable[Path]) -> list[str]:
    """Flag staged files that are *supposed* to be gitignored (.env, accounts.yaml)."""
    flagged: list[str] = []
    for p in staged:
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel in {".env", "accounts.yaml", "config/categories.user.yaml"}:
            flagged.append(rel)
    return flagged


def main() -> int:
    # Windows default stdout is cp1252; force UTF-8 so unicode content
    # in scanned files can be echoed back without crashing.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all-tracked", action="store_true",
                        help="Scan every tracked file instead of staged ones.")
    parser.add_argument("--files", nargs="*", default=None,
                        help="Scan only these files (space-separated paths).")
    args = parser.parse_args()

    files = iter_target_files(args)
    if not files:
        print("pii_scan: no files to scan.")
        return 0

    last4s = load_real_last4s()
    if last4s:
        print(f"pii_scan: loaded {len(last4s)} real last-4 value(s) from accounts.yaml")
    else:
        print("pii_scan: accounts.yaml not present or empty — skipping last-4 checks")

    # Defensive: never let .env / accounts.yaml be staged.
    if not args.all_tracked and not args.files:
        sensitive = warn_staged_sensitive_files(files)
        if sensitive:
            print("pii_scan: BLOCKED — sensitive gitignored files are staged:")
            for s in sensitive:
                print(f"  - {s}")
            print("Unstage them with `git restore --staged <file>`.")
            return 2

    exit_code = 0
    for f in files:
        if not f.is_file():
            continue
        hits = scan_file(f, last4s)
        if hits:
            exit_code = 1
            rel = f.relative_to(REPO_ROOT).as_posix()
            for line_no, label, snippet in hits:
                print(f"pii_scan: {rel}:{line_no}  [{label}]  {snippet}")

    if exit_code == 0:
        print("pii_scan: clean.")
    else:
        print("pii_scan: HITS FOUND — remediate before committing.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
