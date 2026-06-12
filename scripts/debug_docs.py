"""臨時報告書の実際のdocDescriptionを確認する"""
import os, requests

API_KEY = os.environ.get("EDINET_API_KEY", "")
url = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
params = {"date": "2026-06-11", "type": 2, "Subscription-Key": API_KEY}
r = requests.get(url, params=params, timeout=30)
docs = r.json().get("results", [])

# 臨時報告書の説明文を全部表示
seen = set()
for d in docs:
    code = d.get("docTypeCode", "")
    desc = d.get("docDescription") or ""
    if code in ("140", "141") and desc not in seen:
        seen.add(desc)
        print(f"[{code}] {desc}")
