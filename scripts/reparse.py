"""既存JSONの全エントリをXBRL再パースして数値を埋める"""
import os, sys, json, glob, time
sys.path.insert(0, os.path.dirname(__file__))
from fetch import xbrl_parse, load_all_days, generate_html, DATA_DIR
from datetime import datetime
from zoneinfo import ZoneInfo

for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
    with open(path, encoding="utf-8") as f:
        day = json.load(f)
    changed = False
    for e in day.get("entries", []):
        xdata = xbrl_parse(e["docId"])
        xdata.pop("keywords", None)
        if xdata:
            e.update(xdata)
            changed = True
        time.sleep(0.3)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(day, f, ensure_ascii=False, indent=2)
        print(f"{os.path.basename(path)}: updated ({len(day['entries'])} entries)")

now = datetime.now(ZoneInfo("Asia/Tokyo"))
days = load_all_days()
html = generate_html(days, now.strftime("%Y年%m月%d日 %H:%M JST"))
with open(os.path.join(os.path.dirname(__file__), "..", "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("index.html regenerated")
