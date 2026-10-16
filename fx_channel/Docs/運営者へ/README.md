# 🚨 運営者へ — まずここを読んでください

このディレクトリは **fx_channel を実際に運営する人のための説明書** です。


**一般的なVPS / Ubuntu Server / Debian / Windows Serverへ置くだけで動かす手順は [サーバー設置.md](%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC%E8%A8%AD%E7%BD%AE.md) を先に参照してください。**

ゲームを動かす前に、まず `fx_channel/config/operator.example.yaml` をコピーして、

```
fx_channel/config/operator.yaml
```

を作成してください。

**運営者が日常的に変更する設定は、原則としてこの `operator.yaml` に集約します。**
ゲーム本体のコードを書き換えないと変更できない運営設定を増やさない方針です。

---

# 起動するものは3つです

fx_channel は、ユーザー用アプリと運営用アプリを同じ実行ファイルにしません。

```text
fx-channel-server    バックエンド
fx-channel-user      プレイヤー用アプリ
fx-channel-operator  運営者用アプリ
```

## 1. 運営トークンを設定

```bash
export FX_CHANNEL_OPERATOR_TOKEN="十分に長いランダムな値"
```

トークンそのものは `operator.yaml` やGitへ保存しません。

## 2. サーバーを起動

```bash
fx-channel-server --operator config/operator.yaml --content content
```

デフォルトは `127.0.0.1:8787` です。

外部公開する場合は、TLS・リバースプロキシ・ファイアウォール等を運営環境に合わせて構成してください。

## 3. 運営用アプリを起動

```bash
cp config/operator_frontend.example.yaml config/operator_frontend.yaml

fx-channel-operator \
  --server http://127.0.0.1:8787 \
  --frontend config/operator_frontend.yaml
```

運営用アプリはOperator APIのみを利用します。

**プレイヤー用アプリとは起動ポイントもGUIもApplication Portも別です。**

---

# まず決めること：相場をどこから持ってくるか

最重要設定はこれです。

```yaml
market:
  mode: simulated
```

`mode` は次の2種類から選びます。

## 1. simulated — 仮想相場

```yaml
market:
  mode: simulated
```

外部の為替APIを使わず、fx_channel自身が価格を生成します。

**API契約もAPI料金も不要なので、特に理由がなければ最初はこちらを推奨します。**

主に変更する項目：

```yaml
market:
  mode: simulated

  simulated:
    seed: null
    tick_seconds: 5
    default_start_price: 100.0
    base_volatility: 0.001
    drift: 0.0
```

### seed

同じ相場を再現したい場合に指定します。

`null` の場合は起動ごとに異なる相場になります。

### tick_seconds

何秒ごとに価格を更新するか。

### default_start_price

初めて登場する通貨ペアの開始価格です。

架空通貨を追加した場合も、個別の初期値指定がない限りこの値から始まります。

### base_volatility

基本的な値動きの大きさ。

大きくすると激しい相場、小さくすると穏やかな相場になります。

### drift

相場全体の長期的な上昇・下降傾向。

通常は `0.0` を推奨します。

---

## 2. real — 実際の為替レート

```yaml
market:
  mode: real
```

外部の為替レートAPIから値段を取得します。

主に変更する項目：

```yaml
market:
  mode: real

  real:
    provider: generic_http
    endpoint: "https://example.com/api/rates"
    api_key_env: "FX_CHANNEL_API_KEY"
    api_key_header: "X-API-Key"
    poll_seconds: 10
    timeout_seconds: 5
    on_error: keep_last
```

### provider

利用する価格取得アダプター。

初期実装は `generic_http` です。
必要なら特定サービス用のアダプターを追加できます。

### generic_http が期待するレスポンス

次のどちらかのJSONを受け取れるAPIを想定しています。

```json
{
  "rates": {
    "USDJPY": 150.1,
    "EURUSD": 1.08
  }
}
```

または、

```json
{
  "USDJPY": 150.1,
  "EURUSD": 1.08
}
```

リクエスト時には `symbols=USDJPY,EURUSD` のようなクエリを付与します。

利用したいAPIの形式が異なる場合は、そのAPI向けのアダプターを追加してください。

### endpoint

為替レートを取得するAPIのURL。

### api_key_env

**APIキーそのものを書いてはいけません。**

ここにはAPIキーを保存している環境変数名を書きます。

例：

```yaml
api_key_env: "FX_CHANNEL_API_KEY"
```

実際の秘密情報はサーバー側の環境変数へ設定してください。

### api_key_header

APIキーを送るHTTPヘッダー名です。

初期値は：

```yaml
api_key_header: "X-API-Key"
```

利用するAPIに合わせて変更してください。

### poll_seconds

外部APIへ問い合わせる間隔。

利用するAPIのレート制限と料金体系を必ず確認してください。

### on_error

外部APIが落ちたときの挙動です。

- `keep_last` — 最後に取得できた価格を維持
- `pause_market` — エラーとして扱い、市場を止める
- `fallback_simulated` — 仮想相場へ退避

`keep_last` は一度も価格取得に成功していない状態では維持できる価格がないため、市場エラーになります。

---

# 取引対象

```yaml
symbols:
  - USDJPY
  - EURUSD
  - GBPUSD
```

運営するゲームで使う通貨ペアをここに並べます。

仮想相場モードの場合、実在通貨である必要はありません。

例えば：

```yaml
symbols:
  - DORUN_EN
  - EUROA_DORUN
```

のような架空通貨でも運営できます。

---

# プレイヤー初期設定

```yaml
game:
  starting_balance: 1000000
  max_leverage: 25
  allow_negative_balance: false
```

### starting_balance

新規プレイヤーへ配布するゲーム内資金。

**これは現金ではありません。**

### max_leverage

ゲーム上許可する最大レバレッジ。

### allow_negative_balance

残高をマイナスにできるか。

通常は `false` を推奨します。

---

# シーズン

```yaml
season:
  enabled: true
  duration_days: 7
  reset_balance: true
  keep_achievements: true
```

ランキング競争を定期的にリセットするための設定です。

長期運営で一部プレイヤーだけが資産を増やし続ける状態を防ぐため、シーズン制を基本とします。

---

# ⚠️ 現金・換金について

fx_channel の標準実装は、

**「現金を賭けないFXゲーム」**

として設計します。

標準構成では以下を実装しません。

- 現金の入金
- 現金の出金
- ゲーム内通貨の買い取り
- ゲーム内通貨から法定通貨・暗号資産等への換金
- ゲーム内利益に応じた現金報酬

運営者が広告や外見アイテム等によって収益化することと、ゲーム内残高を現金化することは分けて考えてください。

---

# 運営設定を追加するときのルール

新しい運営向け機能を追加する場合は、なるべく次の順序にします。

1. `config/operator.yaml` から変更できるようにする
2. このディレクトリに説明を書く
3. デフォルト値だけで安全に起動できるようにする
4. APIキーなどの秘密情報は設定ファイルへ直接書かせない
5. ソースコードを書き換えないと運営できない仕様を避ける

**「誰か運営してくれ」がこのリポジトリの目的なので、運営者がコードを読まなくても立ち上げられる状態を目標にします。**


---

# キャラクター・スキル・ガチャ

キャラクター、スキル、ガチャ排出テーブルは YAML で追加できます。

詳しくは [キャラとスキル.md](%E3%82%AD%E3%83%A3%E3%83%A9%E3%81%A8%E3%82%B9%E3%82%AD%E3%83%AB.md) を読んでください。

追加後は次のコマンドで参照切れや設定ミスを確認できます。

```bash
cd fx_channel
python -m fx_channel.content_validate --content content
```

キャラクターやスキルは市場価格を変更できません。
スキルには読み取り専用の `MarketSnapshot` だけを渡し、`PriceProvider` や仮想相場エンジンそのものは渡さない設計です。

先読み・予測系スキルも同様に、現在・過去データや公開情報を分析して予測結果を返すだけです。高度な推論を利用しても、予測が当たることは保証しません。
