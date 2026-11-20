"""実データ取り込み実行コマンド。

  python3 -m research.run_imports --init   # imports/ フォルダと手動登録テンプレートを用意
  python3 -m research.run_imports          # imports/ の実データを処理 → output/real/<日時>/
  python3 -m research.run_imports --sample # sample_data/ を処理 → output/sample/<日時>/

実データ（imports/）とサンプル（sample_data/）は読み込み元も出力先も分離している。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .pipeline import BASE, run

IMPORTS = BASE / "imports"
TEMPLATES = BASE / "templates"
SAMPLE = BASE / "sample_data"
OUTPUT = BASE / "output"

FOLDERS = {
    "ads": "ツールのエクスポート広告データ（.csv / .json）",
    "manual": "手動登録（広告URLだけでも可）（.csv）",
    "aliexpress": "AliExpress 調査結果（.csv）",
    "compliance": "法規・安全 手動レビュー（.csv）",
}
TEMPLATE_COPIES = {  # templates/ → imports/ へ初期コピー（既存ファイルは上書きしない）
    "manual_ads_template.csv": "manual/manual_ads.csv",
    "aliexpress_template.csv": "aliexpress/aliexpress.csv",
    "compliance_review_template.csv": "compliance/compliance_review.csv",
}


def _files(folder: Path, exts=(".csv", ".json")) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in exts and not p.name.startswith((".", "_", "~")))


def init(imports_dir: Path = IMPORTS) -> list[Path]:
    created = []
    for name in FOLDERS:
        (imports_dir / name).mkdir(parents=True, exist_ok=True)
    for src, dst in TEMPLATE_COPIES.items():
        target = imports_dir / dst
        if not target.exists():
            shutil.copyfile(TEMPLATES / src, target)
            created.append(target)
    return created


def collect(imports_dir: Path) -> dict:
    return {
        "ads": _files(imports_dir / "ads"),
        "manual": _files(imports_dir / "manual", (".csv",)),
        "sourcing": _files(imports_dir / "aliexpress", (".csv",)),
        "review": _files(imports_dir / "compliance", (".csv",)),
    }


def _has_rows(path: Path) -> bool:
    """ヘッダー行だけのCSV（未記入テンプレート）は入力なしとみなす。"""
    if path.suffix.lower() != ".csv":
        return True
    with open(path, encoding="utf-8-sig") as f:
        return any(line.strip(" ,\r\n") for line in list(f)[1:])


def run_real(imports_dir: Path = IMPORTS, out_root: Path = OUTPUT / "real",
             config_path: Path = BASE / "config.json") -> dict | None:
    files = collect(imports_dir)
    if not any(_has_rows(p) for p in files["ads"] + files["manual"]):
        return None
    out_dir = out_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    return run(files["ads"], config_path, files["sourcing"], files["review"], out_dir,
               manual_paths=files["manual"])


def run_sample(out_root: Path = OUTPUT / "sample", config_path: Path = BASE / "config.json") -> dict:
    out_dir = out_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    return run([SAMPLE / "ads_sample.csv", SAMPLE / "ads_sample.json"], config_path,
               SAMPLE / "aliexpress_sample.csv", SAMPLE / "compliance_review.csv", out_dir)


def _print(res: dict):
    print(f"出力先: {res['out_dir']}")
    for k, v in res["summary"].items():
        print(f"  {k}: {v}")
    for i, p in enumerate(res["top"], 1):
        name = p.rep.product_name if p.rep.product_name != "不明" else p.rep.ad_url
        print(f"  {i:>2}. [{p.decision}] {name}  score={p.score['total']}")
    print("  → top10.csv / report.html / errors.csv / missing_values.csv を確認してください")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="imports/ の実データから販売テスト候補TOP10を出力")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--init", action="store_true", help="imports/ フォルダとテンプレートを作成")
    g.add_argument("--sample", action="store_true", help="サンプルデータで実行（output/sample/）")
    ap.add_argument("--config", default=str(BASE / "config.json"))
    a = ap.parse_args(argv)

    if a.init:
        created = init()
        print(f"imports フォルダ: {IMPORTS}")
        for name, desc in FOLDERS.items():
            print(f"  imports/{name}/  … {desc}")
        for c in created:
            print(f"  作成: {c.relative_to(BASE)}")
        return 0
    if a.sample:
        _print(run_sample(config_path=Path(a.config)))
        return 0

    init()  # フォルダが無ければ作る（既存ファイルは触らない）
    res = run_real(config_path=Path(a.config))
    if res is None:
        print("実データがありません。次のどちらかにファイルを置いてください:\n"
              f"  {IMPORTS / 'ads'}/      … エクスポートした CSV/JSON\n"
              f"  {IMPORTS / 'manual' / 'manual_ads.csv'} … ad_url 列に広告URLを1行ずつ")
        return 2
    _print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
