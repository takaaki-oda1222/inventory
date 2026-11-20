"""パイプライン本体とCLI。

例:
  python -m research.pipeline --ads sample_data/ads_sample.csv sample_data/ads_sample.json \\
      --sourcing sample_data/aliexpress_sample.csv --review sample_data/compliance_review.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .core import RunLog, load_config
from .evaluate import (decide, evaluate_appeal, evaluate_compliance, evaluate_gates,
                       evaluate_pricing, load_reviews, rank, score)
from .loader import load_ads
from .report import write_outputs
from .screening import apply_filters, dedupe
from .sourcing import attach_sourcing, load_sourcing

BASE = Path(__file__).resolve().parent.parent


def run(ads_paths, config_path=BASE / "config.json", sourcing_path=None, review_path=None,
        out_dir=None) -> dict:
    cfg = load_config(config_path)
    log = RunLog()
    out_dir = Path(out_dir or BASE / "output" / datetime.now().strftime("%Y%m%d_%H%M%S"))

    ads = load_ads(ads_paths, cfg, log)
    passed, excluded_ads = apply_filters(ads, cfg)
    products = dedupe(passed, cfg)
    attach_sourcing(products, load_sourcing(sourcing_path, log), cfg, log)
    reviews = load_reviews(review_path, log)
    for p in products:
        evaluate_pricing(p, cfg)
        evaluate_appeal(p, cfg)
        evaluate_compliance(p, reviews, cfg, log)
        evaluate_gates(p, cfg)
        score(p, cfg)
        decide(p, cfg)
    top = rank(products, cfg.get("top_n", 10))
    args = {"ads": [str(a) for a in ads_paths], "config": str(config_path),
            "sourcing": str(sourcing_path), "review": str(review_path)}
    summary = write_outputs(out_dir, products, top, excluded_ads, log, cfg, args)
    return {"out_dir": out_dir, "summary": summary, "top": top, "products": products,
            "excluded_ads": excluded_ads, "log": log}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="広告データから販売テスト候補TOP10を出力")
    ap.add_argument("--ads", nargs="+", required=True, help="広告データ CSV/JSON（複数可）")
    ap.add_argument("--config", default=str(BASE / "config.json"))
    ap.add_argument("--sourcing", help="AliExpress 調査結果 CSV")
    ap.add_argument("--review", help="法規・安全 手動レビュー CSV")
    ap.add_argument("--out", help="出力先ディレクトリ（既定: output/日時）")
    a = ap.parse_args(argv)
    res = run(a.ads, a.config, a.sourcing, a.review, a.out)
    print(f"出力: {res['out_dir']}")
    for k, v in res["summary"].items():
        print(f"  {k}: {v}")
    for i, p in enumerate(res["top"], 1):
        print(f"  {i:>2}. [{p.decision}] {p.rep.product_name}  score={p.score['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
