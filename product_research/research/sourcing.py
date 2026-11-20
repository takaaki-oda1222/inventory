"""AliExpress 仕入れ情報の照合。

AliExpress Open Platform API の仕様は本環境から公式ドキュメントで確認できなかったため、
API呼び出しは実装していない。調査結果（手動確認、または将来の公式API取得結果）を
sourcing CSV に記録し、それを商品と照合する。
"""
from __future__ import annotations

from pathlib import Path

from .core import (FAIL, PASS, REVIEW, UNKNOWN, Product, RunLog, is_unknown,
                   names_match, normalize_name, normalize_url, parse_float, parse_int,
                   similarity)
from .loader import read_rows

SOURCING_COLUMNS = ["product_name", "landing_url", "aliexpress_url", "unit_cost", "shipping_cost",
                    "currency", "match_score", "available", "checked_at", "checked_by", "note"]


def load_sourcing(path, log: RunLog) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    try:
        rows = read_rows(p)
    except Exception as e:  # noqa: BLE001 - 読込失敗はログに残して継続
        log.error("sourcing", str(p), None, str(e))
        log.source("aliexpress", str(p.resolve()), 0, status="error")
        return []
    log.source("aliexpress", str(p.resolve()), len(rows))
    out = []
    for i, r in enumerate(rows, start=2):
        rec = {c: (r.get(c) if not is_unknown(r.get(c)) else UNKNOWN) for c in SOURCING_COLUMNS}
        for c, fn in (("unit_cost", parse_float), ("shipping_cost", parse_float), ("match_score", parse_int)):
            try:
                rec[c] = fn(rec[c])
            except ValueError as e:
                log.error("sourcing", str(p), i, f"{c}: {e}")
                rec[c] = UNKNOWN
        rec["_row"] = i
        rec["_source"] = str(p)
        out.append(rec)
    return out


def _find(product: Product, rows: list[dict], cfg: dict):
    stop = cfg["dedupe"].get("stopwords", [])
    urls = {normalize_url(a.landing_url) for a in product.ads} - {""}
    names = {normalize_name(a.product_name, stop) for a in product.ads} - {""}
    best, best_sim = None, 0.0
    for r in rows:
        if urls and normalize_url(r["landing_url"]) in urls:
            return r
        n = normalize_name(r["product_name"], stop)
        sim = max((1.0 if names_match(n, x, 1.0) else similarity(n, x) for x in names), default=0.0)
        if sim > best_sim:
            best, best_sim = r, sim
    return best if best_sim >= cfg["sourcing"]["name_similarity"] else None


def attach_sourcing(products: list[Product], rows: list[dict], cfg: dict, log: RunLog):
    cur = cfg["pricing"]["currency"]
    min_match = cfg["sourcing"]["min_match_score"]
    for p in products:
        r = _find(p, rows, cfg)
        if r is None:
            p.sourcing = {"status": REVIEW, "reason": "AliExpress未調査", "aliexpress_url": UNKNOWN,
                          "unit_cost": UNKNOWN, "shipping_cost": UNKNOWN, "total_cost": UNKNOWN,
                          "match_score": UNKNOWN, "checked_at": UNKNOWN, "source": UNKNOWN}
            log.miss(p.product_id, "aliexpress", "sourcing", None)
            continue
        info = {k: r[k] for k in ("aliexpress_url", "unit_cost", "shipping_cost", "match_score",
                                  "currency", "checked_at", "checked_by", "note")}
        info["source"] = f"{r['_source']}:{r['_row']}"
        costs_known = not is_unknown(info["unit_cost"]) and not is_unknown(info["shipping_cost"])
        info["total_cost"] = info["unit_cost"] + info["shipping_cost"] if costs_known else UNKNOWN
        avail = str(r["available"]).strip().lower()

        if avail in ("no", "false", "0", "不可", "なし"):
            status, reason = FAIL, "仕入れ不可（在庫/販売終了等）"
        elif not is_unknown(info["match_score"]) and info["match_score"] < min_match:
            status, reason = FAIL, f"商品一致度不足({info['match_score']}<{min_match})"
        elif is_unknown(info["match_score"]) or is_unknown(info["aliexpress_url"]):
            status, reason = REVIEW, "一致度またはURLが不明"
        elif not costs_known:
            status, reason = REVIEW, "仕入れ価格または送料が不明"
        elif not is_unknown(info["currency"]) and str(info["currency"]).upper() != cur.upper():
            # 為替レートは推測で換算しない
            status, reason = REVIEW, f"通貨が{cur}と異なる({info['currency']})"
            info["total_cost"] = UNKNOWN
        elif avail in ("yes", "true", "1", "可", "あり"):
            status, reason = PASS, "仕入れ可"
        else:
            status, reason = REVIEW, "在庫可否が未記録"
        for k in ("unit_cost", "shipping_cost", "match_score", "aliexpress_url"):
            if is_unknown(info[k]):
                log.miss(p.product_id, f"aliexpress.{k}", info["source"], r["_row"])
        info.update(status=status, reason=reason)
        p.sourcing = info
