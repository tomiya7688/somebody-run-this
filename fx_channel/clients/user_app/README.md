# fx_channel User App

Flutter製のユーザー用アプリです。

同じコードから以下を生成します。

- Windows 10+ x64: EXE
- Android 9.0+ arm64-v8a: APK
- Web: Flutter Web

## 初回だけプラットフォーム雛形を生成

リポジトリではGUI/アプリコードを管理し、Flutterのホスト雛形はCIでも再生成可能にします。

```bash
flutter create . \
  --platforms=android,windows,web \
  --org io.github.tomiya7688 \
  --project-name fx_channel_user
```

生成後、Androidのminimum SDKは **API 28** に固定してください。

## Windows EXE

```powershell
flutter build windows --release \
  --dart-define=FX_CHANNEL_SERVER_URL=https://example.com
```

成果物のWindows Runnerに `.exe` が生成されます。

## Android APK

```bash
flutter build apk --release \
  --target-platform android-arm64 \
  --dart-define=FX_CHANNEL_SERVER_URL=https://example.com
```

正式配布時はAndroid署名設定を行います。

## Web

同一GUIをWebでも利用できます。

```bash
flutter build web --release \
  --base-href=/play/ \
  --dart-define=FX_CHANNEL_SERVER_URL=
```

ビルドされた `build/web/` をサーバーバンドルの `web-user/` に入れると、FastAPIサーバーが `/play/` で配信できます。

## GUI差し替え

`lib/frontends/` に別Frontendを追加し、`main.dart` のregistryへ登録します。

ビルド時：

```bash
--dart-define=FX_CHANNEL_USER_FRONTEND=jp_soft_pop
```

ゲーム処理はサーバー側なので、Frontend交換でFXロジックを書き換える必要はありません。
