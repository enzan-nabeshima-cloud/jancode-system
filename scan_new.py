"""
新商品チェック(ハイブリッド)。

既に取得済みの商品はスキップし、「空き番号」だけを再確認して新商品を拾う。
  * frontier (頻繁): 各メーカーの『見つかっている最大番号の少し手前〜先(margin)』だけを
    再チェック。メーカーは番号を概ね連番で増やすため、新作を効率よく捕捉。
  * full (月1回など): 全番号空間の空き枠を、進捗カーソルで少しずつ再チェック(網羅・取りこぼし防止)。

見つかった新商品は通常どおり保存され、created_at(登録日)が新しくなる=「新着」として判別可能。

使い方:
  python scan_new.py --mode frontier --margin 2000 --limit 2000 --delay 1.5
  python scan_new.py --mode full --limit 4000 --delay 1.5
"""

import argparse
import os
import sqlite3
import sys
import time

import apis
import store_lib
import jan as janlib
from bulk_import import CONFIG, ensure_schema, now_iso
from scan_targets import load_targets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def ensure_newprog(db):
    db.execute("CREATE TABLE IF NOT EXISTS scan_new_progress("
               "base TEXT PRIMARY KEY, next_index INTEGER)")
    db.commit()


def set_company(db, jan, t):
    if t["company"]:
        db.execute("UPDATE products SET company=?,company_kana=? WHERE jan=? "
                   "AND (company IS NULL OR company='')",
                   (t["company"], t["company_kana"], jan))


def max_found_item(db, base):
    """そのメーカーで既に見つかっている最大アイテム番号と、番号空間サイズを返す。"""
    fill = 12 - len(base)
    maxn = 10 ** fill if fill >= 0 else 1
    mx = -1
    for (j,) in db.execute("SELECT jan FROM products WHERE jan LIKE ?",
                           (base + "%",)):
        try:
            it = int(j[len(base):12])
        except Exception:
            continue
        if it > mx:
            mx = it
    return mx, maxn


def check_new(db, base, idx, t, delay):
    """1候補を再チェック。既存に無く実在すれば新商品として保存。(消費, 新規)を返す。"""
    code = janlib.make_jan(base, idx)
    if db.execute("SELECT 1 FROM products WHERE jan=?", (code,)).fetchone():
        return 0, 0                      # 既に持っている → APIを呼ばずスキップ
    results, _ = apis.search_all(code, CONFIG)
    new = 0
    if results:
        store_lib.upsert_product(db, code, results)
        set_company(db, code, t)
        new = 1
        nm = next((r["name"] for r in results if r.get("name")), "")
        print("  [NEW] %s  %s  <%s>" % (code, nm[:32], t["company"]))
    db.execute("INSERT OR REPLACE INTO checked(jan,found,checked_at) VALUES(?,?,?)",
               (code, 1 if results else 0, now_iso()))
    time.sleep(delay)
    return 1, new


def run_frontier(db, targets, margin, budget, delay):
    total = new = 0
    for t in targets:
        if budget <= 0:
            break
        base = t["base"]
        mx, maxn = max_found_item(db, base)
        if mx < 0:
            continue                     # まだ商品が無いメーカーはフロンティア無し
        start = max(0, mx - 20)
        end = min(maxn, mx + margin + 1)
        c = n = 0
        for idx in range(start, end):
            if budget <= 0:
                break
            cc, nn = check_new(db, base, idx, t, delay)
            c += cc
            n += nn
            budget -= cc
            if c and c % 50 == 0:
                db.commit()
        db.commit()
        total += c
        new += n
        print("== [frontier] %s (%s): 確認%d / 新商品%d (max番号=%d) =="
              % (base, t["company"] or "?", c, n, mx))
    return total, new


def run_full(db, targets, budget, delay):
    ensure_newprog(db)
    per = max(50, budget // max(1, len(targets)))
    total = new = 0
    for t in targets:
        if budget <= 0:
            break
        base = t["base"]
        fill = 12 - len(base)
        maxn = 10 ** fill if fill >= 0 else 1
        r = db.execute("SELECT next_index FROM scan_new_progress WHERE base=?",
                       (base,)).fetchone()
        idx = r[0] if r else 0
        tb = min(per, budget)
        c = n = 0
        while idx < maxn and c < tb:
            cc, nn = check_new(db, base, idx, t, delay)
            c += cc
            n += nn
            idx += 1
            if idx % 50 == 0:
                db.execute("INSERT INTO scan_new_progress(base,next_index) "
                           "VALUES(?,?) ON CONFLICT(base) DO UPDATE SET next_index=?",
                           (base, idx, idx))
                db.commit()
        if idx >= maxn:
            idx = 0                       # 一巡したら最初に戻る
        db.execute("INSERT INTO scan_new_progress(base,next_index) VALUES(?,?) "
                   "ON CONFLICT(base) DO UPDATE SET next_index=?", (base, idx, idx))
        db.commit()
        budget -= c
        total += c
        new += n
        print("== [full] %s (%s): 確認%d / 新商品%d / next=%d =="
              % (base, t["company"] or "?", c, n, idx))
    return total, new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["frontier", "full"], default="frontier")
    ap.add_argument("--margin", type=int, default=2000)
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
    print("新商品チェック mode=%s / 対象%d社 / 上限%d件"
          % (args.mode, len(targets), args.limit))

    if args.mode == "full":
        total, new = run_full(db, targets, args.limit, args.delay)
    else:
        total, new = run_frontier(db, targets, args.margin, args.limit, args.delay)

    print("\n=== 完了 === 再確認 %d 件 / 新商品 %d 件" % (total, new))
    db.close()


if __name__ == "__main__":
    main()
