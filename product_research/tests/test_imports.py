"""実データ取り込み（imports/）のテスト。一時ディレクトリに実データ相当のファイルを置いて検証する。"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research import run_imports as ri
from research.core import UNKNOWN

EXPORT_CSV = """Ad Link,Title,First Seen,Reactions,Comments,Shares,Website,Format,Lang,Shop Platform,Price
https://ads.example.com/real/1,Galaxy Star Projector,2026-10-01,3400,120,210,https://stars.example.com/p/projector,Video,English,Shopify,$34.99
https://ads.example.com/real/2,Dog Paw Cleaner Cup,2026-09-15,1.5k,60,90,https://pawclean.example.com/p/cup,video,en,WooCommerce,19.99
https://ads.example.com/real/3,Kitchen Gadget Low,2026-10-10,200,5,1,https://low.example.com/p/x,video,en,shopify,9.99
"""
MANUAL_CSV = """ad_url,product_name,landing_url,likes,start_date,media_type,language,platform,sale_price,page_name,checked_at
https://ads.example.com/manual/10,,,,,,,,,,
https://ads.example.com/real/1,,,,,,,,,,
https://ads.example.com/manual/11,Neck Fan,,450,,,,,,,
,Row Without URL,,,,,,,,,
,,,,,,,,,,
,,https://shop.example.com/products/pen?fbclid=abc&utm_source=fb,,,,,,,,
https://ads.example.com/manual/12,Mini Waffle Maker,https://waffle.example.com/p/mini,2000,2026-10-20,video,en,shopify,29.99,WaffleCo,2026-11-20T10:00:00+09:00
"""
SOURCING_CSV = """product_name,ad_url,landing_url,aliexpress_url,unit_cost,shipping_cost,currency,match_score,available,checked_at,checked_by,note
,https://ads.example.com/manual/10,,https://www.aliexpress.example/item/10.html,3.00,2.00,USD,88,yes,2026-11-20,担当A,URLのみ登録の商品
Galaxy Star Projector,,,https://www.aliexpress.example/item/1.html,6.00,3.00,USD,90,yes,2026-11-20,担当A,
"""
REVIEW_CSV = """product_name,ad_url,landing_url,status,reviewer,checked_at,note
Galaxy Star Projector,,,GO,担当B,2026-11-20,
"""


class RealImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.imports = root / "imports"
        self.out_root = root / "output" / "real"
        ri.init(self.imports)
        # 実エクスポートは列名がサンプルと異なる想定 → config の列名対応を一時的に拡張
        cfg = json.loads((ri.BASE / "config.json").read_text(encoding="utf-8"))
        al = cfg["column_aliases"]
        for k, v in {"ad_url": "Ad Link", "product_name": "Title", "start_date": "First Seen",
                     "likes": "Reactions", "landing_url": "Website", "media_type": "Format",
                     "language": "Lang", "platform": "Shop Platform"}.items():
            al[k].append(v)
        self.config = root / "config.json"
        self.config.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        (self.imports / rel).write_text(text, encoding="utf-8")

    def rows(self, out, name):
        with open(out / name, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def test_init_creates_folders_and_templates(self):
        for d in ("ads", "manual", "aliexpress", "compliance"):
            self.assertTrue((self.imports / d).is_dir())
        header = (self.imports / "manual" / "manual_ads.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(header[0].split(",")[0], "ad_url")
        # 既存ファイルは上書きしない
        self.write("manual/manual_ads.csv", MANUAL_CSV)
        ri.init(self.imports)
        self.assertIn("Neck Fan", (self.imports / "manual" / "manual_ads.csv").read_text(encoding="utf-8"))

    def test_no_real_data_returns_none(self):
        # テンプレート（ヘッダーのみ）しかない状態では実行しない
        self.assertIsNone(ri.run_real(self.imports, self.out_root, self.config))
        self.assertFalse(self.out_root.exists())

    def test_real_run_generates_reports(self):
        self.write("ads/export_20261120.csv", EXPORT_CSV)
        self.write("manual/manual_ads.csv", MANUAL_CSV)
        self.write("aliexpress/aliexpress.csv", SOURCING_CSV)
        self.write("compliance/compliance_review.csv", REVIEW_CSV)
        self.write("ads/_draft.csv", "should,be,ignored\n1,2,3\n")
        res = ri.run_real(self.imports, self.out_root, self.config)
        out = res["out_dir"]

        # 5. 実データから top10.csv / report.html / errors.csv が生成される
        self.assertEqual(out.parent, self.out_root)
        for f in ("top10.csv", "report.html", "errors.csv", "missing_values.csv", "run_meta.json"):
            self.assertTrue((out / f).exists(), f)

        # 4. サンプルを読んでいない
        meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
        locations = " ".join(s["location"] for s in meta["sources"])
        self.assertNotIn("sample_data", locations)
        self.assertNotIn("_draft.csv", locations)

        top = {r["ad_url"]: r for r in self.rows(out, "top10.csv")}
        # 3. URLだけの手動登録が「不明」として残り、要確認になる
        url_only = top["https://ads.example.com/manual/10"]
        self.assertEqual(url_only["product_name"], UNKNOWN)
        self.assertEqual(url_only["likes"], UNKNOWN)
        self.assertEqual(url_only["decision"], "要確認")
        self.assertEqual(url_only["entry_type"], "manual")
        self.assertIn("手動登録: 未取得項目あり", url_only["reasons"])
        self.assertEqual(url_only["aliexpress_url"], "https://www.aliexpress.example/item/10.html")

        # エクスポートと同じ広告URLの手動登録は1商品に統合
        merged = [r for r in self.rows(out, "all_candidates.csv") if "real/1" in r["ad_url"]]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["entry_type"], "export/manual")
        self.assertEqual(merged[0]["decision"], "テスト候補")

        # いいねが条件外と分かっている行は手動でも除外
        excluded = {r["ad_url"]: r["reasons"] for r in self.rows(out, "excluded_by_filter.csv")}
        self.assertIn("https://ads.example.com/manual/11", excluded)
        self.assertIn("https://ads.example.com/real/3", excluded)

        errors = " ".join(r["message"] for r in self.rows(out, "errors.csv"))
        self.assertIn("ad_url と landing_url が両方空", errors)
        self.assertEqual(res["summary"]["手動登録"], 5)  # 7行中、空行1件とURLなし1件を除く
        lp_only = [r for r in self.rows(out, "all_candidates.csv") if "shop.example.com" in r["landing_url"]]
        self.assertEqual(len(lp_only), 1)
        self.assertEqual(lp_only[0]["ad_url"], UNKNOWN)
        self.assertEqual(lp_only[0]["decision"], "要確認")
