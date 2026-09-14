"""Kirim notifikasi Telegram untuk rilis yang baru keluar.

Membaca daftar rilis dari NOTIFY_FILE (ditulis oleh update.py).
Butuh secret TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID; kalau belum diisi, keluar tanpa error.
Token tidak pernah dicetak ke log.
"""

import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SITE = os.environ.get("SITE_URL", "https://miracle7788.github.io/news-xauusd/kalender.html")
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
IMP = {"hi": "TINGGI", "md": "SEDANG", "lo": "RENDAH"}
ARAH = {
    "dn": "▼ <b>Tekanan turun untuk emas</b> (hawkish)",
    "up": "▲ <b>Dorongan naik untuk emas</b> (dovish)",
    "nt": "• Netral",
}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def num(v):
    if v in (None, "", "—"):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace("−", "-").replace(",", "."))
    return float(m.group(0)) if m else None


def versus(a, c):
    na, nc = num(a), num(c)
    if na is None or nc is None:
        return "tanpa konsensus"
    if abs(na - nc) < 1e-9:
        return "sesuai konsensus"
    return "di atas konsensus" if na > nc else "di bawah konsensus"


def build_message(events):
    events = sorted(events, key=lambda e: (e["date"], e["t"], {"hi": 0, "md": 1, "lo": 2}.get(e["i"], 3)))
    d = dt.date.fromisoformat(events[0]["date"])
    head = f"<b>NEWS USD KELUAR · {HARI[d.weekday()]} {d.day} {BLN[d.month - 1]} {esc(events[0]['t'])} WIB</b>"
    blocks = [head]
    for e in events:
        ref = f" ({esc(e['r'])})" if e.get("r") else ""
        blocks.append(
            f"\n<b>{esc(e['e'])}</b>{ref} · {IMP.get(e['i'], '')}\n"
            f"Aktual <b>{esc(e['a'])}</b> | Konsensus {esc(e['c'])} | Prev {esc(e['p'])}\n"
            f"{ARAH.get(e['x'], '• Netral')} — {versus(e['a'], e['c'])}"
        )
    blocks.append(f"\n<i>Arah emas dihitung mekanis dari selisih aktual vs konsensus, bukan perintah entry.</i>\n{SITE}")
    return "\n".join(blocks)


def split(text, limit=4000):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts


def send(token, chat, text):
    data = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        body = json.loads(err.read().decode() or "{}")
    if not body.get("ok"):
        sys.exit(f"Telegram menolak pesan: {body.get('error_code')} {body.get('description')}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    dry = os.environ.get("DRY_RUN") == "1"

    if os.environ.get("TEST_TELEGRAM") == "true":
        text = ("<b>Tes notifikasi news XAUUSD</b>\n"
                "Kalau pesan ini masuk, robot kalender sudah tersambung ke Telegram.\n" + SITE)
        groups = [text]
    else:
        path = pathlib.Path(os.environ.get("NOTIFY_FILE", "notify.json"))
        if not path.exists():
            print("Tidak ada rilis baru untuk dikirim.")
            return
        events = json.loads(path.read_text(encoding="utf-8"))
        if not events:
            print("Tidak ada rilis baru untuk dikirim.")
            return
        by_slot = {}
        for e in events:
            by_slot.setdefault((e["date"], e["t"]), []).append(e)
        groups = [build_message(v) for _, v in sorted(by_slot.items())]

    if dry:
        print("\n\n=====\n\n".join(groups))
        return
    if not token or not chat:
        print("Secret TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi - notifikasi dilewati.")
        return

    for text in groups:
        for part in split(text):
            send(token, chat, part)
    print(f"Terkirim {len(groups)} pesan ke Telegram.")


if __name__ == "__main__":
    main()
