# v2.1.0 in progress 03.31.2026 10:31, author Danii Oliver 

from __future__ import annotations

import io
import re
import uuid

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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


DATE_ALIASES = {
    "date",
    "transactiondate",
    "transaction_date",
    "posteddate",
    "posted_date",
    "postingdate",
    "posting_date",
    "transdate",
    "txndate",
    "txn_date",
    "activitydate",
    "activity_date",
    "effectivedate",
    "effective_date",
}

DESCRIPTION_ALIASES = {
    "description",
    "merchant",
    "payee",
    "details",
    "memo",
    "name",
    "transaction",
    "transactiondescription",
    "transaction_description",
}


def _canon_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def _find_col(df: pd.DataFrame, aliases: set[str]) -> str | None:
    for col in df.columns:
        if _canon_col(col) in aliases:
            return col
    return None


def _prepare_upload_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Light pre-normalization only to help complete account history CSVs survive
    common bank/export header differences before pipeline.normalize_bank_csv().
    """
    out = df.copy()
    notes: list[str] = []

    date_col = _find_col(out, DATE_ALIASES)
    desc_col = _find_col(out, DESCRIPTION_ALIASES)

    rename_map: dict[str, str] = {}

    if date_col and date_col != "Date":
        rename_map[date_col] = "Date"
        notes.append(f"Mapped '{date_col}' → 'Date'.")

    if desc_col and desc_col != "Description":
        rename_map[desc_col] = "Description"
        notes.append(f"Mapped '{desc_col}' → 'Description'.")

    if rename_map:
        out = out.rename(columns=rename_map)

    return out, notes


def _extract_years(df: pd.DataFrame) -> tuple[list[int], str | None]:
    """
    Returns sorted distinct years plus the date column used.
    Works before pipeline normalization.
    """
    date_col = None

    if "Date" in df.columns:
        date_col = "Date"
    else:
        date_col = _find_col(df, DATE_ALIASES)

    if not date_col:
        return [], None

    parsed = pd.to_datetime(df[date_col], errors="coerce")
    years = sorted(int(y) for y in parsed.dropna().dt.year.unique().tolist())
    return years, date_col


def _filter_df_to_year(df: pd.DataFrame, year: int, date_col: str | None = None) -> pd.DataFrame:
    working = df.copy()

    if date_col is None:
        if "Date" in working.columns:
            date_col = "Date"
        else:
            date_col = _find_col(working, DATE_ALIASES)

    if not date_col:
        return working

    parsed = pd.to_datetime(working[date_col], errors="coerce")
    return working.loc[parsed.dt.year == int(year)].copy()


def _build_session_payload(
    *,
    df: pd.DataFrame,
    filename: str,
    entity_mode: str,
    upload_notes: list[str] | None = None,
    selected_year: int | None = None,
) -> dict:
    df = normalize_bank_csv(df)
    df = apply_categorization(df)
    df = detect_non_pl_items(df)

    if "_row_id" not in df.columns:
        df = df.reset_index(drop=True).copy()
        df["_row_id"] = df.index.astype(str)

    pl_by_cat, pl_by_month = build_pl_tables(df)
    flags = build_flags(df)
    forms = build_form_checklist(entity_mode=entity_mode)
    updates = fetch_tax_updates()

    warnings: list[str] = []
    if selected_year is not None:
        warnings.append(f"Report filtered to year: {selected_year}")

    if upload_notes:
        warnings.extend(upload_notes)

    return {
        "filename": filename,
        "entity_mode": entity_mode,
        "df": df,
        "pl_by_cat": pl_by_cat,
        "pl_by_month": pl_by_month,
        "flags": flags,
        "forms": forms,
        "updates": updates,
        "warnings": warnings,
        "selected_year": selected_year,
        "undo_stack": [],
        "bulk_edit_filters": {},
    }


def _rebuild_session_outputs(token: str) -> None:
    s = SESSIONS[token]
    df = s["df"].copy()

    pl_by_cat, pl_by_month = build_pl_tables(df)
    flags = build_flags(df)

    s["pl_by_cat"] = pl_by_cat
    s["pl_by_month"] = pl_by_month
    s["flags"] = flags


def _push_undo_snapshot(token: str) -> None:
    s = SESSIONS[token]
    s.setdefault("undo_stack", [])
    s["undo_stack"].append(s["df"].copy())

    if len(s["undo_stack"]) > 10:
        s["undo_stack"] = s["undo_stack"][-10:]


def _undo_last_bulk_edit(token: str) -> bool:
    s = SESSIONS[token]
    stack = s.get("undo_stack", [])
    if not stack:
        return False

    s["df"] = stack.pop()
    _rebuild_session_outputs(token)
    return True


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sources": IRS_UPDATES_SOURCES,
            "nav": "upload",
            "title": "Upload",
            "error": None,
        },
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    entity_mode: str = Form("schedule_c"),
):
    try:
        raw = await file.read()
        df = pd.read_csv(pd.io.common.BytesIO(raw))
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "sources": IRS_UPDATES_SOURCES,
                "nav": "upload",
                "title": "Upload",
                "error": f"Could not read CSV file: {exc}",
            },
            status_code=400,
        )

    prepped_df, upload_notes = _prepare_upload_df(df)
    years, detected_date_col = _extract_years(prepped_df)

    token = str(uuid.uuid4())

    if len(years) > 1:
        SESSIONS[token] = {
            "stage": "awaiting_year_selection",
            "filename": file.filename or "upload.csv",
            "entity_mode": entity_mode,
            "raw_df": prepped_df,
            "upload_notes": upload_notes,
            "years": years,
            "date_col": detected_date_col,
        }
        return RedirectResponse(url=f"/year-select?token={token}", status_code=303)

    try:
        selected_year = years[0] if len(years) == 1 else None
        working_df = (
            prepped_df
            if selected_year is None
            else _filter_df_to_year(prepped_df, selected_year, detected_date_col)
        )

        payload = _build_session_payload(
            df=working_df,
            filename=file.filename or "upload.csv",
            entity_mode=entity_mode,
            upload_notes=upload_notes,
            selected_year=selected_year,
        )
        payload["stage"] = "complete"
        SESSIONS[token] = payload

        return RedirectResponse(url=f"/summary?token={token}", status_code=303)

    except ValueError as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "sources": IRS_UPDATES_SOURCES,
                "nav": "upload",
                "title": "Upload",
                "error": str(exc),
            },
            status_code=400,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "sources": IRS_UPDATES_SOURCES,
                "nav": "upload",
                "title": "Upload",
                "error": f"Upload failed while preparing report: {exc}",
            },
            status_code=500,
        )


@app.get("/year-select", response_class=HTMLResponse)
def year_select(request: Request, token: str):
    r = SESSIONS.get(token)
    if not r:
        return RedirectResponse("/", status_code=303)

    if r.get("stage") != "awaiting_year_selection":
        return RedirectResponse(f"/summary?token={token}", status_code=303)

    return templates.TemplateResponse(
        "year_select.html",
        {
            "request": request,
            "token": token,
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "years": r["years"],
            "upload_notes": r.get("upload_notes", []),
            "nav": "upload",
            "title": "Select Year",
        },
    )


@app.post("/year-select", response_class=HTMLResponse)
async def year_select_submit(
    request: Request,
    token: str = Form(...),
    year: str = Form(...),
):
    r = SESSIONS.get(token)
    if not r:
        return RedirectResponse("/", status_code=303)

    if r.get("stage") != "awaiting_year_selection":
        return RedirectResponse(f"/summary?token={token}", status_code=303)

    raw_df = r["raw_df"]
    filename = r["filename"]
    entity_mode = r["entity_mode"]
    upload_notes = r.get("upload_notes", [])
    date_col = r.get("date_col")

    try:
        if year == "all":
            working_df = raw_df.copy()
            selected_year = None
        else:
            selected_year = int(year)
            working_df = _filter_df_to_year(raw_df, selected_year, date_col)

        payload = _build_session_payload(
            df=working_df,
            filename=filename,
            entity_mode=entity_mode,
            upload_notes=upload_notes,
            selected_year=selected_year,
        )
        payload["stage"] = "complete"
        SESSIONS[token] = payload

        return RedirectResponse(url=f"/summary?token={token}", status_code=303)

    except ValueError as exc:
        return templates.TemplateResponse(
            "year_select.html",
            {
                "request": request,
                "token": token,
                "filename": filename,
                "entity_mode": entity_mode,
                "years": r["years"],
                "upload_notes": upload_notes,
                "nav": "upload",
                "title": "Select Year",
                "error": str(exc),
            },
            status_code=400,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "year_select.html",
            {
                "request": request,
                "token": token,
                "filename": filename,
                "entity_mode": entity_mode,
                "years": r["years"],
                "upload_notes": upload_notes,
                "nav": "upload",
                "title": "Select Year",
                "error": f"Failed while building report: {exc}",
            },
            status_code=500,
        )


@app.get("/summary", response_class=HTMLResponse)
def summary(request: Request, token: str):
    r = SESSIONS.get(token)
    if not r:
        return RedirectResponse("/", status_code=303)

    if r.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = r["df"]

    uncategorized_count = 0
    if "category" in df.columns:
        uncategorized_count = int(df["category"].isna().sum() + (df["category"] == "").sum())

    date_col = next(
        (c for c in df.columns if c.lower() in ["date", "transaction_date", "posted_date", "txn_date"]),
        None,
    )

    date_min = None
    date_max = None
    if date_col:
        if pd.api.types.is_datetime64_any_dtype(df[date_col]):
            date_min = df[date_col].min().strftime("%Y-%m-%d")
            date_max = df[date_col].max().strftime("%Y-%m-%d")
        else:
            date_min = df[date_col].min()
            date_max = df[date_col].max()

    months_covered = None
    if date_col and pd.api.types.is_datetime64_any_dtype(df[date_col]):
        months_covered = int(df[date_col].dt.to_period("M").nunique())

    pl_df = df[df["is_pl_item"] == True].copy()
    total_income = float(pl_df.loc[pl_df["amount"] > 0, "amount"].sum())
    total_expenses = float(pl_df.loc[pl_df["amount"] < 0, "amount"].abs().sum())
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
            "selected_year": r.get("selected_year"),
            "warnings": r.get("warnings", []),
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

    if r.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = r["df"]

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "nav": "results",
            "token": token,
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "selected_year": r.get("selected_year"),
            "warnings": r.get("warnings", []),
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
    if payload.get("stage") == "awaiting_year_selection":
        return HTMLResponse("Please select a year before exporting.", status_code=400)

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
    if r.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "pl_annual.html",
        {
            "request": request,
            "token": token,
            "nav": "annual",
            "pl_cat": r["pl_by_cat"].to_html(index=False),
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "selected_year": r.get("selected_year"),
        },
    )


@app.get("/pl/monthly", response_class=HTMLResponse)
def pl_monthly(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    r = SESSIONS[token]
    if r.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "pl_monthly.html",
        {
            "request": request,
            "token": token,
            "nav": "monthly",
            "pl_month": r["pl_by_month"].to_html(index=False),
            "filename": r["filename"],
            "entity_mode": r["entity_mode"],
            "selected_year": r.get("selected_year"),
        },
    )


@app.get("/flags", response_class=HTMLResponse)
def flags_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    p = SESSIONS[token]
    if p.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "flags.html",
        {
            "request": request,
            "token": token,
            "nav": "flags",
            "flags": p["flags"].to_html(index=False),
        },
    )


@app.get("/non-pl", response_class=HTMLResponse)
def non_pl_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    p = SESSIONS[token]
    if p.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

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
    if p.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "token": token,
            "nav": "categories",
            "pl_cat": p["pl_by_cat"].to_html(index=False),
        },
    )


@app.get("/bulk-edit", response_class=HTMLResponse)
def bulk_edit_page(
    request: Request,
    token: str,
    q: str = "",
    category: str = "",
    tx_type: str = "",
    pl_status: str = "",
    month: str = "",
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    s = SESSIONS[token]
    if s.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = s["df"].copy()
    view = df.copy()

    if q:
        view = view[view["description"].astype(str).str.contains(q, case=False, na=False)]

    if category:
        view = view[view["category"] == category]

    if tx_type:
        view = view[view["amount"].apply(lambda x: "income" if x > 0 else "expense") == tx_type]

    if pl_status == "pl":
        view = view[view["is_pl_item"] == True]
    elif pl_status == "nonpl":
        view = view[view["is_pl_item"] == False]

    if month:
        view = view[view["month"] == month]

    categories = sorted(df["category"].dropna().astype(str).unique().tolist())
    months = sorted(df["month"].dropna().astype(str).unique().tolist())

    sort = request.query_params.get("sort", "date").strip()
    direction = request.query_params.get("dir", "desc").strip().lower()

    view = view.copy()
    view["type"] = view["amount"].apply(lambda x: "income" if x > 0 else "expense")

    sort_map = {
        "date": "date",
        "description": "description",
        "amount": "amount",
        "category": "category",
        "type": "type",
        "month": "month",
    }

    sort_col = sort_map.get(sort, "date")
    ascending = direction == "asc"

    if sort_col in ["description", "category", "type", "month"]:
        view = (
            view.assign(_sort_key=view[sort_col].fillna("").astype(str).str.lower())
            .sort_values(by="_sort_key", ascending=ascending, na_position="last")
            .drop(columns=["_sort_key"])
        )
    else:
        view = view.sort_values(by=sort_col, ascending=ascending, na_position="last").copy()

    return templates.TemplateResponse(
        "bulk_edit.html",
        {
            "request": request,
            "token": token,
            "nav": "bulk_edit",
            "rows": view.to_dict(orient="records"),
            "categories": categories,
            "months": months,
            "filters": {
                "q": q,
                "category": category,
                "tx_type": tx_type,
                "pl_status": pl_status,
                "month": month,
                "sort": sort,
                "dir": direction,
            },
        },
    )


@app.post("/bulk-edit/apply")
async def bulk_edit_apply(
    token: str = Form(...),
    action: str = Form(...),
    selected_ids: list[str] = Form([]),
    new_category: str = Form(""),
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired.", status_code=404)

    s = SESSIONS[token]

    if action == "undo":
        _undo_last_bulk_edit(token)
        return RedirectResponse(f"/bulk-edit?token={token}", status_code=303)

    if not selected_ids:
        return RedirectResponse(f"/bulk-edit?token={token}", status_code=303)

    df = s["df"].copy()
    _push_undo_snapshot(token)

    mask = df["_row_id"].astype(str).isin(selected_ids)

    if action == "set_category" and new_category:
        df.loc[mask, "category"] = new_category
        df.loc[mask, "cat_confidence"] = 1.0
        df.loc[mask, "cat_source"] = "bulk_edit"

    elif action == "mark_pl":
        df.loc[mask, "is_pl_item"] = True
        df.loc[mask, "non_pl_reason"] = ""

    elif action == "mark_non_pl":
        df.loc[mask, "is_pl_item"] = False
        df.loc[mask, "non_pl_reason"] = "User marked non-P&L"

    s["df"] = df
    _rebuild_session_outputs(token)

    return RedirectResponse(f"/bulk-edit?token={token}", status_code=303)







