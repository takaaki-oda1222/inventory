"""販売価格候補・想定粗利・広告訴求力・法規安全・3条件ゲート・加点スコア。"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from .core import (DECISION_EXCLUDE, DECISION_REVIEW, DECISION_TEST, FAIL, GO, NG, PASS,
                   REVIEW, UNKNOWN, Product, RunLog, is_unknown, names_match,
                   normalize_name, normalize_url)


# ---------------------------------------------------------------- 価格・粗利
def _round_price(x: float, ending: float) -> float:
    return math.floor(x) + ending if ending else round(x, 2)


def evaluate_pricing(p: Product, cfg: dict):
    pc = cfg["pricing"]
    cost = p.sourcing.get("total_cost", UNKNOWN)
    # 競合販売価格: 代表広告（いいね最大）の販売ページ価格を優先
    competitor = next((a.sale_price for a in [p.rep, *p.ads] if not is_unknown(a.sale_price)), UNKNOWN)
    candidates = []
    if not is_unknown(cost):
        for m in pc["markups"]:
            candidates.append({"label": f"原価x{m}", "price": _round_price(cost * m, pc["price_ending"])})
    if not is_unknown(competitor):
        candidates.append({"label": "競合販売価格", "price": float(competitor)})

    for c in candidates:
        if is_unknown(cost):
            c["gross_profit"] = c["margin_rate"] = UNKNOWN
            continue
        fee = c["price"] * pc["payment_fee_rate"]
        gp = c["price"] - cost - fee - pc["est_cpa"]
        c["gross_profit"] = round(gp, 2)
        c["margin_rate"] = round(gp / c["price"], 3) if c["price"] else UNKNOWN

    # 推奨価格: 競合価格があればそれ以下で最も粗利の高い候補、無ければ中間の倍率
    rec = None
    priced = [c for c in candidates if not is_unknown(c.get("margin_rate"))]
    if priced:
        limit = competitor if not is_unknown(competitor) else math.inf
        within = [c for c in priced if c["price"] <= limit] or priced
        rec = max(within, key=lambda c: c["gross_profit"])
    p.pricing = {"cost": cost, "competitor_price": competitor, "candidates": candidates,
                 "recommended": rec, "currency": pc["currency"]}


# ---------------------------------------------------------------- 訴求力
def _log_score(v, ref) -> float:
    if is_unknown(v) or v <= 0:
        return 0.0
    return min(1.0, math.log10(v + 1) / math.log10(ref + 1))


def evaluate_appeal(p: Product, cfg: dict):
    sc = cfg["scoring"]
    likes = p.max_likes
    comments = max((a.comments for a in p.ads if isinstance(a.comments, int)), default=UNKNOWN)
    shares = max((a.shares for a in p.ads if isinstance(a.shares, int)), default=UNKNOWN)
    # いいね:コメント:シェア = 0.6:0.2:0.2（不明な指標は残りで按分）
    parts = [(likes, 0.6, sc["appeal_likes_ref"]), (comments, 0.2, sc["appeal_likes_ref"] / 10),
             (shares, 0.2, sc["appeal_likes_ref"] / 10)]
    known = [(v, w, r) for v, w, r in parts if not is_unknown(v)]
    total_w = sum(w for _, w, _ in known)
    ratio = sum(_log_score(v, r) * w for v, w, r in known) / total_w if total_w else 0.0
    p.appeal = {"likes": likes, "comments": comments, "shares": shares,
                "ratio": round(ratio, 3), "ad_count": len(p.ads), "days_running": p.days_running}


# ---------------------------------------------------------------- 法規・安全
def load_reviews(path, log: RunLog) -> list[dict]:
    """人が確認した法規・安全判定（product_name, landing_url, status, reviewer, checked_at, note）。"""
    if not path:
        return []
    p = Path(path)
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        log.error("compliance", str(p), None, str(e))
        log.source("compliance_review", str(p.resolve()), 0, status="error")
        return []
    log.source("compliance_review", str(p.resolve()), len(rows))
    for i, r in enumerate(rows, start=2):
        r["_row"] = i
        r["_source"] = str(p)
    return rows


def _match_review(p: Product, reviews: list[dict], cfg: dict):
    stop = cfg["dedupe"].get("stopwords", [])
    urls = {normalize_url(a.landing_url) for a in p.ads} - {""}
    ad_urls = {normalize_url(a.ad_url) for a in p.ads} - {""}
    names = {normalize_name(a.product_name, stop) for a in p.ads} - {""}
    for r in reviews:
        if urls and normalize_url(r.get("landing_url") or "") in urls:
            return r
        if ad_urls and normalize_url(r.get("ad_url") or "") in ad_urls:
            return r
        n = normalize_name(r.get("product_name") or "", stop)
        if any(names_match(n, x, cfg["dedupe"]["name_similarity"]) for x in names):
            return r
    return None


def _hits(text: str, words: list[str]) -> list[str]:
    padded = f" {text} "
    return [w for w in words if f" {w} " in padded or (" " in w and w in text)]


def evaluate_compliance(p: Product, reviews: list[dict], cfg: dict, log: RunLog):
    """GO は人の確認記録がある場合のみ。自動判定は NG候補 / 要確認 の2値に限定する。"""
    cc = cfg["compliance"]
    text = " ".join(normalize_name(f"{a.product_name} {a.ad_text}") for a in p.ads)
    ng = _hits(text, cc["ng_keywords"])
    rv = _hits(text, cc["review_keywords"])
    auto = NG if ng else REVIEW
    auto_reason = (f"NGキーワード: {', '.join(ng)}" if ng else
                   f"要確認キーワード: {', '.join(rv)}" if rv else "未確認（人による確認記録なし）")

    r = _match_review(p, reviews, cfg)
    if r is None:
        p.compliance = {"status": auto, "auto_status": auto, "reason": auto_reason,
                        "reviewer": UNKNOWN, "checked_at": UNKNOWN, "source": "自動判定"}
        return
    raw = str(r.get("status", "")).strip().upper()
    status = {"GO": GO, "NG": NG, "NG候補": NG, "要確認": REVIEW, "REVIEW": REVIEW}.get(raw)
    reviewer, checked = r.get("reviewer") or UNKNOWN, r.get("checked_at") or UNKNOWN
    if status is None:
        log.error("compliance", r["_source"], r["_row"], f"不正なstatus: {r.get('status')!r}")
        status = auto
    if status == GO and (is_unknown(reviewer) or is_unknown(checked)):
        # 確認者・確認日時のない GO は承認として扱わない
        log.error("compliance", r["_source"], r["_row"], "GOだが確認者/確認日時が無いため要確認に格下げ")
        status = REVIEW
    reason = r.get("note") or ""
    if status == GO and ng:
        reason = f"手動GO（自動ではNG候補: {', '.join(ng)}） {reason}".strip()
    p.compliance = {"status": status, "auto_status": auto, "reason": reason or auto_reason,
                    "reviewer": reviewer, "checked_at": checked,
                    "source": f"{r['_source']}:{r['_row']}"}


# ---------------------------------------------------------------- ゲートと加点
def evaluate_gates(p: Product, cfg: dict):
    likes = p.max_likes
    thr = cfg["gates"]["reaction_min_likes"]
    if is_unknown(likes):
        reaction = REVIEW
    else:
        reaction = PASS if likes >= thr else FAIL
    comp = {GO: PASS, REVIEW: REVIEW, NG: FAIL}[p.compliance["status"]]
    p.gates = {"reaction": reaction, "sourcing": p.sourcing["status"], "compliance": comp}


def score(p: Product, cfg: dict):
    sc = cfg["scoring"]
    w = sc["weights"]
    rec = p.pricing.get("recommended")
    margin = rec["margin_rate"] if rec and not is_unknown(rec["margin_rate"]) else UNKNOWN
    min_m = cfg["pricing"]["min_margin_rate"]
    # 粗利率: min_margin_rate で満点の半分、2倍で満点
    margin_r = 0.0 if is_unknown(margin) else max(0.0, min(1.0, margin / (2 * min_m)))
    match = p.sourcing.get("match_score", UNKNOWN)
    match_r = 0.0 if is_unknown(match) else max(0.0, min(1.0, match / 100))
    days = p.days_running
    long_r = 0.0 if is_unknown(days) else max(0.0, min(1.0, days / sc["longevity_days_ref"]))
    cnt_r = min(1.0, len(p.ads) / sc["ad_count_ref"])
    parts = {"appeal": p.appeal["ratio"] * w["appeal"], "margin": margin_r * w["margin"],
             "match": match_r * w["match"], "longevity": long_r * w["longevity"],
             "ad_count": cnt_r * w["ad_count"]}
    p.score = {k: round(v, 1) for k, v in parts.items()}
    p.score["total"] = round(sum(parts.values()), 1)
    p.score["margin_rate"] = margin


def decide(p: Product, cfg: dict):
    labels = {"reaction": "Dropispy反応", "sourcing": "仕入れ可否", "compliance": "法規安全"}
    reasons = []
    if all(a.entry_type == "manual" for a in p.ads):
        unknown = [k for k in ("product_name", "likes", "start_date", "landing_url", "media_type",
                               "language", "platform") if is_unknown(getattr(p.rep, k))]
        if unknown:
            reasons.append(f"手動登録: 未取得項目あり({', '.join(unknown)})")
    for k, v in p.gates.items():
        if v != PASS:
            reasons.append(f"{labels[k]}: {v}")
    if FAIL in p.gates.values():
        p.decision = DECISION_EXCLUDE
    elif all(v == PASS for v in p.gates.values()):
        p.decision = DECISION_TEST
    else:
        p.decision = DECISION_REVIEW
    m = p.score.get("margin_rate")
    if not is_unknown(m) and m < cfg["pricing"]["min_margin_rate"]:
        reasons.append(f"想定粗利率が基準未満({m:.0%})")
        if p.decision == DECISION_TEST:
            p.decision = DECISION_REVIEW
    if p.compliance["status"] != GO:
        reasons.append(f"法規: {p.compliance['reason']}")
    if p.sourcing.get("status") != PASS:
        reasons.append(f"仕入れ: {p.sourcing.get('reason')}")
    p.decision_reasons = list(dict.fromkeys(reasons))


def rank(products: list[Product], top_n: int) -> list[Product]:
    order = {DECISION_TEST: 0, DECISION_REVIEW: 1}
    eligible = [p for p in products if p.decision != DECISION_EXCLUDE]
    eligible.sort(key=lambda p: (order[p.decision], -p.score["total"], p.product_id))
    return eligible[:top_n]
