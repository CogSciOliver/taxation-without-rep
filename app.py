from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import io
import uuid
import pandas as pd

from pipeline import (
    normalize_bank_csv,
    apply_categorization,
    detect_non_pl_items,
    build_pl_tables,
    build_flags,
    build_form_checklist,
    export_workbook,
)
from tax_updates import fetch_tax_updates, IRS_UPDATES_SOURCES


app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# Simple in-memory store for prototype.
SESSIONS: dict[str, dict] = {}

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "sources": IRS_UPDATES_SOURCES,"nav": "upload", "title": "Upload"})

@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    entity_mode: str = Form("schedule_c"),
):
    raw = await file.read()
    df = pd.read_csv(pd.io.common.BytesIO(raw))

    df = normalize_bank_csv(df)
    df = apply_categorization(df)
    df = detect_non_pl_items(df)

    pl_by_cat, pl_by_month = build_pl_tables(df)
    flags = build_flags(df)
    forms = build_form_checklist(entity_mode=entity_mode)

    updates = fetch_tax_updates()

    token = str(uuid.uuid4())
    SESSIONS[token] = {
        "filename": file.filename,
        "entity_mode": entity_mode,
        "df": df,
        "pl_by_cat": pl_by_cat,
        "pl_by_month": pl_by_month,
        "flags": flags,
        "forms": forms,
        "updates": updates,
    }
    
    return RedirectResponse(url=f"/summary?token={token}", status_code=303)

@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, token: str):
    r = SESSIONS.get(token)
    if not r:
        return RedirectResponse("/", status_code=303)

    df = r["df"]
    
    # Uncategorized count
    uncategorized_count = 0
    if "category" in df.columns:
        uncategorized_count = int(
            df["category"].isna().sum() +
            (df["category"] == "").sum()
        )

    # Date range (detect common date column names)
    date_col = next((c for c in df.columns if c.lower() in ["date", "transaction_date", "posted_date", "txn_date"]), None)
    date_min = None
    date_max = None
    if date_col:
        # If datetime, format nicely; otherwise keep raw min/max
        if pd.api.types.is_datetime64_any_dtype(df[date_col]):
            date_min = df[date_col].min().strftime("%Y-%m-%d")
            date_max = df[date_col].max().strftime("%Y-%m-%d")
        else:
            date_min = df[date_col].min()
            date_max = df[date_col].max()

    # Months covered (only if datetime)
    months_covered = None
    if date_col and pd.api.types.is_datetime64_any_dtype(df[date_col]):
        months_covered = int(df[date_col].dt.to_period("M").nunique())

    # Basic KPIs 
    total_income = float(df.loc[df["type"] == "income", "amount"].sum()) if "type" in df.columns else 0.0
    total_expenses = float(df.loc[df["type"] == "expense", "amount"].sum()) if "type" in df.columns else 0.0
    net_profit = total_income - total_expenses

    kpis = {
        "txn_count": int(len(df)),
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "net_profit": round(net_profit, 2),
        "flag_count": int(len(r["flags"])) if r.get("flags") is not None else 0,
        "non_pl_count": int((df["is_pl_item"] == False).sum()) if "is_pl_item" in df.columns else 0,
        "uncategorized_count": uncategorized_count,
        "date_min": date_min,
        "date_max": date_max,
        "months_covered": months_covered,
    }

    return templates.TemplateResponse(
        "summary.html",
        {
            "request": request,
            "nav": "summary",
            "token": token,
            "kpis": kpis,
            "forms": r["forms"],
            "updates": r["updates"],
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "pl_cat": r["pl_by_cat"].to_html(index=False),
            "pl_monthly": r["pl_by_month"].to_html(index=False),
            "flags": r["flags"].to_html(index=False),
            "non_pl": df[df["is_pl_item"] == False].head(200).to_html(index=False),
        },
    )

@app.get("/results", response_class=HTMLResponse)
def results(request: Request, token: str):
    r = SESSIONS.get(token)
    if not r:
        return RedirectResponse("/", status_code=303)

    df = r["df"]

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "nav": "results",
            "token": token,
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "pl_cat": r["pl_by_cat"].to_html(index=False),
            "pl_month": r["pl_by_month"].to_html(index=False),
            "flags": r["flags"].to_html(index=False),
            "forms": r["forms"],
            "updates": r["updates"],
            "non_pl": df[df["is_pl_item"] == False].head(200).to_html(index=False),
        },
    )

@app.get("/export.xlsx")
def export_xlsx(token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired or token not found. Re-upload your CSV.", status_code=404)

    payload = SESSIONS[token]
    wb_bytes = export_workbook(
        df=payload["df"],
        pl_by_cat=payload["pl_by_cat"],
        pl_by_month=payload["pl_by_month"],
        flags=payload["flags"],
        forms=payload["forms"],
        entity_mode=payload["entity_mode"],
        filename=payload["filename"],
        updates=payload["updates"],
    )

    bio = io.BytesIO(wb_bytes)
    bio.seek(0)
    out_name = "taxpl_export.xlsx"
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )

@app.get("/pl/annual", response_class=HTMLResponse)
def pl_annual(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)
    r = SESSIONS[token]
    return templates.TemplateResponse("pl_annual.html", {
        "request": request,
        "token": token,
        "nav": "annual",
        "pl_cat": r["pl_by_cat"].to_html(index=False),
        "filename": r["filename"],
        "entity_mode": r["entity_mode"],
    })

@app.get("/pl/monthly", response_class=HTMLResponse)
def pl_monthly(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)
    r = SESSIONS[token]
    return templates.TemplateResponse("pl_monthly.html", {
        "request": request,
        "token": token,
        "nav": "monthly",
        "pl_month": r["pl_by_month"].to_html(index=False),
        "filename": r["filename"],
        "entity_mode": r["entity_mode"],
    })

@app.get("/flags", response_class=HTMLResponse)
def flags_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)
    p = SESSIONS[token]
    return templates.TemplateResponse("flags.html", {
        "request": request,
        "token": token,
        "nav": "flags",
        "flags": p["flags"].to_html(index=False),
    })

@app.get("/non-pl", response_class=HTMLResponse)
def non_pl_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    p = SESSIONS[token]
    df = p["df"]

    return templates.TemplateResponse(
        "non_pl.html",
        {
            "request": request,
            "token": token,
            "nav": "nonpl",
            "non_pl": df[df["is_pl_item"] == False].to_html(index=False),
        },
    )

@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    p = SESSIONS[token]

    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "token": token,
            "nav": "categories",
            "pl_cat": p["pl_by_cat"].to_html(index=False),
        },
    )