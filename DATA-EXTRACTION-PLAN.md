# Data Extraction Pipeline - Project Antigravity

This document outlines the architecture and implementation plan for automated data extraction from financial institutions.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Extraction Pipeline (Scheduled or On-Demand)   │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌──────────────┐        │
│  │  Extractors  │─────▶│  Normalizer  │────┐   │
│  └──────────────┘      └──────────────┘    │   │
│        │                                    │   │
│  ┌─────┴─────┐                              │   │
│  │ Validator │                              │   │
│  └───────────┘                              │   │
│                                             ▼   │
│                                   ┌──────────┐  │
│                                   │  Storage │  │
│                                   │  (CSV)   │  │
│                                   └──────────┘  │
└─────────────────────────────────────────────────┘
```

---

## 1. Navy Federal Credit Union

### Method
Web scraping with Playwright/Selenium (NFCU doesn't offer API access)

### Pipeline Steps

**1. Authentication**
- Store credentials securely (keyring, environment variables, or OS credential manager)
- Handle 2FA via TOTP (store secret) or SMS (require manual intervention)

**2. Navigation**
- Log in to navyfederal.org
- Navigate to each account (checking, credit card, loans)
- Select "Download Transactions" → 90 days or custom range

**3. Download**
- Click "Download as CSV"
- Monitor downloads folder for new file
- Rename with account identifier and timestamp

**4. Challenges**
- CAPTCHA detection (may need to solve manually or use service)
- Session timeouts (keep-alive pings)
- Layout changes breaking selectors

### Recommended Tools
- Playwright (headless browser, better than Selenium for modern sites)
- `pyotp` for TOTP 2FA automation

---

## 2. Chase Bank

### Method
Web scraping (Chase blocks most API access for personal accounts)

### Pipeline Steps

**1. Authentication**
- Store credentials securely
- Handle multi-factor authentication (SMS, push notification, or hardware token)

**2. Navigation**
- Log in to chase.com
- For each account: navigate to "Account Activity"
- Use date picker to select range (last 90 days or custom)

**3. Download**
- Click "Download" → CSV format
- Save with account identifier

**4. Challenges**
- Aggressive bot detection (may require residential proxy)
- Device fingerprinting (save browser state between runs)
- Frequent layout updates

### Recommended Tools
- Playwright with persistent browser context (to maintain session cookies)
- `undetected-playwright` to bypass bot detection

---

## 3. Thrift Savings Plan (TSP)

### Method
Manual CSV export or web scraping

### Pipeline Steps

**1. Authentication**
- Log in to tsp.gov
- May require PIV/CAC card or multi-factor authentication

**2. Navigation**
- Go to "Transactions" or "Account Activity"
- Export transaction history as CSV

**3. Download**
- Save CSV with timestamp

**4. Challenges**
- TSP updates infrequently (daily at best)
- PIV/CAC authentication is difficult to automate (may need manual login)
- Limited historical data export range

### Recommended Approach
**Semi-automated**: Provide a browser extension or desktop app that monitors downloads folder for TSP exports. Manual login, automated file detection and processing.

---

## 4. Fidelity

### Method
Web scraping or API (Fidelity has limited third-party integrations)

### Pipeline Steps

**1. Authentication**
- Use Selenium/Playwright to log in
- Handle 2FA (Symantec VIP or SMS)

**2. Navigation**
- Navigate to "Accounts & Trade" → "Activity & Orders"
- Select date range
- Click "Download" → CSV

**3. Alternative**: Fidelity Full View API (if available)
- Some third-party apps use undocumented APIs
- Requires reverse-engineering network requests

**4. Challenges**
- Multi-step navigation
- Complex JavaScript rendering (requires browser automation, not simple requests)

### Recommended Tools
- Playwright for automation
- Consider Plaid API if only balance/holdings are needed (not transactions)

---

## 5. Acorns

### Method
Email exports or web scraping (Acorns has no public API)

### Pipeline Steps

**1. Email-Based Extraction** (Easiest)
- Acorns sends transaction notifications via email
- Set up email filter to forward Acorns emails to a specific address
- Parse emails to extract transaction data
- Limitations: Email format may change; only captures notifications, not full history

**2. Web Scraping Alternative**
- Log in to Acorns website
- Navigate to "Transactions"
- Scrape transaction data from HTML table
- No CSV export available, so parse HTML directly

**3. Challenges**
- No official export function
- App-first platform (mobile app is primary interface)
- Limited web interface

### Recommended Approach
**Email parsing** for new transactions (real-time) + **Manual CSV logging** for historical imports

---

## 6. Affirm

### Method
Web scraping (Affirm has no public API for consumers)

### Pipeline Steps

**1. Authentication**
- Log in to affirm.com
- Handle SMS 2FA

**2. Navigation**
- Navigate to "Transactions" or "Payment History"
- Click "Download" if available, or scrape HTML table

**3. Data Extraction**
- If CSV download exists, use it
- Otherwise, parse transaction table HTML

**4. Challenges**
- Affirm is primarily a loan/financing platform, not a bank
- Transaction history may be limited to loan payments, not all activity
- Layout may vary based on account type

### Recommended Tools
- Playwright for scraping
- HTML parsing with BeautifulSoup if no CSV export

---

## Unified Pipeline Architecture

### Directory Structure

```
project_antigravity/
├── extractors/
│   ├── __init__.py
│   ├── base.py              # Base extractor class
│   ├── nfcu.py              # Navy Federal extractor
│   ├── chase.py             # Chase extractor
│   ├── tsp.py               # TSP extractor
│   ├── fidelity.py          # Fidelity extractor
│   ├── acorns.py            # Acorns extractor
│   ├── affirm.py            # Affirm extractor
│   └── utils.py             # Shared utilities (browser setup, wait logic)
│
├── normalizers/
│   ├── __init__.py
│   ├── base.py              # Base normalizer class
│   ├── nfcu.py              # NFCU CSV → standard format
│   ├── chase.py             # Chase CSV → standard format
│   └── ...
│
├── validators/
│   ├── __init__.py
│   └── schema.py            # Validate normalized data against schema
│
├── storage/
│   ├── __init__.py
│   └── csv_writer.py        # Write to data/ directory with naming convention
│
├── config/
│   ├── credentials.yaml     # Encrypted or env-var references
│   ├── extractors.yaml      # Extractor settings (timeouts, selectors)
│   └── schema.yaml          # Expected output schema
│
├── main.py                  # CLI entry point (run all extractors)
└── scheduler.py             # Optional: cron-like scheduler
```

### Base Extractor Interface

```python
class BaseExtractor:
    def authenticate(self) -> bool:
        """Log in to the institution. Return True if successful."""
        pass
    
    def extract_data(self, start_date, end_date) -> Path:
        """Download transactions for date range. Return path to raw file."""
        pass
    
    def normalize(self, raw_file: Path) -> pd.DataFrame:
        """Convert raw file to standard schema."""
        pass
    
    def validate(self, df: pd.DataFrame) -> bool:
        """Check that normalized data meets schema requirements."""
        pass
    
    def save(self, df: pd.DataFrame, account_name: str):
        """Save to data/ directory with standard naming."""
        pass
```

### Standard Output Schema

Every extractor outputs a DataFrame with these columns:

- `date` (datetime): Transaction date
- `description` (str): Merchant/description
- `amount` (float): Absolute amount
- `signed_amount` (float): Signed amount (positive = credit, negative = debit)
- `category` (str): Initial category (can be "Uncategorized")
- `institution` (str): Institution name
- `account` (str): Account name/type
- `raw_category` (str): Original category from institution (for debugging)

---

## Security Considerations

### 1. Credentials
- Use environment variables or OS keychain (not hardcoded)
- Encrypt credentials.yaml with a master password

### 2. Browser Sessions
- Save browser state between runs to avoid re-authentication
- Use headless mode for automation, but allow headed mode for debugging

### 3. Rate Limiting
- Add delays between requests to avoid triggering anti-bot systems
- Randomize delays (e.g., 2-5 seconds between page navigations)

---

## Error Handling

### 1. Retry Logic
If authentication fails, retry 3 times with exponential backoff

### 2. Notifications
Send email/SMS if extraction fails for 3 consecutive days

### 3. Logging
Log all actions to `logs/extractor_{institution}_{date}.log`

---

## Scheduling Options

### 1. Cron Job (Linux/Mac)
Run daily at 3 AM:
```bash
0 3 * * * python /path/to/main.py --all
```

### 2. Windows Task Scheduler
Same concept on Windows

### 3. Python APScheduler
Built-in scheduler within the app:
```python
from apscheduler.schedulers.background import BackgroundScheduler
scheduler.add_job(extract_all, 'cron', hour=3)
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Set up base extractor class
- [ ] Implement credential storage system
- [ ] Create standard schema validator
- [ ] Build CSV writer with naming convention

### Phase 2: Core Extractors (Week 3-6)
- [ ] Navy Federal extractor (most complex)
- [ ] Chase extractor
- [ ] Test both with real accounts

### Phase 3: Additional Extractors (Week 7-10)
- [ ] TSP extractor (semi-automated)
- [ ] Fidelity extractor
- [ ] Acorns email parser
- [ ] Affirm scraper

### Phase 4: Automation (Week 11-12)
- [ ] Implement scheduler
- [ ] Add error notifications
- [ ] Create monitoring dashboard
- [ ] Write documentation

---

## Testing Strategy

### Unit Tests
- Mock authentication responses
- Test normalizers with sample CSV files
- Validate schema enforcement

### Integration Tests
- Test full pipeline with sandbox accounts (if available)
- Verify CSV output matches expected format

### Manual Tests
- Run extractors on real accounts in headed mode
- Verify downloaded files are correct
- Test error handling (wrong password, network failure, etc.)

---

## Maintenance Plan

### Monthly
- Check for website layout changes
- Update selectors if needed
- Review error logs

### Quarterly
- Test all extractors end-to-end
- Update dependencies
- Review security practices

### Annually
- Rotate credentials
- Audit logging practices
- Evaluate new API opportunities
