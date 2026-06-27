"""
各ECサイトのAPIクライアント。
JANコードを受け取り、正規化した商品情報のリストを返す。

返り値の各要素(dict)の主なキー:
  source, jan, name, price, url, image, shop,
  description (商品説明), genre_id, genre_path (ジャンル階層名), release_date (発売日)
"""

import datetime
import hashlib
import hmac
import json
import re

import requests

TIMEOUT = 10

RAKUTEN_ITEM_URL = (
    "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601")
RAKUTEN_GENRE_URL = (
    "https://openapi.rakuten.co.jp/ichibams/api/IchibaGenre/Search/20120723")

# ジャンルID→階層名 のキャッシュ(同じジャンルで何度もAPIを叩かない)
_genre_cache = {}

_DATE_RE = re.compile(
    r"発売日[\s:：]*?(\d{4})\s*[年/.\-]\s*(\d{1,2})(?:\s*[月/.\-]\s*(\d{1,2}))?")


def _extract_release_date(text):
    """商品説明文から『発売日 YYYY年MM月(DD)』をベスト努力で抽出。"""
    if not text:
        return ""
    m = _DATE_RE.search(text)
    if not m:
        return ""
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3)
    return "%s-%s-%s" % (y, mo, d.zfill(2)) if d else "%s-%s" % (y, mo)


def _clean_listing_name(name):
    """店舗の販売タイトルから宣伝文を除去して、できるだけ正式名称に近づける。"""
    s = name or ""
    s = re.sub(r"\s*[※*].*$", "", s)                 # ※以降の注釈を削除
    s = re.sub(r"/[A-Za-z0-9]{1,8}/\s*$", "", s)      # 末尾の /uy/ 等のコード
    # 先頭が宣伝文(…！/…。)で始まる場合、最初の ! ! 。 までを除去(先頭40字以内)
    m = re.search(r"[!！。]", s[:40])
    if m and re.search(r"(送料|ケース|円|ポイント|％|%|無料|限定|クーポン)", s[:m.start()+1]):
        s = s[m.end():]
    # 先頭の【…】(…)［…］等の宣伝囲みを繰り返し除去
    for _ in range(4):
        s2 = re.sub(r"^\s*[【\[(（［][^】\])）］]{0,40}[】\])）］]\s*", "", s)
        if s2 == s:
            break
        s = s2
    # 文中の宣伝ワードを除去
    s = re.sub(r"(送料無料|送料込み?|あす楽対応?|ポイント\d+倍|最大\d+[%％](OFF|オフ)?|期間限定|まとめ買い|父の日|母の日|お中元|お歳暮)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" \u3000!！・|｜/")
    return s or (name or "")


def _rakuten_headers(access_key, referer):
    h = {"User-Agent": "jancode-system/1.0"}
    if access_key:
        h["accessKey"] = access_key
    if referer:
        h["Referer"] = referer
        h["Origin"] = referer
    return h


def rakuten_genre_path(genre_id, app_id, access_key, referer):
    """ジャンルIDを『親 > 子 > 現在』の名称階層に変換(キャッシュ付き)。"""
    if not genre_id or str(genre_id) in ("0", ""):
        return ""
    gid = str(genre_id)
    if gid in _genre_cache:
        return _genre_cache[gid]
    path = ""
    try:
        params = {"applicationId": app_id, "genreId": gid, "formatVersion": 2}
        r = requests.get(RAKUTEN_GENRE_URL, params=params,
                         headers=_rakuten_headers(access_key, referer),
                         timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        def name_of(node):
            if isinstance(node, list):
                node = node[0] if node else {}
            if isinstance(node, dict):
                return node.get("genreName") or (
                    node.get("child") or {}).get("genreName", "")
            return ""

        names = []
        for p in data.get("parents", []) or []:
            nm = name_of(p)
            if nm:
                names.append(nm)
        cur = name_of(data.get("current"))
        if cur:
            names.append(cur)
        path = " > ".join(names)
    except Exception:
        path = ""
    _genre_cache[gid] = path
    return path


# --------------------------------------------------------------------------
# 楽天市場 商品検索API
# --------------------------------------------------------------------------
def search_rakuten(jan, app_id, access_key="", hits=5,
                   referer="http://localhost:5057", resolve_genre=True):
    if not app_id:
        return []
    params = {
        "applicationId": app_id,
        "keyword": jan,
        "hits": hits,
        "sort": "+itemPrice",
        "imageFlag": 1,
        "formatVersion": 2,
    }
    try:
        r = requests.get(RAKUTEN_ITEM_URL, params=params,
                         headers=_rakuten_headers(access_key, referer),
                         timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [{"source": "rakuten", "jan": jan, "error": str(e)}]

    results = []
    for entry in data.get("Items", []):
        item = entry.get("Item", entry)
        images = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
        image = ""
        if images:
            first = images[0]
            image = first.get("imageUrl") if isinstance(first, dict) else first
            image = image.split("?")[0]
        caption = item.get("itemCaption", "")
        genre_id = item.get("genreId", "")
        genre_path = ""
        if resolve_genre and genre_id:
            genre_path = rakuten_genre_path(genre_id, app_id, access_key, referer)
        results.append({
            "source": "rakuten",
            "jan": jan,
            "name": _clean_listing_name(item.get("itemName", "")),
            "price": item.get("itemPrice"),
            "url": item.get("itemUrl", ""),
            "image": image,
            "shop": item.get("shopName", ""),
            "description": caption,
            "genre_id": str(genre_id) if genre_id else "",
            "genre_path": genre_path,
            "release_date": _extract_release_date(caption),
        })
    return results


# --------------------------------------------------------------------------
# Yahoo!ショッピング 商品検索API (V3)
# --------------------------------------------------------------------------
def search_yahoo(jan, app_id, results_n=5):
    if not app_id:
        return []
    url = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
    params = {"appid": app_id, "jan_code": jan, "results": results_n,
              "sort": "+price"}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [{"source": "yahoo", "jan": jan, "error": str(e)}]

    out = []
    for hit in data.get("hits", []):
        img = hit.get("image") or {}
        image = img.get("medium") or img.get("small") or ""
        if not image:
            image = (hit.get("exImage") or {}).get("url", "")
        seller = (hit.get("seller") or {}).get("name", "")
        # Yahooのジャンル(カテゴリ)階層
        gpath = ""
        gobj = hit.get("genreCategory") or {}
        if gobj.get("name"):
            gpath = gobj.get("name")
        desc = hit.get("description", "") or hit.get("headLine", "")
        out.append({
            "source": "yahoo",
            "jan": jan,
            "name": _clean_listing_name(hit.get("name", "")),
            "price": hit.get("price"),
            "url": hit.get("url", ""),
            "image": image,
            "shop": seller,
            "description": desc,
            "genre_id": str(gobj.get("id", "")) if gobj.get("id") else "",
            "genre_path": gpath,
            "release_date": _extract_release_date(desc),
        })
    return out


# --------------------------------------------------------------------------
# Amazon PA-API v5 (注: 2026/5/15に提供終了。Creators APIへ要移行。当面は空返し)
# --------------------------------------------------------------------------
def search_amazon(jan, access_key, secret_key, partner_tag,
                  host="webservices.amazon.co.jp", region="us-west-2",
                  item_count=3):
    if not (access_key and secret_key and partner_tag):
        return []

    path = "/paapi5/searchitems"
    target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    payload = {
        "Keywords": jan, "SearchIndex": "All", "ItemCount": item_count,
        "PartnerTag": partner_tag, "PartnerType": "Associates",
        "Marketplace": "www.amazon.co.jp",
        "Resources": ["ItemInfo.Title", "Offers.Listings.Price",
                      "Images.Primary.Medium"],
    }
    body = json.dumps(payload)
    t = datetime.datetime.utcnow()
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")
    service = "ProductAdvertisingAPI"
    canonical_headers = ("content-encoding:amz-1.0\n" "host:" + host + "\n"
                         "x-amz-date:" + amz_date + "\n"
                         "x-amz-target:" + target + "\n")
    signed_headers = "content-encoding;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canonical_request = ("POST\n" + path + "\n\n" + canonical_headers + "\n"
                         + signed_headers + "\n" + payload_hash)
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = date_stamp + "/" + region + "/" + service + "/aws4_request"
    string_to_sign = (algorithm + "\n" + amz_date + "\n" + credential_scope + "\n"
                      + hashlib.sha256(canonical_request.encode()).hexdigest())

    def _sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(),
                         hashlib.sha256).hexdigest()
    authorization = (algorithm + " Credential=" + access_key + "/"
                     + credential_scope + ", SignedHeaders=" + signed_headers
                     + ", Signature=" + signature)
    headers = {"content-encoding": "amz-1.0",
               "content-type": "application/json; charset=utf-8", "host": host,
               "x-amz-date": amz_date, "x-amz-target": target,
               "Authorization": authorization}
    try:
        r = requests.post("https://" + host + path, data=body, headers=headers,
                          timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [{"source": "amazon", "jan": jan, "error": str(e)}]

    out = []
    for item in data.get("SearchResult", {}).get("Items", []):
        info = item.get("ItemInfo", {})
        title = (info.get("Title") or {}).get("DisplayValue", "")
        image = ((item.get("Images") or {}).get("Primary") or {}).get(
            "Medium", {}).get("URL", "")
        price = None
        listings = (item.get("Offers") or {}).get("Listings") or []
        if listings:
            price = (listings[0].get("Price") or {}).get("Amount")
        out.append({
            "source": "amazon", "jan": jan, "name": title,
            "price": int(price) if price else None,
            "url": item.get("DetailPageURL", ""), "image": image,
            "shop": "Amazon", "description": "", "genre_id": "",
            "genre_path": "", "release_date": "",
        })
    return out


def search_all(jan, cfg):
    """3サイトを横断検索し、結果リストとエラーリストを返す。"""
    results, errors = [], []
    for items in (
        search_rakuten(jan, cfg.get("RAKUTEN_APP_ID"),
                       access_key=cfg.get("RAKUTEN_ACCESS_KEY", ""),
                       referer=cfg.get("APP_PUBLIC_URL", "http://localhost:5057")),
        search_yahoo(jan, cfg.get("YAHOO_APP_ID")),
        (search_openfoodfacts(jan, cfg.get("OFF_CONTACT", "jancode-system"))
         if str(cfg.get("OFF_ENABLED", "1")) not in ("0", "false", "") else []),
        search_amazon(jan, cfg.get("AMAZON_ACCESS_KEY"),
                      cfg.get("AMAZON_SECRET_KEY"),
                      cfg.get("AMAZON_PARTNER_TAG")),
    ):
        for it in items:
            if "error" in it:
                errors.append("[" + it["source"] + "] " + it["error"])
            else:
                results.append(it)
    return results, errors


# --------------------------------------------------------------------------
# Open Food Facts (無料・キー不要・食品をJANで直接照会)
#   ※OFFはUser-Agentでアプリ識別を必須としているため必ず付与する
# --------------------------------------------------------------------------
def _clean_off_name(name):
    """'日本語名 (English)' の英語併記を取り除く(日本語が残る場合のみ)。"""
    m = re.search(r"^(.*?)\s*[\(（][\x00-\x7F]+[\)）]\s*$", name or "")
    if m and any(ord(c) > 127 for c in m.group(1)):
        return m.group(1).strip()
    return name


OFF_URL = "https://world.openfoodfacts.org/api/v2/product/%s.json"
OFF_FIELDS = ("code,product_name,product_name_ja,generic_name,generic_name_ja,"
              "brands,categories,ingredients_text_ja,ingredients_text,"
              "image_url,image_front_url,selected_images")


def search_openfoodfacts(jan, contact="jancode-system"):
    headers = {"User-Agent": "jancode-system/1.0 (%s)" % contact}
    try:
        r = requests.get(OFF_URL % jan,
                         params={"fields": OFF_FIELDS, "lc": "ja", "cc": "jp"},
                         headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return [{"source": "openfoodfacts", "jan": jan, "error": str(e)}]

    if data.get("status") != 1:
        return []
    p = data.get("product", {}) or {}

    sel = ((p.get("selected_images") or {}).get("front") or {}).get("display") or {}
    image = (sel.get("ja") or sel.get("en") or p.get("image_front_url")
             or p.get("image_url") or "")
    # OFF画像を元の高解像度版に(末尾 .400.jpg 等 -> .full.jpg)
    if "openfoodfacts.org" in image:
        image = re.sub(r"\.(\d+)\.jpg$", ".full.jpg", image)
    name = _clean_off_name(
        p.get("product_name_ja") or p.get("product_name")
        or p.get("generic_name_ja") or p.get("generic_name") or "")
    desc = p.get("ingredients_text_ja") or p.get("ingredients_text") or ""
    cats = p.get("categories") or ""
    genre_path = " > ".join([c.strip() for c in cats.split(",") if c.strip()])
    return [{
        "source": "openfoodfacts", "jan": jan, "name": name, "price": None,
        "url": "https://world.openfoodfacts.org/product/%s" % jan,
        "image": image, "shop": "Open Food Facts", "description": desc,
        "genre_id": "", "genre_path": genre_path, "release_date": "",
    }]
