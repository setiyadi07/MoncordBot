import gspread
from google.oauth2.service_account import Credentials
from config import SHEET_ID, CREDENTIALS_PATH

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
client = gspread.authorize(creds)
wb = client.open_by_key(SHEET_ID)

# Create Budget sheet if not exists
existing = [s.title for s in wb.worksheets()]
if 'Budget' in existing:
    sheet = wb.worksheet('Budget')
    sheet.clear()
    print('Budget sheet cleared and will be rewritten.')
else:
    sheet = wb.add_worksheet(title='Budget', rows=30, cols=3)
    print('Budget sheet created.')

# Write headers and budget data
data = [
    ['Kategori',           'Limit (Rp)', 'Keterangan'],
    ['Makanan & Minuman',   1900000,     'Makan 1.5jt + Jajan/Buah 400rb'],
    ['Belanja Bulanan',      416000,     'Sembako bulanan'],
    ['Kebutuhan Anak',       500000,     'Kebutuhan ade per bulan'],
]

sheet.update('A1', data, value_input_option='USER_ENTERED')

# Format header bold (optional, best effort)
try:
    sheet.format('A1:C1', {'textFormat': {'bold': True}})
except:
    pass

print('Budget limits saved:')
for row in data[1:]:
    print(f'  {row[0]}: Rp{row[1]:,}'.replace(',', '.'))
print('\nDone! You can edit limits anytime in the Budget sheet.')
