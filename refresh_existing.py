"""
既に登録済みの商品を再取得し、説明文・ジャンル・コードタイプ・発売日などを埋め直す。
(総当たりの bulk_import は『検索済み』をスキップするため、既存分の補完にはこちらを使う)

例:
  python refresh_existing.py            # 全件を再取得
  python refresh_existing.py --delay 2  # Yahoo併用時は2秒以上推奨
"""

import argparse
import os
import sqlite3
import time

import apis
from bulk_import import CONFIG, ensure_schema, store, now_iso, BASE_DIR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "jan_db.sqlite3"))
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    ensure_schema(db)
    jans = [r[0] for r in db.execute("SELECT jan FROM products ORDER BY jan")]
    print("対象 %d 件を再取得します。" % len(jans))

    done = updated = 0
    try:
        for jan in jans:
            results, errors = apis.search_all(jan, CONFIG)
            if results:
                store(db, jan, results)
                db.commit()
                updated += 1
            done += 1
            if errors and done <= 3:
                print("  (警告) " + " / ".join(errors))
            if done % 20 == 0:
                print("...%d/%d 完了" % (done, len(jans)))
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\n中断しました。途中まで保存済みです。")

    print("\n=== 完了 === 処理 %d 件 / 更新 %d 件" % (done, updated))
    db.close()


if __name__ == "__main__":
    main()
