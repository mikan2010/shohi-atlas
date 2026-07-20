#!/usr/bin/env python3
"""
e-Stat API から都道府県間のフロー (OD) データを取得し、
data/flow_data.json を生成・統合するスクリプト。

対象:
  people : 住民基本台帳人口移動報告 (都道府県間移動者数, 毎年)
  goods  : 貨物地域流動調査 (都道府県間の貨物流動量)
           ※ e-Stat API に収載されていない場合は取得できません。その場合は
             国土交通省サイトの Excel を変換する必要があります (メッセージ表示)。

使い方 (PowerShell, scripts フォルダで実行):
  $env:ESTAT_APP_ID = "あなたのappId"
  python fetch_flows.py people
  python fetch_flows.py goods
  # 統計表を指定したい場合:
  python fetch_flows.py people --sid 0003XXXXXX

仕組み:
  - 統計表を検索し、「分類軸のカテゴリ名が47都道府県名と一致する軸」を持つ表を
    OD 表とみなす (その軸 = 相手方, area 軸 = 自県)
  - それ以外の軸は「総数」等で自動的に絞り込む
  - 月次データは年単位に合算し、年計行と月次行が混在する表では二重計上を回避
"""

import argparse
import json
import os
import re
import sys

from fetch_estat import api_get, as_list, pref_code_from_area, PREF_NAMES

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "flow_data.json")
PREF_BY_NAME = {v: k for k, v in PREF_NAMES.items()}
# 「東京」「大阪」のような府県サフィックスなしの表記にも対応
PREF_SHORT = {}
for _c, _n in PREF_NAMES.items():
    if _n != "北海道":
        PREF_SHORT[re.sub(r"[都府県]$", "", _n)] = _c


def norm_name(name):
    """「01 北海道」「１３　東京都」のようなコード付き表記を正規化する。"""
    n = str(name or "").strip()
    n = re.sub(r"^[0-9０-９]+[\s　_．.\-]*", "", n)
    return n.strip()


def pref_from_name(name):
    n = norm_name(name)
    return PREF_BY_NAME.get(n) or PREF_SHORT.get(n)

MODES = {
    "people": {
        # 発見済みのOD表 (最優先で試す):
        #   0003423613: 月報2 移動前の住所地別都道府県間移動者数 (2019年1月〜, 月次)
        #   0003021172: 年報(基本集計)2 同上 (2010〜2013年)
        "priority_sids": ["0003423613", "0003021172"],
        "search": ["移動前の住所地別都道府県間移動者数",
                   "住民基本台帳人口移動報告 移動前の住所地"],
        "label": "人の移動 (住民基本台帳人口移動報告)",
        "unit": "人/年", "in": "転入", "out": "転出",
        # OD軸のカテゴリ側が「移動前住所地」= from, area側 = 現在の住所 = to
        "cat_is_from": True,
        "prefer": ["総数", "移動者数", "計", "総計", "男女計", "日本人移動者"],
    },
    "goods": {
        "priority_sids": [],
        "search": ["貨物地域流動調査 都道府県 流動", "貨物地域流動調査"],
        "label": "貨物の流動 (貨物地域流動調査)",
        "unit": "トン/年", "in": "流入", "out": "流出",
        # 発地が分類軸・着地がarea軸の表を想定 (逆の場合はログを見て --swap 指定)
        "cat_is_from": True,
        "prefer": ["合計", "総数", "計", "全輸送機関"],
    },
}


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


def find_od_axis(axes):
    """カテゴリ名が都道府県名と40件以上一致する軸を探す。
    戻り値: (軸ID, {カテゴリコード: 都道府県コード}) or (None, None)"""
    for ax in axes:
        dim = ax.get("@id")
        if dim in ("area", "time") or dim == "tab":
            continue
        mapping = {}
        for c in as_list(ax.get("CLASS")):
            code = pref_from_name(c.get("@name"))
            if code:
                mapping[c.get("@code")] = code
        if len(mapping) >= 40:
            return dim, mapping
    return None, None


def pick_filters(axes, od_dim, prefer):
    """OD軸・area・time以外の軸を1カテゴリに絞る。"""
    extra = {}
    for ax in axes:
        dim, name = ax.get("@id"), ax.get("@name") or ""
        if dim in ("area", "time") or dim == od_dim:
            continue
        classes = as_list(ax.get("CLASS"))
        names = {c.get("@name", ""): c.get("@code") for c in classes}
        code, cname = None, None
        for p in prefer:
            if p in names:
                code, cname = names[p], p
                break
        if code is None:
            for p in prefer:
                for n, cd in names.items():
                    if p in n:
                        code, cname = cd, n
                        break
                if code:
                    break
        mark = ""
        if code is None:
            c0 = classes[0]
            code, cname = c0.get("@code"), c0.get("@name")
            mark = " ⚠ルール外のため先頭を選択"
        extra[f"cd{dim[0].upper()}{dim[1:]}"] = code
        print(f"    {name}: 「{cname}」{mark}")
    return extra


def collect_flows(values, od_dim, od_map, cat_is_from):
    """時間コード別に OD を集計 → 年計/月次の混在を解消して年単位で返す。
    戻り値: {year: {(from,to): value}}"""
    by_time = {}
    for v in values:
        area = pref_code_from_area(v.get("@area", ""))
        other = od_map.get(v.get(f"@{od_dim}", ""))
        raw = v.get("$")
        if area is None or other is None or raw in (None, "", "-", "***", "X"):
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        f, t = (other, area) if cat_is_from else (area, other)
        if f == t:
            continue
        tc = str(v.get("@time", "0000"))
        by_time.setdefault(tc, {})
        by_time[tc][(f, t)] = by_time[tc].get((f, t), 0) + val

    # 年ごとにまとめる。年計行 (最大合計 ≒ 他の合計) があればそれのみ採用
    by_year = {}
    times_per_year = {}
    for tc, m in by_time.items():
        times_per_year.setdefault(tc[:4], []).append(tc)
    for year, tcs in times_per_year.items():
        if len(tcs) == 1:
            by_year[year] = by_time[tcs[0]]
            continue
        totals = {tc: sum(by_time[tc].values()) for tc in tcs}
        top = max(totals, key=totals.get)
        rest = sum(v for k, v in totals.items() if k != top)
        if rest > 0 and 0.85 <= totals[top] / rest <= 1.15:
            by_year[year] = by_time[top]          # 年計行 + 月次行 → 年計のみ
        elif len(tcs) >= 12:
            merged = {}
            for tc in tcs:                         # 月次のみ → 12か月合算
                for k, v in by_time[tc].items():
                    merged[k] = merged.get(k, 0) + v
            by_year[year] = merged
        # 12か月に満たない年 (集計途中) はスキップ
    return by_year


def run(mode, app_id, sid_arg, swap, scale):
    cfg = MODES[mode]
    sids, titles = ([sid_arg], {}) if sid_arg else (list(cfg.get("priority_sids", [])), {})
    if not sid_arg:
        words = cfg["search"] if isinstance(cfg["search"], list) else [cfg["search"]]
        for w in words:
            body = api_get("getStatsList", {"appId": app_id,
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
        if not sids:
            print(f"⚠ 統計表が見つかりませんでした (検索語: {words})")
            if mode == "goods":
                print("  貨物地域流動調査は e-Stat API 未収載の可能性があります。")
                print("  その場合、国土交通省サイトの Excel を data/flow_data.json の")
                print("  形式 (flows.goods.<年> = [[発,着,量],...]) に変換してください。")
            return

    rejected = 0
    for sid in sids[:25]:
        axes = get_axes(app_id, sid)
        if not axes:
            continue
        od_dim, od_map = find_od_axis(axes)
        if not od_dim:
            if rejected < 6:  # 診断: なぜOD表でないかを表示
                ax_desc = " / ".join(f"{a.get('@name')}({len(as_list(a.get('CLASS')))})"
                                     for a in axes if a.get("@id") not in ("time",))[:120]
                print(f"  [候補 {sid}] OD軸なし: {titles.get(sid,'')[:40]} | 軸: {ax_desc}")
            rejected += 1
            continue
        print(f"\n[statsDataId {sid}] OD表として処理 (相手方の軸: {od_dim}, {len(od_map)}都道府県)")
        extra = pick_filters(axes, od_dim, cfg["prefer"])
        values = get_values(app_id, sid, extra)
        if not values:
            print("  ⚠ データなし。次の候補へ")
            continue
        cat_is_from = cfg["cat_is_from"] ^ bool(swap)
        by_year = collect_flows(values, od_dim, od_map, cat_is_from)
        if not by_year:
            print("  ⚠ ODを構成できず。次の候補へ")
            continue

        # 出力に統合
        out = {"meta": {"modes": {}}, "flows": {}}
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as fp:
                out = json.load(fp)
        out["meta"].pop("note", None)   # 実データが入ったのでサンプル注記を外す
        out["meta"].setdefault("modes", {})[mode] = {
            "label": cfg["label"], "unit": cfg["unit"],
            "in": cfg["in"], "out": cfg["out"]}
        out.setdefault("flows", {})[mode] = {
            y: [[f, t, round(v * scale)] for (f, t), v in m.items() if v * scale >= 1]
            for y, m in sorted(by_year.items())}
        with open(OUT, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False)
        yrs = sorted(by_year)
        smp = sorted(by_year[yrs[-1]].items(), key=lambda x: -x[1])[:3]
        print(f"  → {len(yrs)} 年ぶんを書き出し: {yrs}")
        print("  上位フロー (方向の妥当性確認用):")
        for (f, t), v in smp:
            print(f"    {PREF_NAMES[f]} → {PREF_NAMES[t]} : {round(v*scale):,} {cfg['unit']}")
        print("  ※ 矢印の向きが逆に見える場合は --swap を付けて再実行してください。")
        return
    print("⚠ OD構造の統計表を特定できませんでした。search コマンド等で statsDataId を")
    print("  調べ、--sid で直接指定してください。")


def main():
    p = argparse.ArgumentParser(description="e-Stat → 都道府県間フロー JSON 生成")
    p.add_argument("mode", choices=list(MODES))
    p.add_argument("--app-id", default=os.environ.get("ESTAT_APP_ID"))
    p.add_argument("--sid", help="statsDataId を直接指定")
    p.add_argument("--swap", action="store_true", help="発着の向きを反転する")
    p.add_argument("--scale", type=float, default=1.0, help="単位換算係数")
    args = p.parse_args()
    if not args.app_id:
        sys.exit("環境変数 ESTAT_APP_ID を設定してください。")
    run(args.mode, args.app_id, args.sid, args.swap, args.scale)


if __name__ == "__main__":
    main()
