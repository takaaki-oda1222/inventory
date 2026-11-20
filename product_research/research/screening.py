"""検索条件フィルタと商品重複除去。"""
from __future__ import annotations

from .core import Ad, Product, is_unknown, names_match, normalize_name, normalize_url


def apply_filters(ads: list[Ad], cfg: dict) -> tuple[list[Ad], list[dict]]:
    """初期検索条件（動画・英語・Shopify/WooCommerce・いいね600以上）。
    allow_unknown=false の場合、判定に必要な値が不明な広告は除外し理由を残す。"""
    f = cfg["filters"]
    allow_unknown = f.get("allow_unknown", False)
    # 手動登録（URLのみ等）は不明値で除外せず、後段で「要確認」として扱う
    manual_allow_unknown = f.get("manual_allow_unknown", True)
    checks = [
        ("media_type", lambda v: v in f["media_types"], "メディア形式"),
        ("language", lambda v: v in f["languages"], "言語"),
        ("platform", lambda v: v in f["platforms"], "プラットフォーム"),
        ("likes", lambda v: v >= f["min_likes"], f"いいね{f['min_likes']}以上"),
    ]
    passed, excluded = [], []
    for ad in ads:
        reasons = []
        for attr, ok, label in checks:
            v = getattr(ad, attr)
            if is_unknown(v):
                if not (allow_unknown or (ad.entry_type == "manual" and manual_allow_unknown)):
                    reasons.append(f"{label}: 不明")
            elif not ok(v):
                reasons.append(f"{label}: 条件外({v})")
        if reasons:
            excluded.append({"record_id": ad.record_id, "product_name": ad.product_name,
                             "ad_url": ad.ad_url, "reasons": " / ".join(reasons)})
        else:
            passed.append(ad)
    return passed, excluded


def dedupe(ads: list[Ad], cfg: dict) -> list[Product]:
    """販売ページURL一致、または商品名の類似度で同一商品をまとめる。"""
    d = cfg["dedupe"]
    stop = d.get("stopwords", [])
    groups: list[dict] = []
    for ad in ads:
        key_url = normalize_url(ad.landing_url)
        key_ad = normalize_url(ad.ad_url)
        key_name = normalize_name(ad.product_name, stop)
        hit = None
        for g in groups:
            if (key_url and key_url in g["urls"]) or (key_ad and key_ad in g["ad_urls"]):
                hit = g
                break
            if key_name and any(names_match(key_name, n, d["name_similarity"], d.get("token_containment", True))
                                for n in g["names"]):
                hit = g
                break
        if hit is None:
            hit = {"urls": set(), "ad_urls": set(), "names": set(), "ads": []}
            groups.append(hit)
        if key_url:
            hit["urls"].add(key_url)
        if key_ad:
            hit["ad_urls"].add(key_ad)
        if key_name:
            hit["names"].add(key_name)
        hit["ads"].append(ad)

    products = []
    for i, g in enumerate(groups, 1):
        rep = max(g["ads"], key=lambda a: a.likes if isinstance(a.likes, int) else -1)
        products.append(Product(product_id=f"P{i:03d}", rep=rep, ads=g["ads"]))
    return products
