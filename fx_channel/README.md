# fx_channel

現金を掛けず、ゲーム内の仮想資産だけで遊ぶFXソーシャルゲームです。

相場は運営者が設定で切り替えられます。

- **REAL**: 外部の為替レートAPIから価格を取得
- **SIMULATED**: ゲーム内で仮想相場を生成

キャラクター・スキル・ガチャをデータ駆動で追加でき、スキルは相場を変更できません。予測系スキルは分析結果を返すだけで、将来の値動きを保証しません。


## 対応環境

ユーザー用アプリの正式ターゲット：

- **Windows 10以上 / x64**
- **Android 9.0以上 / arm64-v8a**

サーバーの正式ターゲット：

- **Linux x64** — Ubuntu Server / Debian等
- **Linux arm64** — Ubuntu Server ARM64 / Debian ARM64等
- **Windows x64** — Windows Server等

詳しくは [Docs/対応環境.md](Docs/%E5%AF%BE%E5%BF%9C%E7%92%B0%E5%A2%83.md) を参照してください。

サーバーはソースから環境構築する方式ではなく、ReleaseのOS/CPU別バンドルを展開して設定ファイルを置けば起動できる形を正式導線にします。

サーバースペック・帯域の目安と設置手順は [Docs/運営者へ/サーバー設置.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC%E8%A8%AD%E7%BD%AE.md) にあります。

## 起動構成

fx_channel は最初から **3つの別アプリ** として分けます。

```text
fx-channel-server
  ├─ User API ──────→ fx-channel-user
  └─ Operator API ──→ fx-channel-operator
```

### 1. Backend Server

唯一、`operator.yaml`・PriceProvider・コンテンツ定義・将来のDBへ直接アクセスするプロセスです。

```bash
fx-channel-server --operator config/operator.yaml --content content
```

### 2. User App

プレイヤーが使うアプリです。

- 日本ソシャゲ風 + 少しポップな `jp_soft_pop` がデフォルト
- User APIしか利用しない
- `operator.yaml` を読まない
- 運営API・運営トークンを持たない

```bash
fx-channel-user \
  --server http://127.0.0.1:8787 \
  --frontend config/user_frontend.yaml
```

### 3. Operator App

運営者専用アプリです。

- ユーザーGUIとは別パッケージ
- Operator APIしか利用しない
- Bearer Tokenが必要
- 相場モード・コンテンツ・稼働状態などの管理UIを置く

```bash
fx-channel-operator \
  --server http://127.0.0.1:8787 \
  --frontend config/operator_frontend.yaml
```

運営トークンは例として次の環境変数に設定します。

```bash
export FX_CHANNEL_OPERATOR_TOKEN="replace-with-a-long-random-secret"
```

## GUI差し替え

ユーザーGUIと運営GUIは、それぞれ独立して差し替えます。

ユーザー：

```yaml
frontend:
  entrypoint: "fx_channel.frontends.user.jp_soft_pop:Frontend"
```

運営：

```yaml
frontend:
  entrypoint: "fx_channel.frontends.operator.control_panel:Frontend"
```

外部パッケージのFrontendへ変更しても構いません。

## キャラクター・スキル・ガチャ

```text
content/
├─ characters/
├─ skills/
└─ gacha/
```

追加内容の検証：

```bash
python -m fx_channel.content_validate --content content
```

詳しくは [Docs/運営者へ/キャラとスキル.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/%E3%82%AD%E3%83%A3%E3%83%A9%E3%81%A8%E3%82%B9%E3%82%AD%E3%83%AB.md) を参照してください。

## アーキテクチャ検証

```bash
python -m fx_channel.architecture_validate
```

ユーザーGUIが運営用Portをimportしたり、GUIが相場・DB等の内部処理へ直接依存した場合に検出する方針です。

詳しくは [Docs/開発者へ/GUI分離.md](Docs/%E9%96%8B%E7%99%BA%E8%80%85%E3%81%B8/GUI%E5%88%86%E9%9B%A2.md) を参照してください。

## 運営者へ

運営設定は [config/operator.example.yaml](config/operator.example.yaml) をコピーして `config/operator.yaml` を作成します。

**最初に [Docs/運営者へ/README.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/README.md) を読んでください。**
