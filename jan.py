"""
JANコード(EAN-13)の生成ユーティリティ。

GS1事業者コード(企業プレフィックス)を起点に、商品アイテム番号を連番で振り、
チェックディジットを計算して「ありうるJANコード」を生成する。
これを各ECサイトのAPIで検索し、実在する商品だけを拾う使い方を想定。
"""


def ean13_check_digit(twelve):
    """12桁(チェックディジットを除く本体)から13桁目を計算して返す。"""
    if len(twelve) != 12 or not twelve.isdigit():
        raise ValueError("twelve must be 12 digits: %r" % twelve)
    # 左から 1,3,1,3,... の重み(位置1=重み1, 位置2=重み3, ...)
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(twelve))
    return str((10 - total % 10) % 10)


def make_jan(base, item_number):
    """企業プレフィックス base + 連番 item_number から 13桁JANを作る。"""
    fill = 12 - len(base)
    if fill < 0:
        raise ValueError("base too long (max 12 digits): %r" % base)
    body = base + str(item_number).zfill(fill)
    if len(body) != 12:
        raise ValueError("item_number overflowed the fill width")
    return body + ean13_check_digit(body)


def generate_jans(base, start=0, end=None):
    """base配下のアイテム番号 start..end-1 を順にJANにして yield する。"""
    if not base.isdigit():
        raise ValueError("base must be digits: %r" % base)
    fill = 12 - len(base)
    if fill < 0:
        raise ValueError("base too long (max 12 digits): %r" % base)
    upper = 10 ** fill
    end = upper if end is None else min(end, upper)
    for n in range(start, end):
        yield make_jan(base, n)


def is_valid_jan(code):
    """13桁JANのチェックディジットが正しいか検証。"""
    code = str(code)
    if len(code) != 13 or not code.isdigit():
        return False
    return ean13_check_digit(code[:12]) == code[12]


def classify_code(code):
    """コード番号から種別(JAN/UPC/EAN等)を判定して返す。"""
    code = str(code).strip()
    if not code.isdigit():
        return "不明"
    n = len(code)
    if n == 13:
        if code[:2] in ("45", "49"):
            return "JAN(日本)"
        if code[0] == "0":
            return "UPC"          # 先頭0はUPC-AをEAN-13化したもの
        return "EAN"
    if n == 12:
        return "UPC"
    if n == 8:
        return "JAN(8桁)"
    return "不明"
