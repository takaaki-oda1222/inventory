# REVOLUTION式 商品リサーチ自動化（最小構成）

広告データ（CSV/JSON）を読み込み、3条件（**Dropispy反応・仕入れ可否・法規安全**）＋加点スコアで評価し、
販売テスト候補 TOP10 を CSV と HTML に出力します。Python 3.10+、外部ライブラリ不要（標準ライブラリのみ）。

## 使い方

```bash
cd product_research
python3 -m research.pipeline \
  --ads sample_data/ads_sample.csv sample_data/ads_sample.json \
  --sourcing sample_data/aliexpress_sample.csv \
  --review sample_data/compliance_review.csv
# → output/YYYYMMDD_HHMMSS/ に出力

python3 -m unittest discover -s tests -t .   # テスト
```

毎日実行する場合の例（cron、毎朝7:10）:
```
10 7 * * * cd /path/to/product_research && python3 -m research.pipeline --ads data/today.csv --sourcing data/aliexpress.csv --review data/compliance_review.csv
```

## 構成

```
product_research/
├── config.json              検索条件・列名対応・評価基準（すべて変更可能）
├── research/
│   ├── core.py              データモデル / 実行ログ / 正規化（不明値＝「不明」）
│   ├── loader.py            CSV・JSON 読込、列名マッピング、欠損・解析エラー記録
│   ├── screening.py         初期検索条件フィルタ、重複除去
│   ├── sourcing.py          AliExpress 調査結果の照合（仕入れ可否ゲート）
│   ├── evaluate.py          価格候補・想定粗利・訴求力・法規安全・3条件判定・加点・順位
│   ├── report.py            top10.csv / report.html / ログ類の出力
│   └── pipeline.py          実行エントリ（CLI）
├── sample_data/             検証用サンプル（すべて架空データ、URLは example ドメイン）
└── tests/test_pipeline.py   単体＋E2Eテスト
```

処理の流れ: 読込 → 検索条件フィルタ → 重複除去 → AliExpress照合 → 価格/粗利 → 訴求力 → 法規安全 → 3条件ゲート → 加点 → 判定 → TOP10出力

### 判定ロジック

| 主要条件 | PASS | 要確認 | FAIL |
|---|---|---|---|
| Dropispy反応 | いいね ≥ `gates.reaction_min_likes` | いいね不明 | 基準未満 |
| 仕入れ可否 | URL・原価・送料・一致度が揃い、一致度 ≥ 70、在庫あり | 未調査・送料不明・通貨違い・在庫未記録 | 在庫なし／一致度不足 |
| 法規安全 | **人による GO（確認者・確認日時あり）のみ** | 自動判定の既定値 | NGキーワード該当（NG候補）／手動NG |

- 3条件すべて PASS → **テスト候補**、FAIL が1つでもあれば **除外**、それ以外 → **要確認**
- 想定粗利率が `min_margin_rate` 未満なら テスト候補 → 要確認 に格下げ
- 加点（100点満点、重みは `scoring.weights`）: 広告訴求力40（いいね・コメント・シェア）、粗利率25、商品一致度15、掲載継続日数10、広告本数10
- 並び順: テスト候補 → 要確認、各グループ内は加点の高い順。除外は TOP10 に入りません。
- 法規安全は**自動で GO になりません**。キーワード判定は NG候補／要確認 の振り分けのみです。

### 価格・粗利
- 販売価格候補 = 仕入れ総額（原価＋送料）× `markups`（末尾 .99）＋ 競合販売ページ価格
- 想定粗利 = 価格 − 原価 − 送料 − 決済手数料(`payment_fee_rate`) − 想定CPA(`est_cpa`)
- 為替換算は推測しません（通貨が `pricing.currency` と異なる場合は「要確認」）。

### 出力（`output/<日時>/`）
| ファイル | 内容 |
|---|---|
| `top10.csv` / `report.html` | TOP10（Excel で開けるよう BOM 付き UTF-8） |
| `all_candidates.csv` | 重複除去後の全商品と判定理由 |
| `excluded_by_filter.csv` | 検索条件で除外した広告と理由 |
| `missing_values.csv` | 欠損値（レコードID・項目・取得元・行） |
| `errors.csv` | 読込・解析・照合エラー |
| `run_meta.json` | 取得元パス、確認日時、件数、使用した設定 |

## 入力ファイル

### 1. 広告データ（CSV/JSON）
列名は `config.json` の `column_aliases` で対応付けます。**実際のエクスポートファイルを入手したら、その列名を追加してください**（列名を推測で固定していません。未対応の列は errors.csv に「無視」として記録されます）。

内部項目: `product_name, ad_url, start_date, likes, comments, shares, landing_url, media_type, language, platform, sale_price, ad_text, page_name, checked_at`
- 日付は `YYYY-MM-DD` / `YYYY/MM/DD` / ISO8601 のみ。`05/09/2026` のような日/月が曖昧な形式は解釈せず「不明」＋エラー記録。
- `1.2k`、`1,234` 形式のいいね数は解釈します。

### 2. AliExpress 調査結果（`--sourcing`）
`product_name, landing_url, aliexpress_url, unit_cost, shipping_cost, currency, match_score(0-100), available(yes/no), checked_at, checked_by, note`

### 3. 法規・安全 手動レビュー（`--review`）
`product_name, landing_url, status(GO/要確認/NG), reviewer, checked_at, note`

## 必要な接続情報と公式仕様の確認状況

要件「APIやCSV機能を推測で実装しない」に従い、本環境から公式仕様を確認できなかった接続は**実装していません**。
（2026-11-20 時点、この実行環境から developers.facebook.com / dropispy.com / openservice.aliexpress.com へ接続できず、Web検索でも公式仕様を確定できませんでした。）

| 接続先 | 状態 | 自動収集の追加に必要なもの |
|---|---|---|
| Dropispy | **未実装**。公式APIの存在を確認できず。CSV等のエクスポート機能と列名も未確認 | ① 公式API仕様書URL（存在する場合）＋APIキー、または ② 実際のエクスポートファイル1件（列名マッピング用） |
| AliExpress Open Platform | **未実装**。公式ドキュメントでメソッド名・署名方式・価格/送料フィールドを確認できず | openservice.aliexpress.com の該当API仕様書、App Key / App Secret（アプリ審査済み）、必要ならアクセストークン |
| Meta 広告ライブラリ API | **未実装**。公式リファレンスを確認できず。二次情報では対象が政治・社会問題広告中心（EU配信広告の扱いは要確認）で、いいね数は返さないとされる | 公式リファレンスでの対象範囲の確認、本人確認済みアカウントのアクセストークン |

仕様を確認でき次第、`research/collectors/` に取得モジュールを追加し、出力を上記と同じ CSV 形式にして既存パイプラインへ流す設計です（評価ロジックは変更不要）。

## 現時点の制限
- 商品一致度（match_score）は人またはAPIの値を記録するのみで、画像照合はしていません。
- 法規キーワードは英語のみの簡易判定です。最終判断は必ず人が行ってください（販売国の規制・知財・プラットフォーム規約を含む）。
- 重複除去は販売ページURL一致と商品名類似度による簡易判定です（`dedupe.name_similarity`, `token_containment` で調整）。
