# imports/ — 実データ置き場（中身は git 管理外）

| フォルダ | 置くもの | 形式 |
|---|---|---|
| `ads/` | 広告リサーチツールからエクスポートした広告データ | .csv / .json（複数可） |
| `manual/` | 手動登録。`ad_url` 列だけ埋めれば可（他は空欄＝「不明」） | .csv（`templates/manual_ads_template.csv` と同じ列） |
| `aliexpress/` | AliExpress 調査結果 | .csv（`templates/aliexpress_template.csv`） |
| `compliance/` | 法規・安全の手動レビュー | .csv（`templates/compliance_review_template.csv`） |

実行: `python3 -m research.run_imports` → `output/real/<日時>/`
初期化: `python3 -m research.run_imports --init`（テンプレートを各フォルダにコピー。既存ファイルは上書きしない）

- 手動登録の行は、未取得の項目があっても検索条件で除外しません。「要確認」として出力します。
  いいね数等が条件外と分かっている行は除外します。
- 手動登録とエクスポートで同じ広告URLがある場合は1商品にまとめます。
- `_` `.` `~` で始まるファイルは読み込みません（作業中ファイル用）。
