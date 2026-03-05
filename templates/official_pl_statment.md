# Note for pl_statement.html
**notes in _dev-notes/pl.md **

Official P&L a statement with a fixed, conventional order.

A standard (single-step) P&L layout is typically:

Revenue / Income (sales, services, etc.)

Cost of Goods Sold (COGS) (if applicable)

Gross Profit = Revenue − COGS

Operating Expenses (marketing, rent, software, etc.)

Operating Income = Gross Profit − Operating Expenses

Other Income / (Expense) (interest, one-offs)

Net Income (bottom line)

So yes: Revenue → COGS → Gross Profit → Expenses → Net is the core.

How to handle your “Categories” page without confusing the P&L

Right now your pl_by_cat is essentially a category summary, not a true formatted statement. That’s fine, but the page label and layout should reflect that.

You have two good options:

Option A (recommended): Keep Categories as a “Category Summary” page

Show categories grouped into sections (Income, COGS, Expenses, Other)

Within each section you may sort (optional), but the sections stay in statement order

Then show subtotals and computed lines (Gross Profit, Net)

Option B: Make Categories page literally the “Annual P&L” statement

Then it’s no longer “Categories”; it’s “Annual P&L”

Categories become the line items under Income/COGS/Expenses

What you’ll eventually need (the “ultimate format”)

You’ll need a category taxonomy with a display order, e.g.:

statement_section: income | cogs | expense | other

statement_line: human label (e.g., “Software subscriptions”)

statement_order: numeric (so you can enforce the standard layout)

optional rollups (e.g., “Marketing” rollup containing Ads + Sponsorships)

Then your pipeline builds the statement in that fixed order and inserts computed rows:

Gross Profit

Total Expenses

Net Income

The key takeaway for right now

Don’t sort the P&L by magnitude.
Instead, when you’re ready, we’ll implement a fixed statement layout driven by your category map.

When you get to the step where you “share the deeper category list you’ve been using,” that’s exactly the artifact we’ll use to power the final P&L format (with correct sections + ordering + rollups).

If you want to stay on-task today without changing your established steps: keep the Categories page as a simple table for now, and we’ll upgrade it into a proper statement once you paste your category list.

```
## P&L Statement Structure

Sections (fixed order)

1. Revenue / Income
2. Cost of Goods Sold (COGS)
3. Gross Profit (calculated)
4. Operating Expenses
5. Operating Income (calculated)
6. Other Income / Expense
7. Net Income (calculated)

Categories must map to a statement section + display order.
```

```
CATEGORY_MAP = {
    "Consulting Income": {"section": "income", "order": 1},
    "Product Sales": {"section": "income", "order": 2},
    "Merchant Fees": {"section": "cogs", "order": 10},
    "Software": {"section": "expense", "order": 30},
    "Travel": {"section": "expense", "order": 31},
}
```
