import gspread
import json
from gspread.utils import ValueInputOption
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from config import SHEET_ID, SHEET_NAME, CREDENTIALS_PATH, GOOGLE_CREDENTIALS_JSON

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_workbook():
    if GOOGLE_CREDENTIALS_JSON:
        # Railway: load credentials from environment variable
        info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # Local: load credentials from file
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def get_sheet():
    return _get_workbook().worksheet(SHEET_NAME)


def _to_sheets_date(dt: datetime) -> float:
    """Convert Python datetime to Google Sheets date serial number."""
    epoch = datetime(1899, 12, 30)
    return (dt - epoch).days


def _parse_sheets_date(serial) -> datetime:
    """Convert Google Sheets date serial back to datetime."""
    try:
        serial = float(str(serial).replace(",", ""))
        epoch = datetime(1899, 12, 30)
        return epoch + timedelta(days=serial)
    except Exception:
        return None


def append_transaction(jenis: str, kategori: str, keterangan: str, jumlah: str, tanggal: datetime = None) -> bool:
    """Save a new income/expense row to Google Sheets."""
    sheet = get_sheet()
    tanggal_serial = _to_sheets_date(tanggal if tanggal else datetime.now())
    jumlah_int = int(str(jumlah).replace(",", "").replace(".", "").strip())
    sheet.append_row(
        [tanggal_serial, jenis, kategori, keterangan, jumlah_int],
        value_input_option=ValueInputOption.raw
    )
    return True


def get_report_this_month() -> str:
    """Calculate report directly from Tracker sheet for current month."""
    try:
        sheet = get_sheet()
        all_values = sheet.get_all_values(value_render_option='UNFORMATTED_VALUE')
        if len(all_values) <= 1:
            return f"📭 Belum ada transaksi bulan {datetime.now().strftime('%B %Y')}."

        headers = [str(h) for h in all_values[0]]
        try:
            col_tanggal  = headers.index('Tanggal')
            col_jenis    = headers.index('Jenis')
            col_kategori = headers.index('Kategori')
            col_jumlah   = headers.index('Jumlah (Rp)')
        except ValueError:
            return "❌ Format sheet tidak sesuai."

        now = datetime.now()
        start_serial = _to_sheets_date(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        end_serial   = _to_sheets_date(now)

        total_masuk  = 0
        total_keluar = 0
        kategori_keluar = {}

        for row in all_values[1:]:
            if len(row) <= max(col_tanggal, col_jenis, col_kategori, col_jumlah):
                continue
            try:
                serial  = float(str(row[col_tanggal]))
                if not (start_serial <= serial <= end_serial):
                    continue
                jenis   = row[col_jenis]
                kat     = row[col_kategori]
                jumlah  = int(str(row[col_jumlah]).replace("Rp","").replace(",","").replace(".","").strip() or 0)

                if jenis == "Pemasukan":
                    total_masuk += jumlah
                elif jenis == "Pengeluaran":
                    total_keluar += jumlah
                    kategori_keluar[kat] = kategori_keluar.get(kat, 0) + jumlah
            except (ValueError, IndexError):
                continue

        saldo = total_masuk - total_keluar
        month = now.strftime("%B %Y")

        def fmt(n): return f"Rp{n:,}".replace(",", ".")

        lines = [f"📊 *Ringkasan Keuangan — {month}*\n"]
        lines.append(f"💰 Pemasukan  : {fmt(total_masuk)}")
        lines.append(f"💸 Pengeluaran: {fmt(total_keluar)}")
        lines.append(f"🏦 Saldo Sisa : {fmt(saldo)}")

        if kategori_keluar:
            lines.append("\n📂 *Rincian Pengeluaran:*")
            for k, v in sorted(kategori_keluar.items(), key=lambda x: -x[1]):
                pct = (v / total_keluar * 100) if total_keluar > 0 else 0
                lines.append(f"  • {k}: {fmt(v)} ({pct:.1f}%)")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Gagal membuat laporan: {str(e)}"


def get_summary_sheet() -> str:
    """Read the SUMMARY sheet and return as formatted Telegram text."""
    try:
        wb = _get_workbook()
        sheet = wb.worksheet('SUMMARY')
        rows = sheet.get_all_values()
        if not rows:
            return "📭 SUMMARY sheet kosong."

        pemasukan   = "-"
        pengeluaran = "-"
        saldo       = "-"
        kategori_rows = []
        reading_kategori = False
        header_row_idx   = -1

        for i, row in enumerate(rows):
            cells = [str(c).strip() for c in row]

            # Find the header row that contains Pemasukan, Pengeluaran, Saldo
            if "Pemasukan" in cells and "Pengeluaran" in cells:
                header_row_idx = i
                # Values are in the NEXT row
                if i + 1 < len(rows):
                    val_row = [str(c).strip() for c in rows[i + 1]]
                    try:
                        pemasukan   = val_row[cells.index("Pemasukan")]
                    except (ValueError, IndexError):
                        pass
                    try:
                        pengeluaran = val_row[cells.index("Pengeluaran")]
                    except (ValueError, IndexError):
                        pass
                    # Saldo Sisa
                    for label in ["Saldo Sisa", "Saldo"]:
                        if label in cells:
                            try:
                                saldo = val_row[cells.index(label)]
                            except (ValueError, IndexError):
                                pass
                            break
                continue

            # Find kategori table header
            if "Rincian" in " ".join(cells) or ("% Total" in cells) or ("% total" in " ".join(cells).lower()):
                reading_kategori = True
                continue

            # Read kategori rows (after header, skip the values row)
            if reading_kategori and i > header_row_idx + 1:
                name   = cells[0] if len(cells) > 0 else ""
                amount = cells[1] if len(cells) > 1 else "-"
                pct    = cells[2] if len(cells) > 2 else "-"
                if name and name not in ("", "-") and "%" not in name and "Rincian" not in name:
                    kategori_rows.append((name, amount, pct))

        # Build output
        month = datetime.now().strftime("%B %Y")
        lines = [f"📊 *Ringkasan Keuangan — {month}*\n"]
        lines.append(f"💰 Pemasukan  : {pemasukan if pemasukan else '-'}")
        lines.append(f"💸 Pengeluaran: {pengeluaran if pengeluaran else '-'}")
        lines.append(f"🏦 Saldo Sisa : {saldo if saldo else '-'}")

        if kategori_rows:
            lines.append("\n📂 *Rincian Pengeluaran:*")
            for name, amount, pct in kategori_rows:
                if amount and amount not in ("-", ""):
                    lines.append(f"  • {name}: {amount} ({pct})")
                else:
                    lines.append(f"  • {name}: -")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Gagal membaca SUMMARY: {str(e)}"


def get_summary(month: str = None) -> list:
    """Return all rows, optionally filtered by month (format: MM/YYYY)."""
    sheet = get_sheet()
    rows = sheet.get_all_records()
    if month:
        rows = [r for r in rows if str(r.get("Tanggal", "")).endswith(month)]
    return rows


def delete_last_row() -> dict:
    """Delete the last data row and return the deleted record."""
    sheet = get_sheet()
    all_values = sheet.get_all_values()
    if len(all_values) <= 1:
        return None
    last_row_index = len(all_values)
    last_row_data = all_values[-1]
    sheet.delete_rows(last_row_index)
    headers = all_values[0]
    return dict(zip(headers, last_row_data))


def delete_matching_row(jenis: str = None, kategori: str = None,
                        keterangan: str = None, jumlah: str = None) -> dict:
    """Find and delete the most recent row matching the given fields.
    Matches are case-insensitive and partial. Returns the deleted row or None.
    """
    sheet = get_sheet()
    all_values = sheet.get_all_values()
    if len(all_values) <= 1:
        return None

    headers = all_values[0]
    try:
        col_jenis    = headers.index('Jenis')
        col_kategori = headers.index('Kategori')
        col_ket      = headers.index('Keterangan')
        col_jumlah   = headers.index('Jumlah (Rp)')
    except ValueError:
        return None

    # Search from bottom (most recent first)
    for i in range(len(all_values) - 1, 0, -1):
        row = all_values[i]
        if len(row) <= max(col_jenis, col_kategori, col_ket, col_jumlah):
            continue

        match = True
        if jenis and jenis.lower() not in row[col_jenis].lower():
            match = False
        if kategori and kategori.lower() not in row[col_kategori].lower():
            match = False
        if keterangan and keterangan.lower() not in row[col_ket].lower():
            match = False
        if jumlah:
            # Compare numeric value
            try:
                row_jumlah = int(str(row[col_jumlah]).replace("Rp", "").replace(",", "").replace(".", "").strip())
                req_jumlah = int(str(jumlah).replace(",", "").replace(".", "").strip())
                if row_jumlah != req_jumlah:
                    match = False
            except ValueError:
                match = False

        if match:
            sheet.delete_rows(i + 1)  # +1 because sheet rows are 1-indexed
            return dict(zip(headers, row))

    return None


# ─── Budget functions ─────────────────────────────────────────────────────────

def get_budget_limits() -> dict:
    """Read budget limits from Budget sheet. Returns {kategori: limit}."""
    try:
        wb = _get_workbook()
        sheet = wb.worksheet('Budget')
        rows = sheet.get_all_values()
        limits = {}
        for row in rows[1:]:  # skip header
            if len(row) >= 2 and row[0] and row[1]:
                try:
                    limits[row[0].strip()] = int(str(row[1]).replace(",", "").replace(".", "").strip())
                except ValueError:
                    pass
        return limits
    except Exception:
        return {}


def get_spending_by_period(start_date: datetime, end_date: datetime) -> dict:
    """Return total spending per category within a date range.
    Returns {kategori: total_spent}
    """
    sheet = get_sheet()
    all_values = sheet.get_all_values()
    if len(all_values) <= 1:
        return {}

    headers = all_values[0]
    # Find column indices
    try:
        col_tanggal  = headers.index('Tanggal')
        col_jenis    = headers.index('Jenis')
        col_kategori = headers.index('Kategori')
        col_jumlah   = headers.index('Jumlah (Rp)')
    except ValueError:
        return {}

    spending = {}
    start_serial = _to_sheets_date(start_date)
    end_serial   = _to_sheets_date(end_date)

    for row in all_values[1:]:
        if len(row) <= max(col_tanggal, col_jenis, col_kategori, col_jumlah):
            continue
        try:
            tanggal_raw = row[col_tanggal]
            jenis       = row[col_jenis]
            kategori    = row[col_kategori]
            jumlah_raw  = str(row[col_jumlah]).replace("Rp", "").replace(",", "").replace(".", "").strip()

            if jenis != 'Pengeluaran':
                continue
            if not jumlah_raw:
                continue

            # Parse date serial
            serial = float(tanggal_raw)
            if not (start_serial <= serial <= end_serial):
                continue

            jumlah = int(jumlah_raw)
            spending[kategori] = spending.get(kategori, 0) + jumlah
        except (ValueError, IndexError):
            continue

    return spending


def check_budget_alerts(kategori: str) -> str:
    """Check budget status for a category this month.
    Returns alert message or empty string if OK.
    """
    limits = get_budget_limits()
    if kategori not in limits:
        return ""

    limit = limits[kategori]
    now = datetime.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    spending = get_spending_by_period(start, now)
    spent = spending.get(kategori, 0)
    pct = (spent / limit * 100) if limit > 0 else 0

    if pct >= 100:
        return (
            f"\n\n🚨 *BUDGET TERLAMPAUI!*\n"
            f"Kategori: {kategori}\n"
            f"Limit   : Rp{limit:,}\n".replace(",", ".")
            + f"Terpakai: Rp{spent:,} ({pct:.0f}%)".replace(",", ".")
        )
    elif pct >= 80:
        sisa = limit - spent
        return (
            f"\n\n⚠️ *Peringatan Budget 80%!*\n"
            f"Kategori: {kategori}\n"
            f"Limit   : Rp{limit:,}\n".replace(",", ".")
            + f"Terpakai: Rp{spent:,} ({pct:.0f}%)\n".replace(",", ".")
            + f"Sisa    : Rp{sisa:,}".replace(",", ".")
        )
    return ""


def get_budget_status(start_date: datetime, end_date: datetime, period_label: str) -> str:
    """Generate full budget status report for a given period."""
    limits   = get_budget_limits()
    spending = get_spending_by_period(start_date, end_date)

    if not limits:
        return "Belum ada budget yang diset."

    lines = [f"📊 *Budget Status — {period_label}*\n"]
    for kategori, limit in limits.items():
        spent = spending.get(kategori, 0)
        sisa  = limit - spent
        pct   = (spent / limit * 100) if limit > 0 else 0

        if pct >= 100:
            icon = "🚨"
        elif pct >= 80:
            icon = "⚠️"
        elif pct >= 50:
            icon = "🟡"
        else:
            icon = "✅"

        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        lines.append(
            f"{icon} *{kategori}*\n"
            f"[{bar}] {pct:.0f}%\n"
            f"Terpakai: Rp{spent:,} / Rp{limit:,}\n".replace(",", ".")
            + f"Sisa    : Rp{max(sisa,0):,}\n".replace(",", ".")
        )

    return "\n".join(lines)
