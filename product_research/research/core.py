"""共通定義: 定数・データモデル・実行ログ・正規化ユーティリティ。"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

UNKNOWN = "不明"

# 判定ラベル
PASS, REVIEW, FAIL = "PASS", "要確認", "FAIL"
GO, NG = "GO", "NG候補"
DECISION_TEST, DECISION_REVIEW, DECISION_EXCLUDE = "テスト候補", "要確認", "除外"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_unknown(v) -> bool:
    return v is None or v == UNKNOWN or (isinstance(v, str) and v.strip() == "")


def show(v):
    """出力用: 未取得値は「不明」に統一。"""
    return UNKNOWN if is_unknown(v) else v


# ---------------------------------------------------------------- データモデル
@dataclass
class Ad:
    record_id: str
    source: str
    source_row: int
    checked_at: str
    product_name: str = UNKNOWN
    ad_url: str = UNKNOWN
    start_date: str = UNKNOWN  # ISO yyyy-mm-dd
    likes: int | str = UNKNOWN
    comments: int | str = UNKNOWN
    shares: int | str = UNKNOWN
    landing_url: str = UNKNOWN
    media_type: str = UNKNOWN
    language: str = UNKNOWN
    platform: str = UNKNOWN
    sale_price: float | str = UNKNOWN
    ad_text: str = UNKNOWN
    page_name: str = UNKNOWN
    entry_type: str = "export"  # export=ツールのエクスポート / manual=手動登録（URLのみ可）


@dataclass
class Product:
    """重複除去後の商品単位。代表広告 = いいね最大の広告。"""
    product_id: str
    rep: Ad
    ads: list[Ad] = field(default_factory=list)
    # 以降、評価ステップで埋める
    sourcing: dict = field(default_factory=dict)
    pricing: dict = field(default_factory=dict)
    appeal: dict = field(default_factory=dict)
    compliance: dict = field(default_factory=dict)
    gates: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)
    decision: str = DECISION_REVIEW
    decision_reasons: list[str] = field(default_factory=list)

    @property
    def max_likes(self):
        vals = [a.likes for a in self.ads if isinstance(a.likes, int)]
        return max(vals) if vals else UNKNOWN

    @property
    def earliest_start(self):
        vals = [a.start_date for a in self.ads if not is_unknown(a.start_date)]
        return min(vals) if vals else UNKNOWN

    @property
    def days_running(self):
        s = self.earliest_start
        if is_unknown(s):
            return UNKNOWN
        return (date.today() - date.fromisoformat(s)).days


# ---------------------------------------------------------------- 実行ログ
class RunLog:
    """取得元・確認日時・欠損値・エラーを記録する。"""

    def __init__(self):
        self.started_at = now_iso()
        self.sources: list[dict] = []
        self.errors: list[dict] = []
        self.missing: list[dict] = []

    def source(self, kind: str, location: str, rows: int, status: str = "ok"):
        self.sources.append({"kind": kind, "location": location, "rows": rows,
                             "checked_at": now_iso(), "status": status})

    def error(self, stage: str, location: str, row, message: str):
        self.errors.append({"stage": stage, "location": location, "row": row,
                            "message": message, "logged_at": now_iso()})

    def miss(self, record_id: str, field_name: str, location: str, row):
        self.missing.append({"record_id": record_id, "field": field_name,
                             "location": location, "row": row})


# ---------------------------------------------------------------- 正規化
_K_SUFFIX = {"k": 1_000, "m": 1_000_000}


def parse_int(v):
    """'1,234' / '1.2k' / '3M' / 1500 → int。解釈不能なら ValueError。空なら UNKNOWN。"""
    if is_unknown(v):
        return UNKNOWN
    if isinstance(v, bool):
        raise ValueError(f"数値ではありません: {v!r}")
    if isinstance(v, (int, float)):
        return int(v)
    s = unicodedata.normalize("NFKC", str(v)).strip().lower().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", s)
    if not m:
        raise ValueError(f"数値として解釈できません: {v!r}")
    return int(round(float(m.group(1)) * _K_SUFFIX.get(m.group(2), 1)))


def parse_float(v):
    if is_unknown(v):
        return UNKNOWN
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = unicodedata.normalize("NFKC", str(v)).strip().replace(",", "")
    s = re.sub(r"^[^\d\-.]+|[^\d.]+$", "", s)  # 通貨記号などを除去
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"金額として解釈できません: {v!r}") from None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")


def parse_date(v):
    """ISO / yyyy/mm/dd 等のみ受け付ける（dd/mm と mm/dd の曖昧な形式は推測しない）。"""
    if is_unknown(v):
        return UNKNOWN
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"日付として解釈できません（曖昧な形式は不可）: {v!r}")


def normalize_label(v, mapping: dict[str, list[str]]):
    """表記ゆれを正規ラベルに寄せる。辞書に無い値は小文字化してそのまま返す。"""
    if is_unknown(v):
        return UNKNOWN
    s = str(v).strip().lower()
    for canon, aliases in mapping.items():
        if s == canon or s in [a.lower() for a in aliases]:
            return canon
    return s


def normalize_name(name: str, stopwords=()) -> str:
    if is_unknown(name):
        return ""
    s = unicodedata.normalize("NFKC", name).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    words = [w for w in s.split() if w not in set(stopwords)]
    return " ".join(words)


def normalize_url(url: str) -> str:
    """スキーム・www・クエリ・末尾スラッシュを除いた比較用URL。"""
    if is_unknown(url):
        return ""
    p = urlsplit(url.strip().lower())
    host = p.netloc.removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}"


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def names_match(a: str, b: str, threshold: float, containment: bool = True) -> bool:
    """正規化済み商品名の一致判定: 文字列類似度、または短い方の単語(2語以上)が全て長い方に含まれる。"""
    if not a or not b:
        return False
    if similarity(a, b) >= threshold:
        return True
    if containment:
        sa, sb = set(a.split()), set(b.split())
        short, long_ = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
        return len(short) >= 2 and short <= long_
    return False
