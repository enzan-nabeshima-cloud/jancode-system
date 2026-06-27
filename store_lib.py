"""
商品の保存ロジック(画面側 app.py と 一括取り込み bulk_import.py で共通利用)。

優先順位:
  * 名前/説明/ジャンル/発売日は「主データソース」を選んで採用。
    楽天/Yahoo/Amazon が値を返せば最優先。無ければ既存(店舗由来)を維持。
    それも無ければ OFF の日本語データをフォールバック保存。
  * 画像も楽天最優先。楽天画像→(既存の店舗画像を保護)→OFF画像→既存 の順。
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


def merge_fields(existing, results, jan):
    ex = dict(existing) if existing else {}
    ex_src = ex.get("data_source") or ""
    store = [r for r in results if r.get("source") in STORE_SOURCES]
    off = [r for r in results if r.get("source") == "openfoodfacts"]

    if any(r.get("name") for r in store):
        prim, src = store, _src_with_name(store)            # 楽天等を最優先
    elif ex.get("name") and ex_src in STORE_SOURCES:
        prim, src = None, ex_src                            # 既存(店舗由来)を維持
    elif any(r.get("name") for r in off):
        prim, src = off, "openfoodfacts"                    # OFFをフォールバック
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
