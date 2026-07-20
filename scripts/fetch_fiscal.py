#!/usr/bin/env python3
"""
社会・人口統計体系 (e-Stat) から都道府県別の「地方交付税額」を取得し、
data/pref_data.json に指標 grants (財政移転) として統合するスクリプト。
国から都道府県への公的マネーの流入を表す指標です。

使い方 (PowerShell, scripts フォルダで実行):
  $env:ESTAT_APP_ID = "あなたのappId"
  python fetch_fiscal.py

仕組み:
  - 「社会・人口統計体系 都道府県 行政基盤 財政」等で統計表を検索し、
    カテゴリ名に「地方交付税」を含む項目を持つ表を自動特定
  - 単位は項目名・注記から千円と想定し兆円へ換算 (異なる場合は --scale で調整)
  - 地図の年 (2014 / 2019 / 2024 など) に一致する年度を統合。無い年は
    最も近い年で代用し、その旨を表示
"""

import argparse
import json
import os
import sys

from fetch_estat import api_get, as_list, pref_code_from_area, PREF_NAMES

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pref_data.json")

SEARCH_WORDS = ["社会・人口統計体系 都道府県データ 基礎データ 行政基盤",
                "社会・人口統計体系 都道府県 財政"]
ITEM_KEY = "地方交付税"
DEFAULT_SCALE = 1e-9   # 千円 → 兆円


def get_axes(app_id, sid):
    body = api_get("getMetaInfo", {"appId": app_id, "statsDataId": sid})
    root = body.get("GET_META_INFO", {})
    if root.get("RESULT", {}).get("STATUS") != 0:
        return None
    return as_list(root.get("METADATA_INF", {}).get("CLASS_INF", {}).get("CLASS_OBJ"))


def get_values(app_id, sid, extra):
    values, start = [], 1
    while True:
        params = {"appId": app_id, "statsDataId": sid, "metaGetFlg": "N",
                  "cntGetFlg": "N", "limit": 100000, "startPosition": start, **extra}
        body = api_get("getStatsData", params)
        root = body.get("GET_STATS_DATA", {})
        if root.get("RESULT", {}).get("STATUS") not in (0, 1):
            sys.exit(f"APIエラー({sid}): {root.get('RESULT', {}).get('ERROR_MSG')}")
        sd = root.get("STATISTICAL_DATA", {})
        values += as_list(sd.get("DATA_INF", {}).get("VALUE"))
        next_key = sd.get("RESULT_INF", {}).get("NEXT_KEY")
        if not next_key:
            return values
        start = int(next_key)


def nearest(target, available):
    available = [y for y in available]
    if target in available:
        return target
    return min(available, key=lambda y: abs(int(y) - int(target))) if available else None


def main():
    p = argparse.ArgumentParser(description="地方交付税 (財政移転) を pref_data.json に統合")
    p.add_argument("--app-id", default=os.environ.get("ESTAT_APP_ID"))
    p.add_argument("--sid", help="statsDataId を直接指定")
    p.add_argument("--scale", type=float, default=DEFAULT_SCALE,
                   help="兆円への換算係数 (既定: 千円→兆円 = 1e-9)")
    args = p.parse_args()
    if not args.app_id:
        sys.exit("環境変数 ESTAT_APP_ID を設定してください。")
    if not os.path.exists(OUT):
        sys.exit(f"{OUT} がありません。先に quickstart_japan.py を実行してください。")
    with open(OUT, encoding="utf-8") as fp:
        pref_data = json.load(fp)
    targets = sorted(pref_data.get("meta", {}).get("years", []))
    print(f"統合先の年: {targets}")

    sids, titles = ([args.sid], {}) if args.sid else ([], {})
    if not sids:
        for w in SEARCH_WORDS:
            body = api_get("getStatsList", {"appId": args.app_id,
                                            "searchWord": w, "limit": 30})
            for t in as_list(body.get("GET_STATS_LIST", {})
                             .get("DATALIST_INF", {}).get("TABLE_INF")):
                sid = t.get("@id")
                if sid and sid not in sids:
                    sids.append(sid)
                    tt = t.get("TITLE")
                    titles[sid] = tt.get("$", "") if isinstance(tt, dict) else str(tt or "")
            if len(sids) >= 30:
                break

    rejected = 0
    for sid in sids[:20]:
        axes = get_axes(args.app_id, sid)
        if not axes:
            continue
        found = None
        for ax in axes:
            dim = ax.get("@id")
            if dim in ("area", "time"):
                continue
            cands = [((0 if "都道府県" in (c.get("@name") or "") else
                       2 if "市町村" in (c.get("@name") or "") else 1),
                      len(c.get("@name", "")), c.get("@code"), c.get("@name"))
                     for c in as_list(ax.get("CLASS"))
                     if ITEM_KEY in (c.get("@name") or "")
                     and "率" not in (c.get("@name") or "")
                     and "当たり" not in (c.get("@name") or "")]
            if cands:
                found = (dim,) + tuple(sorted(cands)[0][2:])
                break
        if not found:
            if rejected < 5:
                print(f"  [候補 {sid}] 「{ITEM_KEY}」なし: {titles.get(sid, '')[:50]}")
            rejected += 1
            continue
        dim, code, name = found
        print(f"\n[statsDataId {sid}] {titles.get(sid, '')[:60]}")
        print(f"    項目: 「{name}」 (単位が千円か項目名・出典で確認してください)")
        extra = {f"cd{dim[0].upper()}{dim[1:]}": code}
        values = get_values(args.app_id, sid, extra)
        by_year = {}
        for v in values:
            pc = pref_code_from_area(v.get("@area", ""))
            raw = v.get("$")
            if pc is None or raw in (None, "", "-", "***", "X"):
                continue
            year = str(v.get("@time", ""))[:4]
            try:
                by_year.setdefault(year, {})[pc] = round(float(raw) * args.scale, 3)
            except ValueError:
                pass
        good_years = [y for y in sorted(by_year) if len(by_year[y]) >= 40]
        if not good_years:
            print("  ⚠ 47都道府県分そろわず。次の候補へ")
            continue

        hit = 0
        for ty in targets:
            src = nearest(ty, good_years)
            if src is None:
                continue
            if src != ty:
                print(f"  ※ {ty}年には {src}年の値を代用")
            for pc, val in by_year[src].items():
                pref_data["prefs"][str(pc)]["years"].setdefault(ty, {})["grants"] = val
                hit += 1
        pref_data["meta"].setdefault("metrics", {})["grants"] = {
            "label": "財政移転 (地方交付税)", "short": "財政移転",
            "unit": "兆円/年度", "digits": 2}
        note = pref_data["meta"].get("note", "")
        if "地方交付税" not in note:
            pref_data["meta"]["note"] = note + "。財政移転は地方交付税額 (社会・人口統計体系)"
        with open(OUT, "w", encoding="utf-8") as fp:
            json.dump(pref_data, fp, ensure_ascii=False, indent=1)
        latest = nearest(targets[-1], good_years)
        smp = sorted(by_year[latest].items(), key=lambda x: -x[1])[:3]
        print(f"  → {hit} 件を統合 (取得できた年: {good_years[0]}〜{good_years[-1]})")
        print("  上位 (妥当性確認用):",
              " / ".join(f"{PREF_NAMES[c]} {v:.2f}兆円" for c, v in smp))
        print("  ※ 北海道・地方部が上位なら妥当です。桁が変な場合は --scale を調整してください。")
        return
    print("⚠ 該当統計表を特定できませんでした。fetch_estat.py の search で")
    print("  「社会・人口統計体系 行政基盤」を調べ、--sid で指定してください。")


if __name__ == "__main__":
    main()
