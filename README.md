# 🚀 Project Antigravity — Personal Finance Dashboard

## Overview
A fast, interactive, and privacy-focused local finance dashboard built with **Python**, **Dash**, and **Plotly**. It ingests CSV exports from various institutions (Navy Federal, Chase, etc.), normalizes the data, and presents high-level KPIs alongside granular transaction review tools.

## Key Features

### 📊 Visualization & Analytics
- **Net Cash Flow Engine**: Custom logic to exclude internal transfers/savings from Income/Expense calculations to show true cash flow.
- **Income vs Spending**: Monthly bar/line combo chart.
- **Category Breakdown**: Top 12 categories by spend (Pie Chart).
- **Weekly Burn Rate**: Trend line of weekly spending.
- **Officiating Income**: Specialized view for specific income streams ("Hustle P&L").
- **Recurring Expenses**: Auto-detection of subscriptions (Netflix, Spotify, etc.).

### 🛠️ Interactive Tooling
- **Transaction Review Table**: 
    - Full transaction list with pagination (10/15/20/50/100 rows).
    - Sortable & Filterable columns.
    - **Category Filters**: Dropdown to isolate specific transaction groups (e.g., "Checks", "Amazon").
- **Interactive Categorization**:
    - **Edit in Place**: Change any transaction category directly in the table.
    - **Add New Categories**: Create new categories on the fly via modal.
    - **Persistence**: Changes are saved to `category_map.json` and persist across restarts.

## Setup & Run

### Prerequisites
- Python 3.10+
- Dependencies: `dash`, `pandas`, `plotly`

### Running the App
1. Place CSV files in the data directories (e.g., `NavyFed/`, `Chase/`).
2. Run the dashboard:
   ```bash
   python dashboard.py
   ```
3. Open **http://127.0.0.1:8050** in your browser.

## Logic Notes
- **Transfers**: Moves between checking/savings/credit cards are treated as neutral (not income, not expense).
- **Credit Card Payments**: The payment itself is neutral; the *original purchase* on the card is the expense.
- **Categorization**: Priority is `Manual Override (category_map.json)` > `CSV Category`.

---

## 🔧 Development & Improvement Plan

### Current Status
The dashboard is functional and provides valuable financial insights. However, there are **code quality improvements** and **feature additions** planned to make the system more robust, maintainable, and automated.

### 📋 Next Action Steps

This project has two parallel development tracks:

#### **Track 1: Code Quality & Refactoring**
Work through the issues identified in **[ISSUES.md](ISSUES.md)** to improve code maintainability, performance, and reliability.

**Recommended Order:**
1. **Quick Wins** (Start Here - Low Effort, High Impact):
   - Issue #2: Inefficient Category Application
   - Issue #7: Silent Error Handling
   - Issue #9: Unused Color Definitions
   - Issue #12: Inconsistent Excluded Categories

2. **Medium Priority** (Improves Maintainability):
   - Issue #4: Hardcoded File Paths
   - Issue #5: Duplicate Categorization Logic
   - Issue #6: Hardcoded Business Logic
   - Issue #14: No Environment Configuration

3. **Long-term Refactors** (High Effort, High Value):
   - Issue #15: Single Monolithic File (Split into modules)
   - Issue #3: Global State Mutation
   - Issue #1: Data Loading Performance

**How to Work Through Issues:**
- Open the project in your IDE (Cursor, Windsurf, VS Code, etc.)
- Reference **ISSUES.md** for detailed descriptions and suggested fixes
- Tackle issues one at a time, testing after each change
- Commit frequently with descriptive messages (e.g., "Fix #2: Vectorize category application")

#### **Track 2: Automated Data Extraction**
Build the extraction pipeline outlined in **[DATA-EXTRACTION-PLAN.md](DATA-EXTRACTION-PLAN.md)** to eliminate manual CSV exports.

**Implementation Phases:**
1. **Phase 1: Foundation** (Week 1-2)
   - Set up base extractor class
   - Implement credential storage system
   - Create standard schema validator

2. **Phase 2: Core Extractors** (Week 3-6)
   - Navy Federal extractor
   - Chase extractor

3. **Phase 3: Additional Extractors** (Week 7-10)
   - TSP, Fidelity, Acorns, Affirm extractors

4. **Phase 4: Automation** (Week 11-12)
   - Scheduler implementation
   - Error notifications
   - Monitoring dashboard

**How to Start:**
- Review **DATA-EXTRACTION-PLAN.md** for architecture and design decisions
- Begin with Phase 1 (foundation)
- Test each extractor individually before integration
- Start with semi-automated approaches (file monitoring) before full automation

---

## 🎯 Recommended Workflow

### For Code Quality Improvements:
```bash
# 1. Open project in IDE
cd project_antigravity

# 2. Create a feature branch
git checkout -b fix/issue-2-vectorize-categories

# 3. Work on one issue at a time
# Reference ISSUES.md for implementation details

# 4. Test changes
python dashboard.py

# 5. Commit and move to next issue
git commit -m "Fix #2: Vectorize category application for performance"
```

### For Data Extraction Development:
```bash
# 1. Create extractors branch
git checkout -b feature/data-extraction

# 2. Set up directory structure (from DATA-EXTRACTION-PLAN.md)
mkdir -p extractors normalizers validators storage config

# 3. Start with base classes
# Implement BaseExtractor as outlined in DATA-EXTRACTION-PLAN.md

# 4. Build one extractor at a time
# Start with NFCU (most complex) to validate approach

# 5. Test with real accounts in headed mode
python extractors/nfcu.py --headed --test
```

---

## 📚 Documentation

- **[ISSUES.md](ISSUES.md)**: Detailed list of code quality issues and suggested fixes
- **[DATA-EXTRACTION-PLAN.md](DATA-EXTRACTION-PLAN.md)**: Complete architecture and implementation plan for automated data extraction

---

## 🚦 Project Status

| Component | Status | Notes |
|-----------|--------|-------|
| Dashboard Core | ✅ Functional | Working with manual CSV imports |
| Interactive Categorization | ✅ Functional | Category edits persist to JSON |
| Code Quality | ⚠️ Needs Improvement | See ISSUES.md for 15 identified issues |
| Automated Extraction | 🔴 Not Started | See DATA-EXTRACTION-PLAN.md for roadmap |
| Test Coverage | 🔴 None | Add tests as part of refactoring |
| Documentation | ⚠️ In Progress | Core docs complete, extraction plan documented |

---

## 🤝 Contributing

If working on this project with others:
1. Pick an issue from **ISSUES.md** and assign it to yourself
2. Create a feature branch (`fix/issue-N` or `feature/extraction-X`)
3. Make changes and test thoroughly
4. Submit a pull request with reference to the issue number
5. Update ISSUES.md to mark completed items

---

## 📝 Notes for IDE Users (Cursor, Windsurf, etc.)

When working with AI-assisted IDEs:

**For Refactoring Issues:**
- Prompt: "I want to fix Issue #2 from ISSUES.md. Show me how to vectorize the category application."
- Provide the relevant section of `dashboard.py` as context
- Ask for incremental changes with explanations

**For Data Extraction:**
- Prompt: "Help me implement the Navy Federal extractor based on DATA-EXTRACTION-PLAN.md"
- Start with the base class structure
- Build authentication logic first, then navigation, then data extraction

**For Testing:**
- Ask for unit tests for each refactored component
- Request integration test suggestions
- Generate test fixtures from sample CSV data

---

## 🔐 Security Notes

- Never commit credentials to version control
- Use environment variables or OS keychain for sensitive data
- Keep `category_map.json` in `.gitignore` if it contains sensitive transaction descriptions
- When implementing extractors, use encrypted credential storage (see DATA-EXTRACTION-PLAN.md)

---

## 📈 Future Enhancements

Beyond the current ISSUES.md and DATA-EXTRACTION-PLAN.md:
- Budget tracking and forecasting
- Goal setting and progress visualization
- Multi-currency support
- Mobile companion app
- Email/SMS alerts for unusual spending
- Export reports to PDF/Excel
- Integration with tax preparation tools

---

## License

MIT License - This is a personal finance tool. Use at your own risk and ensure you comply with your financial institutions' terms of service.
