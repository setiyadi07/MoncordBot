import json
import re
from groq import Groq
from config import GROQ_API_KEY
from sheets import append_transaction, delete_matching_row, delete_last_row

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """Kamu adalah asisten pencatat keuangan pribadi bernama Moncord.

KATEGORI PEMASUKAN: Gaji, Bonus/THR, Penghasilan Sampingan, Investasi/Dividen, Lainnya
KATEGORI PENGELUARAN: Makanan & Minuman, Transportasi, Tagihan, Sewa/Cicilan, Belanja Bulanan, Hiburan, Kesehatan, Pendidikan, Pakaian, Tabungan, Investasi, Donasi/Zakat, Kebutuhan Anak, Lainnya

Catatan kategori:
- "Kebutuhan Anak" = kebutuhan anak seperti mainan, baju anak, susu, vitamin, obat anak, perlengkapan bayi
- "Makanan & Minuman" = makan harian, lauk pauk, sayur, bumbu, jajan, buah
- "Belanja Bulanan" = sembako (beras, minyak, sabun, dll)

Aturan ketat:
1. Analisis pesan user, tentukan otomatis: Jenis, Kategori, Keterangan, dan Jumlah
2. Jika user ingin MENYIMPAN transaksi dan semua info lengkap, balas HANYA dengan JSON:
   {"action":"save","jenis":"Pengeluaran","kategori":"Makanan & Minuman","keterangan":"Nasi Padang","jumlah":25000}
3. Jika user ingin MENGHAPUS transaksi (kata kunci: hapus, salah, batalkan, delete, cancel), balas HANYA dengan JSON:
   {"action":"delete","jenis":"Pemasukan","kategori":"Investasi/Dividen","keterangan":"Gain Saham","jumlah":1000000}
   Isi field sesuai transaksi yang ingin dihapus. Jika user tidak menyebut detail, gunakan field yang diketahui saja (boleh kosong "").
4. Jika ada info yang benar-benar tidak bisa ditentukan, tanya SATU pertanyaan pendek saja
5. Format jumlah: angka bulat saja tanpa titik/koma (contoh: 25000)
6. Jangan minta konfirmasi sebelum menyimpan atau menghapus

Contoh respons benar:
- User: "makan nasi padang 25rb" → {"action":"save","jenis":"Pengeluaran","kategori":"Makanan & Minuman","keterangan":"Nasi Padang","jumlah":25000}
- User: "gaji 5jt" → {"action":"save","jenis":"Pemasukan","kategori":"Gaji","keterangan":"Gaji Bulanan","jumlah":5000000}
- User: "hapus gain saham 1jt" → {"action":"delete","jenis":"Pemasukan","kategori":"Investasi/Dividen","keterangan":"Gain Saham","jumlah":1000000}
- User: "salah, hapus yang tadi" → {"action":"delete","jenis":"","kategori":"","keterangan":"","jumlah":""}
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
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[user_id],
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

            # ── SAVE ──────────────────────────────────────────
            if data.get("action") == "save":
                kategori = data["kategori"]
                append_transaction(
                    jenis=data["jenis"],
                    kategori=kategori,
                    keterangan=data["keterangan"],
                    jumlah=str(int(data["jumlah"]))
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
