import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY          = os.getenv("GROQ_API_KEY")
SHEET_ID              = os.getenv("SHEET_ID")
SHEET_NAME            = os.getenv("SHEET_NAME", "Tracker")
ALLOWED_USERS         = [int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()]
CREDENTIALS_PATH      = os.getenv("CREDENTIALS_PATH", "credentials.json")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # JSON string for Railway
