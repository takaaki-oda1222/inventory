"""CSV / JSON から広告データを読み込む。

外部ツールのエクスポート列名は公式仕様を確認できていないため推測で固定せず、
config.json の column_aliases で列名を対応付ける方式にしている。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .core import (UNKNOWN, Ad, RunLog, is_unknown, normalize_label, now_iso,
                   parse_date, parse_float, parse_int)

REQUIRED_FIELDS = ("product_name", "ad_url", "start_date", "likes", "landing_url")
INT_FIELDS = ("likes", "comments", "shares")


def _header_map(headers, aliases: dict) -> dict[str, str]:
    """元の列名 → 内部フィールド名。"""
    lookup = {}
    for fname, names in aliases.items():
        if fname.startswith("_"):
            continue
        for n in names:
            lookup[n.strip().lower()] = fname
    return {h: lookup[h.strip().lower()] for h in headers if h and h.strip().lower() in lookup}


def read_rows(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("ads", "data", "items", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError("JSONはオブジェクトの配列、または ads/data/items/results に配列を持つ形式にしてください")
        return data
    raise ValueError(f"未対応のファイル形式: {suffix}（.csv / .json のみ）")


def load_ads(paths, config: dict, log: RunLog, manual: bool = False) -> list[Ad]:
    """manual=True は手動登録テンプレート。ad_url 以外は空欄で良く、空欄は「不明」として扱う。"""
    aliases = config["column_aliases"]
    norm = config["normalize"]
    ads: list[Ad] = []
    for p in map(Path, paths):
        try:
            rows = read_rows(p)
        except (OSError, ValueError, json.JSONDecodeError, csv.Error) as e:
            log.error("load", str(p), None, str(e))
            log.source("ads", str(p.resolve()), 0, status="error")
            continue
        headers = set().union(*(r.keys() for r in rows)) if rows else set()
        hmap = _header_map(headers, aliases)
        unmapped = sorted(h for h in headers if h not in hmap)
        if unmapped:
            log.error("load", str(p), None, f"未対応の列（無視）: {', '.join(unmapped)}")
        loaded_at = now_iso()
        n_before = len(ads)

        for i, raw in enumerate(rows, start=2 if p.suffix.lower() == ".csv" else 1):
            if all(is_unknown(v) for v in raw.values()):
                continue  # 空行は無視
            rec = {hmap[k]: v for k, v in raw.items() if k in hmap}
            rid = f"{p.name}:{i}"
            if manual and is_unknown(rec.get("ad_url")) and is_unknown(rec.get("landing_url")):
                log.error("load", str(p), i, "手動登録: ad_url と landing_url が両方空のため行をスキップ")
                continue
            ad = Ad(record_id=rid, source=str(p), source_row=i,
                    checked_at=str(rec.get("checked_at") or loaded_at),
                    entry_type="manual" if manual else "export")
            for fname, value in rec.items():
                if fname == "checked_at":
                    continue
                try:
                    if fname in INT_FIELDS:
                        value = parse_int(value)
                    elif fname == "sale_price":
                        value = parse_float(value)
                    elif fname == "start_date":
                        value = parse_date(value)
                    elif fname == "media_type":
                        value = normalize_label(value, norm["media_types"])
                    elif fname == "language":
                        value = normalize_label(value, norm["languages"])
                    elif fname == "platform":
                        value = normalize_label(value, norm["platforms"])
                    else:
                        value = UNKNOWN if is_unknown(value) else str(value).strip()
                except ValueError as e:
                    log.error("parse", str(p), i, f"{fname}: {e}")
                    value = UNKNOWN
                setattr(ad, fname, value)
            for fname in REQUIRED_FIELDS:
                if is_unknown(getattr(ad, fname)):
                    log.miss(rid, fname, str(p), i)
            ads.append(ad)
        # 件数は実際に読み込んだ行（空行・スキップ行を除く）
        log.source("manual_ads" if manual else "ads", str(p.resolve()), len(ads) - n_before)
    return ads
