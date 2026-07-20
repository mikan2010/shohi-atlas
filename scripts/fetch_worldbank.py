#!/usr/bin/env python3
"""
World Bank Open Data API から国別の家計消費データを取得し、
世界マップ用 JSON (data/world_data.json) を生成するスクリプト。

- API キー不要 (登録不要のオープン API)
- 使用指標:
    NE.CON.PRVT.CD : 家計最終消費支出 総額 (現在価格 US$) → 十億USDに換算
    SP.POP.TOTL    : 人口 → 百万人に換算
  1人当たり (percap) は 総額÷人口 で導出する
  (World Bank に「1人当たり・現在US$」の直接指標が存在しないため)
- 出力キーは ISO 3166-1 numeric (ゼロ埋め3桁)。world-atlas の国 id と一致するため
  そのままフロントで結合できる。

使い方 (リポジトリの scripts/ ディレクトリで実行):
  python fetch_worldbank.py --years 2013 2018 2023 --out ../data/world_data.json

  # 単年のみ / 直近を含める例:
  python fetch_worldbank.py --years 2023

備考:
  - 国名は API の返す表記 (既定は英語)。--lang ja で日本語名を試みるが、
    World Bank 側の日本語対応は部分的なため、未対応の場合は英語のまま。
  - 地域集計 (World, East Asia など) は ISO numeric に対応しないため自動除外。
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://api.worldbank.org/v2"
WAIT_SEC = 0.6

INDICATORS = {
    "total": ("NE.CON.PRVT.CD", 1e-9, 1),   # → 十億USD/年
    "pop":   ("SP.POP.TOTL", 1e-6, 2),      # → 百万人
}


def api_get(path: str, query: str):
    # date=2013:2023 のコロンを%エンコードすると API がエラー(id:120)を返すことが
    # あるため、クエリ文字列は手組みでそのまま渡す
    url = f"{BASE}/{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "consumption-map/1.0"})
    with urllib.request.urlopen(req, timeout=60) as res:
        body = json.loads(res.read().decode("utf-8"))
    time.sleep(WAIT_SEC)
    return body


def _fetch_pages(code: str, date: str, lang: str):
    """1つの date 指定で全ページ取得。失敗時は None を返す。"""
    rows, page = [], 1
    while True:
        body = api_get(f"{lang}/country/all/indicator/{code}",
                       f"format=json&per_page=1000&page={page}&date={date}")
        if not isinstance(body, list) or len(body) < 2 or body[1] is None:
            print(f"  ⚠ date={date} で取得失敗: {str(body)[:120]}")
            return None
        meta, data = body[0], body[1]
        rows += data
        if page >= int(meta.get("pages", 1)):
            return rows
        page += 1


def fetch_indicator(code: str, years: list, lang: str) -> list:
    """範囲指定で取得し、失敗したら年ごとに個別取得してマージする。"""
    rows = _fetch_pages(code, f"{min(years)}:{max(years)}", lang)
    if rows is not None:
        return rows
    print("  → 年ごとの個別取得に切り替えます")
    merged = []
    for y in years:
        r = _fetch_pages(code, str(y), lang)
        if r is None:
            sys.exit(f"APIから取得できませんでした (indicator={code}, year={y})")
        merged += r
    return merged


def main():
    p = argparse.ArgumentParser(description="World Bank API → 世界マップ用 JSON 生成")
    p.add_argument("--years", nargs="+", required=True, help="取得する年 (例: 2013 2018 2023)")
    p.add_argument("--out", default="../data/world_data.json")
    p.add_argument("--lang", default="en", help="国名の言語 (en / ja など。ja は部分対応)")
    p.add_argument("--iso-map", default="../data/iso3_to_num.json",
                   help="ISO3 → numeric 対応表 (リポジトリに同梱)")
    args = p.parse_args()

    years = [str(y) for y in args.years]
    with open(args.iso_map, encoding="utf-8") as fp:
        iso3_to_num = json.load(fp)

    countries = {}
    for metric, (code, scale, nd) in INDICATORS.items():
        print(f"取得中: {metric} ({code}) {years[0]}〜{years[-1]}")
        rows = fetch_indicator(code, years, args.lang)
        hit = 0
        for r in rows:
            iso3 = r.get("countryiso3code") or ""
            num = iso3_to_num.get(iso3)      # 地域集計 (WLD等) はここで除外される
            year = str(r.get("date"))
            val = r.get("value")
            if num is None or year not in years or val is None:
                continue
            c = countries.setdefault(num, {
                "name": (r.get("country") or {}).get("value", iso3),
                "iso3": iso3, "years": {}})
            c["years"].setdefault(year, {})[metric] = round(float(val) * scale, nd)
            hit += 1
        print(f"  → {hit} 件を取り込み")

    # 1人当たり = 総額 ÷ 人口 (十億USD/百万人 → ×1000 で USD/人)
    derived = 0
    for c in countries.values():
        for y, s in c["years"].items():
            if s.get("total") is not None and s.get("pop"):
                s["percap"] = round(s["total"] / s["pop"] * 1000)
                derived += 1
    print(f"1人当たりを {derived} 件導出")

    out = {"meta": {"years": sorted(years),
                    "source": "World Bank Open Data (NE.CON.PRVT.CD, SP.POP.TOTL)"},
           "countries": countries}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"完了: {len(countries)} か国を {args.out} に書き出しました。")


if __name__ == "__main__":
    main()
