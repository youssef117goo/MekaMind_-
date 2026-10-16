#!/usr/bin/env python3
"""Telegram control bot for the MekaMind carousel automation (long polling + built-in scheduler).

Run:  python bot.py        (needs TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and GEMINI_API_KEY or ANTHROPIC_API_KEY)
Only the chat in TELEGRAM_CHAT_ID is obeyed.
"""
import json
import os
import re
import time
import traceback
import asyncio

import sys

sys.stdout.reconfigure(encoding="utf-8")
import main as app
import render

# محاولة استيراد وحدات تيليجرام لدعم استقبال المستندات (ملفات الـ JSON)
try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, Application
    TELEGRAM_EXT_AVAILABLE = True
except ImportError:
    TELEGRAM_EXT_AVAILABLE = False

HELP = """أهلاً! الأوامر:

/new اسم السلسلة
موضوع الحلقة 1
موضوع الحلقة 2
... (كل سطر = حلقة)
← أعمل السلسلة وأرجّعلك معاينة

/list ← السلاسل وتقدّمها ومواعيدها
/schedule رقم الأيام الساعة ← مثال: /schedule 1 sun,tue,thu 20:00 (أو: يوميا 18:30)
/preview رقم [حلقة] ← معاينة حلقة
/send رقم [حلقة] ← ابعتها دلوقتي (وتتحسب منشورة)
/delete رقم ← امسح سلسلة

💡 **جديد:** يمكنك رفع أي ملف `.json` مباشرة هنا وسيتم حفظه وإضافته لقائمة السلاسل تلقائياً!

الأرقام هي ترتيب السلسلة في /list أو اسمها. الساعة بتوقيت القاهرة.
الأيام: mon tue wed thu fri sat sun أو بالعربي، أو "يوميا"."""

AR_DAYS = {"الاثنين": "mon", "الإثنين": "mon", "الثلاثاء": "tue", "الأربعاء": "wed", "الاربعاء": "wed",
           "الخميس": "thu", "الجمعة": "fri", "السبت": "sat", "الأحد": "sun", "الاحد": "sun"}

AR_NUMS = {
    "الأولى": 1, "اولى": 1, "اولي": 1, "1": 1,
    "الثانية": 2, "تانية": 2, "2": 2,
    "الثالثة": 3, "تالتة": 3, "3": 3,
    "الرابعة": 4, "4": 4,
    "الخامسة": 5, "5": 5,
    "السادسة": 6, "6": 6,
    "السابعة": 7, "7": 7,
    "الثامنة": 8, "8": 8,
    "التاسعة": 9, "9": 9,
    "العاشرة": 10, "10": 10
}


def reply(text):
    app.tg("sendMessage", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text})


def all_series():
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(app.SERIES_DIR.glob("*.json"))]


def resolve(ref):
    """'1' -> first series in /list, or slug/name match."""
    ss = all_series()
    if not ref:
        return None
    ref_clean = ref.strip()
    
    # 1. لو رقم صريح
    if ref_clean.isdigit() and 1 <= int(ref_clean) <= len(ss):
        return ss[int(ref_clean) - 1]
    
    # 2. مطابقة تامة للـ slug
    match = next((s for s in ss if s["slug"] == ref_clean), None)
    if match:
        return match
        
    # 3. بحث ذكي بالاسم
    for s in ss:
        if ref_clean in s["name"] or s["name"] in ref_clean:
            return s
            
    return None


def parse_days(text):
    text = text.strip().lower()
    if text in ("daily", "يوميا", "يومياً", "كل يوم"):
        return list(app.DAYS)
    out = []
    for tok in re.split(r"[,\s،و]+", text):
        tok = AR_DAYS.get(tok, tok)
        if tok in app.DAYS and tok not in out:
            out.append(tok)
    return out


def cmd_list():
    ss = all_series()
    if not ss:
        return reply("مفيش سلاسل لسه. ابعت /new أو ارفع ملف JSON.")
    st = app.load_state()
    lines = []
    for i, s in enumerate(ss, 1):
        done = len(st.get(s["slug"], {}).get("sent", []))
        sc = s["schedule"]
        lines.append(f"{i}) {s['name']} — {done}/{len(s['episodes'])} اتنشرت — {','.join(sc['days'])} الساعة {sc['time']}")
    reply("\n".join(lines))


def cmd_new(body):
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    if len(lines) < 2:
        return reply("ابعت اسم السلسلة في أول سطر، وبعده كل موضوع في سطر.")
    name, topics = lines[0], lines[1:]
    reply(f"بجهّز سلسلة «{name}» ({len(topics)} حلقة)... ممكن تاخد دقيقتين.")
    s = app.create_series(name, topics)
    titles = "\n".join(f"{i}. {e['title']}" for i, e in enumerate(s["episodes"], 1))
    reply(f"تمت السلسلة ✅\n{titles}\n\nالمواعيد الحالية: {','.join(s['schedule']['days'])} الساعة {s['schedule']['time']} (غيّرها بـ /schedule). هبعتلك معاينة الحلقة 1:")
    paths = render.render_episode(s, 0, app.ROOT / "out" / s["slug"] / "ep01")
    app.send_episode(s, 0, paths, preview=True)


def cmd_schedule(args):
    parts = args.split()
    if len(parts) < 3:
        return reply("الصيغة: /schedule رقم الأيام الساعة\nمثال: /schedule 1 sun,tue,thu 20:00")
    s = resolve(parts[0])
    days, hhmm = parse_days(" ".join(parts[1:-1])), parts[-1]
    if not s:
        return reply("مش لاقي السلسلة دي. شوف /list")
    if not days or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hhmm):
        return reply("الأيام أو الساعة مش مفهومة. الساعة بصيغة 20:00 (24 ساعة).")
    s["schedule"].update(days=days, time=hhmm)
    app.save_series(s)
    reply(f"تمام ✅ «{s['name']}» هتنزل {','.join(days)} الساعة {hhmm} بتوقيت القاهرة.")


def parse_episode_number(text):
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        return int(text)
    for word, num in AR_NUMS.items():
        if word in text:
            return num
    nums = re.findall(r'\d+', text)
    if nums:
        return int(nums[0])
    return None


def episode_of(s, parts, default_next):
    rest_text = " ".join(parts[1:]) if len(parts) > 1 else ""
    ep_num = parse_episode_number(rest_text)
    
    if ep_num is not None:
        return ep_num - 1
        
    if default_next:
        sent = {x["ep"] for x in app.load_state().get(s["slug"], {}).get("sent", [])}
        return next((k for k in range(len(s["episodes"])) if k + 1 not in sent), None)
    return 0


def cmd_preview_or_send(args, send):
    parts = args.split()
    if not parts:
        return reply("اكتب رقم السلسلة أو اسمها من /list")
    
    s = resolve(parts[0])
    used_parts_count = 1
    
    if not s and len(parts) > 1:
        s = resolve(f"{parts[0]} {parts[1]}")
        if s:
            used_parts_count = 2
            
    if not s:
        return reply("مش لاقي السلسلة دي. تأكد من الرقم أو الاسم في /list")
        
    i = episode_of(s, parts[used_parts_count-1:], default_next=send)
    
    if i is None or not 0 <= i < len(s["episodes"]):
        return reply("مفيش حلقة بالرقم ده (أو كل الحلقات اتنشرت).")
        
    if send:
        app.do_send(s["slug"], i, False)
    else:
        paths = render.render_episode(s, i, app.ROOT / "out" / s["slug"] / f"ep{i + 1:02d}")
        app.send_episode(s, i, paths, preview=True)


def cmd_delete(args):
    s = resolve(args.strip())
    if not s:
        return reply("مش لاقي السلسلة دي.")
    (app.SERIES_DIR / f"{s['slug']}.json").unlink()
    reply(f"اتمسحت «{s['name']}».")


def handle(text):
    m = re.match(r"/(\w+)(?:@\w+)?\s*(.*)", text.strip(), re.S)
    if not m:
        return reply(HELP)
    cmd, rest = m.group(1).lower(), m.group(2)
    if cmd in ("start", "help"):
        reply(HELP)
    elif cmd == "list":
        cmd_list()
    elif cmd == "new":
        cmd_new(rest)
    elif cmd == "schedule":
        cmd_schedule(rest)
    elif cmd == "preview":
        cmd_preview_or_send(rest, send=False)
    elif cmd == "send":
        cmd_preview_or_send(rest, send=True)
    elif cmd == "delete":
        cmd_delete(rest)
    else:
        reply(HELP)


# معالج استقبال ملفات الـ JSON المرفوعة عبر الشات
async def handle_json_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = str(update.message.chat.id)
    if chat != os.environ.get("TELEGRAM_CHAT_ID"):
        return  # تجاهل أي شات آخر أماناً

    document = update.message.document
    if document:
        file_name = document.file_name
        if file_name and file_name.endswith('.json'):
            try:
                file = await context.bot.get_file(document.file_id)
                app.SERIES_DIR.mkdir(parents=True, exist_ok=True)
                file_path = app.SERIES_DIR / file_name
                await file.download_to_drive(str(file_path))
                
                ss = all_series()
                reply(f"✅ تم استقبال ملف الـ JSON بنجاح!\n📂 تم حفظه في فولدر السلاسل: {file_name}\n📊 إجمالي السلاسل النشطة الآن: {len(ss)}")
            except Exception as e:
                traceback.print_exc()
                reply(f"❌ حدث خطأ أثناء حفظ الملف: {str(e)}")
        else:
            reply("⚠️ يرجى رفع ملفات بصيغة .json فقط.")


def verify_token():
    try:
        name = app.tg("getMe")["result"]["username"]
        print(f"البوت متوصل: @{name}")
    except app.requests.exceptions.ConnectionError:
        raise SystemExit("مفيش اتصال بتليجرام. اتأكد من النت وجرّب تاني.")
    except Exception:
        env = app.ROOT / ".env"
        for f in (env, app.ROOT / ".env.txt"):
            f.unlink(missing_ok=True)
        raise SystemExit("التوكن مرفوض من Telegram، وتم مسح الإعدادات القديمة. شغّل الملف تاني وادخل التوكن الصح.")


def check_env():
    if all(os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        return verify_token()
    print("مش لاقي الإعدادات، هسألك عليهم دلوقتي وأحفظهم لوحدي في ملف .env\n")
    token = input("1) توكن البوت: ").strip()
    chat = input("2) رقم الـ Chat Id: ").strip()
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", token):
        raise SystemExit("التوكن غير صالح. تأكد منه وجرب تاني.")
    if not re.fullmatch(r"-?\d+", chat):
        raise SystemExit("الـ Chat Id يجب أن يكون أرقاماً فقط.")
    gem = input("3) مفتاح Gemini (اختياري): ").strip()
    env = app.ROOT / ".env"
    env.write_text(f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_ID={chat}\nGEMINI_API_KEY={gem}\n", encoding="utf-8")
    for k, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat), ("GEMINI_API_KEY", gem)):
        if v:
            os.environ[k] = v
    print(f"\nاتحفظ في {env}\n")
    verify_token()


def run():
    check_env()
    
    # لو مكتبة python-telegram-bot متوفرة، سنشغل البوت بالطريقة المتقدمة (تعمل polling وتدعم الملفات والرسائل معاً)
    if TELEGRAM_EXT_AVAILABLE:
        print("bot running with advanced polling (supports file uploads & commands)... Ctrl+C to stop")
        
        async def main_bot():
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            application = Application.builder().token(token).build()
            
            # الهاندلر لاستقبال ملفات الـ JSON
            application.add_handler(MessageHandler(filters.Document.ALL, handle_json_file))
            
            # الهاندلر لاستقبال النصوص والأوامر العادية
            async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                chat = str(update.message.chat.id)
                if chat != os.environ.get("TELEGRAM_CHAT_ID"):
                    return
                if update.message.text:
                    try:
                        handle(update.message.text)
                    except Exception as e:
                        traceback.print_exc()
                        reply(f"حصلت مشكلة: {type(e).__name__}: {str(e)[:300]}")

            application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))
            
            # إضافة دعم الأوامر المباشرة كـ handlers منفصلة لتفادي أي مشاكل
            from telegram.ext import CommandHandler
            for cmd_name in ["start", "help", "list", "new", "schedule", "preview", "send", "delete"]:
                async def cmd_router(update: Update, context: ContextTypes.DEFAULT_TYPE, name=cmd_name):
                    chat = str(update.message.chat.id)
                    if chat != os.environ.get("TELEGRAM_CHAT_ID"):
                        return
                    text = update.message.text or ""
                    handle(text)
                application.add_handler(CommandHandler(cmd_name, cmd_router))

            # مهمة دورية للـ Scheduler (Tick) تعمل كل 30 ثانية لتفقد المواعيد
            async def scheduler_task(app_context):
                while True:
                    try:
                        app.tick()
                    except Exception:
                        traceback.print_exc()
                    await asyncio.sleep(30)

            # تشغيل البوت مع الـ Scheduler الخلفي
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
            
            # تشغيل التكتوك في الخلفية
            asyncio.create_task(scheduler_task(application))
            
            # الحفاظ على تشغيل السكربت للأبد
            stop_signal = asyncio.Event()
            await stop_signal.wait()

        try:
            asyncio.run(main_bot())
        except (KeyboardInterrupt, SystemExit):
            print("Bot stopped.")
    else:
        # الطريقة الكلاسيكية القديمة في حال عدم توفر المكتبة المتقدمة
        offset, last_tick = None, 0
        print("bot running (classic polling)... Ctrl+C to stop")
        while True:
            try:
                r = app.tg("getUpdates", data={"timeout": 25, **({"offset": offset} if offset else {})})
                for u in r.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    chat = str(msg.get("chat", {}).get("id", ""))
                    if not msg.get("text"):
                        continue
                    if chat != os.environ.get("TELEGRAM_CHAT_ID"):
                        continue
                    try:
                        handle(msg["text"])
                    except Exception as e:
                        traceback.print_exc()
                        reply(f"حصلت مشكلة: {type(e).__name__}: {str(e)[:300]}")
                if time.time() - last_tick > 30:
                    last_tick = time.time()
                    app.tick()
            except Exception:
                traceback.print_exc()
                time.sleep(5)


if __name__ == "__main__":
    run()