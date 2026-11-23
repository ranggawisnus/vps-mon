#!/usr/bin/env python3
"""vps-mon — alive-check + lease reminder untuk semua VPS. stdlib only, Python 3.12.

Filosofi alert (anti-spam):
  - DOWN  : alert HANYA sekali saat transisi hidup->mati. Tidak ada repeat berkala.
  - RECOVER: alert saat mati->hidup (juga untuk host yang di-mute).
  - Host yang sudah tahu mati: set "mute_down": true di config -> tak ada alert DOWN,
    tapi kalau tiba-tiba hidup lagi tetap di-alert (kejutan).
  - remind_hours (opsional per host): re-alert tiap N jam selama masih down. 0 = off.
  - Status down yang persisten tetap tampil di digest harian (09:00 WIB).

Usage:
  python3 vps_mon.py check    # cek semua host (cron tiap menit)
  python3 vps_mon.py digest   # ringkasan harian + lease countdown (cron 09:00 WIB)
  python3 vps_mon.py send "text"  # kirim pesan tes ke Telegram
"""
import html
import json
import socket
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text())
DB = BASE / "vps.db"
WIB = timezone(timedelta(hours=7))
LEASE_ALERT_DAYS = {14, 7, 3, 1, 0}


def db():
    c = sqlite3.connect(DB, timeout=20)
    c.execute("CREATE TABLE IF NOT EXISTS events(ts INTEGER, host TEXT, up INTEGER, latency_ms INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS state(host TEXT PRIMARY KEY, fail_streak INTEGER DEFAULT 0,"
              " last_up INTEGER, last_change INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS alerts(ts INTEGER, host TEXT, kind TEXT, msg TEXT)")
    return c


def tg_send(text: str) -> bool:
    tf = BASE / CFG["telegram"].get("token_file", "token.txt")
    tok = tf.read_text().strip().replace("\r", "").replace("\n", "").replace(" ", "")
    chat = CFG["telegram"]["chat_id"]
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = bool(json.loads(r.read()).get("ok"))
            if not ok:
                print("TG send returned not-ok", file=sys.stderr)
            return ok
    except Exception as e:  # noqa: BLE001
        print(f"TG send failed: {e}", file=sys.stderr)
        return False


def notify(c, host: str, kind: str, msg: str):
    """Catat alert lalu kirim. Row dicatat hanya jika terkirim (biar bisa retry logis)."""
    if tg_send(msg):
        c.execute("INSERT INTO alerts(ts, host, kind, msg) VALUES(?,?,?,?)",
                  (int(time.time()), host, kind, msg))
        c.commit()


def check_one(ip: str, port: int, timeout: int):
    t0 = time.time()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return 1, max(1, int((time.time() - t0) * 1000))
    except OSError:
        return 0, None


def fmt_since(ts: int) -> str:
    if not ts:
        return "?"
    delta = int(time.time()) - ts
    if delta < 3600:
        return f"{delta // 60}m lalu"
    if delta < 86400:
        return f"{delta // 3600}j {(delta % 3600) // 60}m lalu"
    return f"{delta // 86400}hari lalu"


def cmd_check():
    c = db()
    ts = int(time.time())
    for h in CFG["hosts"]:
        if not h.get("enabled", True):
            continue
        name = h["name"]
        up, lat = check_one(h["ip"], h.get("port", 22), CFG.get("timeout", 6))
        c.execute("INSERT INTO events VALUES(?,?,?,?)", (ts, name, up, lat))
        row = c.execute("SELECT fail_streak, last_up, last_change FROM state WHERE host=?", (name,)).fetchone()
        old_streak = row[0] if row else 0
        prev_up = row[1] if row else None
        prev_change = row[2] if row else None
        streak = 0 if up else old_streak + 1
        changed = prev_up is not None and bool(prev_up) != bool(up)
        new_change = ts if (changed or prev_change is None) else prev_change
        c.execute("INSERT INTO state(host,fail_streak,last_up,last_change) VALUES(?,?,?,?)"
                  " ON CONFLICT(host) DO UPDATE SET fail_streak=excluded.fail_streak,"
                  " last_up=excluded.last_up, last_change=excluded.last_change",
                  (name, streak, up, new_change))
        c.commit()
        note = html.escape(h.get("note") or h.get("role") or "")
        mute_down = bool(h.get("mute_down"))
        remind_hours = int(h.get("remind_hours") or 0)
        if not up:
            if changed and not mute_down:
                msg = (f"\U0001F534 <b>{name}</b> DOWN\n"
                       f"{h['ip']}:{h.get('port', 22)}"
                       + (f"\n<i>{note}</i>" if note else ""))
                notify(c, name, f"down:{name}:{ts}", msg)
            elif not mute_down and remind_hours and streak > 2:
                last = c.execute("SELECT MAX(ts) FROM alerts WHERE kind LIKE ?",
                                 (f"down:{name}:%",)).fetchone()[0]
                if last and ts - last >= remind_hours * 3600:
                    msg = (f"\U0001F501 <b>{name}</b> masih DOWN ({streak}x, sejak {fmt_since(new_change)})\n"
                           f"<i>reminder {remind_hours}j</i>")
                    notify(c, name, f"down:{name}:remind:{ts}", msg)
        elif up and prev_up == 0:
            dur = fmt_since(prev_change or ts)
            msg = f"\U0001F7E2 <b>{name}</b> RECOVER — up lagi (sebelumnya down ~{dur})"
            notify(c, name, f"recover:{name}:{ts}", msg)
    c.close()


def lease_info(h) -> tuple:
    """Return (display, days_left or None)."""
    le = h.get("lease_end")
    if not le:
        return "\u2753 belum diisi", None
    end = date.fromisoformat(str(le))
    days = (end - date.today()).days
    if days < 0:
        return f"\u26A0\uFE0F EXPIRED {abs(days)} hari lalu ({end.isoformat()})", days
    return f"T-{days} ({end.isoformat()})", days


def cmd_digest():
    c = db()
    ts = int(time.time())
    lines = [f"\U0001F6F0 <b>VPS Report — {datetime.now(WIB).strftime('%a %d %b %Y %H:%M')} WIB</b>", ""]
    for h in CFG["hosts"]:
        if not h.get("enabled", True):
            continue
        name = h["name"]
        row = c.execute("SELECT last_up, last_change, fail_streak FROM state WHERE host=?", (name,)).fetchone()
        if row is None:
            status = "\u26AA belum ada data"
            extra = ""
        else:
            last_up, last_change, streak = row
            if last_up:
                ev = c.execute("SELECT latency_ms FROM events WHERE host=? AND up=1 ORDER BY ts DESC LIMIT 1",
                               (name,)).fetchone()
                lat = ev[0] if ev else None
                status = "\u2705 UP"
                extra = f" — {lat}ms" if lat else ""
                if streak:
                    extra += f" (streak {streak})"
            else:
                status = "\U0001F534 DOWN"
                extra = f" — mati sejak {fmt_since(last_change)}"
                if h.get("mute_down"):
                    extra += " [muted]"
        lease_txt, days = lease_info(h)
        role = html.escape(h.get("role") or "")
        lines.append(f"{status} <b>{name}</b>{extra}")
        if role:
            lines.append(f"    {role}")
        lines.append(f"    sewa: {lease_txt}")
        lines.append("")
        if days is not None and (days in LEASE_ALERT_DAYS or days < 0):
            kind = f"lease:{name}:{days}:{date.today().isoformat()}"
            if days < 0:
                msg = (f"\u26A0\uFE0F <b>Sewa {name} SUDAH HABIS</b> {abs(days)} hari lalu!\n"
                       f"Berakhir {h.get('lease_end')} — perpanjang atau migrasi?")
            else:
                msg = (f"\u23F0 <b>Sewa {name} habis dalam {days} hari</b>\n"
                       f"Tanggal akhir: {h.get('lease_end')}")
            notify(c, name, kind, msg)
    # retensi data 14 hari
    c.execute("DELETE FROM events WHERE ts < ?", (ts - 14 * 86400,))
    c.execute("DELETE FROM alerts WHERE ts < ?", (ts - 14 * 86400,))
    c.commit()
    c.close()
    tg_send("\n".join(lines).rstrip())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        cmd_check()
    elif cmd == "digest":
        cmd_digest()
    elif cmd == "send":
        tg_send(sys.argv[2])
    else:
        sys.exit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    main()
