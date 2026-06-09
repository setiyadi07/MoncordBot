import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN          = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY            = os.getenv("GROQ_API_KEY")
SHEET_ID                = os.getenv("SHEET_ID")
SHEET_NAME              = os.getenv("SHEET_NAME", "Tracker")
ALLOWED_USERS           = [int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()]
CREDENTIALS_PATH        = os.getenv("CREDENTIALS_PATH", "credentials.json")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # JSON string for Railway

# Per-user sheet mapping: "userid1:sheetid1,userid2:sheetid2"
def _parse_user_sheets() -> dict:
    raw = os.getenv("USER_SHEETS", "")
    mapping = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            uid, sid = entry.split(":", 1)
            try:
                mapping[int(uid.strip())] = sid.strip()
            except ValueError:
                pass
    # Fallback: all ALLOWED_USERS use the default SHEET_ID
    for uid in ALLOWED_USERS:
        if uid not in mapping and SHEET_ID:
            mapping[uid] = SHEET_ID
    return mapping

USER_SHEETS = _parse_user_sheets()
