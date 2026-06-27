"""
サンプルJANから、bulk_import.py に渡す --base(事業者コード)候補を算出する補助ツール。

使い方:
  python prefix_helper.py 4901777018888 4902102072670 ...
手元にある食品のバーコード番号(13桁)をスペース区切りで渡すと、
そのメーカーを総当たりするためのコマンド例を表示します。
"""

import sys
import jan as janlib


def analyze(code):
    code = code.strip()
    print("=" * 56)
    print("JAN: %s" % code)
    if not janlib.is_valid_jan(code):
        print("  → 13桁のJANとして無効です(桁数かチェック数字が不一致)。スキップ。")
        return
    country = code[:2]
    region = "日本" if country in ("45", "49") else "国コード " + country
    print("  国コード: %s (%s)" % (country, region))

    # 9桁事業者コード方式: 残り3桁が商品アイテム → 約1,000候補
    base9 = code[:9]
    # 7桁事業者コード方式: 残り5桁が商品アイテム → 約100,000候補
    base7 = code[:7]

    print("  ▼ 推奨(9桁事業者コード方式 / 候補 約1,000件・約17分)")
    print("      python bulk_import.py --base %s --start 0 --end 1000" % base9)
    print("  ▼ 取りこぼしが多い場合(7桁方式 / 候補 約100,000件・数時間)")
    print("      python bulk_import.py --base %s --start 0 --end 100000" % base7)


def main():
    if len(sys.argv) < 2:
        print("使い方: python prefix_helper.py <JAN> [<JAN> ...]")
        print("例:     python prefix_helper.py 4901777018888")
        return
    for code in sys.argv[1:]:
        analyze(code)
    print("=" * 56)
    print("まずは --limit 50 を付けて少数で試し、ヒットが出るか確認するのがおすすめです。")


if __name__ == "__main__":
    main()
