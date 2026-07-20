#!/usr/bin/env python3
"""
e-Stat API から都道府県別データを取得し、地図デモ用 JSON (pref_data.json) を生成するスクリプト。

事前準備:
  1. https://www.e-stat.go.jp/api/ でユーザ登録し、アプリケーションID (appId) を無料発行
  2. 環境変数に設定:  export ESTAT_APP_ID="あなたのappId"
     (または --app-id オプションで指定)

使い方 (3ステップ):

  # Step 1: 統計表を検索して statsDataId を特定する
  python fetch_estat.py search "全国家計構造調査 都道府県 消費支出"
  python fetch_estat.py search "県民経済計算 民間最終消費支出"

  # Step 2: 統計表のメタ情報 (分類軸とカテゴリコード) を確認する
  python fetch_estat.py meta 0003XXXXXX

  # Step 3: データを取得して JSON に書き出す (--merge で同じファイルに追記統合)
  #   単一値をメトリクスとして取り込む例 (1人当たり消費支出):
  python fetch_estat.py fetch 0003XXXXXX --metric percap \
      --filter cat01=001 --scale 0.0001 --out pref_data.json

  #   分類軸を「属性」として丸ごと取り込む例 (世帯主の年齢階級別):
  python fetch_estat.py fetch 0003YYYYYY --attr-dim cat02 --attr-name age \
      --scale 0.0001 --out pref_data.json --merge

出力 JSON の形式 (HTML デモがそのまま読み込める形):
  {
    "1": {"name": "北海道", "percap": 232.0, "total": 11.8, "pop": 510,
          "attrs": {"age": {"30代": 205.1, "40代": 228.9, ...}}},
    ...
  }

注意:
  - statsDataId は統計表ごとに異なり、改廃もあるため search / meta で必ず確認してください。
  - e-Stat API はリクエスト間隔を空けるのがマナーです (本スクリプトは自動で待機します)。
  - 属性クロス (都道府県 × 年齢/年収など) が最も充実しているのは「全国家計構造調査」です。
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
WAIT_SEC = 1.0  # リクエスト間の待機

PREF_NAMES = {
    1: "北海道", 2: "青森県", 3: "岩手県", 4: "宮城県", 5: "秋田県", 6: "山形県",
    7: "福島県", 8: "茨城県", 9: "栃木県", 10: "群馬県", 11: "埼玉県", 12: "千葉県",
    13: "東京都", 14: "神奈川県", 15: "新潟県", 16: "富山県", 17: "石川県", 18: "福井県",
    19: "山梨県", 20: "長野県", 21: "岐阜県", 22: "静岡県", 23: "愛知県", 24: "三重県",
    25: "滋賀県", 26: "京都府", 27: "大阪府", 28: "兵庫県", 29: "奈良県", 30: "和歌山県",
    31: "鳥取県", 32: "島根県", 33: "岡山県", 34: "広島県", 35: "山口県", 36: "徳島県",
    37: "香川県", 38: "愛媛県", 39: "高知県", 40: "福岡県", 41: "佐賀県", 42: "長崎県",
    43: "熊本県", 44: "大分県", 45: "宮崎県", 46: "鹿児島県", 47: "沖縄県",
}


# ---------------------------------------------------------------- HTTP
def api_get(endpoint: str, params: dict) -> dict:
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pref-map-demo/1.0"})
    with urllib.request.urlopen(req, timeout=60) as res:
        body = json.loads(res.read().decode("utf-8"))
    time.sleep(WAIT_SEC)
    return body


def as_list(x):
    """e-Stat の JSON は要素が1件だと dict、複数だと list になるため正規化する。"""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def pref_code_from_area(area_code: str):
    """地域コード '01000'〜'47000' → 都道府県コード 1〜47。該当しなければ None。
    (全国 '00000' や市区町村 '13101' などは除外される)"""
    s = str(area_code)
    if len(s) == 5 and s.endswith("000"):
        code = int(s[:2])
        if 1 <= code <= 47:
            return code
    return None


# ---------------------------------------------------------------- search
def cmd_search(args):
    params = {
        "appId": args.app_id,
        "searchWord": args.word,
        "limit": args.limit,
    }
    body = api_get("getStatsList", params)
    root = body.get("GET_STATS_LIST", {})
    if root.get("RESULT", {}).get("STATUS") != 0:
        sys.exit(f"APIエラー: {root.get('RESULT', {}).get('ERROR_MSG')}")
    tables = as_list(root.get("DATALIST_INF", {}).get("TABLE_INF"))
    if not tables:
        print("該当する統計表が見つかりませんでした。検索語を変えてみてください。")
        return
    print(f"{len(tables)} 件ヒット (statsDataId | 調査名 | 表題 | 調査年月)\n")
    for t in tables:
        sid = t.get("@id")
        stat = (t.get("STAT_NAME") or {}).get("$", "")
        title = t.get("TITLE")
        title = title.get("$", "") if isinstance(title, dict) else str(title or "")
        survey = t.get("SURVEY_DATE", "")
        print(f"  {sid} | {stat} | {title[:60]} | {survey}")


# ---------------------------------------------------------------- meta
def cmd_meta(args):
    params = {"appId": args.app_id, "statsDataId": args.stats_data_id}
    body = api_get("getMetaInfo", params)
    root = body.get("GET_META_INFO", {})
    if root.get("RESULT", {}).get("STATUS") != 0:
        sys.exit(f"APIエラー: {root.get('RESULT', {}).get('ERROR_MSG')}")
    objs = as_list(root.get("METADATA_INF", {}).get("CLASS_INF", {}).get("CLASS_OBJ"))
    for obj in objs:
        dim_id = obj.get("@id")       # 例: cat01, cat02, area, time
        dim_name = obj.get("@name")
        classes = as_list(obj.get("CLASS"))
        print(f"\n■ 分類軸 {dim_id} ({dim_name}) — {len(classes)} カテゴリ")
        for c in classes[: args.limit]:
            print(f"    code={c.get('@code')}  {c.get('@name')}")
        if len(classes) > args.limit:
            print(f"    ... ほか {len(classes) - args.limit} 件 (--limit で表示数変更)")


# ---------------------------------------------------------------- fetch
def fetch_all_values(app_id: str, stats_data_id: str, extra_params: dict) -> list:
    """getStatsData をページング (NEXT_KEY) しながら全件取得する。"""
    values, start = [], 1
    while True:
        params = {
            "appId": app_id,
            "statsDataId": stats_data_id,
            "metaGetFlg": "N",
            "cntGetFlg": "N",
            "limit": 100000,
            "startPosition": start,
            **extra_params,
        }
        body = api_get("getStatsData", params)
        root = body.get("GET_STATS_DATA", {})
        if root.get("RESULT", {}).get("STATUS") != 0:
            sys.exit(f"APIエラー: {root.get('RESULT', {}).get('ERROR_MSG')}")
        sd = root.get("STATISTICAL_DATA", {})
        values += as_list(sd.get("DATA_INF", {}).get("VALUE"))
        next_key = sd.get("RESULT_INF", {}).get("NEXT_KEY")
        if not next_key:
            return values
        start = int(next_key)


def fetch_dim_labels(app_id: str, stats_data_id: str, dim_id: str) -> dict:
    """属性軸のカテゴリコード → 名称の対応表を取得する。"""
    body = api_get("getMetaInfo", {"appId": app_id, "statsDataId": stats_data_id})
    objs = as_list(
        body.get("GET_META_INFO", {})
        .get("METADATA_INF", {})
        .get("CLASS_INF", {})
        .get("CLASS_OBJ")
    )
    for obj in objs:
        if obj.get("@id") == dim_id:
            return {c.get("@code"): c.get("@name") for c in as_list(obj.get("CLASS"))}
    sys.exit(f"分類軸 {dim_id} が見つかりません。meta コマンドで確認してください。")


def cmd_fetch(args):
    if not args.metric and not args.attr_dim:
        sys.exit("--metric か --attr-dim のどちらかを指定してください。")

    # --filter cat01=001 → cdCat01=001 のように API パラメータへ変換
    extra = {}
    for f in args.filter or []:
        key, _, val = f.partition("=")
        if not val:
            sys.exit(f"--filter の形式が不正です: {f} (例: cat01=001)")
        extra[f"cd{key[0].upper()}{key[1:]}"] = val
    if args.time:
        extra["cdTime"] = args.time

    print(f"取得中: statsDataId={args.stats_data_id} params={extra or 'なし'}")
    values = fetch_all_values(args.app_id, args.stats_data_id, extra)
    print(f"  → {len(values)} 件のデータポイント")

    labels = fetch_dim_labels(args.app_id, args.stats_data_id, args.attr_dim) if args.attr_dim else {}

    # 出力形式: {"meta":{"years":[...]}, "prefs":{code:{name, years:{year:{...}}}}}
    # (--merge 指定時は既存 JSON に統合。地図側は年スライダーで切り替え表示する)
    out = {"meta": {"years": []}, "prefs": {}}
    if args.merge and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fp:
            loaded = json.load(fp)
        if "prefs" in loaded:
            out = loaded
    for code, name in PREF_NAMES.items():
        out["prefs"].setdefault(str(code), {"name": name, "years": {}})

    hit = 0
    years_seen = set(out["meta"].get("years", []))
    for v in values:
        code = pref_code_from_area(v.get("@area", ""))
        if code is None:
            continue
        raw = v.get("$")
        if raw in (None, "", "-", "***", "X"):  # 秘匿値・欠測
            continue
        try:
            val = round(float(raw) * args.scale, args.round)
        except ValueError:
            continue
        # 時間軸コード (例: "2024000000") の先頭4桁を年として使う
        year = str(v.get("@time", ""))[:4] or "latest"
        years_seen.add(year)
        yslot = out["prefs"][str(code)]["years"].setdefault(year, {})
        if args.attr_dim:
            cat_code = v.get(f"@{args.attr_dim}", "")
            cat_name = labels.get(cat_code, cat_code)
            yslot.setdefault("attrs", {}).setdefault(args.attr_name, {})[cat_name] = val
        else:
            yslot[args.metric] = val
        hit += 1

    out["meta"]["years"] = sorted(years_seen)
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"  → 都道府県に紐づいた {hit} 件を {args.out} に書き出しました。")
    print(f"  → 年: {out['meta']['years']}")
    missing = [n for c, n in PREF_NAMES.items() if not out["prefs"][str(c)]["years"]]
    if missing:
        print(f"  ⚠ 値が入らなかった都道府県: {', '.join(missing[:5])}"
              + (" ほか" if len(missing) > 5 else ""))
        print("    (統計表が都道府県別でない、フィルタ条件が絞れていない等の可能性)")


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="e-Stat API → 地図デモ用 JSON 生成")
    p.add_argument("--app-id", default=os.environ.get("ESTAT_APP_ID"),
                   help="e-Stat の appId (未指定なら環境変数 ESTAT_APP_ID)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="統計表を検索して statsDataId を特定")
    s.add_argument("word", help="検索語 (例: '全国家計構造調査 都道府県 消費支出')")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    m = sub.add_parser("meta", help="統計表の分類軸・カテゴリコードを表示")
    m.add_argument("stats_data_id")
    m.add_argument("--limit", type=int, default=15, help="軸ごとの表示カテゴリ数")
    m.set_defaults(func=cmd_meta)

    f = sub.add_parser("fetch", help="データ取得して JSON 出力")
    f.add_argument("stats_data_id")
    f.add_argument("--metric", help="書き込み先キー名 (percap / total / pop など)")
    f.add_argument("--attr-dim", help="属性として展開する分類軸ID (例: cat02)")
    f.add_argument("--attr-name", default="attr", help="属性の名前 (例: age, income)")
    f.add_argument("--filter", action="append",
                   help="絞り込み (繰り返し可)。例: --filter cat01=001 --filter tab=01")
    f.add_argument("--time", help="時間軸コード (例: 2024000000)。未指定なら全期間")
    f.add_argument("--scale", type=float, default=1.0,
                   help="単位換算係数 (例: 円→万円 は 0.0001)")
    f.add_argument("--round", type=int, default=1, help="丸め桁数")
    f.add_argument("--out", default="pref_data.json")
    f.add_argument("--merge", action="store_true", help="既存の出力 JSON に統合する")
    f.set_defaults(func=cmd_fetch)

    args = p.parse_args()
    if not args.app_id:
        sys.exit("appId が未設定です。--app-id か 環境変数 ESTAT_APP_ID を設定してください。")
    args.func(args)


if __name__ == "__main__":
    main()
