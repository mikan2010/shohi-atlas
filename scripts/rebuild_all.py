#!/usr/bin/env python3
"""
全データを一括で再生成するスクリプト。データがサンプルに戻ってしまった場合や、
定期更新のときはこれ1本を実行すれば OK です。

使い方 (PowerShell, scripts フォルダで実行):
  $env:ESTAT_APP_ID = "あなたのappId"
  python rebuild_all.py

前提: scripts フォルダに syuyo4.xlsx (県民経済計算) と kam22.xlsx (貨物) が
ある場合はそれらも取り込みます (無ければスキップして警告表示)。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 貨物 Excel の設定 (ファイル名と年度が変わったらここを更新)
FREIGHT_FILE = "kam22.xlsx"
FREIGHT_YEAR = "2022"
# 県民経済計算 Excel
KENMIN_FILE = "syuyo4.xlsx"

STEPS = [
    ("日本: 消費・属性・総額・人口 (e-Stat API)",
     [sys.executable, "quickstart_japan.py"], None),
    ("日本: 域際収支 (県民経済計算 Excel)",
     [sys.executable, "convert_excel.py", "kenmin", KENMIN_FILE], KENMIN_FILE),
    ("日本: 産業構成 (県民経済計算 Excel)",
     [sys.executable, "convert_excel.py", "industries", "syuyo1.xlsx"], "syuyo1.xlsx"),
    ("日本: 財政移転 (e-Stat API)",
     [sys.executable, "fetch_fiscal.py"], None),
    ("日本: 通話発信量 (同梱データ)",
     [sys.executable, "add_calls.py"], None),
    ("流れ: 人流 (e-Stat API)",
     [sys.executable, "fetch_flows.py", "people"], None),
    ("流れ: 物流 (貨物 Excel)",
     [sys.executable, "convert_excel.py", "matrix", FREIGHT_FILE,
      "--year", FREIGHT_YEAR, "--scale", "0.001", "--unit", "千トン/年度"],
     FREIGHT_FILE),
    ("世界: 家計消費 (World Bank API)",
     [sys.executable, "fetch_worldbank.py", "--years", "2013", "2018", "2023",
      "--out", "../data/world_data.json"], None),
    ("派生指標: 伸び率・流入率・特化係数",
     [sys.executable, "derive_insights.py"], None),
]


def main():
    if not os.environ.get("ESTAT_APP_ID"):
        sys.exit("環境変数 ESTAT_APP_ID を設定してください。\n"
                 '  PowerShell: $env:ESTAT_APP_ID = "..."')
    results = []
    for name, cmd, requires in STEPS:
        print(f"\n{'='*60}\n■ {name}\n{'='*60}")
        if requires and not os.path.exists(os.path.join(HERE, requires)):
            print(f"⚠ {requires} が見つからないためスキップします。")
            results.append((name, "スキップ"))
            continue
        r = subprocess.run(cmd, cwd=HERE)
        results.append((name, "OK" if r.returncode == 0 else "失敗"))

    print(f"\n{'='*60}\n結果まとめ\n{'='*60}")
    for name, st in results:
        mark = {"OK": "✓", "失敗": "✗", "スキップ": "-"}[st]
        print(f"  {mark} {st}: {name}")
    if any(st == "失敗" for _, st in results):
        print("\n失敗した項目のログを確認してください。")
    else:
        print("\n完了。このあと: cd .. → git add . → git commit → git push")


if __name__ == "__main__":
    main()
