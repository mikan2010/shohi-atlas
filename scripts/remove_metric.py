#!/usr/bin/env python3
"""
pref_data.json から指標を削除するツール。ボタンは自動的に非表示になります。

使い方: python remove_metric.py info
        python remove_metric.py info broadband   # 複数まとめて可
"""

import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pref_data.json")

if len(sys.argv) < 2:
    raise SystemExit("削除する指標キーを指定してください (例: python remove_metric.py info)")
keys = sys.argv[1:]

with open(OUT, encoding="utf-8") as fp:
    d = json.load(fp)
hit = 0
for p in d["prefs"].values():
    for s in p.get("years", {}).values():
        for k in keys:
            if k in s:
                del s[k]
                hit += 1
for k in keys:
    d.get("meta", {}).get("metrics", {}).pop(k, None)
with open(OUT, "w", encoding="utf-8") as fp:
    json.dump(d, fp, ensure_ascii=False, indent=1)
print(f"{keys} を削除しました ({hit} 件)。ブラウザ再読み込みでボタンも消えます。")
