# GUI・ユーザーアプリ・運営アプリの分離

## 採用構成

- Server: Python + FastAPI
- User App: Dart + Flutter
- Operator App: Dart + Flutter（User Appとは別プロジェクト）

```text
clients/user_app/       ← EXE / APK / Web
          │
          │ User API
          ▼
src/fx_channel/         ← Python/FastAPI Server
          ▲
          │ Operator API
          │
clients/operator_app/   ← 運営用アプリ
```

## User App内部

```text
Frontend
   ↓
Application Service
   ↓
Gateway interface
   ↓
HTTP implementation
   ↓
User API
```

デフォルトFrontendは `lib/frontends/jp_soft_pop/`。

GUI差し替え時にサーバーロジックは変更しません。

別GUIを追加する場合は `lib/frontends/` に実装し、`main.dart` のFrontend registryへ登録します。

ビルド時の切替例：

```bash
--dart-define=FX_CHANNEL_USER_FRONTEND=jp_soft_pop
```

## User Appがしてはいけないこと

- FX損益計算の正本を持つ
- ガチャ抽選を行う
- スキル結果を確定する
- 相場を生成する
- Operator APIを呼ぶ
- Operator Tokenを持つ

表示上の一時計算は可能ですが、最終結果は常にサーバーを正とします。

## Operator App

`clients/operator_app/` はユーザーアプリと別プロジェクトです。

- User APK/EXEへ運営コードを混ぜない
- Tokenは実行時入力
- Operator APIだけを利用
- UIは一覧性、監査性、誤操作防止優先

## Web版

User Appと同じFlutterコードからWebビルドします。

サーバーバンドルの `web-user/` へ置くとFastAPIが `/play/` へ静的配信できます。

Web版は追加経路であり、Windows EXE / Android APKを置き換えるものではありません。
