#!/usr/bin/env python3
"""
県民経済計算 (内閣府, e-Stat) から都道府県別の域際収支
「財貨・サービスの移出入 (純)」を取得し、data/pref_data.json に
指標 netexp として統合するスクリプト。

使い方 (PowerShell, scripts フォルダで実行):
  $env:ESTAT_APP_ID = "あなたのappId"
  python fetch_kenmin.py
  # 統計表を直接指定する場合:
  python fetch_kenmin.py --sid 0003XXXXXX

仕組み:
  - 「県民経済計算」を検索し、項目軸に「移出入」を含む統計表を自動特定
  - 単位を軸ラベルから推定 (百万円 → 兆円に換算。異なる場合は --scale で調整)
  - 既存の pref_data.json の年 (2014 / 2019 / 2024 など) に一致する年度の値を統合
  - 対象年に県民経済計算が未公表 (例: 2024) の場合、その年は空欄のまま
    (地図ではグレー表示になります)

注意: 県民経済計算は「年度」ベースです (2019 = 2019年度)。
"""

import argparse
import json
import os
import sys

from fetch_estat import api_get, as_list, pref_code_from_area, PREF_NAMES

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pref_data.json")

SEARCH_WORDS = ["県民経済計算 県内総生産 支出", "県民経済計算"]
ITEM_KEY = "移出入"                       # 項目名にこれを含むカテゴリを採用
PREFER_OTHER = ["実額", "金額", "名目", "当年価格", "総額", "計"]
DEFAULT_SCALE = 1e-6                      # 百万円 → 兆円


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


def find_item_axis(axes):
    """「移出入」を含むカテゴリを持つ軸を探す。
    戻り値: (軸ID, カテゴリコード, カテゴリ名) or (None, None, None)"""
    best = None
    for ax in axes:
        dim = ax.get("@id")
        if dim in ("area", "time"):
            continue
        for c in as_list(ax.get("CLASS")):
            name = c.get("@name") or ""
            if ITEM_KEY in name:
                # 「(純)」を含む名称を優先
                key = (0 if "純" in name else 1, len(name))
                if best is None or key < best[0]:
                    best = (key, dim, c.get("@code"), name)
    return (best[1], best[2], best[3]) if best else (None, None, None)


def pick_other_filters(axes, item_dim):
    extra = {}
    for ax in axes:
        dim, name = ax.get("@id"), ax.get("@name") or ""
        if dim in ("area", "time") or dim == item_dim:
            continue
        classes = as_list(ax.get("CLASS"))
        names = {c.get("@name", ""): c.get("@code") for c in classes}
        code, cname, mark = None, None, ""
        for p in PREFER_OTHER:
            if p in names:
                code, cname = names[p], p
                break
        if code is None:
            for p in PREFER_OTHER:
                for n, cd in names.items():
                    if p in n:
                        code, cname = cd, n
                        break
                if code:
                    break
        if code is None:
            c0 = classes[0]
            code, cname, mark = c0.get("@code"), c0.get("@name"), " ⚠ルール外のため先頭を選択"
        extra[f"cd{dim[0].upper()}{dim[1:]}"] = code
        print(f"    {name}: 「{cname}」{mark}")
    return extra


def main():
    p = argparse.ArgumentParser(description="県民経済計算 → 域際収支 (netexp) を統合")
    p.add_argument("--app-id", default=os.environ.get("ESTAT_APP_ID"))
    p.add_argument("--sid", help="statsDataId を直接指定")
    p.add_argument("--scale", type=float, default=DEFAULT_SCALE,
                   help="兆円への換算係数 (既定: 百万円→兆円 = 1e-6)")
    args = p.parse_args()
    if not args.app_id:
        sys.exit("環境変数 ESTAT_APP_ID を設定してください。")

    if not os.path.exists(OUT):
        sys.exit(f"{OUT} がありません。先に quickstart_japan.py を実行してください。")
    with open(OUT, encoding="utf-8") as fp:
        pref_data = json.load(fp)
    target_years = set(pref_data.get("meta", {}).get("years", []))
    print(f"統合先の年: {sorted(target_years)}")

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
    for sid in sids[:25]:
        axes = get_axes(args.app_id, sid)
        if not axes:
            continue
        item_dim, item_code, item_name = find_item_axis(axes)
        if not item_dim:
            if rejected < 6:
                print(f"  [候補 {sid}] 「移出入」項目なし: {titles.get(sid, '')[:50]}")
            rejected += 1
            continue
        print(f"\n[statsDataId {sid}] {titles.get(sid, '')[:60]}")
        print(f"    項目: 「{item_name}」")
        extra = pick_other_filters(axes, item_dim)
        extra[f"cd{item_dim[0].upper()}{item_dim[1:]}"] = item_code
        values = get_values(args.app_id, sid, extra)
        if not values:
            print("  ⚠ データなし。次の候補へ")
            continue

        by_year = {}
        for v in values:
            code = pref_code_from_area(v.get("@area", ""))
            raw = v.get("$")
            if code is None or raw in (None, "", "-", "***", "X"):
                continue
            year = str(v.get("@time", ""))[:4]
            try:
                by_year.setdefault(year, {})[code] = round(float(raw) * args.scale, 3)
            except ValueError:
                pass

        hit_years = [y for y in sorted(by_year) if len(by_year[y]) >= 40]
        use = [y for y in hit_years if y in target_years]
        if not use:
            print(f"  ⚠ 対象年と一致する年度なし (取得できた年度: {hit_years[-5:]})。次の候補へ")
            continue

        for y in use:
            for code, val in by_year[y].items():
                pref_data["prefs"][str(code)]["years"].setdefault(y, {})["netexp"] = val
        pref_data["meta"].setdefault("metrics", {})["netexp"] = {
            "label": "域際収支 (財貨・サービスの移出入・純)",
            "short": "域際収支", "unit": "兆円/年度", "digits": 2}
        note = pref_data["meta"].get("note", "")
        if "県民経済計算" not in note:
            pref_data["meta"]["note"] = note + "。域際収支は県民経済計算 (年度)"
        with open(OUT, "w", encoding="utf-8") as fp:
            json.dump(pref_data, fp, ensure_ascii=False, indent=1)
        missing = sorted(target_years - set(use))
        print(f"  → 域際収支を統合: {use}")
        if missing:
            print(f"  ※ 未公表等で入らなかった年: {missing} (地図ではグレー表示)")
        smp = sorted(by_year[use[-1]].items(), key=lambda x: -x[1])[:3]
        print("  上位 (妥当性確認用):",
              " / ".join(f"{PREF_NAMES[c]} {v:+.2f}兆円" for c, v in smp))
        return
    print("⚠ 県民経済計算の該当統計表を特定できませんでした。")
    print("  python fetch_estat.py search \"県民経済計算\" で候補を確認し、")
    print("  --sid で直接指定してください。")


if __name__ == "__main__":
    main()
