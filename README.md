# vps-mon

Monitor VPS ringan: alive-check + pengingat tanggal sewa, alert via **Telegram**. 
Python **stdlib only** (zero dependency), jalan via cron, cocok untuk VPS kecil/RAM pas-pasan.

![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.8+-green)

## Fitur

- ✅ **Alive check** per menit (TCP connect ke port SSH) → SQLite
- 🔴 Alert DOWN **sekali** saat transisi (bukan spam tiap N gagal)
- 🟢 Alert RECOVER saat hidup lagi (termasuk host yang di-mute)
- 🔇 `"mute_down": true` per host — untuk host yang memang sudah mati lama
- ⏰ **Lease reminder** T-14/7/3/1/0 hari + peringatan expired
- 📡 **Digest harian**: status semua host + countdown sewa
- 💾 Retensi data 14 hari, auto-cleanup

## Setup

### Cara cepat (wizard interaktif)

```bash
git clone https://github.com/ranggawisnus/vps-mon.git && cd vps-mon
bash setup.sh
```

Wizard akan: validasi token bot -> deteksi chat id Telegram otomatis -> input daftar VPS ->
tes kirim alert -> pasang cron. Selesai.

Headless/CI (tanpa prompt):

```bash
VPSMON_TOKEN="123:ABC" VPSMON_CHAT_ID="67890" bash setup.sh
```

### Cara manual

```bash
# 1. Salin contoh config, isi host + chat id telegram kamu
cp config.example.json config.json

# 2. Simpan token bot (@BotFather) — chmod 600 biar aman
echo "123456:ABC-your-token" > token.txt && chmod 600 token.txt

# 3. Tes kirim + cek
python3 vps_mon.py send "tes"
python3 vps_mon.py check
python3 vps_mon.py digest

# 4. Pasang cron (check tiap menit, digest jam 9 pagi)
crontab -e
# * * * * * cd /path/ke/vps-mon && python3 vps_mon.py check >> vpsmon_check.log 2>&1
# 0 9 * * * cd /path/ke/vps-mon && python3 vps_mon.py digest >> vpsmon_digest.log 2>&1
```

## Konfigurasi host

| Field | Wajib | Keterangan |
|---|---|---|
| `name` | ✔ | nama unik host |
| `ip`, `port` | ✔ | target TCP check |
| `role` | — | catatan, tampil di alert & digest |
| `lease_end` | — | `YYYY-MM-DD` tanggal habis sewa; `null` = skip lease alert |
| `mute_down` | — | `true` = tak ada alert DOWN (recover tetap di-alert) |
| `remind_hours` | — | re-alert tiap N jam selama down; `0` = off |
| `enabled` | — | `false` = dilewati (host retired) |

## Filosofi anti-spam

Host yang mati permanen tidak boleh berisik. Alert DOWN hanya dikirim sekali
saat transisi hidup→mati; setelah itu statusnya cukup muncul di digest harian.
Host yang sudah diketahui mati sejak awal cukup di-set `mute_down`.

## LICENSE

MIT — lihat [LICENSE](LICENSE).
