"""
商品の保存ロジック(画面側 app.py と 一括取り込み bulk_import.py で共通利用)。

優先順位:
  * 商品名: OFFの日本語名(正式名称に近い) → 楽天/Yahoo(宣伝文除去済み) → 既存 → OFF
  * 画像  : 楽天画像 →(既存の店舗画像を保護)→ OFF画像 → 既存
  * 説明/ジャンル/発売日: 店舗系 → 既存 → OFF
  * data_source 列に主ソースを記録し次回判定に使う。
  * オファー(価格)は今回取得できたソースのぶんだけ差し替え(失敗ソースは温存)。
"""

from datetime import datetime, timezone

import jan as janlib

STORE_SOURCES = ("rakuten", "yahoo", "amazon")
FILL_FIELDS = ["name", "image", "description", "genre_path", "genre_id",
               "release_date"]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _first(rows, key):
    return next((r[key] for r in rows if r.get(key)), "")


def _src_with_name(rows):
    for r in rows:
        if r.get("name"):
            return r.get("source")
    return rows[0].get("source") if rows else ""


def _has_jp(s):
    return any(ord(c) >= 0x3040 for c in (s or ""))


def merge_fields(existing, results, jan):
    ex = dict(existing) if existing else {}
    ex_src = ex.get("data_source") or ""
    store = [r for r in results if r.get("source") in STORE_SOURCES]
    off = [r for r in results if r.get("source") == "openfoodfacts"]

    if any(r.get("name") for r in store):
        prim, src = store, _src_with_name(store)
    elif ex.get("name") and ex_src in STORE_SOURCES:
        prim, src = None, ex_src
    elif any(r.get("name") for r in off):
        prim, src = off, "openfoodfacts"
    else:
        prim, src = None, ex_src

    out = {}
    for k in FILL_FIELDS:
        if prim is not None:
            out[k] = _first(prim, k) or (ex.get(k) or "")
        else:
            out[k] = ex.get(k) or ""

    # 画像は楽天最優先: 楽天画像 →(既存の店舗画像を保護)→ OFF画像 → 既存
    img_store = _first(store, "image")
    img_off = _first(off, "image")
    ex_img = ex.get("image") or ""
    if img_store:
        out["image"] = img_store
    elif src in STORE_SOURCES and ex_img:
        out["image"] = ex_img
    else:
        out["image"] = img_off or ex_img

    # 商品名は OFF日本語名 → 楽天等(宣伝除去済み) → 既存 → OFF
    off_name = _first(off, "name")
    store_name = _first(store, "name")
    ex_name = ex.get("name") or ""
    if off_name and _has_jp(off_name):
        out["name"] = off_name
    elif store_name:
        out["name"] = store_name
    elif ex_name:
        out["name"] = ex_name
    else:
        out["name"] = off_name or ""

    out["code_type"] = janlib.classify_code(jan)
    out["data_source"] = src
    return out


def upsert_product(db, jan, results, note=None):
    """商品をupsertし、オファーをソース単位で差し替える。commitは呼び出し側で。"""
    ts = now_iso()
    existing = db.execute("SELECT * FROM products WHERE jan=?", (jan,)).fetchone()
    f = merge_fields(existing, results, jan)
    if existing:
        db.execute(
            "UPDATE products SET name=?,image=?,description=?,genre_path=?,"
            "genre_id=?,release_date=?,code_type=?,data_source=?,updated_at=? "
            "WHERE jan=?",
            (f["name"], f["image"], f["description"], f["genre_path"],
             f["genre_id"], f["release_date"], f["code_type"], f["data_source"],
             ts, jan))
        if note is not None:
            db.execute("UPDATE products SET note=? WHERE jan=?", (note, jan))
    else:
        db.execute(
            "INSERT INTO products(jan,name,image,note,description,genre_path,"
            "genre_id,code_type,release_date,data_source,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (jan, f["name"], f["image"], note or "", f["description"],
             f["genre_path"], f["genre_id"], f["code_type"], f["release_date"],
             f["data_source"], ts, ts))

    for src in {r["source"] for r in results}:
        db.execute("DELETE FROM offers WHERE jan=? AND source=?", (jan, src))
    for r in results:
        db.execute(
            "INSERT INTO offers(jan,source,name,price,url,shop,image,fetched_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (jan, r["source"], r.get("name"), r.get("price"), r.get("url"),
             r.get("shop"), r.get("image"), ts))
