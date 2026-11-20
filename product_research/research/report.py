"""CSV / HTML レポートと実行ログの出力。"""
from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from .core import UNKNOWN, Product, RunLog, is_unknown, now_iso, show

TOP_COLUMNS = [
    "rank", "decision", "product_id", "product_name", "score_total",
    "gate_reaction", "gate_sourcing", "gate_compliance",
    "likes", "comments", "shares", "ad_count", "start_date", "days_running",
    "ad_url", "landing_url", "platform", "page_name",
    "aliexpress_url", "unit_cost", "shipping_cost", "total_cost", "match_score", "sourcing_checked_at",
    "competitor_price", "recommended_price", "est_gross_profit", "est_margin_rate", "price_candidates",
    "appeal_score", "compliance_status", "compliance_auto", "compliance_reviewer", "compliance_checked_at",
    "reasons", "source", "checked_at", "entry_type",
]


def _fmt(v, nd=2):
    if is_unknown(v):
        return UNKNOWN
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return v


def product_row(rank, p: Product) -> dict:
    rep, s, pr, c = p.rep, p.sourcing, p.pricing, p.compliance
    rec = pr.get("recommended") or {}
    cands = "; ".join(f"{x['label']}={x['price']:.2f}(粗利{_fmt(x['gross_profit'])})"
                      for x in pr.get("candidates", []))
    return {
        "rank": rank, "decision": p.decision, "product_id": p.product_id,
        "product_name": show(rep.product_name), "score_total": p.score["total"],
        "gate_reaction": p.gates["reaction"], "gate_sourcing": p.gates["sourcing"],
        "gate_compliance": p.gates["compliance"],
        "likes": show(p.appeal["likes"]), "comments": show(p.appeal["comments"]),
        "shares": show(p.appeal["shares"]), "ad_count": len(p.ads),
        "start_date": show(p.earliest_start), "days_running": show(p.days_running),
        "ad_url": " | ".join(dict.fromkeys(show(a.ad_url) for a in p.ads)),
        "landing_url": show(rep.landing_url), "platform": show(rep.platform),
        "page_name": show(rep.page_name),
        "aliexpress_url": show(s.get("aliexpress_url")), "unit_cost": _fmt(s.get("unit_cost")),
        "shipping_cost": _fmt(s.get("shipping_cost")), "total_cost": _fmt(s.get("total_cost")),
        "match_score": show(s.get("match_score")), "sourcing_checked_at": show(s.get("checked_at")),
        "competitor_price": _fmt(pr.get("competitor_price")),
        "recommended_price": _fmt(rec.get("price", UNKNOWN)),
        "est_gross_profit": _fmt(rec.get("gross_profit", UNKNOWN)),
        "est_margin_rate": (f"{rec['margin_rate']:.1%}" if rec and not is_unknown(rec["margin_rate"]) else UNKNOWN),
        "price_candidates": cands or UNKNOWN,
        "appeal_score": p.score["appeal"],
        "compliance_status": c["status"], "compliance_auto": c["auto_status"],
        "compliance_reviewer": show(c["reviewer"]), "compliance_checked_at": show(c["checked_at"]),
        "reasons": " / ".join(p.decision_reasons) or "-",
        "source": " | ".join(dict.fromkeys(f"{a.source}:{a.source_row}" for a in p.ads)),
        "checked_at": rep.checked_at,
        "entry_type": "/".join(sorted({a.entry_type for a in p.ads})),
    }


def write_csv(path: Path, rows: list[dict], columns=None):
    columns = columns or (list(rows[0].keys()) if rows else ["(empty)"])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # Excel で文字化けしないよう BOM 付き
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


_BADGE = {"PASS": "ok", "テスト候補": "ok", "GO": "ok", "要確認": "warn",
          "FAIL": "ng", "NG候補": "ng", "除外": "ng"}


def _badge(v):
    return f'<span class="b {_BADGE.get(v, "")}">{escape(str(v))}</span>'


def _link(url):
    if is_unknown(url):
        return UNKNOWN
    u = escape(url, quote=True)
    if not url.lower().startswith(("http://", "https://")):
        return escape(url)
    return f'<a href="{u}" target="_blank" rel="noopener noreferrer">link</a>'


def write_html(path: Path, top: list[dict], summary: dict, log: RunLog, excluded_products: list[dict]):
    cards = []
    for r in top:
        ads = " ".join(_link(u.strip()) for u in r["ad_url"].split("|"))
        cards.append(f"""
<tr>
 <td class="num">{r['rank']}</td>
 <td><b>{escape(str(r['product_name']))}</b><div class="sub">{escape(r['product_id'])} · {escape(str(r['platform']))} · {escape(str(r['page_name']))}</div></td>
 <td>{_badge(r['decision'])}</td>
 <td class="num">{r['score_total']}</td>
 <td>{_badge(r['gate_reaction'])}<br>{_badge(r['gate_sourcing'])}<br>{_badge(r['gate_compliance'])}</td>
 <td class="num">{escape(str(r['likes']))}<div class="sub">広告{r['ad_count']}本 / {escape(str(r['days_running']))}日</div></td>
 <td style="white-space:nowrap">{escape(str(r['start_date']))}</td>
 <td>{ads}<br>販売: {_link(str(r['landing_url']))}</td>
 <td>{_link(str(r['aliexpress_url']))}<div class="sub">原価 {escape(str(r['unit_cost']))} + 送料 {escape(str(r['shipping_cost']))}<br>一致度 {escape(str(r['match_score']))}</div></td>
 <td class="num">{escape(str(r['recommended_price']))}<div class="sub">粗利 {escape(str(r['est_gross_profit']))} ({escape(str(r['est_margin_rate']))})<br>競合 {escape(str(r['competitor_price']))}</div></td>
 <td class="reason">{escape(str(r['reasons']))}</td>
</tr>""")
    err_rows = "".join(f"<tr><td>{escape(e['stage'])}</td><td>{escape(e['location'])}</td>"
                       f"<td>{escape(str(e['row']))}</td><td>{escape(e['message'])}</td></tr>"
                       for e in log.errors) or '<tr><td colspan="4">なし</td></tr>'
    src_rows = "".join(f"<tr><td>{escape(s['kind'])}</td><td>{escape(s['location'])}</td>"
                       f"<td>{s['rows']}</td><td>{escape(s['status'])}</td><td>{escape(s['checked_at'])}</td></tr>"
                       for s in log.sources)
    exc_rows = "".join(f"<tr><td>{escape(e['product_id'])}</td><td>{escape(str(e['product_name']))}</td>"
                       f"<td>{escape(e['reasons'])}</td></tr>" for e in excluded_products) \
        or '<tr><td colspan="3">なし</td></tr>'
    stat = "".join(f'<div class="stat"><div class="k">{escape(k)}</div><div class="v">{escape(str(v))}</div></div>'
                   for k, v in summary.items())
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>商品リサーチ TOP{len(top)}</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#e3e3e0;--ok:#1a7f37;--okb:#e6f4ea;--warn:#9a6700;--warnb:#fff4d6;--ng:#c62828;--ngb:#fde7e7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--fg:#ececec;--mut:#9a9aa0;--card:#1f1f22;--line:#333338;--okb:#163a22;--ok:#7ee2a0;--warnb:#3d3214;--warn:#f2cc60;--ngb:#4a1c1c;--ng:#ff9a9a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.meta{{color:var(--mut);margin-bottom:16px}}
.stats{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px}}
.stat .k{{color:var(--mut);font-size:12px}} .stat .v{{font-size:18px;font-weight:600}}
.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}
th{{font-size:12px;color:var(--mut);white-space:nowrap;background:var(--card);position:sticky;top:0}}
.num{{text-align:right;white-space:nowrap}} .sub{{color:var(--mut);font-size:12px}} .reason{{font-size:12px;min-width:220px}}
.b{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;margin:1px 0;white-space:nowrap}}
.ok{{background:var(--okb);color:var(--ok)}} .warn{{background:var(--warnb);color:var(--warn)}} .ng{{background:var(--ngb);color:var(--ng)}}
a{{color:inherit}} .note{{color:var(--mut);font-size:12px;margin-top:8px}}
</style></head><body><main>
<h1>販売テスト候補 TOP{len(top)}</h1>
<div class="meta">生成日時 {escape(now_iso())} ／ 主要判断基準: Dropispy反応・仕入れ可否・法規安全（3条件）＋加点スコア</div>
<div class="stats">{stat}</div>
<div class="wrap"><table>
<tr><th>#</th><th>商品</th><th>判定</th><th>加点</th><th>反応/仕入/法規</th><th>いいね</th><th>掲載開始</th><th>広告/販売ページ</th><th>AliExpress</th><th>推奨価格</th><th>要確認事項</th></tr>
{''.join(cards) or '<tr><td colspan="11">候補なし</td></tr>'}
</table></div>
<p class="note">「要確認」は自動承認していません。法規・安全の GO は確認者と確認日時が記録された手動レビューのみで付与されます。</p>
<h2>3条件で除外した商品</h2>
<div class="wrap"><table><tr><th>ID</th><th>商品</th><th>理由</th></tr>{exc_rows}</table></div>
<h2>取得元</h2>
<div class="wrap"><table><tr><th>種別</th><th>場所</th><th>件数</th><th>状態</th><th>確認日時</th></tr>{src_rows}</table></div>
<h2>エラー・警告 ({len(log.errors)})</h2>
<div class="wrap"><table><tr><th>工程</th><th>場所</th><th>行</th><th>内容</th></tr>{err_rows}</table></div>
<p class="note">欠損値 {len(log.missing)} 件の詳細は missing_values.csv を参照。</p>
</main></body></html>"""
    path.write_text(html, encoding="utf-8")


def write_outputs(out_dir: Path, products: list[Product], top: list[Product], excluded_ads: list[dict],
                  log: RunLog, config: dict, args: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    top_rows = [product_row(i, p) for i, p in enumerate(top, 1)]
    all_rows = [product_row("-", p) for p in products]
    exc_products = [{"product_id": p.product_id, "product_name": show(p.rep.product_name),
                     "reasons": " / ".join(p.decision_reasons)} for p in products if p.decision == "除外"]

    write_csv(out_dir / "top10.csv", top_rows, TOP_COLUMNS)
    write_csv(out_dir / "all_candidates.csv", all_rows, TOP_COLUMNS)
    write_csv(out_dir / "excluded_by_filter.csv", excluded_ads,
              ["record_id", "product_name", "ad_url", "reasons"])
    write_csv(out_dir / "missing_values.csv", log.missing, ["record_id", "field", "location", "row"])
    write_csv(out_dir / "errors.csv", log.errors, ["stage", "location", "row", "message", "logged_at"])

    summary = {"読込広告": sum(s["rows"] for s in log.sources if s["kind"] == "ads"),
               "手動登録": sum(s["rows"] for s in log.sources if s["kind"] == "manual_ads"),
               "条件通過": sum(len(p.ads) for p in products), "重複除去後": len(products),
               "テスト候補": sum(p.decision == "テスト候補" for p in products),
               "要確認": sum(p.decision == "要確認" for p in products),
               "除外": len(exc_products), "エラー": len(log.errors), "欠損値": len(log.missing)}
    write_html(out_dir / "report.html", top_rows, summary, log, exc_products)
    meta = {"started_at": log.started_at, "finished_at": now_iso(), "args": args,
            "sources": log.sources, "summary": summary, "config": config}
    (out_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
