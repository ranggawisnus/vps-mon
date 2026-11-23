#!/usr/bin/env bash
# vps-mon interactive setup — clone & run: bash setup.sh
# Requirements: Linux + python3 only (curl optional, not needed).
set -euo pipefail
cd "$(dirname "$0")"

hr() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 tidak ditemukan. Install dulu (mis. apt install python3)."

hr "vps-mon setup"
echo "Yang dibutuhkan: bot Telegram (buat via @BotFather kalau belum punya), lalu daftar VPS kamu."

if [ -f config.json ]; then
  read -rp "config.json sudah ada. Timpa dengan setup baru? [y/N] " yn
  [ "${yn:-n}" = "y" ] || { echo "Batal — config lama dipertahankan."; exit 0; }
fi

hr "1/5 Token bot"
if [ -n "${VPSMON_TOKEN:-}" ]; then
  TOKEN=$(printf '%s' "${VPSMON_TOKEN}" | tr -d ' \t\r\n')
  echo "Token diambil dari env VPSMON_TOKEN"
else
  read -rp "Bot token (format 123456:ABC-xxx): " TOKEN
  TOKEN=$(printf '%s' "$TOKEN" | tr -d ' \t\r\n')
fi
[ -n "$TOKEN" ] || die "token kosong"
BOT_NAME=$(TOKEN="$TOKEN" python3 - <<'PY'
import json, os, sys, urllib.request
try:
    req = urllib.request.Request("https://api.telegram.org/bot%s/getMe" % os.environ["TOKEN"])
    with urllib.request.urlopen(req, timeout=15) as r:
        print(json.load(r)["result"]["username"])
except Exception:
    sys.exit(1)
PY
) || die "Token tidak valid / tidak bisa terhubung ke api.telegram.org"
echo "Token OK — bot: @$BOT_NAME"

hr "2/5 Chat ID tujuan alert"
echo "Deteksi otomatis: mencari chat yang pernah /start ke @$BOT_NAME..."
CHAT_ID=""
UPDATES=$(TOKEN="$TOKEN" python3 - <<'PY'
import json, os, sys, urllib.request, urllib.error
try:
    req = urllib.request.Request("https://api.telegram.org/bot%s/getUpdates" % os.environ["TOKEN"])
    with urllib.request.urlopen(req, timeout=15) as r:
        print(r.read().decode())
except urllib.error.HTTPError as e:
    print(json.dumps({"conflict": e.code == 409}))
except Exception:
    print(json.dumps({"conflict": False}))
PY
)
CONFLICT=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("conflict", False))' "$UPDATES")
if [ "$CONFLICT" = "True" ]; then
  echo "(getUpdates ditolak 409 — token ini sedang dipakai gateway/poller lain. Deteksi otomatis dilewati.)"
else
  CHAT_ID=$(python3 - "$UPDATES" <<'PY'
import json, sys
try:
    d = json.loads(sys.argv[1])
    for u in d.get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        cid = (m.get("chat") or {}).get("id")
        if cid:
            print(cid); break
except Exception:
    pass
PY
)
fi
if [ -n "${VPSMON_CHAT_ID:-}" ]; then
  CHAT_ID="${VPSMON_CHAT_ID}"
  echo "Chat ID diambil dari env VPSMON_CHAT_ID: $CHAT_ID"
elif [ -n "$CHAT_ID" ]; then
  echo "Terdeteksi chat ID: $CHAT_ID"
else
  read -rp "Masukkan chat ID manual (angka, tanya @userinfobot): " CHAT_ID
fi
[ -n "$CHAT_ID" ] || die "chat id kosong"

hr "3/5 Daftar VPS"
HOSTS="[]"
while true; do
  read -rp "Nama host (kosongkan untuk selesai): " NAME
  [ -z "$NAME" ] && break
  read -rp "  IP/hostname: " IP
  [ -n "$IP" ] || die "ip kosong"
  read -rp "  Port SSH [22]: " PORT
  PORT=${PORT:-22}
  read -rp "  Catatan/role (opsional): " ROLE
  read -rp "  Tanggal habis sewa YYYY-MM-DD (kosongkan = tanpa lease alert): " LEASE
  HOSTS=$(HOSTS="$HOSTS" NAME="$NAME" IP="$IP" PORT="$PORT" ROLE="$ROLE" LEASE="$LEASE" python3 - <<'PY'
import json, os
arr = json.loads(os.environ["HOSTS"])
h = {"name": os.environ["NAME"], "ip": os.environ["IP"], "port": int(os.environ["PORT"]),
     "role": os.environ["ROLE"], "enabled": True}
if os.environ["LEASE"]:
    h["lease_end"] = os.environ["LEASE"]
arr.append(h)
print(json.dumps(arr))
PY
)
done
echo "Terdaftar: $(echo "$HOSTS" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))') host"

hr "4/5 Menulis file"
CONFIG=$(CHAT_ID="$CHAT_ID" HOSTS="$HOSTS" python3 - <<'PY'
import json, os
print(json.dumps({
    "timeout": 6,
    "telegram": {"token_file": "token.txt", "chat_id": os.environ["CHAT_ID"]},
    "hosts": json.loads(os.environ["HOSTS"]),
}, indent=2))
PY
)
printf '%s\n' "$CONFIG" > config.json
printf '%s\n' "$TOKEN" > token.txt
chmod 600 token.txt config.json
echo "config.json + token.txt (chmod 600) ditulis."

hr "5/5 Tes"
echo "Kirim pesan tes..."
python3 vps_mon.py send "✅ vps-mon setup selesai di $(hostname) — alert akan masuk ke chat ini."
python3 vps_mon.py check && echo "Check pertama OK (data masuk vps.db)."

read -rp "Pasang cron otomatis (check tiap menit + digest 09:00)? [Y/n] " yn
if [ "${yn:-y}" = "y" ]; then
  command -v crontab >/dev/null || die "crontab tidak tersedia; pasang cron manual (lihat README)."
  DIR=$(pwd)
  ( { crontab -l 2>/dev/null | grep -v 'vps_mon.py' || true; } ; \
    echo "* * * * * cd $DIR && python3 vps_mon.py check >> vpsmon_check.log 2>&1" ; \
    echo "0 9 * * * cd $DIR && python3 vps_mon.py digest >> vpsmon_digest.log 2>&1" ) | crontab -
  echo "Cron terpasang ✓  (crontab -l untuk melihat)"
fi

printf '\n\033[32mSelesai!\033[0m Alert DOWN/recover/lease akan masuk ke Telegram kamu.\n'
echo "Perintah manual: python3 vps_mon.py check | digest | send \"pesan\""
