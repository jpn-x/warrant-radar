"""臨時報告書の実際のdocDescriptionを確認する"""
import os, requests
from collections import Counter

API_KEY = os.environ.get("EDINET_API_KEY", "")
url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
params = {"date": "2026-06-11", "type": 2, "Subscription-Key": API_KEY}
r = requests.get(url, params=params, timeout=30)
docs = r.json().get("results", [])

print(f"Total docs: {len(docs)}")

# 全docTypeCodeの分布
codes = Counter(d.get("docTypeCode") for d in docs)
print("\n=== docTypeCode 分布 ===")
for code, cnt in sorted(codes.items()):
    print(f"  [{code}] {cnt}件")

# 新株予約権が含まれる説明文を全部表示
print("\n=== 新株予約権 含む説明 ===")
for d in docs:
    desc = d.get("docDescription") or ""
    if "新株予約権" in desc or "新株" in desc:
        print(f"  [{d.get('docTypeCode')}] {desc} | {d.get('filerName','')[:20]}")
