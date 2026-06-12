"""バックフィル: 指定期間の過去データを取得する"""
import os, sys, json
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from fetch import fetch_day, save_day, load_all_days, generate_html, DATA_DIR
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

START = date(2026, 1, 5)
END   = date.today()

existing = {f[:10] for f in os.listdir(DATA_DIR) if f.endswith(".json")} if os.path.exists(DATA_DIR) else set()

d = START
while d <= END:
    if d.weekday() < 5:  # 平日のみ
        ds = d.isoformat()
        if ds in existing:
            print(f"  {ds}: スキップ (既存)")
        else:
            print(f"  {ds}: 取得中...")
            try:
                entries = fetch_day(ds)
                if entries:
                    save_day(ds, entries)
                else:
                    print(f"    0件 → スキップ")
            except Exception as ex:
                print(f"    ERROR: {ex}")
    d += timedelta(days=1)

print("\nindex.html 再生成...")
now_jst = datetime.now(JST)
days = load_all_days()
html = generate_html(days, now_jst.strftime("%Y年%m月%d日 %H:%M JST"))
out = os.path.join(os.path.dirname(__file__), "..", "index.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
total = sum(len(d.get("entries", [])) for d in days)
print(f"Done: {len(days)} 日 / {total} 件 → index.html 更新")
