import gspread
from google.oauth2.service_account import Credentials
from config import SHEET_ID, CREDENTIALS_PATH

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)
wb = client.open_by_key(SHEET_ID)

def fix_formula(formula: str) -> str:
    """Replace hardcoded row limits with 1000."""
    import re
    # Replace $X$2:$X$6 → $X$2:$X$1000 for Tracker references
    fixed = re.sub(
        r'(Tracker!\$[A-Z]\$2:\$[A-Z]\$)\d+',
        r'\g<1>1000',
        formula
    )
    return fixed

updates = []

for sheet_name in ['Budgeting Plan', 'Data from Tracker', 'SUMMARY']:
    sheet = wb.worksheet(sheet_name)
    formulas = sheet.get_all_values(value_render_option='FORMULA')
    sheet_updates = []

    for i, row in enumerate(formulas):
        for j, cell in enumerate(row):
            if 'Tracker!' in str(cell) and '$F$6' in str(cell):
                new_formula = fix_formula(cell)
                col_letter = chr(65 + j)
                cell_ref = f'{col_letter}{i+1}'
                sheet_updates.append({
                    'range': cell_ref,
                    'values': [[new_formula]]
                })
                print(f'  [{sheet_name}] {cell_ref}: {cell}')
                print(f'           -> {new_formula}')

    if sheet_updates:
        sheet.batch_update(sheet_updates, value_input_option='USER_ENTERED')
        print(f'  OK: Updated {len(sheet_updates)} formulas in {sheet_name}\n')
    else:
        print(f'  (no fixes needed in {sheet_name})\n')

print('Done! All formulas now cover up to row 1000.')
