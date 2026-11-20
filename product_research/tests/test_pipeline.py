import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.core import (DECISION_EXCLUDE, DECISION_TEST, GO, NG, REVIEW, UNKNOWN, Ad,
                           RunLog, load_config, parse_date, parse_int)
from research.evaluate import evaluate_compliance
from research.pipeline import BASE, run
from research.screening import apply_filters, dedupe

SAMPLE = BASE / "sample_data"
CFG = load_config(BASE / "config.json")


def ad(i, **kw):
    base = dict(record_id=f"t:{i}", source="t", source_row=i, checked_at="2026-11-20",
                product_name="Item", ad_url=f"https://ads.example.com/{i}", start_date="2026-10-01",
                likes=1000, landing_url=f"https://s{i}.example.com/p", media_type="video",
                language="en", platform="shopify")
    base.update(kw)
    return Ad(**base)


class ParseTest(unittest.TestCase):
    def test_parse_int(self):
        self.assertEqual(parse_int("1,234"), 1234)
        self.assertEqual(parse_int("1.2k"), 1200)
        self.assertEqual(parse_int(""), UNKNOWN)
        with self.assertRaises(ValueError):
            parse_int("many")

    def test_parse_date_rejects_ambiguous(self):
        self.assertEqual(parse_date("2026/09/01"), "2026-09-01")
        self.assertEqual(parse_date("2026-09-01T10:00:00Z"), "2026-09-01")
        with self.assertRaises(ValueError):
            parse_date("05/09/2026")


class FilterTest(unittest.TestCase):
    def test_initial_conditions(self):
        ads = [ad(1), ad(2, media_type="image"), ad(3, language="fr"), ad(4, platform="amazon"),
               ad(5, likes=599), ad(6, likes=600), ad(7, platform=UNKNOWN), ad(8, platform="woocommerce")]
        passed, excluded = apply_filters(ads, CFG)
        self.assertEqual([a.source_row for a in passed], [1, 6, 8])
        self.assertEqual(len(excluded), 5)

    def test_threshold_configurable(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["filters"]["min_likes"] = 2000
        passed, _ = apply_filters([ad(1, likes=1500), ad(2, likes=2500)], cfg)
        self.assertEqual([a.source_row for a in passed], [2])


class DedupeTest(unittest.TestCase):
    def test_merge_by_url_and_name(self):
        ads = [ad(1, product_name="Posture Corrector Pro", landing_url="https://a.example.com/p/x"),
               ad(2, product_name="Back Brace", landing_url="https://www.a.example.com/p/x/?utm=1"),
               ad(3, product_name="Sunset Lamp", likes=700),
               ad(4, product_name="Sunset Projection Lamp", likes=5000),
               ad(5, product_name="Cloud Slides")]
        products = dedupe(ads, CFG)
        self.assertEqual(len(products), 3)
        lamp = next(p for p in products if "Lamp" in p.rep.product_name)
        self.assertEqual(lamp.rep.likes, 5000)
        self.assertEqual(len(lamp.ads), 2)


class ComplianceTest(unittest.TestCase):
    def _product(self, name):
        return dedupe([ad(1, product_name=name)], CFG)[0]

    def test_never_auto_go(self):
        p = self._product("Pet Hair Remover Roller")
        evaluate_compliance(p, [], CFG, RunLog())
        self.assertEqual(p.compliance["status"], REVIEW)

    def test_ng_keyword(self):
        p = self._product("Tactical Pocket Knife")
        evaluate_compliance(p, [], CFG, RunLog())
        self.assertEqual(p.compliance["status"], NG)

    def test_go_requires_reviewer_and_date(self):
        log = RunLog()
        p = self._product("Pet Hair Remover Roller")
        review = {"product_name": "Pet Hair Remover Roller", "status": "GO", "reviewer": "",
                  "checked_at": "", "_row": 2, "_source": "r.csv"}
        evaluate_compliance(p, [review], CFG, log)
        self.assertEqual(p.compliance["status"], REVIEW)
        review.update(reviewer="B", checked_at="2026-11-19")
        evaluate_compliance(p, [review], CFG, log)
        self.assertEqual(p.compliance["status"], GO)


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.res = run([SAMPLE / "ads_sample.csv", SAMPLE / "ads_sample.json"],
                      BASE / "config.json", SAMPLE / "aliexpress_sample.csv",
                      SAMPLE / "compliance_review.csv", Path(cls.tmp.name))
        cls.out = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rows(self, name):
        with open(self.out / name, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def test_outputs_exist(self):
        for f in ("top10.csv", "report.html", "all_candidates.csv", "excluded_by_filter.csv",
                  "missing_values.csv", "errors.csv", "run_meta.json"):
            self.assertTrue((self.out / f).exists(), f)

    def test_top10(self):
        top = self.rows("top10.csv")
        self.assertEqual(len(top), 10)
        self.assertNotIn(DECISION_EXCLUDE, {r["decision"] for r in top})
        # テスト候補が要確認より上位
        decisions = [r["decision"] for r in top]
        self.assertEqual(decisions, sorted(decisions, key=lambda d: d != DECISION_TEST))
        names = {r["product_name"] for r in top}
        self.assertNotIn("Tactical Pocket Knife", names)

    def test_test_candidates_have_all_three_pass(self):
        for r in self.rows("all_candidates.csv"):
            if r["decision"] == DECISION_TEST:
                self.assertEqual((r["gate_reaction"], r["gate_sourcing"], r["gate_compliance"]),
                                 ("PASS", "PASS", "PASS"))
                self.assertEqual(r["compliance_status"], GO)
                self.assertNotEqual(r["compliance_reviewer"], UNKNOWN)

    def test_dedupe_counts(self):
        s = self.res["summary"]
        self.assertEqual(s["読込広告"], 26)
        self.assertEqual(s["条件通過"], 20)
        self.assertEqual(s["重複除去後"], 17)  # posture×2, roller×2, sunset lamp×2 を統合

    def test_unknown_values_and_errors_recorded(self):
        errors = self.rows("errors.csv")
        msgs = " ".join(e["message"] for e in errors)
        self.assertIn("many", msgs)
        self.assertIn("05/09/2026", msgs)
        missing = {(m["record_id"], m["field"]) for m in self.rows("missing_values.csv")}
        self.assertIn(("ads_sample.csv:16", "start_date"), missing)
        shower = next(r for r in self.rows("all_candidates.csv") if r["product_name"] == "Shower Head Filter")
        self.assertEqual(shower["start_date"], UNKNOWN)

    def test_sourcing_rules(self):
        by = {r["product_name"]: r for r in self.rows("all_candidates.csv")}
        self.assertEqual(by["Foldable Laptop Stand"]["gate_sourcing"], "FAIL")       # 販売終了
        self.assertEqual(by["Self Cleaning Water Bottle"]["gate_sourcing"], "FAIL")  # 一致度55
        self.assertEqual(by["Ice Face Roller"]["gate_sourcing"], REVIEW)             # 送料不明
        self.assertEqual(by["Under Bed Storage Bag"]["gate_sourcing"], REVIEW)       # 通貨違い
        self.assertEqual(by["Spiral Plant Pot"]["aliexpress_url"], UNKNOWN)

    def test_provenance(self):
        meta = json.loads((self.out / "run_meta.json").read_text(encoding="utf-8"))
        kinds = {s["kind"] for s in meta["sources"]}
        self.assertEqual(kinds, {"ads", "aliexpress", "compliance_review"})
        for r in self.rows("top10.csv"):
            self.assertTrue(r["source"] and r["checked_at"])

    def test_html_escapes(self):
        html = (self.out / "report.html").read_text(encoding="utf-8")
        self.assertIn("販売テスト候補 TOP10", html)
        self.assertIn('rel="noopener noreferrer"', html)


if __name__ == "__main__":
    unittest.main()
