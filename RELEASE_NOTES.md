# Release Notes
pending patch — Full Account Upload with Year selection 
## v2.0.0 - Bulk Upload
{# v2.2.1
save merchant rule
I’d go “Save as Rule” system design next, not UI.
That’s where this becomes dangerously powerful.

3.31.26 ->  v2.2.0
when changes are made where is it all getting stored to for later continued work? #}

v2.1.0
Users click: Date, Description, amount, Category click again to reverse: asc / desc





## v1.0.0 — Full Account or Partial Upload and proper sorting


## v0.2.0 — Sidebar + Summary Dashboard + Annual P&L

### Added
- App-wide base layout (`base.html`) with persistent left sidebar navigation.
- New landing **Summary** page after upload with key KPIs and report links.
- New **Annual P&L** page plus existing Monthly P&L broken out as separate views.
- “Results (All)” page remains available for users who want an at-a-glance combined view.
- New drilldown pages/routes:
  - Monthly P&L
  - Annual P&L
  - Flags
  - Non-P&L candidates
  - Categories
  - Excel export

### Improved
- Defensive date-range detection in Summary to prevent crashes across inconsistent bank CSVs.
  - Supported date column names: `Date`, `Transaction Date`, `Posted Date`, `Txn Date` (case-insensitive).
- Added `months_covered` KPI to quickly show whether uploads contain a full year vs partial data.
- Added `uncategorized_count` KPI and conditional display block so users can immediately spot categorization gaps.

### Notes
- P&L statement formatting will be upgraded later to a standard report layout (Revenue → COGS → Gross Profit → Expenses → Net) driven by an expanded category map and ordering rules.
- Future: upgrade P&L rendering to a standard statement layout (Revenue → COGS → Gross Profit → Expenses → Net) driven by an expanded category map and ordering rules.