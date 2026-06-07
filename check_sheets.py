import gspread
from google.oauth2.service_account import Credentials
from config import SHEET_ID, CREDENTIALS_PATH

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)
wb = client.open_by_key(SHEET_ID)

# Check Tracker headers and column positions
tracker = wb.worksheet('Tracker')
print('=== TRACKER HEADERS (row 1) ===')
header_row = tracker.row_values(1)
for i, h in enumerate(header_row):
    print(f'  Col {i+1} ({chr(65+i)}): "{h}"')

print()
print('=== TRACKER ROW 2 (first data) ===')
row2 = tracker.row_values(2)
for i, v in enumerate(row2):
    print(f'  Col {i+1} ({chr(65+i)}): "{v}"')

# Check all formulas in other sheets
for sheet_name in ['Budgeting Plan', 'Data from Tracker', 'SUMMARY']:
    sheet = wb.worksheet(sheet_name)
    formulas = sheet.get_all_values(value_render_option='FORMULA')
    print(f'\n=== {sheet_name} - ALL FORMULAS ===')
    found = False
    for i, row in enumerate(formulas):
        for j, cell in enumerate(row):
            if str(cell).startswith('='):
                print(f'  Row {i+1}, Col {j+1} ({chr(65+j)}): {cell}')
                found = True
    if not found:
        print('  (no formulas found)')
