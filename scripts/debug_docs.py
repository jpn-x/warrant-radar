"""臨時報告書の実際のdocDescriptionを確認する"""
import os, requests
from collections import Counter

API_KEY = os.environ.get("EDINET_API_KEY", "")
url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
params = {"date": "2026-06-04", "type": 2, "Subscription-Key": API_KEY}
r = requests.get(url, params=params, timeout=30)
docs = r.json().get("results", [])

print(f"Total docs: {len(docs)}")

# 全docTypeCodeの分布
codes = Counter(d.get("docTypeCode") for d in docs)
print("\n=== docTypeCode 分布 ===")
for code, cnt in sorted(codes.items(), key=lambda x: x[0] or ""):
    print(f"  [{code}] {cnt}件")

# 全コードの説明文サンプル
print("\n=== 各コードの説明文サンプル ===")
from collections import defaultdict
by_code = defaultdict(list)
for d in docs:
    by_code[d.get("docTypeCode","")].append(d.get("docDescription") or "")
for code in sorted(by_code, key=lambda x: x or ""):
    descs = list(set(by_code[code]))[:3]
    for desc in descs:
        print(f"  [{code}] {desc}")

# 新株予約権が含まれる説明文
print("\n=== 新株/予約権 含む ===")
for d in docs:
    desc = d.get("docDescription") or ""
    if "新株" in desc or "予約権" in desc or "発行" in desc:
        print(f"  [{d.get('docTypeCode')}] {desc} | {d.get('filerName','')[:20]}")
