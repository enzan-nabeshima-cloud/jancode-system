"""
JANコード一括取り込みスクリプト (CLI)
GS1事業者コードからJAN候補を総当たり生成し、楽天/Yahoo APIで検索 →
実在した商品だけを jan_db.sqlite3 に蓄積する。説明文/ジャンル/コードタイプ/発売日も保存。

例:
  python bulk_import.py --base 4901085 --start 0 --end 100000 --delay 1
  python bulk_import.py --base 490108516 --limit 50
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import jan as janlib
import apis
import store_lib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG = {
    "RAKUTEN_APP_ID": os.environ.get("RAKUTEN_APP_ID", ""),
    "RAKUTEN_ACCESS_KEY": os.environ.get("RAKUTEN_ACCESS_KEY", ""),
    "YAHOO_APP_ID": os.environ.get("YAHOO_APP_ID", ""),
    "AMAZON_ACCESS_KEY": os.environ.get("AMAZON_ACCESS_KEY", ""),
    "AMAZON_SECRET_KEY": os.environ.get("AMAZON_SECRET_KEY", ""),
    "AMAZON_PARTNER_TAG": os.environ.get("AMAZON_PARTNER_TAG", ""),
    "APP_PUBLIC_URL": os.environ.get(
        "APP_PUBLIC_URL", "http://localhost:" + os.environ.get("PORT", "5057")),
    "OFF_ENABLED": os.environ.get("OFF_ENABLED", "1"),
    "OFF_CONTACT": os.environ.get("OFF_CONTACT", "jancode-system"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    jan TEXT PRIMARY KEY, name TEXT, image TEXT, note TEXT,
    created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jan TEXT NOT NULL, source TEXT NOT NULL,
    name TEXT, price INTEGER, url TEXT, shop TEXT, image TEXT, fetched_at TEXT,
    FOREIGN KEY (jan) REFERENCES products(jan) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_offers_jan ON offers(jan);
CREATE TABLE IF NOT EXISTS checked (
    jan TEXT PRIMARY KEY, found INTEGER, checked_at TEXT);
"""
EXTRA_COLS = ["description", "genre_path", "genre_id", "code_type", "release_date", "data_source", "company", "company_kana"]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_schema(db):
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    have = {r[1] for r in db.execute("PRAGMA table_info(products)")}
    for col in EXTRA_COLS:
        if col not in have:
            db.execute("ALTER TABLE products ADD COLUMN %s TEXT" % col)
    db.commit()


def first(results, key):
    return next((r[key] for r in results if r.get(key)), "")


def store(db, jan_code, results):
    store_lib.upsert_product(db, jan_code, results)


def main():
    ap = argparse.ArgumentParser(description="JANコード一括取り込み")
    ap.add_argument("--base", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "jan_db.sqlite3"))
    args = ap.parse_args()

    if not CONFIG["RAKUTEN_APP_ID"] and not CONFIG["YAHOO_APP_ID"]:
        sys.exit("楽天またはYahooのキーが.envに設定されていません。")

    db = sqlite3.connect(args.db)
    ensure_schema(db)

    checked = found = skipped = 0
    t0 = time.time()
    try:
        for code in janlib.generate_jans(args.base, args.start, args.end):
            if args.limit is not None and checked >= args.limit:
                break
            if db.execute("SELECT 1 FROM checked WHERE jan=?", (code,)).fetchone():
                skipped += 1
                continue
            results, errors = apis.search_all(code, CONFIG)
            hit = 1 if results else 0
            if results:
                store(db, code, results)
                found += 1
                nm = first(results, "name")
                print("  [HIT] %s  %s" % (code, nm[:40]))
            db.execute("INSERT OR REPLACE INTO checked(jan,found,checked_at)"
                       " VALUES(?,?,?)", (code, hit, now_iso()))
            db.commit()
            checked += 1
            if errors and checked <= 3:
                print("  (警告) " + " / ".join(errors))
            if checked % 25 == 0:
                print("...検索 %d件 / ヒット %d件 / %.2f件/秒"
                      % (checked, found, checked / max(time.time() - t0, 1e-9)))
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\n中断しました。途中まで保存済みです。")

    print("\n=== 完了 ===")
    print("検索: %d 件 / ヒット: %d 件 / スキップ: %d 件" % (checked, found, skipped))
    print("保存先: %s" % args.db)
    db.close()


if __name__ == "__main__":
    main()
