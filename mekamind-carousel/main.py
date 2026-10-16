#!/usr/bin/env python3
"""MekaMind carousel automation.

  python main.py list                          # show series + progress
  python main.py new "اسم السلسلة" --topics topics.txt [--days sun,tue,thu --time 20:00]
  python main.py add  <slug> --topics more.txt # add episodes to an existing series
  python main.py render <slug> [--ep 1]        # PNGs only, into out/<slug>/epNN
  python main.py send   <slug> [--ep 1] [--dry-run]
  python main.py tick                          # run every 30 min (cron): sends what is due
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import render

def _load_env():
    """Read KEY=VALUE lines from .env next to this file (works the same on Windows/Mac/Linux)."""
    d = Path(__file__).parent
    f = next((x for x in (d / ".env", d / ".env.txt") if x.exists()), None)  # Notepad may add .txt
    if not f:
        return
    raw = f.read_bytes()
    try:
        text = raw.decode("utf-8-sig")  # utf-8-sig: Notepad adds a hidden BOM
    except UnicodeDecodeError:
        text = raw.decode("utf-16")     # Notepad "Unicode" save
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v)[0].strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)

_load_env()

ROOT = Path(__file__).parent
SERIES_DIR = ROOT / "series"
STATE_FILE = ROOT / "data" / "state.json"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

# ---------- storage ----------
def load_series(slug):
    return json.loads((SERIES_DIR / f"{slug}.json").read_text(encoding="utf-8"))

def save_series(s):
    (SERIES_DIR / f"{s['slug']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

def save_state(st):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2))

def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "series-" + datetime.now().strftime("%Y%m%d%H%M")

# ---------- Telegram ----------
def tg(method, **kw):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", timeout=120, **kw)
    r.raise_for_status()
    return r.json()

def send_episode(series, ep_index, paths, preview=False):
    chat = os.environ["TELEGRAM_CHAT_ID"]
    ep = series["episodes"][ep_index]
    header = ("👀 معاينة — " if preview else "📌 ") + f"{series['name']} — الحلقة {ep_index + 1}/{len(series['episodes'])}\n{ep['title']}"
    tg("sendMessage", data={"chat_id": chat, "text": header})
    for start in range(0, len(paths), 10):  # Telegram albums max 10 images
        chunk = paths[start:start + 10]
        media, files = [], {}
        for i, p in enumerate(chunk):
            media.append({"type": "photo", "media": f"attach://f{i}"})
            files[f"f{i}"] = open(p, "rb")
        tg("sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media)}, files=files)
    # caption as a separate plain message so it can be copied easily
    tg("sendMessage", data={"chat_id": chat, "text": ep["caption"]})

# ---------- content generation (Claude API) ----------
SCHEMA = """Slide types (JSON objects). Episode = 6 to 9 slides, in this order: one cover, 3-4 content slides, then optionally compare / stats, one note, one cta.
- {"type":"cover","kicker":"الحلقة N","title":"...","subtitle":"..."}
- {"type":"point","num":"01","title":"...","icon":"<chip|wifi|bell|shield|bolt|gear|phone|chart|thermo|drop|cloud|wave>","chip":"short English label","body":"1-2 short sentences","tip":"one short line"}
- {"type":"compare","title":"...","left":"...","right":"...","rows":[["a","b"],...3-5 rows]}
- {"type":"stats","title":"...","unit":"%","bars":[{"label":"...","value":number,"hi":true on the highlighted one}],"takeaway":"...","source":"..."}
- {"type":"note","title":"...","sticky":"short sticky-note text","bullets":["3 short lines"]}
- {"type":"cta","title":"...","lines":["3 short lines"]}
Use **word** to highlight 1-2 key words per title. Keep every text short (it sits on a social image)."""

def generate_episodes(series_name, topics, start_num):
    brand = (ROOT / "brand" / "voice.md").read_text(encoding="utf-8")
    prompt = f"""{brand}

Series name: {series_name}
Write one carousel episode per topic below. Episode numbers start at {start_num}.
Topics:
{chr(10).join(f'- {t}' for t in topics)}

{SCHEMA}

Rules: no invented statistics or client names; if a stats slide is used with illustrative numbers, say so in "source". Explain every technical term the first time it appears.
Return ONLY a JSON array; each item: {{"title":"...","caption":"Facebook/Instagram caption in the brand voice with hashtags","slides":[...]}}."""
    if os.environ.get("GEMINI_API_KEY"):  # free-tier option
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          params={"key": os.environ["GEMINI_API_KEY"]}, timeout=300,
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseMimeType": "application/json"}})
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=300, headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"])
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)

def read_topics(path):
    return [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

def create_series(name, topics, days=("sun", "tue", "thu"), time="20:00"):
    slug = slugify(name)
    s = {"name": name, "slug": slug, "tag": name,
         "schedule": {"days": list(days), "time": time, "tz": "Africa/Cairo"},
         "episodes": generate_episodes(name, topics, 1)}
    save_series(s)
    return s

# ---------- commands ----------
def cmd_new(a):
    s = {"name": a.name, "slug": a.slug or slugify(a.name), "tag": a.tag or a.name,
         "schedule": {"days": a.days.split(","), "time": a.time, "tz": "Africa/Cairo"}, "episodes": []}
    s["episodes"] = generate_episodes(a.name, read_topics(a.topics), 1)
    save_series(s)
    print(f"saved series/{s['slug']}.json with {len(s['episodes'])} episodes")

def cmd_add(a):
    s = load_series(a.slug)
    s["episodes"] += generate_episodes(s["name"], read_topics(a.topics), len(s["episodes"]) + 1)
    save_series(s)
    print(f"{a.slug}: now {len(s['episodes'])} episodes")

def cmd_render(a):
    s = load_series(a.slug)
    idx = [a.ep - 1] if a.ep else range(len(s["episodes"]))
    for i in idx:
        render.render_episode(s, i, ROOT / "out" / a.slug / f"ep{i + 1:02d}")
        print(f"rendered ep{i + 1:02d}")

def do_send(slug, i, dry):
    s = load_series(slug)
    paths = render.render_episode(s, i, ROOT / "out" / slug / f"ep{i + 1:02d}")
    if dry:
        print(f"dry-run: {len(paths)} images in out/{slug}/ep{i + 1:02d}")
        return
    send_episode(s, i, paths)
    st = load_state()
    st.setdefault(slug, {"sent": []})["sent"].append({"ep": i + 1, "at": datetime.now().isoformat(timespec="minutes")})
    save_state(st)
    print(f"sent {slug} ep{i + 1}")

def cmd_send(a):
    s = load_series(a.slug)
    sent = {x["ep"] for x in load_state().get(a.slug, {}).get("sent", [])}
    i = (a.ep - 1) if a.ep else next((k for k in range(len(s["episodes"])) if k + 1 not in sent), None)
    if i is None:
        sys.exit("all episodes already sent")
    do_send(a.slug, i, a.dry_run)

def cmd_list(_):
    st = load_state()
    for f in sorted(SERIES_DIR.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        n = len(st.get(s["slug"], {}).get("sent", []))
        sc = s["schedule"]
        print(f"{s['slug']}: {s['name']} | {n}/{len(s['episodes'])} sent | {','.join(sc['days'])} @ {sc['time']}")

def cmd_tick(a):
    tick(a.ignore_time)

def tick(ignore_time=False):
    """Cron entry point: for each series, send the next episode once per due day, after the set time."""
    st = load_state()
    for f in sorted(SERIES_DIR.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        sc = s["schedule"]
        now = datetime.now(ZoneInfo(sc["tz"]))
        if DAYS[now.weekday()] not in sc["days"] or (not ignore_time and now.strftime("%H:%M") < sc["time"]):
            continue
        sent = st.get(s["slug"], {}).get("sent", [])
        if any(x["at"][:10] == now.strftime("%Y-%m-%d") for x in sent):
            continue  # already sent today
        done = {x["ep"] for x in sent}
        nxt = next((k for k in range(len(s["episodes"])) if k + 1 not in done), None)
        if nxt is not None:
            do_send(s["slug"], nxt, False)
            st = load_state()

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("name"); n.add_argument("--topics", required=True)
    n.add_argument("--slug"); n.add_argument("--tag"); n.add_argument("--days", default="sun,tue,thu"); n.add_argument("--time", default="20:00")
    n.set_defaults(f=cmd_new)
    ad = sub.add_parser("add"); ad.add_argument("slug"); ad.add_argument("--topics", required=True); ad.set_defaults(f=cmd_add)
    r = sub.add_parser("render"); r.add_argument("slug"); r.add_argument("--ep", type=int); r.set_defaults(f=cmd_render)
    s = sub.add_parser("send"); s.add_argument("slug"); s.add_argument("--ep", type=int); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_send)
    sub.add_parser("list").set_defaults(f=cmd_list)
    tk = sub.add_parser("tick"); tk.add_argument("--ignore-time", action="store_true"); tk.set_defaults(f=cmd_tick)
    a = p.parse_args()
    a.f(a)

if __name__ == "__main__":
    main()
