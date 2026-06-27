"""
JANコード商品データベース — Webアプリ本体 (Flask)
  画面 + REST API + SQLite。楽天/Yahoo/Amazonから取得して蓄積。
"""

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone

from flask import (Flask, g, jsonify, render_template, request, Response, abort)

import apis
import jan as janlib
import store_lib

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "jan_db.sqlite3"))

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
API_KEY = os.environ.get("APP_API_KEY", "")

# productsテーブルに後から増やした列(既存DBにも自動で足す)
EXTRA_COLS = ["description", "genre_path", "genre_id", "code_type", "release_date", "data_source", "company", "company_kana"]

app = Flask(__name__)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            jan TEXT PRIMARY KEY, name TEXT, image TEXT, note TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, jan TEXT NOT NULL,
            source TEXT NOT NULL, name TEXT, price INTEGER, url TEXT,
            shop TEXT, image TEXT, fetched_at TEXT,
            FOREIGN KEY (jan) REFERENCES products(jan) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_offers_jan ON offers(jan);
        """
    )
    have = {r[1] for r in db.execute("PRAGMA table_info(products)")}
    for col in EXTRA_COLS:
        if col not in have:
            db.execute("ALTER TABLE products ADD COLUMN %s TEXT" % col)
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def require_api_key():
    if API_KEY and request.headers.get("X-API-KEY") != API_KEY:
        abort(401, description="invalid or missing X-API-KEY")


def _first(results, key):
    return next((r[key] for r in results if r.get(key)), "")


def fetch_and_store(jan, note=None):
    results, errors = apis.search_all(jan, CONFIG)
    db = get_db()
    store_lib.upsert_product(db, jan, results, note)
    db.commit()
    return get_product(jan), errors


def get_product(jan):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE jan=?", (jan,)).fetchone()
    if not p:
        return None
    offers = db.execute(
        "SELECT source,name,price,url,shop,image,fetched_at FROM offers "
        "WHERE jan=? ORDER BY price IS NULL, price ASC", (jan,)).fetchall()
    prices = [o["price"] for o in offers if o["price"] is not None]
    keys = p.keys()
    return {
        "jan": p["jan"], "name": p["name"], "image": p["image"],
        "note": p["note"],
        "description": p["description"] if "description" in keys else "",
        "genre_path": p["genre_path"] if "genre_path" in keys else "",
        "genre_id": p["genre_id"] if "genre_id" in keys else "",
        "code_type": p["code_type"] if "code_type" in keys else "",
        "release_date": p["release_date"] if "release_date" in keys else "",
        "company": p["company"] if "company" in keys else "",
        "company_kana": p["company_kana"] if "company_kana" in keys else "",
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "offers": [dict(o) for o in offers],
    }


def list_products(q=""):
    db = get_db()
    if q:
        like = "%" + q + "%"
        rows = db.execute(
            "SELECT jan FROM products WHERE jan LIKE ? OR name LIKE ? "
            "OR genre_path LIKE ? ORDER BY updated_at DESC",
            (like, like, like)).fetchall()
    else:
        rows = db.execute(
            "SELECT jan FROM products ORDER BY updated_at DESC").fetchall()
    return [get_product(r["jan"]) for r in rows]


@app.route("/")
def index():
    configured = {
        "rakuten": bool(CONFIG["RAKUTEN_APP_ID"]),
        "yahoo": bool(CONFIG["YAHOO_APP_ID"]),
        "amazon": bool(CONFIG["AMAZON_ACCESS_KEY"]),
        "off": str(CONFIG.get("OFF_ENABLED", "1")) not in ("0", "false", ""),
    }
    return render_template("index.html", configured=configured)


@app.route("/api/products", methods=["GET"])
def api_list():
    require_api_key()
    return jsonify(list_products(request.args.get("q", "").strip()))


@app.route("/api/products", methods=["POST"])
def api_create():
    require_api_key()
    data = request.get_json(silent=True) or request.form
    jan = (data.get("jan") or "").strip()
    if not jan.isdigit() or len(jan) not in (8, 13):
        abort(400, description="jan must be 8 or 13 digit number")
    product, errors = fetch_and_store(jan, data.get("note"))
    return jsonify({"product": product, "errors": errors}), 201


@app.route("/api/products/<jan>", methods=["GET"])
def api_get(jan):
    require_api_key()
    p = get_product(jan)
    if not p:
        abort(404)
    return jsonify(p)


@app.route("/api/products/<jan>", methods=["PATCH"])
def api_update(jan):
    require_api_key()
    db = get_db()
    if not db.execute("SELECT 1 FROM products WHERE jan=?", (jan,)).fetchone():
        abort(404)
    data = request.get_json(silent=True) or {}
    for field in ("name", "note", "description", "genre_path", "release_date",
                  "company", "company_kana"):
        if field in data:
            db.execute("UPDATE products SET " + field + "=?, updated_at=? "
                       "WHERE jan=?", (data[field], now_iso(), jan))
    db.commit()
    return jsonify(get_product(jan))


@app.route("/api/products/<jan>", methods=["DELETE"])
def api_delete(jan):
    require_api_key()
    db = get_db()
    db.execute("DELETE FROM products WHERE jan=?", (jan,))
    db.commit()
    return "", 204


@app.route("/api/products/<jan>/refresh", methods=["POST"])
def api_refresh(jan):
    require_api_key()
    product, errors = fetch_and_store(jan)
    return jsonify({"product": product, "errors": errors})


@app.route("/api/products/apply-company", methods=["POST"])
def api_apply_company():
    """指定したGS1事業者コード(先頭桁)で始まる全商品に会社名を一括設定。"""
    require_api_key()
    data = request.get_json(silent=True) or {}
    prefix = (data.get("prefix") or "").strip()
    if not prefix.isdigit() or len(prefix) < 5:
        abort(400, description="prefix must be >= 5 digits")
    company = data.get("company", "")
    kana = data.get("company_kana", "")
    only_empty = bool(data.get("only_empty"))
    db = get_db()
    sql = ("UPDATE products SET company=?, company_kana=?, updated_at=? "
           "WHERE jan LIKE ?")
    if only_empty:
        sql += " AND (company IS NULL OR company='')"
    cur = db.execute(sql, (company, kana, now_iso(), prefix + "%"))
    db.commit()
    return jsonify({"updated": cur.rowcount, "prefix": prefix})


@app.route("/api/search", methods=["GET"])
def api_search():
    require_api_key()
    jan = request.args.get("jan", "").strip()
    if not jan.isdigit():
        abort(400, description="jan required")
    results, errors = apis.search_all(jan, CONFIG)
    return jsonify({"jan": jan, "results": results, "errors": errors})


@app.route("/export.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["JAN", "コードタイプ", "商品名", "会社名", "会社名カナ", "ジャンル",
                "発売日", "サイト", "店舗", "価格", "URL", "画像", "商品説明", "取得日時"])
    for p in list_products():
        rows = p["offers"] or [{}]
        for o in rows:
            w.writerow([p["jan"], p["code_type"], p["name"], p.get("company", ""),
                        p.get("company_kana", ""), p["genre_path"],
                        p["release_date"], o.get("source", ""), o.get("shop", ""),
                        o.get("price", ""), o.get("url", ""),
                        o.get("image", "") or p["image"],
                        (p["description"] or "").replace("\n", " ")[:1000],
                        o.get("fetched_at", "")])
    out = buf.getvalue().encode("utf-8-sig")
    return Response(out, mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=jan_products.csv"})


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
def handle_err(e):
    return jsonify({"error": getattr(e, "description", str(e))}), e.code


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5057))
    app.run(host="0.0.0.0", port=port, debug=True)
