import os
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_TOKEN_PATH = "token.json"
_CREDS_PATH = "credentials.json"


def get_sheet():
    """Authenticate and return the Google Sheet specified by GOOGLE_SHEET_ID in .env."""
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID not set in .env")

    creds = None
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_CREDS_PATH, _SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def get_or_create_tab(sheet, tab_name: str, headers: list[str]) -> gspread.Worksheet:
    """Return existing tab or create it with the given headers in row 1."""
    try:
        ws = sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


def read_tab_as_df(ws: gspread.Worksheet):
    """Read all rows from a worksheet into a pandas DataFrame."""
    import pandas as pd
    data = ws.get_all_records()
    return pd.DataFrame(data) if data else pd.DataFrame()


def overwrite_tab(ws: gspread.Worksheet, headers: list[str], rows: list[list]):
    """Clear tab and write headers + rows."""
    ws.clear()
    ws.append_row(headers)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
