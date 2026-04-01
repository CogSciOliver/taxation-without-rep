# Release Notes
pending patch — Full Account Upload with Year selection does not have functionality
pending patch - Bulk edit Undo does not have functionality. 

{# 
03.31.26
v2.2.0 = local named workspaces with saved editable transaction state
v2.3.0 = merchant rule persistence layered on top
 #}

03.31.26 > Stopped work at append imports into existing workspace
============================================================

## v2.2.0 — Local working files
Build this next.

Goal:

user uploads 1+ revenue CSVs
user uploads 1+ expense CSVs
app merges them into one named working file
working file is saved locally
user can reopen later and continue editing

This is more important than merchant rules because:

it solves real workflow continuity
it supports partial work across sessions
it makes the app feel like a real tool, not a one-shot analyzer

What v2.2.0 should become
New concept: Working File

A working file is your local project file.

It should store:

user-given project name
raw imported transactions
edited transaction state
P&L inclusion state
cash flow / non-P&L state
category edits
selected entity mode
selected year if applicable
saved timestamp
Suggested local storage format

Use a single local JSON file first.

Example:
data/workspaces/my_2025_tax_work.json

Why JSON first:

easy to inspect
easy to save/load
easy to debug
safer than prematurely building sqlite complexity

You can always move to SQLite later.

v2.2.0 user flow
Create or open workspace

New landing options:

Create Working File
Open Working File
Create Working File

User enters:

workspace name
entity mode
optional tax year

Then uploads:

1 or more revenue CSVs
1 or more expense CSVs

App:

normalizes all files
tags source file
combines into one dataframe
saves locally as that workspace
Open Working File

User sees list of saved local workspaces.
Select one.
Continue editing from last saved state.

============================================================



Final P&L Structure I need to be able to Take in Revenue CSV (1 or more) > Save to selected working file for final data pull Take in Expense CSV (1 or more) > Save to selected working file for final data pull = uploading 1 or more files that copy and save to 1 working file (Named by User stored Locally) The Selected file (Named by User stored Locally), needs to be is editable moving income to income section only and expenses to expenses only and removing non-pl items to "cash flow" selection removed from the flagged for P&L edits not deleted forever but saved for cash flow reports much later on. So lets work on saving for later continued work > user edits a bit leaves then comes back, selects a working file to keep working on









## v2.2.0 
Sidebar now opens saved workspaces. upload: pass bulk edit: pass save named workspace: pass open working file entry: pass auto-save after edit: pass preserved edits after reopen: pass load reports from saved edits: pass.

## v2.1.0
Results, Users click: Date, Description, Amount, Category click again to reverse: asc / desc

## v2.0.0 - Bulk Edit 
bulk correct & rebuild P&L cleanly (does not save beyond session)

## v1.0.0 
Full Account or Partial Upload and proper sorting


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