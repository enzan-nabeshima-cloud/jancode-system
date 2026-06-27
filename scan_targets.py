"""
複数メーカーを「毎回少しずつ・全社並行(ラウンドロビン)」で総当たり取得する。

targets.csv の各メーカー(base)を、1回の実行で均等に少しずつ進める。
ヒット商品には targets.csv の会社名・カナを自動設定する(空欄のみ)。
進捗(scan_progress)を保存して次回続行。1社が終わると残りに予算が回る。

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
                out.append({"base": base,
                            "company": (row.get("company") or "").strip(),
                            "company_kana": (row.get("company_kana") or "").strip()})
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


def scan_one(db, t, budget, delay):
    """1メーカーを進捗カーソルから最大 budget 件フェッチ。(消費数, ヒット数)を返す。"""
    base = t["base"]
    fill = 12 - len(base)
    if fill < 0:
        return 0, 0
    maxn = 10 ** fill
    idx, done = get_progress(db, base)
    if done:
        return 0, 0
    consumed = found = 0
    while idx < maxn and consumed < budget:
        code = janlib.make_jan(base, idx)
        if not db.execute("SELECT 1 FROM checked WHERE jan=?", (code,)).fetchone():
            results, errors = apis.search_all(code, CONFIG)
            if results:
                store_lib.upsert_product(db, code, results)
                set_company(db, code, t)
                found += 1
                nm = next((r["name"] for r in results if r.get("name")), "")
                print("  [HIT] %s  %s  <%s>" % (code, nm[:32], t["company"]))
            db.execute("INSERT OR REPLACE INTO checked(jan,found,checked_at)"
                       " VALUES(?,?,?)", (code, 1 if results else 0, now_iso()))
            consumed += 1
            time.sleep(delay)
        idx += 1
        if idx % 50 == 0:
            set_progress(db, base, idx, 0)
            db.commit()
    set_progress(db, base, idx, 1 if idx >= maxn else 0)
    db.commit()
    tag = "完了" if idx >= maxn else "→index=%d" % idx
    print("== %s (%s): %d件取得 / ヒット%d / %s ==" %
          (base, t["company"] or "?", consumed, found, tag))
    return consumed, found


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

    # 未完了メーカーだけを対象に、予算を均等配分(ラウンドロビン)
    incomplete = [t for t in targets if not get_progress(db, t["base"])[1]]
    if not incomplete:
        print("全メーカー完了済みです。targets.csv に追加してください。")
        db.close()
        return

    per = max(50, args.limit // len(incomplete))
    print("対象メーカー %d 社 / 1社あたり最大 %d 件 / 合計上限 %d 件"
          % (len(incomplete), per, args.limit))

    budget = args.limit
    total = found = 0
    try:
        for t in incomplete:
            if budget <= 0:
                break
            c, fnd = scan_one(db, t, min(per, budget), args.delay)
            budget -= c
            total += c
            found += fnd
    except KeyboardInterrupt:
        print("\n中断しました。途中まで保存済みです。")

    print("\n=== 実行完了 === 取得 %d 件 / 新規ヒット %d 件" % (total, found))
    db.close()


if __name__ == "__main__":
    main()
