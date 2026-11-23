# AGENT.md — instruksi untuk AI agent (Claude Code, Cursor, Codex, Hermes, dll)

Halaman ini ditulis untuk AI agent yang diminta user memasang **vps-mon**.
User-facing docs ada di [README.md](README.md) — halaman ini fokus ke langkah eksekusi + aturan keselamatan.

## Apa ini

vps-mon = monitor VPS ringan (stdlib-only Python): alive-check per menit via TCP,
pengingat tanggal habis sewa, alert Telegram anti-spam (DOWN sekali saat transisi,
recover selalu di-alert, opsi `mute_down` per host).

## Prasyarat

- Linux/macOS + python3 (>=3.8, stdlib only — TIDAK perlu `pip install` apa pun)
- Bot Telegram token (user dapat dari @BotFather; jika belum ada, MINTA ke user — jangan buat sendiri)
- `crontab` tersedia (opsional, untuk auto-install cron)

## Langkah pemasangan

1. `git clone https://github.com/ranggawisnus/vps-mon.git && cd vps-mon`
2. Jalankan `bash setup.sh`. Wizard interaktif meminta:
   - token bot (validasi via `getMe`; sanitasi CRLF otomatis)
   - chat id Telegram (auto-detect dari riwayat `/start`; fallback: minta manual ke user)
   - daftar host (nama, IP, port, catatan, `lease_end` `YYYY-MM-DD` bila diketahui)
   Wizard menulis `config.json` + `token.txt` (chmod 600) lalu mengetes kirim alert.
   - Headless alternative: `VPSMON_TOKEN=... VPSMON_CHAT_ID=... bash setup.sh`
3. Setuju auto-install cron bila user ingin check per menit + digest harian.
4. Verifikasi:
   - `python3 vps_mon.py check` → exit 0, `vps.db` berisi baris events
   - `python3 vps_mon.py send "tes"` → user menerima pesan
   - `crontab -l` menampilkan 2 baris vps_mon (jika cron dipilih)

## Aturan keselamatan (WAJIB)

- JANGAN pernah commit/menampilkan `config.json`, `token.txt`, `vps.db` — ketiganya sudah di-.gitignore; pertahankan.
- Token bot hanya dikirim ke `api.telegram.org`; jangan menuliskannya ke log, output, atau file lain.
- `token.txt` dan `config.json` harus tetap chmod 600.
- Jangan mengubah logika alert tanpa diminta (DOWN-once semantics = fitur, bukan bug).
- Host yang sudah diketahui mati sejak awal → set `"mute_down": true`, bukan menghapus alert.
- Contoh `lease_end` di config milik user; bila tidak yakin tanggalnya, tanyakan — jangan mengarang.

## Troubleshooting singkat

- `Token tidak valid` → token salah/ter-copas dengan spasi; wizard sudah men-strip whitespace.
- Alert tidak masuk → pastikan user sudah `/start` bot minimal sekali; chat id harus angka (DM user) atau `-100...` (grup).
- `getUpdates` 409 → token dipakai poller lain (mis. gateway); wizard otomatis fallback ke input manual chat id.
- Statistik/digest tidak jalan → cek `vpsmon_check.log` / `vpsmon_digest.log`.
