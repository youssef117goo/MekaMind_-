# MekaMind Carousel Automation

## Run locally (test)
    pip install -r requirements.txt && python -m playwright install chromium
    copy .env.example .env   # (Mac/Linux: cp) then open .env and fill the values
    python bot.py            # leave it running

Then in Telegram, message your bot:
    /new اسم السلسلة
    موضوع الحلقة 1
    موضوع الحلقة 2
It builds the series and sends back a preview of episode 1.
    /list                              series, progress, schedule
    /schedule 1 sun,tue,thu 20:00      you set the days/time (Cairo time); also "يوميا" or Arabic day names
    /preview 1 2    /send 1 [ep]    /delete 1

While bot.py is running it also sends the next episode automatically at the times you set.
A ready sample series is in series/iot-workshop.json (3 episodes), so you can test without a Gemini key:
    /send 1        -> sends episode 1 to your Telegram now

## Hosting later
The bot must stay running to read your messages and keep the schedule, so it needs an always-on free host (to be chosen when you are ready).
`.github/workflows/post.yml` is a simpler alternative that only SENDS on fixed days/times (no chat commands).

## CLI (optional)
`python main.py list | render <slug> | send <slug> [--dry-run] | tick`
