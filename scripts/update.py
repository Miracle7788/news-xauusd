"""Tarik kalender ekonomi AS dari TradingEconomics dan perbarui data/events.json.

Jalan di GitHub Actions tiap 15 menit. Hanya pustaka standar Python.
File JSON hanya ditulis kalau ada angka yang berubah, supaya tidak ada commit kosong.
"""

import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "events.json"
URL = "https://tradingeconomics.com/united-states/calendar"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

WIB = dt.timezone(dt.timedelta(hours=7))
LOOKBACK_DAYS = 10
LOOKAHEAD_DAYS = 28

# data-event TradingEconomics -> (nama tampil, dampak, polaritas)
# polaritas +1: aktual di atas konsensus = hawkish = emas tertekan
# polaritas -1: kebalikannya (pengangguran)
# polaritas 0 : tanpa arah
TRACKED = {
    "non farm payrolls": ("Non-Farm Payrolls", "hi", 1),
    "unemployment rate": ("Tingkat Pengangguran", "hi", -1),
    "average hourly earnings yoy": ("Upah per Jam y/y", "md", 1),
    "average hourly earnings mom": ("Upah per Jam m/m", "md", 1),
    "adp employment change": ("ADP", "md", 1),
    "jolts job openings": ("JOLTS Lowongan Kerja", "md", 1),
    "initial jobless claims": ("Klaim Pengangguran Awal", "md", 1),
    "inflation rate yoy": ("CPI y/y", "hi", 1),
    "inflation rate mom": ("CPI m/m", "hi", 1),
    "core inflation rate yoy": ("Core CPI y/y", "hi", 1),
    "core inflation rate mom": ("Core CPI m/m", "hi", 1),
    "ppi yoy": ("PPI y/y", "md", 1),
    "ppi mom": ("PPI m/m", "hi", 1),
    "core ppi yoy": ("Core PPI y/y", "lo", 1),
    "core ppi mom": ("Core PPI m/m", "md", 1),
    "retail sales mom": ("Retail Sales m/m", "md", 1),
    "ism manufacturing pmi": ("ISM Manufaktur", "md", 1),
    "ism services pmi": ("ISM Jasa", "md", 1),
    "michigan consumer sentiment prel": ("Sentimen Michigan", "lo", 1),
    "pce price index yoy": ("PCE Price Index y/y", "md", 1),
    "core pce price index yoy": ("Core PCE y/y", "hi", 1),
    "core pce price index mom": ("Core PCE m/m", "hi", 1),
    "fed interest rate decision": ("FOMC · keputusan", "hi", 1),
    "fomc minutes": ("Notulen FOMC", "lo", 0),
    "gdp growth rate qoq adv": ("GDP q/q · awal", "lo", 1),
    "gdp growth rate qoq 2nd est": ("GDP q/q · revisi", "lo", 1),
    "gdp growth rate qoq final": ("GDP q/q · final", "lo", 1),
}

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = {"JAN": "Jan", "FEB": "Feb", "MAR": "Mar", "APR": "Apr", "MAY": "Mei", "JUN": "Jun",
         "JUL": "Jul", "AUG": "Agu", "SEP": "Sep", "OCT": "Okt", "NOV": "Nov", "DEC": "Des"}


def fetch_html(start, end):
    req = urllib.request.Request(URL, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": f"cal-custom-range={start}|{end}; cal-timezone-offset=0",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def cell(row, ident):
    m = re.search(r"id='%s'[^>]*>([^<]*)<" % ident, row)
    return m.group(1).strip() if m else ""


def parse_rows(html):
    starts = [m.start() for m in re.finditer(r"<tr[^>]*data-url=", html)] + [len(html)]
    rows = []
    for a, b in zip(starts, starts[1:]):
        r = html[a:b]
        ev = re.search(r'data-event="([^"]+)"', r)
        day = re.search(r"class='\s*(\d{4}-\d\d-\d\d)'", r)
        tm = re.search(r'calendar-date-\d">\s*([^<]+?)\s*<', r)
        if not (ev and day and tm):
            continue
        ref = re.search(r'calendar-reference">([^<]*)<', r)
        rows.append({
            "event": ev.group(1).strip().lower(),
            "day": day.group(1),
            "time": tm.group(1).strip(),
            "ref": ref.group(1).strip() if ref else "",
            "actual": cell(r, "actual"),
            "previous": cell(r, "previous"),
            "consensus": cell(r, "consensus"),
        })
    return rows


def to_wib(day, time_str):
    try:
        t = dt.datetime.strptime(f"{day} {time_str}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        return None
    return t.replace(tzinfo=dt.timezone.utc).astimezone(WIB)


def fmt(v):
    """'0.4%' -> '0,4%', '-0.6%' -> '−0,6%', '7.271M' -> '7,27 jt'."""
    v = (v or "").strip()
    if not v:
        return "—"
    m = re.fullmatch(r"(-?)(\d+(?:\.\d+)?)M", v)
    if m:
        v = f"{m.group(1)}{float(m.group(2)):.2f} jt"
    return v.replace("-", "−").replace(".", ",")


def num(v):
    if v in (None, "", "—"):
        return None
    s = str(v).replace("−", "-").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def direction(actual, consensus, polarity):
    if actual in (None, "", "—"):
        return "?"
    a, c = num(actual), num(consensus)
    if polarity == 0 or a is None or c is None:
        return "nt"
    if abs(a - c) < 1e-9:
        return "nt"
    hawkish = (a > c) if polarity > 0 else (a < c)
    return "dn" if hawkish else "up"


def ref_label(key, ref):
    ref = ref.upper()
    if key == "initial jobless claims":
        m = re.fullmatch(r"([A-Z]{3})/(\d\d)", ref)
        return f"pekan {int(m.group(2))} {BULAN.get(m.group(1), m.group(1))}" if m else ref.lower()
    if key == "michigan consumer sentiment prel" and ref in BULAN:
        return f"{BULAN[ref]} awal"
    if re.fullmatch(r"Q\d", ref):
        return ref
    return BULAN.get(ref, ref.title() if ref else "")


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=LOOKBACK_DAYS)
    end = today + dt.timedelta(days=LOOKAHEAD_DAYS)

    html = fetch_html(start.isoformat(), end.isoformat())
    rows = parse_rows(html)
    if not rows:
        sys.exit("Tidak ada baris kalender yang terbaca - struktur halaman mungkin berubah.")

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    events = doc["events"]
    changed = []
    released = []
    now_wib = dt.datetime.now(WIB)

    def fresh(when):
        # Hanya rilis 6 jam terakhir yang dinotifikasi, supaya isi ulang data lama tidak memicu spam.
        return dt.timedelta(minutes=-10) <= now_wib - when <= dt.timedelta(hours=6)

    for row in rows:
        key = row["event"]
        if key not in TRACKED:
            continue
        name, impact, pol = TRACKED[key]
        when = to_wib(row["day"], row["time"])
        if when is None:
            continue
        date = when.date()

        tol = 2 if key == "initial jobless claims" else 12
        match = None
        for ev in events:
            if ev.get("key") != key:
                continue
            d = dt.date.fromisoformat(ev["date"])
            if abs((d - date).days) <= tol:
                match = ev
                break

        new = {
            "date": date.isoformat(),
            "t": when.strftime("%H.%M"),
            "p": fmt(row["previous"]),
            "c": fmt(row["consensus"]),
            "a": fmt(row["actual"]) if row["actual"] else None,
        }
        new["x"] = direction(new["a"], new["c"], pol)

        if match is None:
            ev = {"date": new["date"], "t": new["t"], "key": key, "e": name,
                  "r": ref_label(key, row["ref"]), "i": impact,
                  "p": new["p"], "c": new["c"], "a": new["a"], "x": new["x"]}
            if key.startswith("gdp") and row["ref"]:
                ev["e"] = f'{name.split(" · ")[0]} · {row["ref"].upper()} {name.split(" · ")[1]}'
            events.append(ev)
            if ev["a"] is not None and fresh(when):
                released.append(ev)
            changed.append(f'+ {ev["date"]} {ev["e"]}')
            continue

        # Baris yang sudah punya aktual dikunci: sejarah tidak ditulis ulang dari sumber lain.
        if match.get("a") is not None:
            continue

        # Jangan timpa angka yang sudah ada dengan sel kosong dari sumber.
        for field in ("p", "c"):
            if new[field] == "—" and match.get(field) not in (None, "", "—"):
                new[field] = match[field]
        if new["a"] is None and match.get("a") is not None:
            new["a"] = match["a"]
        new["x"] = direction(new["a"], new["c"], pol)

        before = {k: match.get(k) for k in new}
        if before != new or match.get("est"):
            match.update(new)
            if new["a"] is not None and fresh(when):
                released.append(match)
            match.pop("est", None)
            changed.append(f'~ {match["date"]} {match["e"]}: {before} -> {new}')

    notify_file = os.environ.get("NOTIFY_FILE")
    if notify_file and released:
        pathlib.Path(notify_file).write_text(json.dumps(released, ensure_ascii=False), encoding="utf-8")
        print(f"{len(released)} rilis baru dicatat untuk notifikasi.")

    if not changed:
        print(f"Tidak ada perubahan ({len(rows)} baris dibaca).")
        return

    events.sort(key=lambda ev: (ev["date"], ev["t"] if ev["t"][0].isdigit() else "00.00"))
    doc["updated"] = dt.datetime.now(WIB).isoformat(timespec="minutes")
    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n".join(changed))


if __name__ == "__main__":
    main()
