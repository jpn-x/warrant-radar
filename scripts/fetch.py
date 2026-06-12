"""
新株予約権 Radar — fetch.py
EDINET 臨時報告書 (docTypeCode=140) から新株予約権行使に関する開示を取得し
JSON + index.html を生成する。
"""
import os, re, sys, json, time, zipfile, io, argparse
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import requests

JST = ZoneInfo("Asia/Tokyo")
API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
API_KEY  = os.environ.get("EDINET_API_KEY", "")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# 臨時報告書 (180) + 訂正臨時報告書 (190)
TARGET_CODES = {"180", "190"}
WARRANT_KEYWORDS = [
    "新株予約権", "新株の発行", "株式の発行（新株予約権",
    "発行登録", "ストックオプション",
]


# ─── EDINET API ───────────────────────────────────────────────────────────────

def fetch_docs(target_date: str) -> list:
    """臨時報告書 (180/190) を全件取得 — XBRL内容でフィルタリングするため説明文フィルターなし"""
    url = f"{API_BASE}/documents.json"
    params = {"date": target_date, "type": 2, "Subscription-Key": API_KEY}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    all_docs = data.get("results", [])
    out = [d for d in all_docs if d.get("docTypeCode", "") in TARGET_CODES]
    print(f"  {target_date}: 全{len(all_docs)}件中 臨時報告書 {len(out)} 件")
    return out


# ─── XBRL パース ─────────────────────────────────────────────────────────────

def _ixval(txt: str, *elem_names) -> str | None:
    for name in elem_names:
        m = re.search(
            rf'<ix:non(?:Numeric|Fraction)[^>]+name="[^"]*:{re.escape(name)}"[^>]*>\s*([^<]+?)\s*</ix:non',
            txt)
        if m:
            v = m.group(1).strip()
            if v:
                return v
    return None


def xbrl_parse(doc_id: str) -> dict:
    """臨時報告書XBRLから新株予約権関連数値を抽出する。
    WARRANT_KEYWORDSが含まれない場合は空dict(=スキップ)を返す。
    """
    result = {}
    url = f"{API_BASE}/documents/{doc_id}?type=1&Subscription-Key={API_KEY}"
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return result
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
            htm_files = [n for n in names if n.endswith(".htm")]
            honbun = next((n for n in htm_files if "honbun" in n), None) \
                  or (htm_files[0] if htm_files else None)
            if not honbun:
                return result
            txt = zf.read(honbun).decode("utf-8", errors="ignore")

        # 新株予約権関連でなければスキップ
        matched = [kw for kw in WARRANT_KEYWORDS if kw in txt]
        if not matched:
            return result
        # キーワードヒット → 数値が取れなくてもエントリは残す
        result["warrant"] = True
        result["keywords"] = matched

        # 今回行使による新発行株式数
        issued_raw = _ixval(txt,
            "NumberOfNewlyIssuedSharesDueToExerciseOfShareAcquisitionRight",
            "NumberOfSharesIssuedByExercise",
            "NumberOfNewlyIssuedShares",
            "IssuedSharesIncreasedByExerciseOfShareAcquisitionRight",
        )
        if issued_raw:
            try:
                result["issued"] = int(re.sub(r"[^\d]", "", issued_raw))
            except ValueError:
                pass

        # 残存新株予約権数（個）
        remaining_raw = _ixval(txt,
            "NumberOfShareAcquisitionRightsOutstanding",
            "RemainingNumberOfShareAcquisitionRights",
            "OutstandingShareAcquisitionRights",
            "NumberOfRemainingWarrants",
        )
        if remaining_raw:
            try:
                result["remaining"] = int(re.sub(r"[^\d]", "", remaining_raw))
            except ValueError:
                pass

        # 行使価格（円）
        price_raw = _ixval(txt,
            "ExercisePriceOfShareAcquisitionRight",
            "ExercisePrice",
            "StrikePrice",
        )
        if price_raw:
            try:
                result["exercise_price"] = int(re.sub(r"[^\d]", "", price_raw))
            except ValueError:
                pass

        # 行使期限
        expire_raw = _ixval(txt,
            "ExpirationDateOfShareAcquisitionRight",
            "ExercisePeriodTo",
            "ExpirationDateOfWarrant",
        )
        if expire_raw:
            result["expire"] = expire_raw.strip()

        # 1個あたり行使株数（通常100株 or 1株）
        per_right_raw = _ixval(txt,
            "NumberOfSharesPerShareAcquisitionRight",
            "SharesPerWarrant",
        )
        if per_right_raw:
            try:
                result["per_right"] = int(re.sub(r"[^\d]", "", per_right_raw))
            except ValueError:
                pass

        # ── 本文テキストからの正規表現フォールバック ──
        plain = re.sub(r"&#\d+;", "", txt)
        plain = re.sub(r"<[^>]+>", "", plain)
        plain = re.sub(r"\s+", "", plain)
        # 全角数字・カンマを半角に正規化
        plain = plain.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))

        def _num(pattern):
            m = re.search(pattern, plain)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    return None
            return None

        # 発行数（個）→ remaining として扱う（発行決議時点の予約権数）
        if "remaining" not in result:
            v = _num(r"発行数(?:第\d+回新株予約権)?([\d,]+)個")
            if v is None:
                v = _num(r"(?:未行使|残存)(?:の)?(?:本)?新株予約権(?:の)?(?:個数|数)[：:は]?([\d,]+)個")
            if v is not None:
                result["remaining"] = v

        # 1個あたり株数
        if "per_right" not in result:
            v = _num(r"[1１]個(?:あた?り|につき)([\d,]+)株")
            if v is None:
                v = _num(r"新株予約権[1１]個(?:あた?り|につき)(?:、)?([\d,]+)株")
            if v is not None:
                result["per_right"] = v

        # 行使により交付される株式総数 → issued（潜在株数）
        if "issued" not in result:
            v = _num(r"(?:行使する|行使)(?:ことにより|により)交付(?:を受けることができる|される)株式の総数は(?:、)?(?:当社普通株式)?([\d,]+)株")
            if v is None:
                v = _num(r"新規発行株式数[：:]?(?:普通株式)?([\d,]+)株")
            if v is not None:
                result["issued"] = v

        # 行使価額
        if "exercise_price" not in result:
            v = _num(r"行使価額は(?:、)?金?([\d,]+)円")
            if v is None:
                v = _num(r"行使価額[：:]?(?:[1１]株(?:当た?り|あた?り)?)?(?:、)?金?([\d,]+)円")
            if v is None:
                v = _num(r"払込金額[：:は]?(?:[1１]株(?:当た?り|あた?り)?)?(?:、)?金?([\d,]+)円")
            if v is not None:
                result["exercise_price"] = v

        # 行使期限（行使期間の終了日）
        if "expire" not in result:
            m = re.search(
                r"行使期間.{0,80}?\d{4}年\d{1,2}月\d{1,2}日(?:から|～|〜|乃至)(\d{4}年\d{1,2}月\d{1,2}日)",
                plain)
            if m:
                result["expire"] = m.group(1)

    except Exception as e:
        print(f"    xbrl error {doc_id}: {e}")
    return result


# ─── エントリ構築 ─────────────────────────────────────────────────────────────

def build_entry(doc: dict) -> dict:
    sec = (doc.get("secCode") or "").strip()
    # EDINET の secCode は末尾に "0" が付く場合がある (e.g. "39590" → "3959")
    if len(sec) == 5 and sec.endswith("0"):
        sec = sec[:4]
    return {
        "docId":   doc.get("docID", ""),
        "sec":     sec,
        "name":    (doc.get("filerName") or "").strip(),
        "desc":    (doc.get("docDescription") or "").strip(),
        "issued":        None,
        "remaining":     None,
        "exercise_price": None,
        "expire":        None,
        "per_right":     None,
    }


# ─── 保存 / 読み込み ──────────────────────────────────────────────────────────

def save_day(day_date: str, entries: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{day_date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": day_date, "entries": entries}, f, ensure_ascii=False, indent=2)
    print(f"  Saved {path} ({len(entries)} 件)")


def load_all_days() -> list:
    files = sorted(
        [f for f in os.listdir(DATA_DIR) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f)],
        reverse=True
    )
    days = []
    for fn in files:
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8") as f:
            days.append(json.load(f))
    return days


# ─── HTML 生成 ────────────────────────────────────────────────────────────────

def generate_html(days: list, updated_str: str) -> str:
    from collections import defaultdict
    import json as _json

    by_month: dict[str, list] = defaultdict(list)
    for d in days:
        m = d["date"][:7]
        by_month[m].append(d)
    months = sorted(by_month.keys(), reverse=True)
    first_month = months[0] if months else ""

    all_entries = []
    for d in days:
        for e in d.get("entries", []):
            all_entries.append({
                "date":  d["date"],
                "sec":   e.get("sec") or "",
                "name":  e.get("name") or "",
                "desc":  e.get("desc") or "",
                "docId": e.get("docId") or "",
                "issued":         e.get("issued"),
                "remaining":      e.get("remaining"),
                "exercise_price": e.get("exercise_price"),
                "expire":         e.get("expire") or "",
                "per_right":      e.get("per_right"),
            })
    all_json = _json.dumps(all_entries, ensure_ascii=False)

    # 月タブボタン
    tab_btns = "".join(
        f'<button class="tab-btn{" active" if m == first_month else ""}" '
        f'onclick="switchTab(\'{m}\')">{m.replace("-", "/")}</button>'
        for m in months
    )

    # 月別パネル
    def fmt_num(n):
        if n is None: return "—"
        return f"{n:,}"

    def make_rows(d_list):
        rows = ""
        for d in d_list:
            date_str = d["date"]
            for e in d.get("entries", []):
                sec   = e.get("sec", "")
                name  = e.get("name", "") or "—"
                desc  = e.get("desc", "") or ""
                docId = e.get("docId", "")
                issued    = e.get("issued")
                remaining = e.get("remaining")
                ep        = e.get("exercise_price")
                expire    = e.get("expire") or "—"
                per_right = e.get("per_right") or 100

                code_cell = f'<a href="https://finance.yahoo.co.jp/quote/{sec}.T" target="_blank" class="code-link">{sec}</a>' if sec else "—"
                pdf_url   = f"https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{docId},,"
                issued_str    = f"{issued:,} 株" if issued is not None else "—"
                remaining_str = f"{remaining:,} 個" if remaining is not None else "—"
                # 潜在株数 = 残存個数 × 1個あたり株数
                potential_shares = (remaining * per_right) if remaining is not None else None
                potential_str = f"{potential_shares:,} 株" if potential_shares is not None else "—"
                ep_str = f"¥{ep:,}" if ep is not None else "—"

                rows += f"""<tr>
  <td class="td-date">{date_str}</td>
  <td class="td-code">{code_cell}</td>
  <td class="td-name">{name}</td>
  <td class="td-issued">{issued_str}</td>
  <td class="td-remaining">{remaining_str}</td>
  <td class="td-potential">{potential_str}</td>
  <td class="td-price">{ep_str}</td>
  <td class="td-expire">{expire}</td>
  <td><a href="{pdf_url}" target="_blank" class="btn-pdf">PDF</a></td>
</tr>"""
        return rows

    panels = ""
    for m in months:
        d_list = by_month[m]
        total = sum(len(d.get("entries", [])) for d in d_list)
        rows = make_rows(d_list)
        panels += f"""<div class="tab-panel" id="panel-{m}" style="display:none">
<div class="panel-meta">{len(d_list)} 営業日 ／ {total} 件の開示</div>
<div class="wrap"><table style="table-layout:fixed;width:100%">
<colgroup>
  <col style="width:100px"><col style="width:70px"><col style="width:200px">
  <col style="width:110px"><col style="width:90px"><col style="width:100px">
  <col style="width:80px"><col style="width:110px"><col style="width:50px">
</colgroup>
<thead><tr>
  <th>報告日</th><th>コード</th><th>会社名</th>
  <th>今回行使発行株数</th><th>残存個数</th><th>潜在株数</th>
  <th>行使価格</th><th>行使期限</th><th></th>
</tr></thead>
<tbody>{rows}</tbody>
</table></div></div>"""

    total_days  = len(days)
    total_items = sum(len(d.get("entries", [])) for d in days)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>新株予約権 Radar</title>
<meta name="description" content="EDINET 臨時報告書から新株予約権行使・潜在希薄化リスクを毎日自動集計">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
:root{{
  --bg:#0d0f14;--surf:#161a23;--border:#252a35;
  --text:#e8ecf4;--muted:#8892a4;
  --gold:#f5c842;--green:#3ddc84;--red:#ff5c5c;--blue:#4fa8ff;--purple:#b47fff;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Hiragino Sans','Noto Sans JP',sans-serif;font-size:14px;min-height:100vh}}
header{{background:var(--surf);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.logo{{width:32px;height:32px;flex-shrink:0}}
h1{{font-size:18px;font-weight:700;color:var(--purple);letter-spacing:.05em}}
.meta{{margin-left:auto;font-size:12px;color:var(--muted)}}
main{{padding:20px 24px;max-width:1400px;margin:0 auto}}

/* 検索 */
.search-bar{{display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap}}
.search-label{{color:var(--text);font-weight:600;font-size:13px;white-space:nowrap}}
.search-input{{background:var(--surf);border:1px solid var(--gold);color:var(--text);padding:6px 12px;border-radius:6px;font-size:13px;width:200px;outline:none}}
.search-input::placeholder{{color:var(--muted)}}
.btn-clear{{background:none;border:1px solid var(--border);color:var(--muted);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px}}
.btn-clear:hover{{border-color:var(--text);color:var(--text)}}
.search-hint{{font-size:12px;color:var(--muted);margin-bottom:16px}}
.search-meta{{font-size:12px;color:var(--muted);margin-bottom:8px}}

/* タブ */
.tab-bar{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}}
.tab-btn{{background:none;border:1px solid var(--text);color:var(--text);padding:5px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600}}
.tab-btn.active{{background:rgba(180,127,255,.15);border-color:var(--purple);color:var(--purple)}}

/* テーブル */
.panel-meta{{font-size:12px;color:var(--muted);margin-bottom:8px}}
.wrap{{overflow-x:auto;border-radius:10px;border:1px solid var(--border)}}
table{{width:100%;border-collapse:collapse}}
thead th{{background:#1c2130;padding:9px 12px;text-align:left;color:var(--text);font-size:11px;font-weight:600;white-space:nowrap;border-bottom:1px solid var(--border)}}
tbody tr{{border-bottom:1px solid var(--border)}}
tbody tr:last-child{{border-bottom:none}}
tbody tr:hover{{background:rgba(255,255,255,.03)}}
td{{padding:9px 12px;vertical-align:middle;font-size:13px}}
.td-date{{color:var(--muted);font-size:12px;white-space:nowrap}}
.td-code{{font-weight:700}}
.code-link{{color:var(--gold);text-decoration:none}}
.code-link:hover{{text-decoration:underline}}
.td-name{{color:var(--text)}}
.td-issued{{color:var(--blue);text-align:right;white-space:nowrap}}
.td-remaining{{color:var(--text);text-align:right;white-space:nowrap}}
.td-potential{{color:var(--red);font-weight:700;text-align:right;white-space:nowrap}}
.td-price{{color:var(--green);text-align:right;white-space:nowrap}}
.td-expire{{color:var(--muted);font-size:12px;white-space:nowrap}}
.btn-pdf{{display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;background:rgba(79,168,255,.1);color:var(--blue);border:1px solid rgba(79,168,255,.3);text-decoration:none;white-space:nowrap}}
.btn-pdf:hover{{background:rgba(79,168,255,.2)}}

/* 凡例 */
.legend{{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px;padding:12px 16px;background:var(--surf);border-radius:8px;border:1px solid var(--border)}}
.legend-item{{font-size:12px;color:var(--muted)}}
.legend-item span{{font-weight:700}}
.lc-blue{{color:var(--blue)}}
.lc-red{{color:var(--red)}}
.lc-green{{color:var(--green)}}

/* 検索パネル */
#search-panel{{display:none}}
footer{{text-align:center;padding:32px 16px;color:var(--muted);font-size:12px;line-height:2}}
footer a{{color:var(--muted);text-decoration:none}}
footer a:hover{{color:var(--gold)}}
</style>
</head>
<body>
<header>
  <svg class="logo" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="32" height="32" rx="8" fill="#1c1f2e"/>
    <text x="4" y="23" font-size="20">⚠️</text>
  </svg>
  <h1>新株予約権 Radar</h1>
  <div class="meta">
    更新: {updated_str} ｜
    データ: <a href="https://disclosure.edinet-fsa.go.jp/" target="_blank">EDINET</a> ｜
    累計 {total_days} 日 / {total_items} 件
  </div>
</header>
<main>

<div class="legend">
  <div class="legend-item"><span class="lc-blue">今回行使発行株数</span> — この報告で実際に行使・発行された株数</div>
  <div class="legend-item"><span class="lc-red">潜在株数</span> — 残存個数×行使株数（将来の希薄化リスク）</div>
  <div class="legend-item"><span class="lc-green">行使価格</span> — これより株価が高いと行使されやすい</div>
</div>

<div class="search-bar">
  <span class="search-label">コード検索</span>
  <input id="inp-code" class="search-input" type="text" placeholder="例: 3191, 4385"
    list="dl-code" oninput="doSearch()" autocomplete="off">
  <datalist id="dl-code"></datalist>
  <span class="search-label">会社名検索</span>
  <input id="inp-name" class="search-input" type="text" placeholder="例: enish"
    list="dl-name" oninput="doSearch()" autocomplete="off">
  <datalist id="dl-name"></datalist>
  <button class="btn-clear" onclick="clearSearch()">✕ クリア</button>
</div>
<div class="search-hint">※ コード番号または会社名で全期間のデータを絞り込めます</div>

<div id="search-panel">
  <div id="search-meta" class="search-meta"></div>
  <div class="wrap"><table style="table-layout:fixed;width:100%">
  <colgroup>
    <col style="width:100px"><col style="width:70px"><col style="width:200px">
    <col style="width:110px"><col style="width:90px"><col style="width:100px">
    <col style="width:80px"><col style="width:110px"><col style="width:50px">
  </colgroup>
  <thead><tr>
    <th>報告日</th><th>コード</th><th>会社名</th>
    <th>今回行使発行株数</th><th>残存個数</th><th>潜在株数</th>
    <th>行使価格</th><th>行使期限</th><th></th>
  </tr></thead>
  <tbody id="search-tbody"></tbody>
  </table></div>
</div>

<div id="tab-bar" class="tab-bar">{tab_btns}</div>
{panels}

</main>
<footer>
  新株予約権 Radar — EDINET 臨時報告書（新株予約権行使）毎日自動集計<br>
  データ取得元: EDINET（金融庁 電子開示システム）<br>
  当サイトは情報提供のみを目的としています。投資判断は自己責任でお願いします。
</footer>
<script>
const ALL = {all_json};

function rowHtml(e) {{
  const sec  = e.sec || '';
  const name = e.name || '—';
  const pdf  = `https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?${{e.docId}},,`;
  const code = sec ? `<a href="https://finance.yahoo.co.jp/quote/${{sec}}.T" target="_blank" class="code-link">${{sec}}</a>` : '—';
  const issued    = e.issued    != null ? e.issued.toLocaleString()    + ' 株' : '—';
  const remaining = e.remaining != null ? e.remaining.toLocaleString() + ' 個' : '—';
  const per = e.per_right || 100;
  const potential = e.remaining != null ? (e.remaining * per).toLocaleString() + ' 株' : '—';
  const ep    = e.exercise_price != null ? '¥' + e.exercise_price.toLocaleString() : '—';
  const expire = e.expire || '—';
  return `<tr>
    <td class="td-date">${{e.date}}</td>
    <td class="td-code">${{code}}</td>
    <td class="td-name">${{name}}</td>
    <td class="td-issued">${{issued}}</td>
    <td class="td-remaining">${{remaining}}</td>
    <td class="td-potential">${{potential}}</td>
    <td class="td-price">${{ep}}</td>
    <td class="td-expire">${{expire}}</td>
    <td><a href="${{pdf}}" target="_blank" class="btn-pdf">PDF</a></td>
  </tr>`;
}}

function doSearch() {{
  const code = document.getElementById('inp-code').value.trim().toUpperCase();
  const name = document.getElementById('inp-name').value.trim();
  if (!code && !name) {{ clearSearch(); return; }}
  const results = ALL.filter(e => {{
    const codeOk = !code || (e.sec || '').toUpperCase().includes(code);
    const nameOk = !name || (e.name || '').includes(name) || (e.name || '').toLowerCase().includes(name.toLowerCase());
    return codeOk && nameOk;
  }});
  document.getElementById('search-tbody').innerHTML = results.map(rowHtml).join('');
  document.getElementById('search-meta').textContent = `検索結果: ${{results.length}} 件`;
  document.getElementById('search-panel').style.display = 'block';
  document.getElementById('tab-bar').style.display = 'none';
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  if (code) addHist('code', document.getElementById('inp-code').value.trim());
  if (name) addHist('name', name);
}}

function clearSearch() {{
  document.getElementById('inp-code').value = '';
  document.getElementById('inp-name').value = '';
  document.getElementById('search-panel').style.display = 'none';
  document.getElementById('tab-bar').style.display = '';
  switchTab(currentTab);
}}

function switchTab(m) {{
  currentTab = m;
  document.querySelectorAll('.tab-btn').forEach(b => {{
    b.classList.toggle('active', b.textContent.replace('/','-') === m || b.getAttribute('onclick').includes(m));
  }});
  document.querySelectorAll('.tab-panel').forEach(p => {{
    p.style.display = p.id === 'panel-' + m ? 'block' : 'none';
  }});
}}

const HIST = {{ code: 'wr_hist_code', name: 'wr_hist_name' }};
function addHist(t, v) {{
  if (!v) return;
  let h = JSON.parse(localStorage.getItem(HIST[t]) || '[]');
  h = [v, ...h.filter(x => x !== v)].slice(0, 10);
  localStorage.setItem(HIST[t], JSON.stringify(h));
  updateDatalist(t);
}}
function updateDatalist(t) {{
  const dl = document.getElementById('dl-' + t);
  if (!dl) return;
  const h = JSON.parse(localStorage.getItem(HIST[t]) || '[]');
  dl.innerHTML = h.map(v => `<option value="${{v}}">`).join('');
}}

let currentTab = '{first_month}';
switchTab('{first_month}');
updateDatalist('code');
updateDatalist('name');
window.addEventListener('load', () => {{ if (document.activeElement) document.activeElement.blur(); }});
</script>
</body>
</html>"""


# ─── メイン処理 ───────────────────────────────────────────────────────────────

def fetch_day(target_date: str) -> list:
    docs = fetch_docs(target_date)
    if not docs:
        return []
    entries = []
    for i, doc in enumerate(docs):
        e = build_entry(doc)
        print(f"  [{i+1}/{len(docs)}] {e['sec'] or '----':6} {e['name'][:25]:25} | {e['desc'][:40]}")
        xdata = xbrl_parse(e["docId"])
        if not xdata:
            print(f"    → 新株予約権関連なし / スキップ")
            time.sleep(0.3)
            continue
        e.update(xdata)
        entries.append(e)
        time.sleep(0.4)
    return entries


def last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regen-only", action="store_true")
    args = parser.parse_args()

    now_jst = datetime.now(JST)
    updated_str = now_jst.strftime("%Y年%m月%d日 %H:%M JST")

    if not args.regen_only:
        target = os.environ.get("TARGET_DATE", "").strip() \
              or last_weekday(now_jst.date()).isoformat()
        json_path = os.path.join(DATA_DIR, f"{target}.json")
        if os.path.exists(json_path):
            print(f"{target}: 既存データあり → スキップ (--force で上書き可)")
        else:
            print(f"Fetching {target} ...")
            entries = fetch_day(target)
            if entries:
                save_day(target, entries)
            else:
                print(f"  {target}: 0件 → 保存スキップ")

    print("\nindex.html 再生成中...")
    days = load_all_days()
    html = generate_html(days, updated_str)
    out_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    total = sum(len(d.get("entries", [])) for d in days)
    print(f"Done: {len(days)} days / {total} items -> index.html updated")


if __name__ == "__main__":
    main()
