# TaxPL App v2 (Prototype)

FastAPI prototype that:
- uploads a bank CSV
- normalizes + categorizes transactions (rules + vendor map)
- detects likely transfers / non-P&L items
- produces P&L (by month + by category), flags, and a tax-form checklist
- exports an Excel workbook

## Install
pip install -r requirements.txt

## Run
uvicorn app:app --reload

Open: http://127.0.0.1:8000
