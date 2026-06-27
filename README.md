# JANコード商品データベース (Webアプリ)

JANコードをキーに、楽天市場・Yahoo!ショッピング・Amazon から商品情報と画像を
取得して蓄積する、Web上の商品データベースです。画面で一覧・検索できるほか、
REST API で外部システムと連携できます。

待受ポート: **5057**（http://localhost:5057）

---

## 1. セットアップ

1. `.env` をメモ帳で開き、取得したキーを記入（取得方法は下記2章）
2. `start.bat` をダブルクリック（初回は仮想環境作成とライブラリ導入が走ります）
3. ブラウザで http://localhost:5057

データは同フォルダの `jan_db.sqlite3` に蓄積されます。

---

## 2. APIキーの取得（楽天は2026年2月の新方式）

### 楽天（無料）
楽天ウェブサービス https://webservice.rakuten.co.jp/ でアプリを作成し、以下2つを `.env` へ:

- **アプリケーションID（UUID形式）** → `RAKUTEN_APP_ID`
- **アクセスキー（`pk_` で始まる）** → `RAKUTEN_ACCESS_KEY` ※新APIで必須

アプリ作成時の設定:
- アプリケーションタイプ: Webアプリケーション
- APIアクセススコープ: **楽天市場API** にチェック
- 許可されたWebサイト: 実在ドメインが必要（`localhost`は不可）。会社ドメイン等を登録し、
  同じURLを `.env` の `APP_PUBLIC_URL` にも設定（Origin/Refererとして送信され照合されます）

> 新APIはエンドポイントが `openapi.rakuten.co.jp/ichibams/api` に変わり、
> `accessKey` が必須・Origin/Refererの照合があります。本アプリは対応済みです。

### Yahoo!ショッピング（無料）
https://e.developer.yahoo.co.jp/ でアプリ登録し、Client ID を `YAHOO_APP_ID` に設定。

### Amazon（審査あり・後回し可）
アソシエイト審査通過後、PA-API v5 のキーを `AMAZON_*` に設定。

---

## 3. JANコードの一括取り込み（初期データ作成）

楽天/YahooのAPIは **JANコードを項目として返しません**（説明文に埋め込まれている場合がある程度）。
そこで本ツールは「GS1事業者コードからJAN候補を総当たり生成 → 各候補をAPIで検索 → 実在した
商品だけ蓄積」という方式を採ります。`bulk_import.py` がそれを行います。

```bash
# 例: 企業プレフィックス 4912345 配下のアイテム番号 0〜999 を試す
python bulk_import.py --base 4912345 --start 0 --end 1000

# まず少数で動作確認
python bulk_import.py --base 4912345 --limit 50
```

主なオプション:
- `--base`  先頭桁（GS1事業者コード等。残り桁を連番で自動補完しチェックディジットを付与）
- `--start` / `--end` アイテム番号の範囲（end は含まない）
- `--limit` 実際に問い合わせる最大件数
- `--delay` 1候補ごとの待機秒（既定1.0。楽天の負荷制限に配慮）

特徴:
- 検索済みJANは記録され、**中断しても再実行で続きから再開**します
- 実在した商品のみ `products` / `offers` に保存（=画面にそのまま並びます）

注意: 総当たりのため候補が多いと時間がかかります（1秒/件なら1万件で約3時間）。
対象メーカーのGS1事業者コードに絞るほど効率的です。日本の国コードは 45 / 49 です。
JANが取れない商品も多く、完全な網羅はできない点をご理解ください。

---

## 4. 画面の使い方

- 左の枠（JANコード）に番号を入れて「登録/更新」→ その1件を取得・蓄積
- 右の枠は、蓄積済み一覧の絞り込み検索（新規取得はしない）
- 「CSVエクスポート」で全件をCSV出力（Excelでそのまま開けます）

---

## 5. REST API（外部システム連携）

`APP_API_KEY` を設定すると、すべての `/api/*` で `X-API-KEY` ヘッダが必須になります。

| メソッド | パス | 説明 |
|---|---|---|
| GET    | `/api/products`            | 一覧（`?q=` で検索） |
| POST   | `/api/products`            | `{"jan":"..."}` を登録/更新 |
| GET    | `/api/products/<jan>`      | 1商品の詳細（全オファー付き） |
| PATCH  | `/api/products/<jan>`      | `name` / `note` を更新 |
| DELETE | `/api/products/<jan>`      | 削除 |
| POST   | `/api/products/<jan>/refresh` | 価格を再取得 |
| GET    | `/api/search?jan=...`      | 保存せずライブ検索のみ |
| GET    | `/export.csv`             | CSVダウンロード |

---

## 6. ファイル構成

```
jancode-system/
├─ app.py            Flask本体（画面 + REST API + DB）
├─ apis.py           楽天/Yahoo/Amazon APIクライアント
├─ jan.py            JAN(EAN-13)生成・検証ユーティリティ
├─ bulk_import.py    JAN候補を総当たり生成して一括取り込みするCLI
├─ templates/index.html  画面
├─ requirements.txt
├─ .env              設定（キーを記入。Gitに上げない）
├─ .env.example      設定見本
├─ Procfile          PaaSデプロイ用
├─ start.bat         Windows起動用
└─ README.md
```

## 注意
- 各APIの利用規約・レート制限・商用利用条件を順守してください。
- 個人/自社で利用可能な範囲のAPIを最大限活用する構成です。完全な網羅性は保証されません。
