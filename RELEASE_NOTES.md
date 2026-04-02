# Release Notes
pending patch — Full Account Upload with Year selection does not have functionality
pending patch - Bulk edit Undo does not have functionality. 

{# 
v4.0.0 = merchant rule persistence layered on top
 #}

============================================================

============================================================

Final P&L Structure I need to be able to Take in Revenue CSV (1 or more) > Save to selected working file for final data pull Take in Expense CSV (1 or more) > Save to selected working file for final data pull = uploading 1 or more files that copy and save to 1 working file (Named by User stored Locally) The Selected file (Named by User stored Locally), needs to be is editable moving income to income section only and expenses to expenses only and removing non-pl items to "cash flow" selection removed from the flagged for P&L edits not deleted forever but saved for cash flow reports much later on. So lets work on saving for later continued work > user edits a bit leaves then comes back, selects a working file to keep working on

======================== Pending ====================================
## Later Patch 
clean duplicate notes/import messaging
or incomplete upload detection / partial P&L warnings, which is the next trust feature from your earlier app goals

## Later Patch 
Change 
```
if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)
```

to return to main landing page = load select workspace page (with last working file as first card) or upload new 



## v3.3.0 - Display: Tables: Duplicate Warning 
dedupe or separate import notes display.


## v3.3.1 - Display: Tables: Collapse Table 
Show Icon to Open table display 
Table Name 
TH 
3 rows ...
when closed 

Show Icon to Close table display 
Table Name 
TH 
ALL rows
when open 

## v3.3.2 - Display: Tables: Sorting 
Flags, Non-P&L <th> Sort 


## v3.4.0 - Display: Year Select 
in Summary if multiple years deteched ask which year to use and/or time frame in case fiscal year is not calendar year or the user need a snapshot for the quarter or custom time frame. 
Expose Year Select in the upload flow if multi year is uploaded 
foundation for full account upload with expense and income and multiple years 

## v later
standardize your P&L category order and naming, so COGS, operating expenses, and later maybe Other Income / Other Expense display in a fixed order instead of just by amount.

Next after this, the right cleanup is fixed P&L line ordering so expenses display in an accounting order instead of by largest amount.

## v later
There is also a still-open app-level nav inconsistency: Summary links to /categories, but the sidebar still has no Categories item in base.html.

============================== Working ===============================

## v3.1.2 - Display: P&L: Total and Bottom Line Styling 

## v3.1.1 - Display: P&L: Add in COGS for proper P&L Structure 

## v3.1.0 - Display: P&L: Format & Display
Income Should display above Expenses
Income should be its own table 
Expenses should be its own table 



=============================== Commited =============================

## v3.0.1 - Display: Summary visible uncategorized section for review and edits

## v3.0.0 - Display: Summary Uncategorized Display Sum 
On the summary page uncategorized is listed as 0 while the results page states 
expense	Uncategorized	74344.61
Uncategorized on the summary page is not calculating 

## v3.0.0 - Display 

## v2.2.4 Bulk Edit: Save: Import landing page supports mixed, revenue, and expense multi-file imports from start
Make Upload offer the same CSV sorting for revnues upload , expense upload and keep bank upload for mixed as Add More Data does

test:
mixed only  : pass
revenue only  : pass
expense only : pass
revenue + expense together  : pass
save workspace  : pass
reopen and confirm merged result : pass

The app can now start a working file in two good ways:

Landing page
mixed CSV(s)
revenue CSV(s)
expense CSV(s)
Inside an existing workspace
Add More Data
import more revenue/expense later


## v2.2.3 Bulk Edit: Save: Imports (Add More Data and Merge/Save)
foundation for 1+ revenue and 1+ expense files later
Goal - A user should be able to:
create or open a working file
add 1 or more revenue CSVs
add 1 or more expense CSVs
merge them into the current workspace
keep editing in Bulk Edit
auto-save the merged result back to that workspace
> now
reads multiple files
normalizes each separately
forces sign by revenue or expense
stamps source tracking columns
appends into current session
rebuilds reports
auto-saves if workspace already exists
> then
imported revenue/expense file history gets written into workspace JSON
reopening a saved workspace restores that import history
later your import page can show those imported files reliably

> test this flow
click Add More Data : pass 
confirm page loads : pass with duplicates 
confirm sidebar highlights Add More Data : pass 

upload a new CSV for new workspace  : pass 
import one revenue file  : pass 
import one expense file  : pass 
confirm merged rows show in Bulk Edit and reports  : pass 

## v2.2.2 - Bulk Edit: Save: User Workspace Title Display, minor nav display fixes, save file location fix, pipeline import corrected 
User should know while workspace file they are viewing / editing after opening/load a saved file or having had uploaded a new file that was not yet saves 
Syntax: 
Saved {current file name}
Unsaved New Upload File {Warn: Save now to retain changes}
this should be at the top of all pages after a session starts so maybe in base for navigation persistence? Unless you have a better thought. 
User Flow: 
Open Working File active state: pass
Persistent saved/unsaved session banner: pass
Inline save form for unsaved uploads: pass

## v2.2.1  — Bulk Edit: Save: Working files auto save edits & reopen from landing page
Sidebar now opens saved workspaces. upload: pass bulk edit: pass save named workspace: pass open working file entry: pass auto-save after edit: pass preserved edits after reopen: pass load reports from saved edits: pass.

## v2.2.0 — Bulk Edit: Save 
Locally Save uploaded working file with Bulk Edits made

## v2.1.0 - Bulk Edit: Sort
Results, Users click: Date, Description, Amount, Category click again to reverse: asc / desc

# v2.0.0 - Bulk Edit: 
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