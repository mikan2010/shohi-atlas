#!/usr/bin/env python3
"""
全国家計構造調査から都道府県データを「一発で」取得するクイックスタートスクリプト。

使い方 (PowerShell):
  $env:ESTAT_APP_ID = "あなたのappId"
  python quickstart_japan.py

やること:
  1. 2014 / 2019 / 2024 の「1世帯当たり1か月間の収入と支出 (二人以上の世帯)」から
     消費支出 (円/月 → 万円/月) を取得
  2. 「世帯主の年齢階級別」の統計表を検索して自動特定し、属性データとして取得
  3. ../data/pref_data.json に地図がそのまま読める形式で書き出し

仕組み:
  - 世帯の種類・収支項目などの軸は名前ルールで1カテゴリに絞る
  - 「表章項目」は事前に決め打ちせず全候補を取得し、ラベル (金額系を優先、
    世帯数・分布・率などを除外) と都道府県カバレッジで正しい系列を自動判定する
  - データが取れなかった場合は、軸とカテゴリの一覧を診断出力する
"""

import json
import os
import re
import sys

from fetch_estat import api_get, as_list, pref_code_from_area, PREF_NAMES

# ---- 対象の統計表 (search コマンドの結果から特定済み) --------------------
PERCAP_TABLES = {
    "2014": "0003424506",
    "2019": "0003424729",
    "2024": "0004040034",
}
AGE_SEARCH_WORD = "全国家計構造調査 都道府県 世帯主の年齢階級"
# ユーザ検索で判明済みの正しい統計表 (収入と支出 × 世帯主の年齢階級)。最優先で試す
KNOWN_AGE_TABLES = {"2019": ["0003424741"], "2024": ["0004040023"]}
# 年齢階級の集約: 5歳刻み等を「29歳以下/30代/.../70歳以上」に単純平均でまとめる
COARSE_AGE = True
AGE_BUCKETS = ["29歳以下", "30代", "40代", "50代", "60代", "70歳以上"]

# ---- 軸の絞り込みルール (軸名キーワード → 優先カテゴリ名) ----------------
PREFER = [
    (["世帯の種類"], ["二人以上の世帯", "総世帯"]),
    (["世帯区分"],   ["全世帯", "総数", "二人以上の世帯"]),
    (["月額階級", "収入階級", "資産", "貯蓄", "世帯人員", "性別"], ["総数", "平均"]),
    (["収支項目", "品目", "用途分類", "家計収支"], ["消費支出"]),
]
# 表章項目の自動判定: 加点/減点キーワード
TAB_GOOD = ["金額", "円", "支出", "収入"]
TAB_BAD  = ["世帯数", "分布", "構成", "人員", "率", "年齢", "持家"]

SCALE = 0.0001   # 円 → 万円
ROUND = 2
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pref_data.json")


# ---------------------------------------------------------------- e-Stat
def get_values(app_id, sid, extra):
    """getStatsData を全ページ取得。データなしは [] を返す (エラー終了しない)。"""
    values, start = [], 1
    while True:
        params = {"appId": app_id, "statsDataId": sid, "metaGetFlg": "N",
                  "cntGetFlg": "N", "limit": 100000, "startPosition": start, **extra}
        body = api_get("getStatsData", params)
        root = body.get("GET_STATS_DATA", {})
        status = root.get("RESULT", {}).get("STATUS")
        if status not in (0, 1):  # 1 = 正常終了・該当データなし
            sys.exit(f"APIエラー({sid}): {root.get('RESULT', {}).get('ERROR_MSG')}")
        sd = root.get("STATISTICAL_DATA", {})
        values += as_list(sd.get("DATA_INF", {}).get("VALUE"))
        next_key = sd.get("RESULT_INF", {}).get("NEXT_KEY")
        if not next_key:
            return values
        start = int(next_key)


def get_axes(app_id, sid):
    body = api_get("getMetaInfo", {"appId": app_id, "statsDataId": sid})
    root = body.get("GET_META_INFO", {})
    if root.get("RESULT", {}).get("STATUS") != 0:
        sys.exit(f"APIエラー(meta {sid}): {root.get('RESULT', {}).get('ERROR_MSG')}")
    return as_list(root.get("METADATA_INF", {}).get("CLASS_INF", {}).get("CLASS_OBJ"))


def dump_axes(axes):
    """診断用: 軸とカテゴリの一覧を表示する。"""
    print("  ---- 診断: この統計表の軸とカテゴリ ----")
    for ax in axes:
        classes = as_list(ax.get("CLASS"))
        print(f"  {ax.get('@id')} ({ax.get('@name')}): "
              + " / ".join(c.get("@name", "") for c in classes[:8])
              + (" ..." if len(classes) > 8 else ""))


# ---------------------------------------------------------------- 軸の選択
def pick_code(axis_name, classes):
    for keys, prefs in PREFER:
        if any(k in axis_name for k in keys):
            names = {c.get("@name"): c.get("@code") for c in classes}
            for p in prefs:                      # 完全一致を優先
                if p in names:
                    return names[p], p, True
            for p in prefs:                      # 次に部分一致
                for n, code in names.items():
                    if n and p in n:
                        return code, n, True
    c = classes[0]
    return c.get("@code"), c.get("@name"), False


def build_filters(app_id, sid, attr_axis_keyword=None):
    """tab / area / time / 属性軸 以外を1カテゴリに絞る。
    戻り値: (extra, tab_labels, attr_dim, attr_labels, axes)"""
    axes = get_axes(app_id, sid)
    extra, tab_labels, attr_dim, attr_labels = {}, {}, None, {}
    print(f"  [statsDataId {sid}] 軸の絞り込み:")
    for ax in axes:
        dim, name = ax.get("@id"), ax.get("@name") or ""
        classes = as_list(ax.get("CLASS"))
        if dim in ("area", "time"):
            continue
        if dim == "tab" or "表章項目" in name:
            tab_labels = {c.get("@code"): c.get("@name", "") for c in classes}
            print(f"    {name}: 全{len(tab_labels)}候補を取得後に自動判定")
            continue
        if attr_axis_keyword and attr_axis_keyword in name:
            attr_dim = dim
            attr_labels = {c.get("@code"): c.get("@name") for c in classes
                           if "総数" not in (c.get("@name") or "")
                           and "平均" not in (c.get("@name") or "")}
            print(f"    {name}: 属性として全カテゴリ取得 ({len(attr_labels)}区分)")
            continue
        code, cname, matched = pick_code(name, classes)
        extra[f"cd{dim[0].upper()}{dim[1:]}"] = code
        mark = "" if matched else " ⚠ルール外のため先頭を選択"
        print(f"    {name}: 「{cname}」{mark}")
    return extra, tab_labels, attr_dim, attr_labels, axes


def choose_tab_group(values, tab_labels):
    """表章項目でグループ化し、金額系かつ都道府県カバレッジの高い系列を選ぶ。"""
    if not tab_labels:
        return values, None
    groups = {}
    for v in values:
        groups.setdefault(v.get("@tab"), []).append(v)

    def coverage(rows):
        return len({pref_code_from_area(r.get("@area", "")) for r in rows
                    if pref_code_from_area(r.get("@area", "")) is not None
                    and r.get("$") not in (None, "", "-", "***", "X")})

    def score(code):
        name = tab_labels.get(code, "")
        s = sum(2 for k in TAB_GOOD if k in name)
        s -= sum(5 for k in TAB_BAD if k in name)
        return s

    ranked = sorted(groups, key=lambda c: (score(c), coverage(groups[c])), reverse=True)
    for code in ranked:
        if score(code) > 0 and coverage(groups[code]) >= 40:
            others = [tab_labels.get(c, c) for c in ranked if c != code][:3]
            print(f"    表章項目: 「{tab_labels.get(code, code)}」を採用"
                  + (f" (他候補: {' / '.join(others)})" if others else ""))
            return groups[code], code
    return [], None


# ---------------------------------------------------------------- 年齢集約
def bucket_age(name):
    """年齢階級名を粗い区分にまとめる。対象外 (再掲等) は None。"""
    if any(k in name for k in ("再掲", "うち", "平均", "総数")):
        return None
    m = re.search(r"(\d+)\s*歳未満", name)
    if m:
        lb = int(m.group(1)) - 1
    else:
        m = re.search(r"(\d+)", name)  # 「25～29歳」「85歳以上」等の先頭数値
        if not m:
            return name  # 数値なし → そのまま
        lb = int(m.group(1))
    if lb < 30: return "29歳以下"
    if lb < 40: return "30代"
    if lb < 50: return "40代"
    if lb < 60: return "50代"
    if lb < 70: return "60代"
    return "70歳以上"


def coarsen(attr_raw):
    """{県コード: {カテゴリ名: 値}} を粗い区分の単純平均に集約する。"""
    if not COARSE_AGE:
        return attr_raw
    # カテゴリの大半が年齢として解釈できる場合のみ集約
    cats = {c for m in attr_raw.values() for c in m}
    parsable = [c for c in cats if bucket_age(c) in AGE_BUCKETS]
    if len(parsable) < len(cats) * 0.6:
        return attr_raw
    out = {}
    for code, m in attr_raw.items():
        acc = {}
        for cat, val in m.items():
            b = bucket_age(cat)
            if b in AGE_BUCKETS:
                acc.setdefault(b, []).append(val)
        out[code] = {b: round(sum(acc[b]) / len(acc[b]), ROUND)
                     for b in AGE_BUCKETS if b in acc}
    return out


# ---------------------------------------------------------------- 取得処理
def store(out, code, year, val, attr_name=None, cat=None):
    p = out["prefs"][str(code)]["years"].setdefault(year, {})
    if attr_name:
        p.setdefault("attrs", {}).setdefault(attr_name, {})[cat] = val
    else:
        p["percap"] = val


def ingest(values, out, year, attr_dim=None, attr_labels=None):
    hit = 0
    attr_raw = {}
    for v in values:
        code = pref_code_from_area(v.get("@area", ""))
        raw = v.get("$")
        if code is None or raw in (None, "", "-", "***", "X"):
            continue
        cat = None
        if attr_dim:
            cat = (attr_labels or {}).get(v.get(f"@{attr_dim}", ""))
            if cat is None:
                continue
        try:
            val = round(float(raw) * SCALE, ROUND)
        except ValueError:
            continue
        if attr_dim:
            attr_raw.setdefault(code, {})[cat] = val
        else:
            store(out, code, year, val)
        hit += 1
    if attr_dim and attr_raw:
        coarsened = coarsen(attr_raw)
        n_cat = len({c for m in coarsened.values() for c in m})
        if coarsened is not attr_raw:
            print(f"    年齢階級を {n_cat} 区分に集約 (単純平均)")
        # 妥当性検証: 属性値の中央値が、その年の消費支出の中央値と大きく乖離して
        # いれば誤カテゴリ (世帯数等) とみなして不採用にする
        refs = sorted(p["years"].get(year, {}).get("percap")
                      for p in out["prefs"].values()
                      if p["years"].get(year, {}).get("percap") is not None)
        vals = sorted(v for m in coarsened.values() for v in m.values())
        if refs and vals:
            ref_med = refs[len(refs)//2]
            val_med = vals[len(vals)//2]
            ratio = val_med / ref_med if ref_med else 0
            if not (0.2 <= ratio <= 5):
                print(f"    ⚠ 属性値の水準が消費支出と不整合 (中央値 {val_med:.1f} vs "
                      f"{ref_med:.1f}) のため、この表は不採用")
                return 0
        for code, m in coarsened.items():
            for cat, val in m.items():
                store(out, code, year, val, "age", cat)
    return hit


def fetch_table(app_id, sid, out, year, attr_axis_keyword=None):
    extra, tab_labels, attr_dim, attr_labels, axes = \
        build_filters(app_id, sid, attr_axis_keyword)
    values = get_values(app_id, sid, extra)
    if not values:
        print("  ⚠ データが返りませんでした。")
        dump_axes(axes)
        return 0
    picked, _ = choose_tab_group(values, tab_labels)
    if not picked:
        print("  ⚠ 金額系の表章項目を特定できませんでした。")
        dump_axes(axes)
        return 0
    hit = ingest(picked, out, year, attr_dim, attr_labels)
    print(f"  → {hit} 件取得")
    return hit


def find_age_tables(app_id):
    """年ごとの候補IDリストを返す。「収入と支出」を含む表を優先し、
    既知の正解 (KNOWN_AGE_TABLES) は先頭に置く。"""
    body = api_get("getStatsList", {"appId": app_id,
                                    "searchWord": AGE_SEARCH_WORD, "limit": 100})
    tables = as_list(body.get("GET_STATS_LIST", {})
                     .get("DATALIST_INF", {}).get("TABLE_INF"))
    found = {y: list(ids) for y, ids in KNOWN_AGE_TABLES.items()}
    scored = []
    for t in tables:
        title = t.get("TITLE")
        title = title.get("$", "") if isinstance(title, dict) else str(title or "")
        if "世帯主の年齢階級" not in title:
            continue
        year = str(t.get("SURVEY_DATE", ""))[:4]
        if year not in PERCAP_TABLES:
            continue
        pri = 0 if "収入と支出" in title else (1 if "支出" in title else 2)
        scored.append((pri, year, t.get("@id")))
    for pri, year, sid in sorted(scored):
        lst = found.setdefault(year, [])
        if sid not in lst:
            lst.append(sid)
    return found


def main():
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        sys.exit("環境変数 ESTAT_APP_ID を設定してください。\n"
                 '  PowerShell: $env:ESTAT_APP_ID = "..."\n'
                 '  bash/zsh  : export ESTAT_APP_ID="..."')

    out = {"meta": {}, "prefs": {str(c): {"name": n, "years": {}}
                                 for c, n in PREF_NAMES.items()}}

    for year, sid in PERCAP_TABLES.items():
        print(f"\n■ {year}年 消費支出 (二人以上の世帯)")
        fetch_table(app_id, sid, out, year)

    print("\n■ 世帯主の年齢階級別の統計表を検索中...")
    age_tables = find_age_tables(app_id)
    if not age_tables:
        print("  ⚠ 見つかりませんでした。属性なしで出力します。")
    for year, sids in sorted(age_tables.items()):
        print(f"\n■ {year}年 世帯主の年齢階級別 (候補{len(sids)}件)")
        for sid in sids[:4]:
            if fetch_table(app_id, sid, out, year, attr_axis_keyword="年齢階級"):
                break
            print(f"  → 次の候補を試します")
        else:
            print(f"  ⚠ {year}年の年齢階級別は取得できませんでした (属性なしで続行)")

    years = sorted({y for p in out["prefs"].values() for y in p["years"]})
    if not years:
        sys.exit("\n1件も取得できませんでした。上の診断出力を確認してください。")
    out["meta"] = {
        "years": years,
        "note": "出典: 全国家計構造調査 (e-Stat)。年齢属性は5歳階級を単純平均で集約",
        "metrics": {"percap": {"label": "1世帯当たり消費支出 (二人以上の世帯)",
                               "unit": "万円/月", "digits": 1}},
        "attr_unit": "万円/月",
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"\n完了: {os.path.normpath(OUT)} に書き出しました。年: {years}")
    print("ブラウザを再読み込みすると反映されます。")


if __name__ == "__main__":
    main()
