"""
複数メーカーを順番に総当たり取得するスクリプト(GitHub Actions向け)。

targets.csv の各メーカー(base)を上から順にスキャンし、実在商品を蓄積する。
ヒットした商品には targets.csv の会社名・カナを自動設定する(空欄のみ)。
1回の実行で最大 --limit 件だけ取得し、進捗(scan_progress)を保存して次回続行する。

使い方:
  python scan_targets.py --limit 2000 --delay 1.5
"""

import argparse
import csv
import os
import sqlite3
import sys
import time

import apis
import store_lib
import jan as janlib
from bulk_import import CONFIG, ensure_schema, now_iso

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_targets(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(
                r for r in f if r.strip() and not r.lstrip().startswith("#")):
            base = (row.get("base") or "").strip()
            if base.isdigit():
                out.append({
                    "base": base,
                    "company": (row.get("company") or "").strip(),
                    "company_kana": (row.get("company_kana") or "").strip(),
                })
    return out


def ensure_progress(db):
    db.execute("CREATE TABLE IF NOT EXISTS scan_progress("
               "base TEXT PRIMARY KEY, next_index INTEGER, done INTEGER)")
    db.commit()


def get_progress(db, base):
    r = db.execute("SELECT next_index,done FROM scan_progress WHERE base=?",
                   (base,)).fetchone()
    return (r[0], r[1]) if r else (0, 0)


def set_progress(db, base, idx, done):
    db.execute("INSERT INTO scan_progress(base,next_index,done) VALUES(?,?,?) "
               "ON CONFLICT(base) DO UPDATE SET next_index=?,done=?",
               (base, idx, done, idx, done))


def set_company(db, jan, t):
    if t["company"]:
        db.execute("UPDATE products SET company=?,company_kana=? WHERE jan=? "
                   "AND (company IS NULL OR company='')",
                   (t["company"], t["company_kana"], jan))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--targets", default=os.path.join(BASE_DIR, "targets.csv"))
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "jan_db.sqlite3"))
    args = ap.parse_args()

    if not CONFIG["RAKUTEN_APP_ID"] and not CONFIG["YAHOO_APP_ID"]:
        sys.exit("楽天またはYahooのキーが設定されていません。")

    targets = load_targets(args.targets)
    if not targets:
        sys.exit("targets.csv に対象がありません。")

    db = sqlite3.connect(args.db)
    ensure_schema(db)
    ensure_progress(db)

    budget = args.limit
    found = 0
    t0 = time.time()

    for t in targets:
        if budget <= 0:
            break
        base = t["base"]
        fill = 12 - len(base)
        if fill < 0:
            print("skip(基底が長すぎ):", base)
            continue
        maxn = 10 ** fill
        idx, done = get_progress(db, base)
        if done:
            continue
        print("== %s (%s) を index=%d から ==" % (base, t["company"] or "?", idx))

        while idx < maxn and budget > 0:
            code = janlib.make_jan(base, idx)
            if not db.execute("SELECT 1 FROM checked WHERE jan=?",
                              (code,)).fetchone():
                results, errors = apis.search_all(code, CONFIG)
                if results:
                    store_lib.upsert_product(db, code, results)
                    set_company(db, code, t)
                    found += 1
                    nm = next((r["name"] for r in results if r.get("name")), "")
                    print("  [HIT] %s  %s  <%s>" % (code, nm[:34], t["company"]))
                db.execute("INSERT OR REPLACE INTO checked(jan,found,checked_at)"
                           " VALUES(?,?,?)", (code, 1 if results else 0, now_iso()))
                budget -= 1
                if budget % 25 == 0:
                    print("...残り予算 %d / ヒット %d / %.2f件/秒"
                          % (budget, found, (args.limit - budget)
                             / max(time.time() - t0, 1e-9)))
                time.sleep(args.delay)
            idx += 1
            if idx % 50 == 0:
                set_progress(db, base, idx, 0)
                db.commit()

        set_progress(db, base, idx, 1 if idx >= maxn else 0)
        db.commit()
        if idx >= maxn:
            print("== %s 完了 ==" % base)

    print("\n=== 実行完了 === 取得 %d 件 / 新規ヒット %d 件"
          % (args.limit - budget, found))
    db.close()


if __name__ == "__main__":
    main()
