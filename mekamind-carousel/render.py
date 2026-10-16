"""MekaMind carousel renderer: JSON slides -> 1080x1350 PNGs (brand template)."""
import html
import re
from pathlib import Path

from jinja2 import Template
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
W, H = 1080, 1350
HANDLE = "@mekamind.systems"

ICONS = {  # 24x24 stroke icons; keys are used in the "icon" field of a slide
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "wifi": '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10.5 10.5 0 0 1 14 0M8.5 16a5.5 5.5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1.2"/>',
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5L16 9.5"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "gear": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18.5h2"/>',
    "chart": '<path d="M3 21h18M6 17v-5M11 17V8M16 17v-8M21 17V4"/>',
    "thermo": '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "cloud": '<path d="M7 18a4 4 0 0 1-.5-8A5.5 5.5 0 0 1 17 8.5 4.5 4.5 0 0 1 17.5 18z"/>',
    "wave": '<path d="M2 12h3l2-6 4 12 3-9 2 3h6"/>',
}

CSS = """
@font-face{font-family:Cairo;font-weight:400;src:url(fonts/cairo-arabic-400-normal.woff2)}
@font-face{font-family:Cairo;font-weight:600;src:url(fonts/cairo-arabic-600-normal.woff2)}
@font-face{font-family:Cairo;font-weight:700;src:url(fonts/cairo-arabic-700-normal.woff2)}
@font-face{font-family:Cairo;font-weight:800;src:url(fonts/cairo-arabic-800-normal.woff2)}
@font-face{font-family:Montserrat;font-weight:500;src:url(fonts/montserrat-latin-500-normal.woff2)}
@font-face{font-family:Montserrat;font-weight:600;src:url(fonts/montserrat-latin-600-normal.woff2)}
@font-face{font-family:Montserrat;font-weight:700;src:url(fonts/montserrat-latin-700-normal.woff2)}
@font-face{font-family:Ruqaa;font-weight:400;src:url(fonts/aref-ruqaa-arabic-400-normal.woff2)}
@font-face{font-family:Ruqaa;font-weight:700;src:url(fonts/aref-ruqaa-arabic-700-normal.woff2)}
:root{--navy:#0A1F4D;--cyan:#04DBEF;--teal:#2CC2CA;--ice:#C8F8F8;--slate:#2F3749;--white:#FEFEFE;--warm:#F6F7F4}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;direction:rtl}
body{font-family:Cairo,Montserrat,sans-serif;color:var(--slate)}
.slide{position:relative;width:1080px;height:1350px;overflow:hidden;padding:64px 72px}
.light{background:
  radial-gradient(900px 600px at 0% 0%,rgba(200,248,248,.75),transparent 70%),
  radial-gradient(700px 500px at 100% 100%,rgba(200,248,248,.55),transparent 70%),
  var(--warm)}
.light::before{content:"";position:absolute;inset:0;opacity:.5;
  background-image:radial-gradient(rgba(10,31,77,.10) 2px,transparent 2px);background-size:44px 44px}
.dark{background:linear-gradient(160deg,#0C2766 0%,#0A1F4D 45%,#06143A 100%);color:#fff}
.dark .circuit{position:absolute;inset:0;opacity:.9}
.top{position:relative;display:flex;justify-content:space-between;align-items:center;z-index:2}
.tag{display:flex;align-items:center;gap:12px;font-weight:700;font-size:26px;color:var(--navy);
  background:#fff;border:2px solid var(--ice);border-radius:40px;padding:8px 22px}
.tag i{width:14px;height:14px;border-radius:50%;background:var(--cyan);display:block}
.dark .tag{background:rgba(255,255,255,.08);border-color:rgba(4,219,239,.4);color:#fff}
.count{font-family:Montserrat;font-weight:600;font-size:26px;color:var(--teal);letter-spacing:2px;direction:ltr}
.foot{position:absolute;left:72px;right:72px;bottom:54px;display:flex;justify-content:space-between;align-items:center;z-index:2;
  font-family:Montserrat;font-weight:500;font-size:24px;color:var(--slate);direction:ltr}
.dark .foot{color:rgba(255,255,255,.75)}
.foot .arrow{font-family:Cairo;font-weight:800;font-size:44px;color:var(--cyan);line-height:1}
.foot img{height:44px;opacity:.95}
b,.hl{font-weight:800;color:var(--navy);background:linear-gradient(transparent 62%,rgba(4,219,239,.38) 62%);padding:0 4px}
.dark b,.dark .hl{color:var(--cyan);background:none}
.body{position:relative;z-index:2}
.ltr{direction:ltr;unicode-bidi:isolate;white-space:nowrap;font-family:Montserrat,Cairo,sans-serif}
/* cover */
.cover .body{margin-top:150px}
.kicker{display:inline-block;background:var(--cyan);color:var(--navy);font-weight:800;font-size:30px;border-radius:12px;padding:6px 24px;margin-bottom:34px}
.cover h1{font-size:118px;line-height:1.18;font-weight:800;margin-bottom:34px}
.cover p{font-size:44px;line-height:1.6;color:rgba(255,255,255,.82);max-width:860px}
.cover .logochip{position:absolute;right:72px;bottom:130px;background:#fff;border-radius:28px;padding:20px 30px;z-index:2}
.cover .logochip img{height:150px;display:block}
.ep{position:absolute;left:72px;bottom:150px;z-index:2;font-family:Montserrat;font-weight:700;direction:ltr;text-align:left}
.ep small{display:block;color:var(--cyan);font-size:26px;letter-spacing:4px}
.ep span{font-size:96px;line-height:1;color:#fff}
/* point */
.point .body{margin-top:44px}
.numrow{display:flex;align-items:center;gap:22px;margin-bottom:22px}
.num{width:92px;height:92px;border-radius:50%;background:var(--navy);color:var(--cyan);display:grid;place-items:center;
  font-family:Montserrat;font-weight:700;font-size:44px;box-shadow:0 0 0 8px var(--ice)}
.point h2{font-size:78px;line-height:1.25;font-weight:800;color:var(--navy)}
.iconcard{margin:34px auto 12px;width:100%;height:380px;border-radius:44px;background:linear-gradient(135deg,#fff,var(--ice));
  border:3px solid #fff;box-shadow:0 18px 50px rgba(10,31,77,.12);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px}
.iconcard svg{width:210px;height:210px;stroke:var(--navy);fill:none;stroke-width:1.3;stroke-linecap:round;stroke-linejoin:round}
.iconcard svg .acc{stroke:var(--teal)}
.chip{font-family:Montserrat,Cairo;font-weight:700;font-size:30px;color:var(--navy);background:#fff;border-radius:30px;padding:6px 28px;border:2px solid var(--cyan)}
.point p{font-size:44px;line-height:1.6;margin-top:26px}
.tip{display:flex;gap:22px;align-items:center;margin-top:30px;background:#fff;border-right:10px solid var(--cyan);
  border-radius:24px;padding:24px 30px;box-shadow:0 10px 30px rgba(10,31,77,.08);font-size:36px;line-height:1.5;color:var(--navy);font-weight:600}
.tip svg{flex:none;width:56px;height:56px;stroke:var(--navy);fill:var(--cyan);stroke-width:1.2;stroke-linejoin:round}
/* compare */
.compare h2,.stats h2{font-size:76px;line-height:1.28;font-weight:800;color:var(--navy);margin:44px 0 36px}
table{width:100%;border-collapse:separate;border-spacing:0 14px;font-size:38px}
th{padding:20px;font-weight:800;font-size:40px}
th.l{background:var(--navy);color:#fff;border-radius:0 24px 24px 0;width:50%}
th.r{background:var(--cyan);color:var(--navy);border-radius:24px 0 0 24px}
td{background:#fff;padding:22px 24px;line-height:1.4;font-weight:600;text-align:center;box-shadow:0 6px 20px rgba(10,31,77,.06)}
td:first-child{border-radius:0 22px 22px 0;color:var(--slate)}
td:last-child{border-radius:22px 0 0 22px;color:var(--navy);font-weight:800}
/* stats */
.bars{display:flex;align-items:flex-end;justify-content:space-around;height:560px;gap:26px;margin:10px 10px 0;border-bottom:4px solid var(--navy)}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.bar .v{font-family:Montserrat;font-weight:800;font-size:46px;color:var(--navy);margin-bottom:10px;direction:ltr}
.bar .col{width:100%;border-radius:18px 18px 0 0;background:#B7BDC9}
.bar.hi .col{background:linear-gradient(180deg,var(--cyan),var(--teal))}
.barlabels{display:flex;justify-content:space-around;gap:26px;margin:12px 10px 0}
.barlabels div{flex:1;text-align:center;font-weight:700;font-size:30px;line-height:1.3}
.take{margin-top:36px;background:var(--navy);color:#fff;border-radius:28px;padding:28px 34px;font-size:38px;line-height:1.5;font-weight:600}
.take b{color:var(--cyan);background:none}
.src{font-size:24px;color:var(--slate);opacity:.8;margin-top:14px}
/* note (notebook) */
.note{background-color:#FBFAF4;
  background-image:linear-gradient(rgba(44,194,202,.22) 2px,transparent 2px),linear-gradient(90deg,rgba(44,194,202,.22) 2px,transparent 2px);
  background-size:54px 54px}
.note .body{margin-top:50px;font-family:Ruqaa,Cairo,serif}
.note h2{font-weight:700;font-size:92px;line-height:1.35;color:var(--navy);margin-bottom:30px}
.note h2 u{text-decoration:none;border-bottom:8px solid var(--cyan)}
.note li{list-style:none;font-size:56px;line-height:1.75;color:var(--slate);position:relative;padding-right:64px;margin-bottom:10px}
.note li::before{content:"\\2190";position:absolute;right:0;top:0;color:var(--cyan);font-family:Cairo;font-weight:800}
.note b{font-weight:700;color:#0A1F4D;background:linear-gradient(transparent 55%,rgba(4,219,239,.4) 55%)}
.pin{position:absolute;left:72px;top:150px;width:210px;height:210px;transform:rotate(-8deg);background:#FFF6B8;padding:26px;
  font-family:Ruqaa;font-size:38px;line-height:1.4;color:var(--navy);box-shadow:0 14px 30px rgba(0,0,0,.18);z-index:2;text-align:center;display:flex;align-items:center;justify-content:center}
/* cta */
.cta .body{margin-top:130px;text-align:center}
.cta .logochip{display:inline-block;background:#fff;border-radius:34px;padding:26px 40px;margin-bottom:60px}
.cta .logochip img{height:230px;display:block}
.cta h2{font-size:92px;line-height:1.3;font-weight:800;margin-bottom:34px}
.cta ul{list-style:none;display:inline-block;text-align:right}
.cta li{font-size:46px;line-height:1.5;margin-bottom:18px;padding-right:56px;position:relative}
.cta li::before{content:"";position:absolute;right:0;top:18px;width:28px;height:28px;border-radius:50%;background:var(--cyan)}
.cta .handle{margin-top:36px;font-family:Montserrat;font-weight:700;font-size:44px;color:var(--cyan);direction:ltr}
"""

CIRCUIT = """<svg class="circuit" viewBox="0 0 1080 1350" fill="none" stroke="#04DBEF" stroke-width="2" opacity=".35">
<path d="M1080 120H900l-60 60v140l-50 50H640"/><circle cx="640" cy="370" r="9"/>
<path d="M1080 260H980l-40 40"/><circle cx="940" cy="300" r="7" fill="#04DBEF"/>
<path d="M1080 520H860l-70 70v110"/><circle cx="790" cy="700" r="10"/>
<path d="M1080 860H930l-50 50v90l-40 40H700"/><circle cx="700" cy="1040" r="8" fill="#04DBEF"/>
<path d="M0 980h120l50 50v150"/><circle cx="170" cy="1180" r="9"/>
<path d="M0 1120h70"/><circle cx="70" cy="1120" r="6" fill="#04DBEF"/></svg>"""

PAGE = Template("""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{{css}}</style></head><body>
{% if s.type=='cover' %}
<div class="slide dark cover">{{circuit}}
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  <div class="body">{% if s.kicker %}<span class="kicker">{{s.kicker}}</span>{% endif %}
    <h1>{{s.title}}</h1>{% if s.subtitle %}<p>{{s.subtitle}}</p>{% endif %}</div>
  <div class="ep"><small>EPISODE</small><span>{{'%02d'|format(ep)}}</span></div>
  <div class="logochip"><img src="assets/logo.png"></div>
  <div class="foot"><span>{{handle}}</span><span class="arrow">&larr;</span></div></div>
{% elif s.type=='point' %}
<div class="slide light point">
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  <div class="body">
    <div class="numrow">{% if s.num %}<div class="num">{{s.num}}</div>{% endif %}<h2>{{s.title}}</h2></div>
    {% if s.icon %}<div class="iconcard"><svg viewBox="0 0 24 24">{{icon}}</svg>{% if s.chip %}<span class="chip">{{s.chip}}</span>{% endif %}</div>{% endif %}
    <p>{{s.body}}</p>
    {% if s.tip %}<div class="tip"><svg viewBox="0 0 24 24">{{bolt}}</svg><span>{{s.tip}}</span></div>{% endif %}</div>
  <div class="foot"><span>{{handle}}</span><span class="arrow">&larr;</span></div></div>
{% elif s.type=='compare' %}
<div class="slide light compare">
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  <div class="body"><h2>{{s.title}}</h2>
    <table><tr><th class="l">{{s.left}}</th><th class="r">{{s.right}}</th></tr>
    {% for a,b in s.rows %}<tr><td>{{a}}</td><td>{{b}}</td></tr>{% endfor %}</table></div>
  <div class="foot"><span>{{handle}}</span><span class="arrow">&larr;</span></div></div>
{% elif s.type=='stats' %}
<div class="slide light stats">
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  <div class="body"><h2>{{s.title}}</h2>
    <div class="bars">{% for b in s.bars %}<div class="bar {{'hi' if b.hi}}"><div class="v">{{b.value}}{{s.unit or ''}}</div><div class="col" style="height:{{(b.value/maxv*100)|round}}%"></div></div>{% endfor %}</div>
    <div class="barlabels">{% for b in s.bars %}<div>{{b.label}}</div>{% endfor %}</div>
    <div class="take">{{s.takeaway}}</div>{% if s.source %}<div class="src">{{s.source}}</div>{% endif %}</div>
  <div class="foot"><span>{{handle}}</span><span class="arrow">&larr;</span></div></div>
{% elif s.type=='note' %}
<div class="slide note">
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  {% if s.sticky %}<div class="pin">{{s.sticky}}</div>{% endif %}
  <div class="body"><h2>{{s.title}}</h2><ul>{% for l in s.bullets %}<li>{{l}}</li>{% endfor %}</ul></div>
  <div class="foot"><span>{{handle}}</span><span class="arrow">&larr;</span></div></div>
{% elif s.type=='cta' %}
<div class="slide dark cta">{{circuit}}
  <div class="top"><div class="tag"><i></i>{{tag}}</div><div class="count">{{n}} / {{total}}</div></div>
  <div class="body"><div class="logochip"><img src="assets/logo.png"></div>
    <h2>{{s.title}}</h2><ul>{% for l in s.lines %}<li>{{l}}</li>{% endfor %}</ul>
    <div class="handle">{{handle}}</div></div>
  <div class="foot"><span>Intelligent Technology</span><span></span></div></div>
{% endif %}</body></html>""")


def md(text):
    """Escape HTML, then turn **word** into a highlighted <b>."""
    t = html.escape(str(text))
    t = re.sub(r"(^|\s)(\*\*)?و(?=[A-Za-z0-9])", r"\1\2و ", t)  # "وRS485" -> "و RS485"
    # keep Latin/number runs (e.g. 4-20mA, Modbus RTU, Master / Slave) as one LTR unit
    t = re.sub(r"[A-Za-z0-9][A-Za-z0-9%\-\+\.]*(?: (?:[A-Za-z0-9][A-Za-z0-9%\-\+\.]*|/))*", lambda m: f'<span class="ltr">{m.group(0)}</span>', t)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def prep(slide):
    s = dict(slide)
    for k in ("title", "subtitle", "kicker", "body", "tip", "takeaway", "left", "right", "chip", "sticky", "source"):
        if k in s:
            s[k] = md(s[k])
    for k in ("bullets", "lines"):
        if k in s:
            s[k] = [md(x) for x in s[k]]
    if "rows" in s:
        s["rows"] = [[md(a), md(b)] for a, b in s["rows"]]
    for b in s.get("bars", []):
        b["label"] = md(b["label"])
    return s


def render_episode(series, ep_index, out_dir):
    """Render one episode (0-based index) to PNGs; returns list of paths."""
    ep = series["episodes"][ep_index]
    slides = ep["slides"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        for i, raw in enumerate(slides, 1):
            s = prep(raw)
            maxv = max([b["value"] for b in s.get("bars", [])] or [1])
            doc = PAGE.render(
                css=CSS, s=s, n=i, total=len(slides), tag=html.escape(series["tag"]), ep=ep_index + 1,
                handle=HANDLE, circuit=CIRCUIT, maxv=maxv,
                icon=ICONS.get(raw.get("icon", ""), ""), bolt=ICONS["bolt"],
            )
            f = ROOT / f"_slide_{i}.html"
            f.write_text(doc, encoding="utf-8")
            page.goto(f.as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            dest = out_dir / f"slide_{i:02d}.png"
            page.screenshot(path=str(dest), clip={"x": 0, "y": 0, "width": W, "height": H})
            f.unlink()
            paths.append(dest)
        browser.close()
    return paths
