## Rule editor UI
- Click transaction → reclassify → auto-create a vendor rule
- Persist vendor_map + rules in SQLite

## Better transfer matching
- Match equal/opposite amounts across accounts within a time window
- Detect “split payments” and “sweep transfers”
ie Chase CSV importer, Amex importer, Stripe payouts importer, Auto transfer matching

## True tax-line mapping per entity
- Schedule C line mapping
- 1120-S buckets + payroll prompts
- 990 functional expense mapping (program/admin/fundraising)
- 501(d) “member allocation pack” (exportable statements)

## Audit-grade substantiation workflow
- Receipt upload
- Business purpose notes
- Meals/travel substantiation prompts

## Importer library
- Plug-ins for Chase / Amex / Stripe / Square / PayPal exports
- Normalize all to the same schema

- one major error I see is the Expenses are listed as type:income when they are expenses 
- I also need a deeper category list I will share the one I have been using when we get there, please remember to ask me for that 
- I need a P&L page for the annual report not just the monthly I envision this a an option tab in a left sidebar where other feature options will live