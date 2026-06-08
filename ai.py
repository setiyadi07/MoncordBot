import json
import re
from datetime import datetime, timedelta
from groq import Groq
from config import GROQ_API_KEY
from sheets import append_transaction, delete_matching_row, delete_last_row, get_summary, get_report_this_month

client = Groq(api_key=GROQ_API_KEY)

def _build_system_prompt():
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return f"""Kamu adalah asisten pencatat keuangan pribadi bernama Moncord.
Hari ini: {today}. Kemarin: {yesterday}.

KATEGORI PEMASUKAN: Gaji, Bonus/THR, Penghasilan Sampingan, Investasi/Dividen, Lainnya
KATEGORI PENGELUARAN: Makanan & Minuman, Transportasi, Tagihan, Sewa/Cicilan, Belanja Bulanan, Hiburan, Kesehatan, Pendidikan, Pakaian, Tabungan, Investasi, Donasi/Zakat, Kebutuhan Anak, Lainnya

Catatan kategori:
- "Kebutuhan Anak" = kebutuhan anak seperti mainan, baju anak, susu, vitamin, obat anak, perlengkapan bayi
- "Makanan & Minuman" = makan di luar, jajan, beli makanan siap saji, minuman, restoran, warung
- "Belanja Bulanan" = belanja bahan masak: sayur, bumbu, lauk pauk, beras, minyak, telur, tahu, tempe, sabun, sembako, kebutuhan dapur

Aturan ketat:
1. Analisis pesan user, tentukan otomatis: Jenis, Kategori, Keterangan, Jumlah, dan Tanggal
2. Jika user ingin MENYIMPAN transaksi dan semua info lengkap, balas HANYA dengan JSON:
   {{"action":"save","jenis":"Pengeluaran","kategori":"Makanan & Minuman","keterangan":"Nasi Padang","jumlah":25000,"tanggal":"{today}"}}
   - Jika user sebut "kemarin" → tanggal: "{yesterday}"
   - Jika user sebut "hari ini" atau tidak menyebut waktu → tanggal: "{today}"
3. Jika user ingin MENGHAPUS transaksi (kata kunci: hapus, salah, batalkan, delete, cancel), balas HANYA dengan JSON:
   {{"action":"delete","jenis":"Pemasukan","kategori":"Investasi/Dividen","keterangan":"Gain Saham","jumlah":1000000}}
4. Jika user minta LAPORAN/RINGKASAN/REPORT (kata kunci: laporan, laporkan, report, ringkasan, rekap, summary, catatan keuangan, pengeluaran bulan, total), balas HANYA dengan JSON:
   {{"action":"report"}}
5. Jika ada info yang benar-benar tidak bisa ditentukan, tanya SATU pertanyaan pendek saja
6. Format jumlah: angka bulat saja tanpa titik/koma (contoh: 25000)
7. Jangan minta konfirmasi sebelum menyimpan atau menghapus

Contoh respons benar:
- User: "makan nasi padang 25rb" → {{"action":"save","jenis":"Pengeluaran","kategori":"Makanan & Minuman","keterangan":"Nasi Padang","jumlah":25000,"tanggal":"{today}"}}
- User: "kemarin beli sayur 50rb" → {{"action":"save","jenis":"Pengeluaran","kategori":"Makanan & Minuman","keterangan":"Sayur","jumlah":50000,"tanggal":"{yesterday}"}}
- User: "gaji 5jt" → {{"action":"save","jenis":"Pemasukan","kategori":"Gaji","keterangan":"Gaji Bulanan","jumlah":5000000,"tanggal":"{today}"}}
- User: "hapus gain saham 1jt" → {{"action":"delete","jenis":"Pemasukan","kategori":"Investasi/Dividen","keterangan":"Gain Saham","jumlah":1000000}}
- User: "salah, hapus yang tadi" → {{"action":"delete","jenis":"","kategori":"","keterangan":"","jumlah":""}}
- User: "laporkan pengeluaran" → {{"action":"report"}}
- User: "bisa kasih laporan?" → {{"action":"report"}}
"""

# Per-user conversation history (in-memory)
conversation_history: dict[int, list] = {}


def chat(user_id: int, message: str) -> tuple[str, str | None]:
    """Process a user message. Returns (reply, saved_kategori or None)."""
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": message})

    # Keep last 6 messages (3 back-and-forth exchanges)
    if len(conversation_history[user_id]) > 6:
        conversation_history[user_id] = conversation_history[user_id][-6:]

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": _build_system_prompt()}] + conversation_history[user_id],
        temperature=0.1,
        max_tokens=256,
    )

    reply = response.choices[0].message.content.strip()
    conversation_history[user_id].append({"role": "assistant", "content": reply})

    # Try to parse action from AI reply
    try:
        json_match = re.search(r'\{.*?\}', reply, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())

            # ── REPORT ────────────────────────────────────────
            if data.get("action") == "report":
                return get_report_this_month(), None

            # ── SAVE ──────────────────────────────────────────
            if data.get("action") == "save":
                kategori = data["kategori"]
                # Parse tanggal from AI response, fallback to today
                tanggal_str = data.get("tanggal", "")
                try:
                    tanggal_dt = datetime.strptime(tanggal_str, "%Y-%m-%d")
                except (ValueError, TypeError):
                    tanggal_dt = datetime.now()
                append_transaction(
                    jenis=data["jenis"],
                    kategori=kategori,
                    keterangan=data["keterangan"],
                    jumlah=str(int(data["jumlah"])),
                    tanggal=tanggal_dt
                )
                conversation_history[user_id] = []
                return "Berhasil dicatat!", kategori

            # ── DELETE ────────────────────────────────────────
            if data.get("action") == "delete":
                conversation_history[user_id] = []

                jenis      = data.get("jenis", "") or ""
                kategori   = data.get("kategori", "") or ""
                keterangan = data.get("keterangan", "") or ""
                jumlah_raw = data.get("jumlah", "") or ""

                # If no specific info given, delete last row
                if not any([jenis, kategori, keterangan, jumlah_raw]):
                    deleted = delete_last_row()
                else:
                    jumlah_str = str(int(float(str(jumlah_raw)))) if jumlah_raw else ""
                    deleted = delete_matching_row(
                        jenis=jenis or None,
                        kategori=kategori or None,
                        keterangan=keterangan or None,
                        jumlah=jumlah_str or None
                    )

                if deleted:
                    ket  = deleted.get("Keterangan", "-")
                    jns  = deleted.get("Jenis", "-")
                    jml  = deleted.get("Jumlah (Rp)", "-")
                    tgl  = deleted.get("Tanggal", "-")
                    return (
                        f"Berhasil dihapus!\n\n"
                        f"Tanggal : {tgl}\n"
                        f"Jenis   : {jns}\n"
                        f"Catatan : {ket}\n"
                        f"Jumlah  : {jml}"
                    ), None
                else:
                    return "Transaksi tidak ditemukan. Coba sebutkan detail yang lebih spesifik.", None

    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    return reply, None


def clear_history(user_id: int):
    """Clear conversation history for a user."""
    conversation_history.pop(user_id, None)
