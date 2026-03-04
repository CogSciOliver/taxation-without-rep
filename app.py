from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
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

# Simple in-memory store for prototype.
SESSIONS: dict[str, dict] = {}

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "sources": IRS_UPDATES_SOURCES})

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

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "token": token,
            "filename": file.filename,
            "entity_mode": entity_mode,
            "pl_cat": pl_by_cat.to_html(index=False),
            "pl_month": pl_by_month.to_html(index=False),
            "flags": flags.to_html(index=False),
            "forms": forms,
            "updates": updates,
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
