"""EDINETのdocTypeCode調査 — 臨時報告書を探す"""
import os, requests
from collections import Counter, defaultdict

API_KEY = os.environ.get("EDINET_API_KEY", "")
url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"

# 1週間分チェック
dates = [
    "2026-06-04", "2026-06-03", "2026-06-02",
    "2026-05-30", "2026-05-29", "2026-05-28",
]

all_codes = Counter()
rinjis = []  # 臨時報告書らしきもの

for date in dates:
    r = requests.get(url, params={"date": date, "type": 2, "Subscription-Key": API_KEY}, timeout=30)
    docs = r.json().get("results", [])
    print(f"\n=== {date}: {len(docs)}件 ===")

    by_code = defaultdict(list)
    for d in docs:
        by_code[d.get("docTypeCode","")].append(d)
        all_codes[d.get("docTypeCode","")] += 1

    # 各コードのdocDescriptionサンプル（重複なし）
    for code in sorted(by_code, key=lambda x: x or ""):
        descs = list({d.get("docDescription","")[:50] for d in by_code[code]})[:2]
        for desc in descs:
            print(f"  [{code}] {desc}")

    # 臨時報告書 or 新株 or 予約権 含む
    for d in docs:
        desc = d.get("docDescription","") or ""
        if any(kw in desc for kw in ["臨時", "新株", "予約権", "発行"]):
            rinjis.append({
                "date": date,
                "code": d.get("docTypeCode"),
                "desc": desc[:60],
                "filer": d.get("filerName","")[:25],
                "sec": d.get("secCode"),
                "docId": d.get("docID"),
            })

print("\n\n=== 全期間: 臨時/新株/予約権/発行 含むdoc ===")
for e in rinjis:
    print(f"  [{e['code']}] {e['date']} | {e['desc']} | {e['filer']} | sec={e['sec']} | {e['docId']}")

print("\n=== 全コード集計 ===")
for code, cnt in sorted(all_codes.items(), key=lambda x: x[0] or ""):
    print(f"  [{code}] {cnt}件")
