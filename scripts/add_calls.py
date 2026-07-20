#!/usr/bin/env python3
"""
都道府県別の通話発信量 (携帯電話・年間発信回数) を pref_data.json に
指標 calls として統合するスクリプト。ダウンロード不要 (データ同梱)。

出典: 総務省「通信量からみた我が国の音声通信利用状況 (令和5年度)」
      図表IV-3 都道府県別の通信の発信状況 (通信回数)
      https://www.soumu.go.jp/main_content/001000769.pdf
値は令和5年度 (2023年度) のもの。地図の最新年 (2024) の枠に「2023年度値」
として格納します (注記あり)。

使い方: python add_calls.py
"""

import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pref_data.json")

# 都道府県コード順 (1〜47) の携帯電話発信回数 (千回/年, 令和5年度)
CALLS_R5 = [1450742, 300995, 289619, 695448, 245000, 299003, 558187, 867180,
            572558, 561032, 1789817, 1696154, 4862314, 2169763, 552838, 276163,
            340043, 237305, 282612, 577814, 566186, 1048229, 2228998, 579386,
            389519, 793357, 3095633, 1513786, 358197, 318227, 165466, 190931,
            643002, 897533, 408695, 244653, 326477, 436079, 249170, 1924000,
            292537, 423226, 646026, 414709, 385169, 601832, 659983]


def main():
    if not os.path.exists(OUT):
        raise SystemExit(f"{OUT} がありません。先に quickstart_japan.py を実行してください。")
    with open(OUT, encoding="utf-8") as fp:
        pref_data = json.load(fp)
    years = sorted(pref_data.get("meta", {}).get("years", []))
    slot_year = years[-1] if years else "2024"

    for i, v in enumerate(CALLS_R5, start=1):
        pref_data["prefs"][str(i)]["years"].setdefault(slot_year, {})["calls"] = \
            round(v / 1e5, 2)   # 千回 → 億回
    pref_data["meta"].setdefault("metrics", {})["calls"] = {
        "label": "通話発信量 (携帯電話, 2023年度)", "short": "通話",
        "unit": "億回/年", "digits": 1}
    note = pref_data["meta"].get("note", "")
    if "音声通信" not in note:
        pref_data["meta"]["note"] = note + "。通話は音声通信利用状況 (2023年度)"
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(pref_data, fp, ensure_ascii=False, indent=1)
    print(f"通話発信量を {slot_year} の枠に47県ぶん統合しました (値は2023年度)。")
    top = sorted(enumerate(CALLS_R5, 1), key=lambda x: -x[1])[:3]
    names = {13: "東京都", 27: "大阪府", 23: "愛知県", 14: "神奈川県", 40: "福岡県"}
    print("上位:", " / ".join(f"{names.get(c, c)} {v/1e5:.1f}億回" for c, v in top))


if __name__ == "__main__":
    main()
