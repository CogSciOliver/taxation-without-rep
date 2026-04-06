# app.py WORK IN PROGRESS, author Danii Oliver
# v3.3.0 Display: Branding Update 04.02.2026 08:54 

from __future__ import annotations

import io
import re
import uuid
import json

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from html import escape

from pipeline import (
    normalize_bank_csv,
    initialize_workspace_columns,
    apply_source_group_sign,
    apply_categorization,
    detect_non_pl_items,
    build_pl_tables,
    build_flags,
    build_form_checklist,
    export_workbook,
)

from tax_updates import fetch_tax_updates, IRS_UPDATES_SOURCES
from pathlib import Path
from datetime import datetime
from starlette.requests import Request


app = FastAPI()
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

STANDARD_PL_STRUCTURE = {
    "income": [
        "Sales",
        "Service Income",
        "Other Income",
    ],
    "expense": [
        "Advertising",
        "Bank Fees",
        "Car & Truck",
        "Commissions & Fees",
        "Contract Labor",
        "Cost of Goods Sold",
        "Direct Labor",
        "Furniture, Fixtures, and Equipment",
        "Insurance",
        "Interest",
        "Inventory",
        "Legal & Professional",
        "Materials",
        "Meals",
        "Office and Operational",
        "Other",
        "Packaging",
        "Personnel Costs",
        "Professional Fees",
        "Rent/Lease",
        "Repairs & Maintenance",
        "Startup Costs",
        "Supplies",
        "Taxes & Licenses",
        "Travel and Vehicles",
        "Uncategorized",
        "Utilities",
    ],
}

WORKSPACES_DIR = Path("data/workspaces")
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

def _get_uncategorized_count(df: pd.DataFrame) -> int:
    if "category" not in df.columns:
        return 0

    category_series = df["category"].fillna("").astype(str).str.strip()
    return int(
        (category_series == "").sum()
        + (category_series.str.lower() == "uncategorized").sum()
    )

def template_shared_context(request: Request) -> dict:
    token = request.query_params.get("token")
    uncategorized_count = 0

    if token and token in SESSIONS:
        sess = SESSIONS[token]
        df = sess.get("df")
        if isinstance(df, pd.DataFrame):
            uncategorized_count = _get_uncategorized_count(df)

    return {
        "nav_uncategorized_count": uncategorized_count,
    }

templates = Jinja2Templates(
    directory="templates",
    context_processors=[template_shared_context],
)

# Create and Save Local Workspace Functions
# =============================================

def _slugify_workspace_name(name: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower())
    return text.strip("-") or "workspace"


def _workspace_path(name: str) -> Path:
    return WORKSPACES_DIR / f"{_slugify_workspace_name(name)}.json"


def _serialize_df(df: pd.DataFrame) -> list[dict]:
    serial = df.copy()

    if "date" in serial.columns:
        serial["date"] = pd.to_datetime(serial["date"], errors="coerce")
        serial["date"] = serial["date"].dt.strftime("%Y-%m-%d")

    return serial.to_dict(orient="records")


def _deserialize_df(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df


def save_workspace(name: str, session_payload: dict) -> str:
    path = _workspace_path(name)
    df = session_payload["df"].copy()

    payload = {
        "workspace_name": name,
        "filename": session_payload.get("filename", ""),
        "entity_mode": session_payload.get("entity_mode", "schedule_c"),
        "selected_year": session_payload.get("selected_year"),
        "warnings": session_payload.get("warnings", []),
        "imported_files": session_payload.get("imported_files", []),
        "updated_at": datetime.now().isoformat(),
        "df": _serialize_df(df),
    }

    path.write_text(json.dumps(payload, indent=2))
    return str(path)


def load_workspace(name: str) -> dict:
    path = _workspace_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Workspace not found: {name}")

    payload = json.loads(path.read_text())
    df = _deserialize_df(payload.get("df", []))

    if "_row_id" not in df.columns:
        df = df.reset_index(drop=True).copy()
        df["_row_id"] = df.index.astype(str)

    pl_by_cat, pl_by_month = build_pl_tables(df)
    flags = build_flags(df)
    forms = build_form_checklist(entity_mode=payload.get("entity_mode", "schedule_c"))
    updates = fetch_tax_updates()

    return {
        "stage": "complete",
        "workspace_name": payload.get("workspace_name", name),
        "filename": payload.get("filename", f"{name}.json"),
        "entity_mode": payload.get("entity_mode", "schedule_c"),
        "selected_year": payload.get("selected_year"),
        "warnings": payload.get("warnings", []),
        "imported_files": payload.get("imported_files", []),
        "df": df,
        "pl_by_cat": pl_by_cat,
        "pl_by_month": pl_by_month,
        "flags": flags,
        "forms": forms,
        "updates": updates,
        "undo_stack": [],
        "bulk_edit_filters": {},
    }


def list_workspaces() -> list[str]:
    return sorted([p.stem for p in WORKSPACES_DIR.glob("*.json")])

# =============================================
# End Create and Save Local Workspace Functions



# Create P&L Tables, Styles, Flags, and Form Checklist Functions
# =============================================

def _render_pl_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""

    display_df = df.copy()

    def tr_class(label: str) -> str:
        label = str(label).strip().lower()

        if label in {"gross profit", "net profit"}:
            return "pl-row-final"
        if label.startswith("total "):
            return "pl-row-total"
        return ""

    rows = []
    for _, row in display_df.iterrows():
        row_class = tr_class(row.get("category", ""))
        category = escape(str(row.get("category", "")))
        total = f"{float(row.get('total', 0)):,.2f}"

        rows.append(
            f'<tr class="{row_class}">'
            f"<td>{category}</td>"
            f"<td>{total}</td>"
            f"</tr>"
        )

    return (
        '<table class="data-table pl-table">'
        "<thead>"
        "<tr><th>Category</th><th>Total</th></tr>"
        "</thead>"
        "<tbody>"
        + "".join(rows) +
        "</tbody>"
        "</table>"
    )

# =============================================
# End P&L Tables, Styles, Flags, and Form Checklist Functions

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
    df = initialize_workspace_columns(df)
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
        "workspace_name": None,
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
        "imported_files": [],
    }


async def _import_files_into_session(
    *,
    token: str,
    files: list[UploadFile],
    source_group: str,
) -> list[str]:
    session = SESSIONS[token]
    existing_df = session["df"].copy()
    import_notes: list[str] = []
    batch_id = str(uuid.uuid4())

    for file in files:
        raw = await file.read()

        try:
            incoming_df = pd.read_csv(pd.io.common.BytesIO(raw))
        except Exception as exc:
            import_notes.append(f"Could not read {file.filename or 'upload.csv'}: {exc}")
            continue

        try:
            prepped_df, upload_notes = _prepare_upload_df(incoming_df)

            incoming_df = normalize_bank_csv(prepped_df)
            incoming_df = initialize_workspace_columns(incoming_df)
            incoming_df = apply_source_group_sign(incoming_df, source_group)
            incoming_df = apply_categorization(incoming_df)
            incoming_df = detect_non_pl_items(incoming_df)

            incoming_df["source_group"] = source_group
            incoming_df["source_file"] = file.filename or "upload.csv"
            incoming_df["import_batch_id"] = batch_id
            incoming_df["source_kind"] = f"{source_group}_import"

            existing_df = pd.concat([existing_df, incoming_df], ignore_index=True)

            import_notes.append(
                f"Imported {len(incoming_df)} rows from {file.filename or 'upload.csv'} as {source_group}."
            )

            if upload_notes:
                import_notes.extend(upload_notes)

        except Exception as exc:
            import_notes.append(f"Failed to import {file.filename or 'upload.csv'}: {exc}")

    existing_df = existing_df.reset_index(drop=True).copy()
    existing_df["_row_id"] = existing_df.index.astype(str)

    session["df"] = existing_df
    session.setdefault("warnings", [])
    session["warnings"].extend(import_notes)

    imported_files = session.setdefault("imported_files", [])
    for file in files:
        imported_files.append(
            {
                "name": file.filename or "upload.csv",
                "group": source_group,
                "batch_id": batch_id,
            }
        )

    _rebuild_session_outputs(token)

    workspace_name = session.get("workspace_name")
    if workspace_name:
        save_workspace(workspace_name, session)

    return import_notes


async def _build_df_from_uploaded_files(
    *,
    files: list[UploadFile],
    source_group: str | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    merged_df = pd.DataFrame()
    notes: list[str] = []
    batch_id = str(uuid.uuid4())

    for file in files:
        raw = await file.read()

        try:
            incoming_df = pd.read_csv(pd.io.common.BytesIO(raw))
        except Exception as exc:
            notes.append(f"Could not read {file.filename or 'upload.csv'}: {exc}")
            continue

        try:
            prepped_df, upload_notes = _prepare_upload_df(incoming_df)

            incoming_df = normalize_bank_csv(prepped_df)
            incoming_df = initialize_workspace_columns(incoming_df)

            if source_group:
                incoming_df = apply_source_group_sign(incoming_df, source_group)
                incoming_df["source_group"] = source_group
                incoming_df["source_kind"] = f"{source_group}_import"
            else:
                incoming_df["source_kind"] = "mixed_upload"

            incoming_df = apply_categorization(incoming_df)
            incoming_df = detect_non_pl_items(incoming_df)

            incoming_df["source_file"] = file.filename or "upload.csv"
            incoming_df["import_batch_id"] = batch_id

            merged_df = pd.concat([merged_df, incoming_df], ignore_index=True)

            notes.append(f"Loaded {len(incoming_df)} rows from {file.filename or 'upload.csv'}.")
            if upload_notes:
                notes.extend(upload_notes)

        except Exception as exc:
            notes.append(f"Failed to process {file.filename or 'upload.csv'}: {exc}")

    if merged_df.empty:
        raise ValueError("No valid CSV rows were loaded from the selected files.")

    merged_df = merged_df.reset_index(drop=True).copy()
    merged_df["_row_id"] = merged_df.index.astype(str)

    return merged_df, notes


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


def _get_uncategorized_count(df: pd.DataFrame) -> int:
    if "category" not in df.columns:
        return 0

    category_series = df["category"].fillna("").astype(str).str.strip()
    return int(
        (category_series == "").sum()
        + (category_series.str.lower() == "uncategorized").sum()
    )


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


@app.post("/upload/start", response_class=HTMLResponse)
async def upload_start(
    request: Request,
    mixed_files: list[UploadFile] = File([]),
    revenue_files: list[UploadFile] = File([]),
    expense_files: list[UploadFile] = File([]),
    entity_mode: str = Form("schedule_c"),
):
    has_mixed = any(f.filename for f in mixed_files)
    has_revenue = any(f.filename for f in revenue_files)
    has_expense = any(f.filename for f in expense_files)

    if not (has_mixed or has_revenue or has_expense):
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "sources": IRS_UPDATES_SOURCES,
                "nav": "upload",
                "title": "Upload",
                "error": "Select at least one CSV file to start.",
            },
            status_code=400,
        )

    try:
        all_frames = []
        all_notes = []

        if has_mixed:
            mixed_df, mixed_notes = await _build_df_from_uploaded_files(
                files=[f for f in mixed_files if f.filename],
                source_group=None,
            )
            all_frames.append(mixed_df)
            all_notes.extend(mixed_notes)

        if has_revenue:
            revenue_df, revenue_notes = await _build_df_from_uploaded_files(
                files=[f for f in revenue_files if f.filename],
                source_group="revenue",
            )
            all_frames.append(revenue_df)
            all_notes.extend(revenue_notes)

        if has_expense:
            expense_df, expense_notes = await _build_df_from_uploaded_files(
                files=[f for f in expense_files if f.filename],
                source_group="expense",
            )
            all_frames.append(expense_df)
            all_notes.extend(expense_notes)

        df = pd.concat(all_frames, ignore_index=True).reset_index(drop=True)
        df["_row_id"] = df.index.astype(str)

        token = str(uuid.uuid4())

        pl_by_cat, pl_by_month = build_pl_tables(df)
        flags = build_flags(df)
        forms = build_form_checklist(entity_mode=entity_mode)
        updates = fetch_tax_updates()

        SESSIONS[token] = {
            "stage": "complete",
            "workspace_name": None,
            "filename": "File(s) Uploaded At Start",
            "entity_mode": entity_mode,
            "df": df,
            "pl_by_cat": pl_by_cat,
            "pl_by_month": pl_by_month,
            "flags": flags,
            "forms": forms,
            "updates": updates,
            "warnings": all_notes,
            "selected_year": None,
            "undo_stack": [],
            "bulk_edit_filters": {},
            "imported_files": [],
        }

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
    sess = SESSIONS.get(token)
    if not sess:
        return RedirectResponse("/", status_code=303)

    if sess.get("stage") != "awaiting_year_selection":
        return RedirectResponse(f"/summary?token={token}", status_code=303)

    return templates.TemplateResponse(
        "year_select.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "entity_mode": sess["entity_mode"],
            "years": sess["years"],
            "upload_notes": sess.get("upload_notes", []),
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
    sess = SESSIONS.get(token)
    if not sess:
        return RedirectResponse("/", status_code=303)

    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = sess["df"]

    uncategorized_count = 0
    if "category" in df.columns:
        category_series = df["category"].fillna("").astype(str).str.strip()
        uncategorized_count = int(
            (category_series == "").sum()
            + (category_series.str.lower() == "uncategorized").sum()
        )
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
        "flag_count": int(len(sess["flags"])) if sess.get("flags") is not None else 0,
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
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "kpis": kpis,
            "forms": sess["forms"],
            "updates": sess["updates"],
            "entity_mode": sess["entity_mode"],
            "selected_year": sess.get("selected_year"),
            "warnings": sess.get("warnings", []),
            "pl_cat": sess["pl_by_cat"].to_html(index=False),
            "pl_monthly": sess["pl_by_month"].to_html(index=False),
            "flags": sess["flags"].to_html(index=False),
            "non_pl": df[df["is_pl_item"] == False].head(200).to_html(index=False),
        },
    )


@app.get("/results", response_class=HTMLResponse)
def results(request: Request, token: str):
    sess = SESSIONS.get(token)
    if not sess:
        return RedirectResponse("/", status_code=303)

    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = sess["df"]

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "nav": "results",
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "entity_mode": sess["entity_mode"],
            "selected_year": sess.get("selected_year"),
            "warnings": sess.get("warnings", []),
            "pl_cat": sess["pl_by_cat"].to_html(index=False),
            "pl_month": sess["pl_by_month"].to_html(index=False),
            "flags": sess["flags"].to_html(index=False),
            "forms": sess["forms"],
            "updates": sess["updates"],
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

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    pl_cat_df = sess["pl_by_cat"].copy()

    COGS_CATEGORIES = {
        "cost of goods sold",
        "cogs",
        "inventory",
        "materials",
        "packaging",
        "direct labor",
    }

    income_df = (
        pl_cat_df[pl_cat_df["type"] == "income"]
        .drop(columns=["type"], errors="ignore")
        .sort_values(["total", "category"], ascending=[False, True])
        .reset_index(drop=True)
    )

    expense_rows = pl_cat_df[pl_cat_df["type"] == "expense"].copy()
    expense_rows["_category_key"] = (
        expense_rows["category"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    cogs_df = (
        expense_rows[expense_rows["_category_key"].isin(COGS_CATEGORIES)]
        .drop(columns=["type", "_category_key"], errors="ignore")
        .sort_values(["total", "category"], ascending=[False, True])
        .reset_index(drop=True)
    )

    expense_df = (
        expense_rows[~expense_rows["_category_key"].isin(COGS_CATEGORIES)]
        .drop(columns=["type", "_category_key"], errors="ignore")
        .sort_values(["total", "category"], ascending=[False, True])
        .reset_index(drop=True)
    )

    total_income = round(float(income_df["total"].sum()), 2) if not income_df.empty else 0.0
    total_cogs = round(float(cogs_df["total"].sum()), 2) if not cogs_df.empty else 0.0
    total_expenses = round(float(expense_df["total"].sum()), 2) if not expense_df.empty else 0.0

    gross_profit = round(total_income - total_cogs, 2)
    net_profit = round(gross_profit - total_expenses, 2)

    income_display = pd.concat(
        [
            income_df,
            pd.DataFrame([{"category": "Total Revenue", "total": total_income}]),
        ],
        ignore_index=True,
    )

    cogs_display = pd.concat(
        [
            cogs_df,
            pd.DataFrame(
                [
                    {"category": "Total Cost of Goods Sold", "total": total_cogs},
                    {"category": "Gross Profit", "total": gross_profit},
                ]
            ),
        ],
        ignore_index=True,
    )

    expense_display = pd.concat(
        [
            expense_df,
            pd.DataFrame(
                [
                    {"category": "Total Expenses", "total": total_expenses},
                    {"category": "Net Profit", "total": net_profit},
                ]
            ),
        ],
        ignore_index=True,
    )

    return templates.TemplateResponse(
        "pl_annual.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "annual",
            "entity_mode": sess["entity_mode"],
            "selected_year": sess.get("selected_year"),
            
            "income_table": _render_pl_table(income_display),
            "cogs_table": _render_pl_table(cogs_display),
            "expense_table": _render_pl_table(expense_display),
            
            "total_income": total_income,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
        },
    )


@app.get("/pl/monthly", response_class=HTMLResponse)
def pl_monthly(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "pl_monthly.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "monthly",
            "pl_month": sess["pl_by_month"].to_html(index=False),
            "entity_mode": sess["entity_mode"],
            "selected_year": sess.get("selected_year"),
        },
    )


@app.get("/flags", response_class=HTMLResponse)
def flags_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "flags.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "flags",
            "flags": sess["flags"].to_html(index=False),
        },
    )


@app.get("/non-pl", response_class=HTMLResponse)
def non_pl_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = sess["df"]

    return templates.TemplateResponse(
        "non_pl.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "nonpl",
            "non_pl": df[df["is_pl_item"] == False].to_html(index=False),
        },
    )


    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "categories",
            "pl_cat": sess["pl_by_cat"].to_html(index=False),
        },
    )



@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = sess["df"].copy()
    pl_view = df[df["is_pl_item"] == True].copy()
    pl_view["type"] = pl_view["amount"].apply(lambda x: "income" if x > 0 else "expense")
    pl_view["abs_amount"] = pl_view["amount"].abs()

    grouped = (
        pl_view.groupby(["type", "category"], as_index=False)["abs_amount"]
        .sum()
        .rename(columns={"abs_amount": "total"})
    )

    totals_map = {
        (row["type"], row["category"]): float(row["total"])
        for _, row in grouped.iterrows()
    }

    existing_by_type = {
        "income": sorted(
            grouped.loc[grouped["type"] == "income", "category"].dropna().astype(str).unique(),
            key=str.lower,
        ),
        "expense": sorted(
            grouped.loc[grouped["type"] == "expense", "category"].dropna().astype(str).unique(),
            key=str.lower,
        ),
    }

    rows = []
    for tx_type in ["income", "expense"]:
        category_names = sorted(
            set(STANDARD_PL_STRUCTURE.get(tx_type, [])) | set(existing_by_type.get(tx_type, [])),
            key=str.lower,
        )
        for category in category_names:
            rows.append(
                {
                    "type": tx_type,
                    "category": category,
                    "total": round(float(totals_map.get((tx_type, category), 0.0)), 2),
                }
            )

    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "categories",
            "selected_year": sess.get("selected_year"),
            "rows": rows,
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

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    df = sess["df"].copy()
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
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
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
    q: str = Form(""),
    category: str = Form(""),
    tx_type: str = Form(""),
    pl_status: str = Form(""),
    month: str = Form(""),
    sort: str = Form("date"),
    dir: str = Form("desc"),
    return_to: str = Form("bulk_edit"),
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired.", status_code=404)

    sess = SESSIONS[token]

    def _return_url():
        base = "/uncategorized" if return_to == "uncategorized" else "/bulk-edit"
        return (
            f"{base}?token={token}"
            f"&q={q}"
            f"&category={category}"
            f"&tx_type={tx_type}"
            f"&pl_status={pl_status}"
            f"&month={month}"
            f"&sort={sort}"
            f"&dir={dir}"
        )

    if action == "undo":
        _undo_last_bulk_edit(token)
        return RedirectResponse(f"/bulk-edit?token={token}", status_code=303)

    if not selected_ids:
        return RedirectResponse(f"/bulk-edit?token={token}", status_code=303)

    df = sess["df"].copy()
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

    sess["df"] = df
    _rebuild_session_outputs(token)

    workspace_name = sess.get("workspace_name")
    if workspace_name:
        save_workspace(workspace_name, sess)

    return RedirectResponse(_return_url(), status_code=303)


@app.get("/uncategorized", response_class=HTMLResponse)
def uncategorized_page(
    request: Request,
    token: str,
    q: str = "",
    tx_type: str = "",
    pl_status: str = "",
    month: str = "",
):
    return bulk_edit_page(
        request=request,
        token=token,
        q=q,
        category="Uncategorized",
        tx_type=tx_type,
        pl_status=pl_status,
        month=month,
    )


# NEW V2.0.0 FEATURE ROUTES START HERE

@app.post("/workspace/save")
async def workspace_save(
    token: str = Form(...),
    workspace_name: str = Form(...),
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired.", status_code=404)

    save_workspace(workspace_name, SESSIONS[token])
    SESSIONS[token]["workspace_name"] = workspace_name
    return RedirectResponse(f"/summary?token={token}", status_code=303)

@app.get("/workspace/open", response_class=HTMLResponse)
def workspace_open_page(request: Request):
    return templates.TemplateResponse(
        "workspace_open.html",
        {
            "request": request,
            "nav": "workspace_open",
            "title": "Open Working File",
            "workspaces": list_workspaces(),
        },
    )


@app.post("/workspace/load")
async def workspace_load(
    workspace_name: str = Form(...),
):
    payload = load_workspace(workspace_name)
    token = str(uuid.uuid4())
    SESSIONS[token] = payload
    return RedirectResponse(f"/summary?token={token}", status_code=303)


@app.get("/workspace/import", response_class=HTMLResponse)
def workspace_import_page(request: Request, token: str):
    if token not in SESSIONS:
        return HTMLResponse("Session expired. Re-upload.", status_code=404)

    sess = SESSIONS[token]
    if sess.get("stage") == "awaiting_year_selection":
        return RedirectResponse(f"/year-select?token={token}", status_code=303)

    return templates.TemplateResponse(
        "workspace_import.html",
        {
            "request": request,
            "token": token,
            "workspace_name": sess.get("workspace_name"),
            "filename": sess.get("filename"),
            "nav": "workspace_import",
            "entity_mode": sess["entity_mode"],
            "selected_year": sess.get("selected_year"),
            "warnings": sess.get("warnings", []),
            "imported_files": sess.get("imported_files", []),
        },
    )

@app.post("/workspace/import/revenue")
async def workspace_import_revenue(
    token: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired.", status_code=404)

    await _import_files_into_session(
        token=token,
        files=files,
        source_group="revenue",
    )
    return RedirectResponse(f"/workspace/import?token={token}", status_code=303)

@app.post("/workspace/import/expense")
async def workspace_import_expense(
    token: str = Form(...),
    files: list[UploadFile] = File(...),
):
    if token not in SESSIONS:
        return HTMLResponse("Session expired.", status_code=404)

    await _import_files_into_session(
        token=token,
        files=files,
        source_group="expense",
    )
    return RedirectResponse(f"/workspace/import?token={token}", status_code=303)


# END NEW V2.0.0 FEATURE ROUTES HERE



