# fx_channel

現金を掛けず、ゲーム内の仮想資産だけで遊ぶFXソーシャルゲームです。

- REAL: 実際の為替レートAPI
- SIMULATED: サーバー内仮想相場
- キャラ / スキル / ガチャをデータ駆動で追加
- スキルは相場そのものを変更しない
- 予測スキルは予測であり的中保証なし

## 現在動くもの

- REAL / SIMULATED価格Provider
- BUY / SELL、証拠金、レバレッジ、含み損益、決済
- SQLiteによるサーバー再起動後の状態復元
- 署名付き匿名User Session
- キャラ所持
- ガチャ、排出率表示、1回/10回抽選
- 運営アプリから通貨付与
- 読み取り専用相場データを使うスキル
- 現在評価額ランキング
- 自動シーズン切替、残高/ランキングリセット、手動シーズン進行
- Operator AppからDB + User Session鍵のバックアップ
- Windows EXE / Android APK / Web / Server BundleのCI

## 技術構成

### Server

**Python + FastAPI + Uvicorn**

サーバーだけが相場、FX処理、ガチャ、スキル、DB、運営設定を扱います。

### User App

**Dart + Flutter**

同じユーザーアプリコードから：

- Windows 10+ x64 → **EXE**
- Android 9.0+ arm64-v8a → **APK**
- Web → **Flutter Web**

を生成します。

Windows版は `fx_channel_user.exe` を含むZIPとして配布します。

Web版は任意でサーバーに同梱し、`/play/` から遊べるようにできます。

### Operator App

**Dart + Flutter**

ユーザー用とは別プロジェクト・別成果物です。

詳しくは [Docs/技術スタック.md](Docs/%E6%8A%80%E8%A1%93%E3%82%B9%E3%82%BF%E3%83%83%E3%82%AF.md) を参照してください。

## ディレクトリ

```text
fx_channel/
├─ clients/
│  ├─ user_app/       # Flutter: EXE / APK / Web
│  └─ operator_app/   # Flutter: 運営用
├─ src/fx_channel/    # Python/FastAPI server
├─ content/           # キャラ / スキル / ガチャ
├─ config/            # 運営設定
└─ Docs/
```

## 対応環境

ユーザー：

- Windows 10以上 x64
- Android 9.0以上 arm64-v8a
- Webブラウザ

サーバー：

- Ubuntu Server / Debian等 Linux x64
- Linux arm64
- Windows Server x64

[対応環境の詳細](Docs/%E5%AF%BE%E5%BF%9C%E7%92%B0%E5%A2%83.md)

## サーバー起動

開発時：

```bash
fx-channel-server --operator config/operator.yaml --content content
```

正式運営ではReleaseの自己完結バンドルを展開して起動します。

[サーバー設置手順](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC%E8%A8%AD%E7%BD%AE.md)

## Web版

Flutter User AppをWebビルドして `web-user/` へ配置すると、FastAPIサーバーが `/play/` で配信します。

Web版は便利な追加経路で、APK/EXEを置き換えるものではありません。

## キャラクター・スキル・ガチャ

```text
content/
├─ characters/
├─ skills/
└─ gacha/
```

運営者向け登録方法は [Docs/運営者へ/キャラとスキル.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/%E3%82%AD%E3%83%A3%E3%83%A9%E3%81%A8%E3%82%B9%E3%82%AD%E3%83%AB.md) を参照してください。
