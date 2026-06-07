import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from config import TELEGRAM_TOKEN, ALLOWED_USERS
from ai import chat, clear_history
from sheets import get_summary, delete_last_row, check_budget_alerts, get_budget_status

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─── Auth check ───────────────────────────────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    text = (
        "Halo! Saya *Moncord* — asisten pencatat keuangan kamu.\n\n"
        "Cukup kirim pesan seperti:\n"
        "- makan siang 25000\n"
        "- gaji bulan ini 5jt\n"
        "- bensin 80rb\n\n"
        "*Perintah tersedia:*\n"
        "/report — Ringkasan bulan ini\n"
        "/budget — Cek status budget\n"
        "/delete — Hapus transaksi terakhir\n"
        "/reset — Reset percakapan\n"
        "/help — Bantuan"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── /help ────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    text = (
        "*Cara pakai Moncord:*\n\n"
        "Kirim pesan natural language, contoh:\n"
        "- makan nasi padang 25rb\n"
        "- bayar listrik 150000\n"
        "- gaji 5jt\n"
        "- beli mainan anak 50rb\n\n"
        "Bot otomatis mendeteksi kategori dan simpan ke Google Sheets.\n\n"
        "*Perintah:*\n"
        "/report — Ringkasan bulan ini\n"
        "/budget — Cek status budget (ketik /budget untuk panduan)\n"
        "/delete — Hapus transaksi terakhir\n"
        "/reset — Hapus riwayat percakapan\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── /report ──────────────────────────────────────────────────────────────────

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    await update.message.reply_text("⏳ Mengambil data...")

    try:
        current_month = datetime.now().strftime("%m/%Y")
        rows = get_summary(month=current_month)

        if not rows:
            await update.message.reply_text(
                f"📭 Belum ada transaksi bulan {datetime.now().strftime('%B %Y')}."
            )
            return

        total_masuk = sum(
            int(str(r.get("Jumlah (Rp)", 0)).replace(",", "").replace(".", "") or 0)
            for r in rows if r.get("Jenis") == "Pemasukan"
        )
        total_keluar = sum(
            int(str(r.get("Jumlah (Rp)", 0)).replace(",", "").replace(".", "") or 0)
            for r in rows if r.get("Jenis") == "Pengeluaran"
        )
        saldo = total_masuk - total_keluar

        # Breakdown by category (expenses)
        kategori_keluar: dict[str, int] = {}
        for r in rows:
            if r.get("Jenis") == "Pengeluaran":
                kat = r.get("Kategori", "Lainnya")
                amt = int(str(r.get("Jumlah (Rp)", 0)).replace(",", "").replace(".", "") or 0)
                kategori_keluar[kat] = kategori_keluar.get(kat, 0) + amt

        breakdown = "\n".join(
            f"  • {k}: Rp {v:,}".replace(",", ".")
            for k, v in sorted(kategori_keluar.items(), key=lambda x: -x[1])
        )

        text = (
            f"📊 *Laporan {datetime.now().strftime('%B %Y')}*\n"
            f"Total transaksi: {len(rows)}\n\n"
            f"💰 Pemasukan : Rp {total_masuk:,}\n".replace(",", ".")
            + f"💸 Pengeluaran: Rp {total_keluar:,}\n".replace(",", ".")
            + f"🏦 Saldo      : Rp {saldo:,}\n\n".replace(",", ".")
            + f"📂 *Rincian Pengeluaran:*\n{breakdown}"
        )

        await update.message.reply_text(text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Report error: {e}")
        await update.message.reply_text(f"❌ Gagal mengambil data: {str(e)}")


# ─── /budget ──────────────────────────────────────────────────────────────────

def _parse_period(args: list) -> tuple:
    """Parse period from command args. Returns (start_date, end_date, label)."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if not args:
        # Default: this month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, f"Bulan {now.strftime('%B %Y')}"

    arg = " ".join(args).lower().strip()

    if arg in ["hari ini", "today", "harian"]:
        return today_start, now, "Hari Ini"

    if arg in ["kemarin", "yesterday"]:
        yesterday = today_start - timedelta(days=1)
        return yesterday, today_start - timedelta(seconds=1), "Kemarin"

    if arg in ["minggu ini", "minggu", "weekly", "week"]:
        start = today_start - timedelta(days=now.weekday())
        return start, now, "Minggu Ini"

    if arg in ["bulan ini", "bulan", "monthly", "month"]:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, f"Bulan {now.strftime('%B %Y')}"

    # Handle "X hari" or "X hari terakhir"
    import re
    match = re.match(r'(\d+)\s*hari', arg)
    if match:
        days = int(match.group(1))
        start = today_start - timedelta(days=days - 1)
        return start, now, f"{days} Hari Terakhir"

    # Handle "X minggu"
    match = re.match(r'(\d+)\s*minggu', arg)
    if match:
        weeks = int(match.group(1))
        start = today_start - timedelta(weeks=weeks)
        return start, now, f"{weeks} Minggu Terakhir"

    # Default fallback: this month
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now, f"Bulan {now.strftime('%B %Y')}"


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Akses ditolak.")
        return

    start, end, label = _parse_period(context.args)

    await update.message.reply_text("Mengambil data budget...")

    try:
        report = get_budget_status(start, end, label)
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Budget error: {e}")
        await update.message.reply_text(f"Gagal mengambil data budget: {str(e)}")


# ─── /delete ──────────────────────────────────────────────────────────────────

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    try:
        deleted = delete_last_row()
        if deleted:
            text = (
                f"🗑️ *Transaksi terakhir dihapus:*\n"
                f"Tanggal   : {deleted.get('Tanggal', '-')}\n"
                f"Jenis     : {deleted.get('Jenis', '-')}\n"
                f"Kategori  : {deleted.get('Kategori', '-')}\n"
                f"Keterangan: {deleted.get('Keterangan', '-')}\n"
                f"Jumlah    : Rp {deleted.get('Jumlah (Rp)', '-')}"
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text("📭 Tidak ada transaksi yang bisa dihapus.")
    except Exception as e:
        logger.error(f"Delete error: {e}")
        await update.message.reply_text(f"❌ Gagal menghapus: {str(e)}")


# ─── /reset ───────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    clear_history(update.effective_user.id)
    await update.message.reply_text("🔄 Riwayat percakapan direset.")


# ─── Message handler ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    user_message = update.message.text
    logger.info(f"User {user_id}: {user_message}")

    try:
        reply, saved_kategori = chat(user_id, user_message)
        await update.message.reply_text(reply, parse_mode="Markdown")

        # Check budget alert if a transaction was just saved
        if saved_kategori:
            try:
                alert = check_budget_alerts(saved_kategori)
                if alert:
                    await update.message.reply_text(alert, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Budget check error: {e}")

    except Exception as e:
        logger.error(f"Chat error: {e}")
        await update.message.reply_text(f"Terjadi kesalahan: {str(e)}")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import asyncio
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.set_event_loop(asyncio.new_event_loop())

    print("Moncord Bot starting...")
    print(f"Authorized users: {ALLOWED_USERS}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)
