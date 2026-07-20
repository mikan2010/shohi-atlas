# 消費マップ (都道府県別 / 国別)

政府統計 (e-Stat) と World Bank Open Data をもとに、消費関連指標を地図上で
ビジュアライズするための静的サイトです。GitHub Pages でそのまま公開できます。

- **日本ページ** (`index.html`): 都道府県別コロプレスマップ
  - 基本指標 (1人当たり消費 / 総額 / 人口) の切り替え
  - 属性 (年齢階級など) のカテゴリ別表示
  - 2カテゴリの**差分マップ** (例:「30代」−「60代」、朱⇄藍のダイバージング配色)
  - **年スライダー**による時系列切り替え
  - クリックで詳細パネル (属性の内訳グラフ・全国順位)
- **世界ページ** (`world.html`): 国別コロプレスマップ
  - 1人当たり家計消費 (USD) / 総額 / 人口、対数スケール配色
  - 年スライダー、国別ランキング、時系列の推移バー

初期状態のデータは**構成確認用のサンプル値**です(実測値ではありません)。
下記スクリプトで実データに差し替えてください。

## ディレクトリ構成

```
├── index.html            日本ページ
├── world.html            世界ページ
├── assets/
│   ├── style.css         共通スタイル
│   ├── app.js            日本ページのロジック
│   ├── world.js          世界ページのロジック
│   ├── japan.topojson    都道府県境界 (国土数値情報ベース・簡略化済み)
│   └── world.topojson    国境界 (world-atlas / Natural Earth)
├── data/
│   ├── pref_data.json    都道府県データ (サンプル → fetch_estat.py で置換)
│   ├── world_data.json   国別データ (サンプル → fetch_worldbank.py で置換)
│   └── iso3_to_num.json  ISO3 → ISO numeric 対応表
└── scripts/
    ├── fetch_estat.py    e-Stat API 取得スクリプト (要 appId)
    └── fetch_worldbank.py  World Bank API 取得スクリプト (キー不要)
```

## ローカルでの確認

データを `fetch` で読み込むため、`file://` 直開きでは動きません。
リポジトリ直下で簡易サーバを立ててください。

```bash
python -m http.server 8000
# → http://localhost:8000/ (日本) / http://localhost:8000/world.html (世界)
```

## データの更新

### 日本 (e-Stat API)

1. https://www.e-stat.go.jp/api/ でアプリケーションID (appId) を無料発行
2. `export ESTAT_APP_ID="発行されたappId"`
3. 統計表を探す → メタ情報を確認 → 取得、の3ステップ:

```bash
cd scripts

# statsDataId を検索 (属性クロスが充実しているのは全国家計構造調査)
python fetch_estat.py search "全国家計構造調査 都道府県 消費支出"

# 分類軸 (cat01 等) とカテゴリコードを確認
python fetch_estat.py meta 0003XXXXXX

# 基本指標として取得 (例: 円→万円換算)
python fetch_estat.py fetch 0003XXXXXX --metric percap \
    --filter cat01=001 --scale 0.0001 --out ../data/pref_data.json

# 属性 (例: 世帯主の年齢階級 = cat02) をまるごと取得して統合
python fetch_estat.py fetch 0003YYYYYY --attr-dim cat02 --attr-name age \
    --scale 0.0001 --out ../data/pref_data.json --merge
```

出力は年別 (`meta.years` / 各県の `years`) に整理され、複数年ぶんのデータが
入っていれば地図の年スライダーが自動で有効になります。属性を追加すると
「属性で見る」セレクタと差分マップにも自動で反映されます。

主な統計ソースの使い分け:

| 目的 | 統計 | 備考 |
|---|---|---|
| 1人当たり消費 × 属性 | 全国家計構造調査 | 5年周期。都道府県 × 年齢/年収/世帯類型のクロスが充実 |
| 毎月の消費動向 | 家計調査 | 地域区分は都道府県庁所在市別な点に注意 |
| 消費の総量 | 県民経済計算 (民間最終消費支出) | 内閣府。e-Stat 経由で取得可 |

### 世界 (World Bank API)

API キー不要です。

```bash
cd scripts
python fetch_worldbank.py --years 2013 2018 2023 --out ../data/world_data.json
```

家計最終消費支出の1人当たり (USD)・総額・人口を取得し、ISO numeric コードで
world-atlas の国境界と自動結合されます。

## GitHub Pages での公開

1. GitHub で新規リポジトリを作成し、このフォルダ一式を push

```bash
git init
git add .
git commit -m "consumption map"
git branch -M main
git remote add origin https://github.com/<ユーザ名>/<リポジトリ名>.git
git push -u origin main
```

2. リポジトリの **Settings → Pages** で
   Source: `Deploy from a branch`、Branch: `main` / `(root)` を選択して保存
3. 数分後に `https://<ユーザ名>.github.io/<リポジトリ名>/` で公開されます

相対パスのみで構成しているため、サブパス配下でもそのまま動きます。
データ更新は `data/*.json` を差し替えて push するだけです。

## 出典・ライセンス表記 (公開時の推奨)

- 統計データ: 政府統計の総合窓口 (e-Stat) — 利用規約に従い出典を明記
- 世界データ: World Bank Open Data (CC BY 4.0)
- 日本地図: 国土交通省 国土数値情報 (行政区域データ) を加工
- 世界地図: Natural Earth (パブリックドメイン) / world-atlas
