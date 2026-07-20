#!/usr/bin/env python3
"""
既存データから「参入示唆」の派生指標を計算するスクリプト。
外部APIやExcelは使わず、pref_data.json と flow_data.json だけから導出します。

  1. growth : 消費支出の伸び率 (最古年→最新年, %)   … 需要が伸びている県
  2. netmig : 人口純流入率 (人流の最新年, ‰)         … 人が集まっている県
  3. attrs.lq : 産業別特化係数 (全国=1)              … 集積 (>1) と空白 (<1)

使い方: python derive_insights.py
(quickstart / industries / fetch_flows people の後に実行してください。
 rebuild_all.py にも組み込み済みです)
"""

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
PREF = os.path.join(BASE, "..", "data", "pref_data.json")
FLOW = os.path.join(BASE, "..", "data", "flow_data.json")


def main():
    with open(PREF, encoding="utf-8") as fp:
        pd = json.load(fp)
    years = sorted(pd["meta"]["years"])
    latest, oldest = years[-1], years[0]

    # ---- 1. 消費の伸び率 (percap の 最古年→最新年) ----
    hit = 0
    for p in pd["prefs"].values():
        a = p["years"].get(oldest, {}).get("percap")
        b = p["years"].get(latest, {}).get("percap")
        if a and b:
            p["years"][latest]["growth"] = round((b / a - 1) * 100, 1)
            hit += 1
    if hit:
        pd["meta"].setdefault("metrics", {})["growth"] = {
            "label": f"消費の伸び ({oldest}→{latest})", "short": "消費の伸び",
            "unit": "%", "digits": 1}
        print(f"消費の伸び率: {hit} 県 ({oldest}→{latest})")

    # ---- 2. 人口純流入率 (flow_data の people 最新年) ----
    if os.path.exists(FLOW):
        with open(FLOW, encoding="utf-8") as fp:
            fd = json.load(fp)
        people = fd.get("flows", {}).get("people", {})
        if people:
            fy = sorted(people)[-1]
            inn, out = {}, {}
            for f, t, v in people[fy]:
                inn[t] = inn.get(t, 0) + v
                out[f] = out.get(f, 0) + v
            hit = 0
            for code, p in pd["prefs"].items():
                pop = p["years"].get(latest, {}).get("pop")  # 万人
                if not pop:
                    continue
                net = inn.get(int(code), 0) - out.get(int(code), 0)
                p["years"][latest]["netmig"] = round(net / (pop * 1e4) * 1000, 2)
                hit += 1
            pd["meta"]["metrics"]["netmig"] = {
                "label": f"人口純流入率 ({fy}年の移動)", "short": "人口流入",
                "unit": "‰", "digits": 1}
            print(f"人口純流入率: {hit} 県 ({fy}年の人流から)")

    # ---- 3. 産業別特化係数 (LQ) ----
    lq_years = []
    for y in years:
        nat = {}
        gdp_nat = 0.0
        for p in pd["prefs"].values():
            ind = p["years"].get(y, {}).get("attrs", {}).get("industry")
            if not ind:
                continue
            for k, v in ind.items():
                nat[k] = nat.get(k, 0) + v
                gdp_nat += v
        if not nat:
            continue
        for p in pd["prefs"].values():
            ind = p["years"].get(y, {}).get("attrs", {}).get("industry")
            if not ind:
                continue
            gdp_p = sum(ind.values())
            lq = {}
            for k, v in ind.items():
                if gdp_p > 0 and nat[k] > 0:
                    lq[k] = round((v / gdp_p) / (nat[k] / gdp_nat), 2)
            p["years"][y]["attrs"]["lq"] = lq
        lq_years.append(y)
    if lq_years:
        pd["meta"].setdefault("attr_units", {})["lq"] = "倍 (全国=1)"
        pd["meta"].setdefault("attr_titles", {})["lq"] = "産業別 特化係数"
        print(f"産業別特化係数: {lq_years} の各年で計算")

    note = pd["meta"].get("note", "")
    if "派生指標" not in note:
        pd["meta"]["note"] = note + "。伸び率・流入率・特化係数は当サイトによる派生指標"
    with open(PREF, "w", encoding="utf-8") as fp:
        json.dump(pd, fp, ensure_ascii=False, indent=1)

    # 妥当性確認の表示
    g = sorted(((p["name"], p["years"].get(latest, {}).get("netmig"))
                for p in pd["prefs"].values()
                if p["years"].get(latest, {}).get("netmig") is not None),
               key=lambda x: -x[1])[:3]
    if g:
        print("人口流入の上位 (妥当性確認用):",
              " / ".join(f"{n} {v:+.1f}‰" for n, v in g))
        print("※ 東京・首都圏・福岡・沖縄あたりが上位なら妥当です。")


if __name__ == "__main__":
    main()
