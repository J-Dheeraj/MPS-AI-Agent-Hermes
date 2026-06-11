#!/usr/bin/env python3
"""
MPS CRM Bridge — MCP Server
============================
Connects Hermes Agent to your MPS case management system via the
Model Context Protocol (MCP). Supports five backends:

  CRM_BACKEND=sqlite        Local SQLite file (default — no infrastructure needed)
  CRM_BACKEND=google_sheets Google Sheets spreadsheet
  CRM_BACKEND=rest_api      Any REST API (generic JSON)
  CRM_BACKEND=sharepoint    Microsoft SharePoint / SharePoint Online lists
  CRM_BACKEND=csv           Plain CSV files (read-only, for legacy exports)

Set the backend and its credentials in .env (see bottom of this file
for the full .env reference). Then wire this server into each Hermes
profile's config.yaml under mcp.servers.

Install:
  pip install fastmcp python-dotenv requests gspread google-auth \
              Office365-REST-Python-Client

Run:
  python mcp-crm-server.py            # stdio mode (default)
  python mcp-crm-server.py --http     # HTTP mode on MCP_PORT (default 8000)
"""

import os
import sys
import json
import base64
import hashlib
import hmac
import logging
import sqlite3
import datetime
import time
import csv
import io
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MPS-CRM] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mps-crm")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND = os.getenv("CRM_BACKEND", "sqlite").lower().strip()
DATA_DIR = Path(os.getenv("CRM_DATA_DIR", "~/mps-hermes/crm-data")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite
SQLITE_PATH = DATA_DIR / os.getenv("CRM_SQLITE_FILE", "mps-cases.db")

# Google Sheets
GSHEET_SPREADSHEET_ID   = os.getenv("CRM_GSHEET_ID", "")
GSHEET_CREDENTIALS_JSON = os.getenv("CRM_GSHEET_CREDENTIALS", str(DATA_DIR / "gsheet-credentials.json"))

# REST API
REST_BASE_URL   = os.getenv("CRM_REST_BASE_URL", "")
REST_API_KEY    = os.getenv("CRM_REST_API_KEY", "")
REST_API_HEADER = os.getenv("CRM_REST_API_HEADER", "X-API-Key")

# SharePoint
SP_SITE_URL      = os.getenv("CRM_SP_SITE_URL", "")
SP_CLIENT_ID     = os.getenv("CRM_SP_CLIENT_ID", "")
SP_CLIENT_SECRET = os.getenv("CRM_SP_CLIENT_SECRET", "")
SP_LIST_NAME     = os.getenv("CRM_SP_LIST_NAME", "MPS Cases")

# CSV
CSV_CASES_PATH   = Path(os.getenv("CRM_CSV_CASES",   str(DATA_DIR / "cases.csv")))
CSV_LETTERS_PATH = Path(os.getenv("CRM_CSV_LETTERS", str(DATA_DIR / "letters.csv")))

# Writes are disabled unless an operator explicitly selects approval_required.
# The bridge only receives the verification secret; agents have no tool that
# can mint approval tokens.
WRITE_MODE = os.getenv("CRM_WRITE_MODE", "disabled").lower().strip()
APPROVAL_SECRET = os.getenv("CRM_APPROVAL_SECRET", "")
if WRITE_MODE not in {"disabled", "approval_required"}:
    raise RuntimeError("CRM_WRITE_MODE must be disabled or approval_required")
if WRITE_MODE == "approval_required" and len(APPROVAL_SECRET) < 32:
    raise RuntimeError("CRM_APPROVAL_SECRET must be at least 32 characters")

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

try:
    from fastmcp import FastMCP
except ImportError:
    print(
        "ERROR: fastmcp not installed. Run:  pip install fastmcp",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP("mps-crm-bridge")

# ---------------------------------------------------------------------------
# Backend: SQLite (default)
# ---------------------------------------------------------------------------

def _sqlite_init():
    """Create tables if they do not exist."""
    con = sqlite3.connect(SQLITE_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS constituents (
            nric        TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            address     TEXT,
            phone       TEXT,
            email       TEXT,
            notes       TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS cases (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            constituent_nric TEXT NOT NULL,
            issue_type       TEXT NOT NULL,
            agency           TEXT NOT NULL,
            summary          TEXT NOT NULL,
            urgency          TEXT DEFAULT 'normal',
            status           TEXT DEFAULT 'open',
            volunteer_name   TEXT,
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            updated_at       TEXT DEFAULT (datetime('now','localtime')),
            reply_received   INTEGER DEFAULT 0,
            reply_date       TEXT,
            reply_notes      TEXT,
            FOREIGN KEY(constituent_nric) REFERENCES constituents(nric)
        );

        CREATE TABLE IF NOT EXISTS letters (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      INTEGER NOT NULL,
            letter_text  TEXT NOT NULL,
            addressed_to TEXT NOT NULL,
            letter_date  TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(case_id) REFERENCES cases(id)
        );
    """)
    con.commit()
    return con


def _sqlite_lookup_constituent(nric: str = "", name: str = "") -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    if nric:
        cur.execute("SELECT * FROM constituents WHERE nric = ?", (nric.upper(),))
    elif name:
        cur.execute("SELECT * FROM constituents WHERE name LIKE ?", (f"%{name}%",))
    else:
        con.close()
        return {"error": "Provide nric or name."}
    row = cur.fetchone()
    if not row:
        return {"found": False, "message": "Constituent not found in database."}
    constituent = dict(row)
    cur.execute(
        "SELECT * FROM cases WHERE constituent_nric = ? ORDER BY created_at DESC",
        (constituent["nric"],),
    )
    constituent["cases"] = [dict(r) for r in cur.fetchall()]
    for case in constituent["cases"]:
        cur.execute(
            "SELECT * FROM letters WHERE case_id = ? ORDER BY created_at DESC",
            (case["id"],),
        )
        case["letters"] = [dict(r) for r in cur.fetchall()]
    constituent["found"] = True
    con.close()
    return constituent


def _sqlite_create_case(
    constituent_nric: str,
    issue_type: str,
    agency: str,
    summary: str,
    urgency: str,
    volunteer_name: str,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO constituents (nric, name) VALUES (?, ?)",
        (constituent_nric.upper(), constituent_nric.upper()),
    )
    cur.execute(
        """INSERT INTO cases
           (constituent_nric, issue_type, agency, summary, urgency, volunteer_name)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (constituent_nric.upper(), issue_type, agency, summary, urgency, volunteer_name),
    )
    case_id = cur.lastrowid
    con.commit()
    con.close()
    return {"success": True, "case_id": case_id, "message": f"Case #{case_id} created."}


def _sqlite_attach_letter(
    case_id: int,
    letter_text: str,
    addressed_to: str,
    letter_date: str,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,))
    if not cur.fetchone():
        con.close()
        return {"error": "Case not found."}
    cur.execute(
        "INSERT INTO letters (case_id, letter_text, addressed_to, letter_date) VALUES (?, ?, ?, ?)",
        (case_id, letter_text, addressed_to, letter_date),
    )
    letter_id = cur.lastrowid
    cur.execute(
        "UPDATE cases SET updated_at = datetime('now','localtime') WHERE id = ?",
        (case_id,),
    )
    con.commit()
    con.close()
    return {"success": True, "letter_id": letter_id}


def _sqlite_update_case_status(
    case_id: int,
    status: str,
    notes: str,
    reply_received: bool,
) -> dict:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """UPDATE cases SET
           status = ?,
           reply_notes = ?,
           reply_received = ?,
           reply_date = CASE WHEN ? THEN datetime('now','localtime') ELSE reply_date END,
           updated_at = datetime('now','localtime')
           WHERE id = ?""",
        (status, notes, int(reply_received), int(reply_received), case_id),
    )
    if cur.rowcount != 1:
        con.close()
        return {"error": "Case not found."}
    con.commit()
    con.close()
    return {"success": True, "case_id": case_id, "new_status": status}


def _sqlite_get_pending_cases(days_overdue: int = 21) -> list:
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """SELECT c.id, c.constituent_nric, c.issue_type, c.agency, c.summary,
                  c.urgency, c.volunteer_name, c.created_at,
                  julianday('now') - julianday(c.created_at) AS days_open
           FROM cases c
           WHERE c.status = 'open'
             AND c.reply_received = 0
             AND julianday('now') - julianday(c.created_at) >= ?
           ORDER BY days_open DESC""",
        (days_overdue,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _sqlite_get_todays_queue() -> list:
    today = datetime.date.today().isoformat()
    con = _sqlite_init()
    cur = con.cursor()
    cur.execute(
        """SELECT c.*, co.name AS constituent_name, co.phone, co.address
           FROM cases c
           LEFT JOIN constituents co ON c.constituent_nric = co.nric
           WHERE date(c.created_at) = ?
           ORDER BY
             CASE c.urgency WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END,
             c.id""",
        (today,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


# ---------------------------------------------------------------------------
# Backend: Google Sheets
# ---------------------------------------------------------------------------

def _gsheets_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise RuntimeError("Install gspread and google-auth: pip install gspread google-auth")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        GSHEET_CREDENTIALS_JSON,
        scopes=scope,
    )
    return gspread.authorize(creds)


def _gsheets_ensure_sheets(client):
    ss = client.open_by_key(GSHEET_SPREADSHEET_ID)
    existing = [ws.title for ws in ss.worksheets()]
    if "Cases" not in existing:
        ws = ss.add_worksheet("Cases", rows=1000, cols=20)
        ws.append_row([
            "Case ID", "Constituent NRIC", "Issue Type", "Agency", "Summary",
            "Urgency", "Status", "Volunteer", "Created At", "Updated At",
            "Reply Received", "Reply Date", "Reply Notes",
        ])
    if "Constituents" not in existing:
        ws = ss.add_worksheet("Constituents", rows=1000, cols=10)
        ws.append_row(["NRIC", "Name", "Address", "Phone", "Email", "Notes", "Created At"])
    if "Letters" not in existing:
        ws = ss.add_worksheet("Letters", rows=1000, cols=8)
        ws.append_row(["Letter ID", "Case ID", "Addressed To", "Letter Date", "Created At", "Letter Text"])
    return ss


def _gsheets_lookup_constituent(nric: str = "", name: str = "") -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Constituents")
    records = ws.get_all_records()
    match = None
    for r in records:
        if nric and str(r.get("NRIC", "")).upper() == nric.upper():
            match = r; break
        if name and name.lower() in str(r.get("Name", "")).lower():
            match = r; break
    if not match:
        return {"found": False, "message": "Constituent not found."}
    cases_ws = ss.worksheet("Cases")
    cases = [
        c for c in cases_ws.get_all_records()
        if str(c.get("Constituent NRIC", "")).upper() == str(match["NRIC"]).upper()
    ]
    match["cases"] = cases
    match["found"] = True
    return match


def _gsheets_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    all_rows = ws.get_all_values()
    case_id = len(all_rows)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([
        case_id, constituent_nric.upper(), issue_type, agency, summary,
        urgency, "open", volunteer_name, now, now, "No", "", "",
    ])
    c_ws = ss.worksheet("Constituents")
    existing_nrics = [str(r.get("NRIC", "")).upper() for r in c_ws.get_all_records()]
    if constituent_nric.upper() not in existing_nrics:
        c_ws.append_row([constituent_nric.upper(), "", "", "", "", "", now])
    return {"success": True, "case_id": case_id}


def _gsheets_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Letters")
    letter_id = len(ws.get_all_values())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([letter_id, case_id, addressed_to, letter_date, now, letter_text])
    return {"success": True, "letter_id": letter_id}


def _gsheets_update_case_status(case_id, status, notes, reply_received) -> dict:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    records = ws.get_all_records()
    header = ws.row_values(1)
    for i, r in enumerate(records, start=2):
        if str(r.get("Case ID")) == str(case_id):
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.update_cell(i, header.index("Status") + 1, status)
            ws.update_cell(i, header.index("Reply Notes") + 1, notes)
            ws.update_cell(i, header.index("Updated At") + 1, now)
            ws.update_cell(i, header.index("Reply Received") + 1, "Yes" if reply_received else "No")
            if reply_received:
                ws.update_cell(i, header.index("Reply Date") + 1, now)
            return {"success": True, "case_id": case_id, "new_status": status}
    return {"error": f"Case {case_id} not found."}


def _gsheets_get_pending_cases(days_overdue=21) -> list:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    records = ws.get_all_records()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_overdue)
    result = []
    for r in records:
        if r.get("Status") != "open" or r.get("Reply Received") == "Yes":
            continue
        try:
            created = datetime.datetime.strptime(str(r["Created At"])[:16], "%Y-%m-%d %H:%M")
            if created <= cutoff:
                r["days_open"] = (datetime.datetime.now() - created).days
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda x: x.get("days_open", 0), reverse=True)


def _gsheets_get_todays_queue() -> list:
    client = _gsheets_client()
    ss = _gsheets_ensure_sheets(client)
    ws = ss.worksheet("Cases")
    today = datetime.date.today().strftime("%Y-%m-%d")
    records = ws.get_all_records()
    result = [r for r in records if str(r.get("Created At", "")).startswith(today)]
    urgency_order = {"urgent": 0, "high": 1, "normal": 2}
    return sorted(result, key=lambda r: urgency_order.get(str(r.get("Urgency", "normal")).lower(), 2))


# ---------------------------------------------------------------------------
# Backend: REST API
# ---------------------------------------------------------------------------

def _rest_get(path: str, params: dict = None) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_post(path: str, data: dict) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=data, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_patch(path: str, data: dict) -> Any:
    import requests
    url = REST_BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    headers = {REST_API_HEADER: REST_API_KEY, "Content-Type": "application/json"}
    r = requests.patch(url, headers=headers, json=data, timeout=15)
    r.raise_for_status()
    return r.json()


def _rest_lookup_constituent(nric="", name="") -> dict:
    try:
        if nric:
            result = _rest_get(f"constituents/{nric.upper()}")
        else:
            results = _rest_get("constituents", {"name": name})
            result = results[0] if results else None
        if not result:
            return {"found": False, "message": "Not found."}
        result["cases"] = _rest_get(f"constituents/{result.get('nric', nric)}/cases")
        result["found"] = True
        return result
    except Exception as e:
        return {"error": str(e)}


def _rest_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    try:
        return _rest_post("cases", {
            "constituent_nric": constituent_nric.upper(),
            "issue_type": issue_type, "agency": agency, "summary": summary,
            "urgency": urgency, "volunteer_name": volunteer_name,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    try:
        return _rest_post(f"cases/{case_id}/letters", {
            "letter_text": letter_text,
            "addressed_to": addressed_to,
            "letter_date": letter_date,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_update_case_status(case_id, status, notes, reply_received) -> dict:
    try:
        return _rest_patch(f"cases/{case_id}", {
            "status": status, "reply_notes": notes,
            "reply_received": reply_received,
            "reply_date": datetime.date.today().isoformat() if reply_received else None,
        })
    except Exception as e:
        return {"error": str(e)}


def _rest_get_pending_cases(days_overdue=21) -> list:
    try:
        return _rest_get("cases", {"status": "open", "days_overdue": days_overdue})
    except Exception as e:
        return [{"error": str(e)}]


def _rest_get_todays_queue() -> list:
    try:
        return _rest_get("cases", {"date": datetime.date.today().isoformat()})
    except Exception as e:
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Backend: SharePoint
# ---------------------------------------------------------------------------

def _sp_client():
    try:
        from office365.runtime.auth.client_credential import ClientCredential
        from office365.sharepoint.client_context import ClientContext
    except ImportError:
        raise RuntimeError("Install Office365-REST-Python-Client: pip install Office365-REST-Python-Client")
    ctx = ClientContext(SP_SITE_URL).with_credentials(
        ClientCredential(SP_CLIENT_ID, SP_CLIENT_SECRET)
    )
    return ctx


def _sp_list_items(ctx, list_name: str, filter_str: str = None) -> list:
    lst = ctx.web.lists.get_by_title(list_name)
    items = lst.items.filter(filter_str) if filter_str else lst.items
    ctx.load(items)
    ctx.execute_query()
    return [item.properties for item in items]


def _sp_lookup_constituent(nric="", name="") -> dict:
    try:
        ctx = _sp_client()
        if nric:
            rows = _sp_list_items(ctx, "Constituents", f"NRIC eq '{nric.upper()}'")
        else:
            rows = _sp_list_items(ctx, "Constituents", f"substringof('{name}', Name)")
        if not rows:
            return {"found": False, "message": "Not found."}
        constituent = rows[0]
        constituent["cases"] = _sp_list_items(
            ctx, SP_LIST_NAME, f"ConstituentNRIC eq '{constituent.get('NRIC', '')}'"
        )
        constituent["found"] = True
        return constituent
    except Exception as e:
        return {"error": str(e)}


def _sp_create_case(constituent_nric, issue_type, agency, summary, urgency, volunteer_name) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title(SP_LIST_NAME)
        item = lst.add_item({
            "ConstituentNRIC": constituent_nric.upper(),
            "IssueType": issue_type, "Agency": agency, "Summary": summary,
            "Urgency": urgency, "Status": "open", "VolunteerName": volunteer_name,
            "CreatedAt": datetime.datetime.now().isoformat(),
        })
        ctx.execute_query()
        return {"success": True, "case_id": item.properties.get("Id")}
    except Exception as e:
        return {"error": str(e)}


def _sp_attach_letter(case_id, letter_text, addressed_to, letter_date) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title("Letters")
        item = lst.add_item({
            "CaseID": case_id, "LetterText": letter_text,
            "AddressedTo": addressed_to, "LetterDate": letter_date,
        })
        ctx.execute_query()
        return {"success": True, "letter_id": item.properties.get("Id")}
    except Exception as e:
        return {"error": str(e)}


def _sp_update_case_status(case_id, status, notes, reply_received) -> dict:
    try:
        ctx = _sp_client()
        lst = ctx.web.lists.get_by_title(SP_LIST_NAME)
        item = lst.get_item_by_id(case_id)
        item.set_property("Status", status)
        item.set_property("ReplyNotes", notes)
        item.set_property("ReplyReceived", reply_received)
        if reply_received:
            item.set_property("ReplyDate", datetime.date.today().isoformat())
        item.update()
        ctx.execute_query()
        return {"success": True, "case_id": case_id, "new_status": status}
    except Exception as e:
        return {"error": str(e)}


def _sp_get_pending_cases(days_overdue=21) -> list:
    try:
        ctx = _sp_client()
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days_overdue)).isoformat()
        return _sp_list_items(ctx, SP_LIST_NAME, f"Status eq 'open' and CreatedAt le '{cutoff}'")
    except Exception as e:
        return [{"error": str(e)}]


def _sp_get_todays_queue() -> list:
    try:
        ctx = _sp_client()
        today = datetime.date.today().isoformat()
        return _sp_list_items(ctx, SP_LIST_NAME, f"startswith(CreatedAt, '{today}')")
    except Exception as e:
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Backend: CSV (read-only)
# ---------------------------------------------------------------------------

def _csv_read(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _csv_lookup_constituent(nric="", name="") -> dict:
    rows = _csv_read(CSV_CASES_PATH)
    match = None
    for r in rows:
        if nric and str(r.get("nric", r.get("NRIC", ""))).upper() == nric.upper():
            match = r; break
        if name and name.lower() in str(r.get("name", r.get("Name", ""))).lower():
            match = r; break
    if not match:
        return {"found": False, "message": "Not found in CSV export."}
    match["found"] = True
    match["_note"] = "CSV backend is read-only. Updates not persisted."
    return match


def _csv_get_pending_cases(days_overdue=21) -> list:
    rows = _csv_read(CSV_CASES_PATH)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_overdue)
    result = []
    for r in rows:
        if str(r.get("status", r.get("Status", ""))).lower() != "open":
            continue
        created_str = r.get("created_at", r.get("Created At", ""))
        try:
            created = datetime.datetime.fromisoformat(created_str[:16])
            if created <= cutoff:
                r["days_open"] = (datetime.datetime.now() - created).days
                result.append(r)
        except Exception:
            pass
    return sorted(result, key=lambda x: x.get("days_open", 0), reverse=True)


def _csv_get_todays_queue() -> list:
    rows = _csv_read(CSV_CASES_PATH)
    today = datetime.date.today().isoformat()
    return [r for r in rows if str(r.get("created_at", r.get("Created At", ""))).startswith(today)]


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_BACKENDS = {
    "sqlite": {
        "lookup_constituent": _sqlite_lookup_constituent,
        "create_case":        _sqlite_create_case,
        "attach_letter":      _sqlite_attach_letter,
        "update_case_status": _sqlite_update_case_status,
        "get_pending_cases":  _sqlite_get_pending_cases,
        "get_todays_queue":   _sqlite_get_todays_queue,
    },
    "google_sheets": {
        "lookup_constituent": _gsheets_lookup_constituent,
        "create_case":        _gsheets_create_case,
        "attach_letter":      _gsheets_attach_letter,
        "update_case_status": _gsheets_update_case_status,
        "get_pending_cases":  _gsheets_get_pending_cases,
        "get_todays_queue":   _gsheets_get_todays_queue,
    },
    "rest_api": {
        "lookup_constituent": _rest_lookup_constituent,
        "create_case":        _rest_create_case,
        "attach_letter":      _rest_attach_letter,
        "update_case_status": _rest_update_case_status,
        "get_pending_cases":  _rest_get_pending_cases,
        "get_todays_queue":   _rest_get_todays_queue,
    },
    "sharepoint": {
        "lookup_constituent": _sp_lookup_constituent,
        "create_case":        _sp_create_case,
        "attach_letter":      _sp_attach_letter,
        "update_case_status": _sp_update_case_status,
        "get_pending_cases":  _sp_get_pending_cases,
        "get_todays_queue":   _sp_get_todays_queue,
    },
    "csv": {
        "lookup_constituent": _csv_lookup_constituent,
        "create_case":        lambda *a, **kw: {"error": "CSV backend is read-only."},
        "attach_letter":      lambda *a, **kw: {"error": "CSV backend is read-only."},
        "update_case_status": lambda *a, **kw: {"error": "CSV backend is read-only."},
        "get_pending_cases":  _csv_get_pending_cases,
        "get_todays_queue":   _csv_get_todays_queue,
    },
}

if BACKEND not in _BACKENDS:
    log.error("Unknown CRM_BACKEND: %s. Choose from: %s", BACKEND, ", ".join(_BACKENDS))
    sys.exit(1)

_fn = _BACKENDS[BACKEND]
log.info("MPS CRM Bridge starting — backend: %s", BACKEND.upper())

# ---------------------------------------------------------------------------
# MCP Tool definitions
# ---------------------------------------------------------------------------

import re as _re

_MASKED_NRIC_RE = _re.compile(r"^[STFGM]\*{4}\d{3}[A-Z]$")
_FULL_NRIC_RE   = _re.compile(r"^[STFGM]\d{7}[A-Z]$", _re.IGNORECASE)
_VALID_URGENCIES = {"normal", "high", "urgent"}
_VALID_STATUSES = {"open", "replied", "resolved", "closed", "escalated"}


def _canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# V-H11/V4-C4: approval tokens are one-time. Consumed token ids are stored in
# SQLite under CRM_DATA_DIR so consumption is atomic (UNIQUE constraint) and
# survives restarts and concurrent processes. Rows are pruned once expired;
# tokens are capped at 900s TTL so the table stays small.
_CONSUMED_DB = os.path.join(DATA_DIR, "consumed_approvals.db")


def _consumed_conn():
    conn = sqlite3.connect(_CONSUMED_DB, timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS consumed_jti "
        "(jti TEXT PRIMARY KEY, exp INTEGER NOT NULL)"
    )
    return conn


def _consume_jti(jti: str, exp: int, now: int) -> bool:
    """Atomically consume a token id. Returns False if already used."""
    conn = _consumed_conn()
    try:
        conn.execute("DELETE FROM consumed_jti WHERE exp < ?", (now,))
        conn.execute("INSERT INTO consumed_jti (jti, exp) VALUES (?, ?)", (jti, exp))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _approval_error(action: str, payload: dict, approval_token: str):
    if WRITE_MODE == "disabled":
        return {"error": "CRM writes are disabled by policy."}
    if not approval_token:
        return {"error": "A human approval token is required for this write."}
    try:
        encoded, supplied_signature = approval_token.split(".", 1)
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(encoded + padding)
        expected_signature = hmac.new(
            APPROVAL_SECRET.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise ValueError("signature mismatch")
        claims = json.loads(raw.decode("utf-8"))
        if claims.get("action") != action:
            raise ValueError("action mismatch")
        payload_hash = hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()
        if not hmac.compare_digest(str(claims.get("payload_sha256", "")), payload_hash):
            raise ValueError("payload mismatch")
        if int(claims.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        if int(claims.get("exp", 0)) > int(time.time()) + 900:
            raise ValueError("token lifetime is too long")
        if not str(claims.get("approved_by", "")).strip():
            raise ValueError("missing approver")
        jti = str(claims.get("jti", "")).strip()
        if not jti:
            raise ValueError("token has no one-time identifier")
        now = int(time.time())
        if not _consume_jti(jti, int(claims["exp"]), now):
            raise ValueError("token already used")
        return None
    except Exception:
        return {"error": "Invalid, expired, or mismatched human approval token."}

def _check_masked_nric(nric: str):
    """Full NRICs are never accepted or stored anywhere in this system.
    Only the masked form (S****567A) may be used as a constituent key.
    Returns an error dict if invalid, else None."""
    if _FULL_NRIC_RE.match(nric):
        return {"error": "Full NRIC rejected. Use the masked form S****567A — "
                         "full NRICs are never stored in this system."}
    if not _MASKED_NRIC_RE.match(nric.upper()):
        return {"error": "NRIC must be in masked form S****567A "
                         "(first letter, four asterisks, last 3 digits, checksum letter)."}
    return None


@mcp.tool()
def lookup_constituent(nric: str = "", name: str = "") -> dict:
    """
    Look up a constituent by masked NRIC (S****567A) or name. Returns their
    profile and all previous MPS cases with letters attached. Use this BEFORE
    the MP meets a constituent — it gives the full case history for context.
    Full NRICs are rejected: only the masked form is accepted.
    """
    log.info("lookup_constituent nric=%s name=%s",
             "***" if nric else "-", name or "-")
    if not nric and not name:
        return {"error": "Provide nric (masked, S****567A) or name."}
    if name and (len(name.strip()) < 3 or len(name.strip()) > 200):
        return {"error": "Name search must be between 3 and 200 characters."}
    if nric:
        err = _check_masked_nric(nric)
        if err:
            return err
        nric = nric.upper()
    return _fn["lookup_constituent"](nric=nric, name=name)


@mcp.tool()
def create_case(
    constituent_nric: str,
    issue_type: str,
    agency: str,
    summary: str,
    urgency: str = "normal",
    volunteer_name: str = "",
    approval_token: str = "",
) -> dict:
    """
    Create a new MPS case for a constituent. Call this once the MP has
    heard the constituent's problem and decided on a course of action.
    constituent_nric must be MASKED (S****567A) — full NRICs are rejected.
    urgency: "urgent" | "high" | "normal"
    """
    log.info("create_case nric=*** type=%s agency=%s urgency=%s", issue_type, agency, urgency)
    err = _check_masked_nric(constituent_nric)
    if err:
        return err
    urgency = urgency.strip().lower()
    if urgency not in _VALID_URGENCIES:
        return {"error": f"urgency must be one of {sorted(_VALID_URGENCIES)}"}
    if not issue_type.strip() or len(issue_type) > 100:
        return {"error": "issue_type must be between 1 and 100 characters."}
    if not agency.strip() or len(agency) > 50:
        return {"error": "agency must be between 1 and 50 characters."}
    if not summary.strip() or len(summary) > 10_000:
        return {"error": "summary must be between 1 and 10000 characters."}
    payload = {
        "constituent_nric": constituent_nric.upper(),
        "issue_type": issue_type.strip(),
        "agency": agency.strip().upper(),
        "summary": summary.strip(),
        "urgency": urgency,
        "volunteer_name": volunteer_name.strip(),
    }
    approval_error = _approval_error("create_case", payload, approval_token)
    if approval_error:
        return approval_error
    return _fn["create_case"](**payload)


@mcp.tool()
def attach_letter(
    case_id: int,
    letter_text: str,
    addressed_to: str,
    letter_date: str = "",
    approval_token: str = "",
) -> dict:
    """
    Attach a completed MP appeal letter to an existing case.
    letter_date defaults to today (YYYY-MM-DD format).
    """
    if not letter_date:
        letter_date = datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(letter_date)
    except ValueError:
        return {"error": "letter_date must use YYYY-MM-DD format."}
    if not letter_text.strip() or len(letter_text) > 20_000:
        return {"error": "letter_text must be between 1 and 20000 characters."}
    if not addressed_to.strip() or len(addressed_to) > 300:
        return {"error": "addressed_to must be between 1 and 300 characters."}
    payload = {
        "case_id": case_id,
        "letter_text": letter_text,
        "addressed_to": addressed_to.strip(),
        "letter_date": letter_date,
    }
    approval_error = _approval_error("attach_letter", payload, approval_token)
    if approval_error:
        return approval_error
    log.info("attach_letter case_id=%s to=%s date=%s", case_id, addressed_to, letter_date)
    return _fn["attach_letter"](**payload)


@mcp.tool()
def update_case_status(
    case_id: int,
    status: str,
    notes: str = "",
    reply_received: bool = False,
    approval_token: str = "",
) -> dict:
    """
    Update the status of a case.
    status: "open" | "replied" | "resolved" | "closed" | "escalated"
    """
    status = status.strip().lower()
    if status not in _VALID_STATUSES:
        return {"error": f"status must be one of {sorted(_VALID_STATUSES)}"}
    if len(notes) > 4_000:
        return {"error": "notes must not exceed 4000 characters."}
    payload = {
        "case_id": case_id,
        "status": status,
        "notes": notes,
        "reply_received": bool(reply_received),
    }
    approval_error = _approval_error("update_case_status", payload, approval_token)
    if approval_error:
        return approval_error
    log.info("update_case_status case_id=%s status=%s reply=%s", case_id, status, reply_received)
    return _fn["update_case_status"](**payload)


@mcp.tool()
def get_pending_cases(days_overdue: int = 21) -> list:
    """
    Return all open cases with no agency reply for N+ days.
    Used for weekly follow-up digest and pre-MPS briefing.
    """
    if days_overdue < 1 or days_overdue > 3650:
        return [{"error": "days_overdue must be between 1 and 3650."}]
    log.info("get_pending_cases days_overdue=%s", days_overdue)
    return _fn["get_pending_cases"](days_overdue)


@mcp.tool()
def get_todays_queue() -> list:
    """
    Return all cases created today, sorted by urgency (urgent first).
    Use at the start of each MPS session to see tonight's queue.
    """
    log.info("get_todays_queue")
    return _fn["get_todays_queue"]()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        if os.getenv("MCP_ENABLE_HTTP", "false").lower() not in {"1", "true", "yes"}:
            raise SystemExit("HTTP transport is disabled. Set MCP_ENABLE_HTTP=true explicitly.")
        port = int(os.getenv("MCP_PORT", "8000"))
        host = os.getenv("MCP_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit(
                "Remote MCP HTTP binding is prohibited. Use stdio or an authenticated TLS gateway."
            )
        log.info("Starting loopback-only HTTP mode on %s:%s", host, port)
        mcp.run(transport="http", host=host, port=port)
    else:
        log.info("Starting stdio mode")
        mcp.run(transport="stdio")


# ---------------------------------------------------------------------------
# .env reference
# ---------------------------------------------------------------------------
#
# CRM_BACKEND=sqlite
# CRM_DATA_DIR=~/mps-hermes/crm-data
# CRM_SQLITE_FILE=mps-cases.db
#
# # Google Sheets
# CRM_BACKEND=google_sheets
# CRM_GSHEET_ID=<spreadsheet-id>
# CRM_GSHEET_CREDENTIALS=~/mps-hermes/crm-data/gsheet-credentials.json
#
# # REST API
# CRM_BACKEND=rest_api
# CRM_REST_BASE_URL=https://your-crm.example.com/api/v1
# CRM_REST_API_KEY=your-key
# CRM_REST_API_HEADER=X-API-Key
#
# # SharePoint
# CRM_BACKEND=sharepoint
# CRM_SP_SITE_URL=https://yourorg.sharepoint.com/sites/MPS
# CRM_SP_CLIENT_ID=<client-id>
# CRM_SP_CLIENT_SECRET=<client-secret>
# CRM_SP_LIST_NAME=MPS Cases
#
# # CSV (read-only)
# CRM_BACKEND=csv
# CRM_CSV_CASES=~/mps-hermes/crm-data/cases.csv
# CRM_CSV_LETTERS=~/mps-hermes/crm-data/letters.csv
