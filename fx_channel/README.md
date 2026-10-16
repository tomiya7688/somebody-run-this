# fx_channel

現金を掛けず、ゲーム内の仮想資産だけで遊ぶFXソーシャルゲームです。

相場は運営者が設定で切り替えられます。

- **REAL**: 外部の為替レートAPIから価格を取得する
- **SIMULATED**: ゲーム内で仮想相場を生成する

ゲームロジック側は価格の取得元を意識せず、共通の PriceProvider インターフェース経由で価格を利用します。

## 運営者へ

**サーバーを立てる前に、必ず [Docs/運営者へ/README.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/README.md) を読んでください。**

運営者が変更するべき設定は、原則として `config/operator.yaml` に集約します。

テンプレートは [config/operator.example.yaml](config/operator.example.yaml) です。

## 現在の最小実装

`market.mode` によって価格取得方法を切り替えられます。

```yaml
market:
  mode: simulated
```

または、

```yaml
market:
  mode: real
```

動作確認：

```bash
cd fx_channel
python -m venv .venv
# .venv を有効化
pip install -e .

cp config/operator.example.yaml config/operator.yaml
python -m fx_channel --config config/operator.yaml --ticks 3
```

## 基本方針

- 現金の入金機能を持たない
- ゲーム内通貨を現金へ換金する機能を持たない
- ゲーム内残高はゲームのスコアとして扱う
- 外部為替APIを使わなくても運営できる
- 相場生成部分を差し替え可能にする


## キャラクター・スキル

キャラクター、スキル、ガチャは `content/` 以下の YAML を追加して登録できます。

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

スキルには市場を書き換えるAPIを渡しません。
予測・分析系スキルは読み取り専用の相場情報から結果を返すだけで、将来の値動きを保証しません。

運営者向けの詳しい登録方法は [Docs/運営者へ/キャラとスキル.md](Docs/%E9%81%8B%E5%96%B6%E8%80%85%E3%81%B8/%E3%82%AD%E3%83%A3%E3%83%A9%E3%81%A8%E3%82%B9%E3%82%AD%E3%83%AB.md) にあります。


## GUI / Frontend の完全分離

GUIはゲーム処理から完全に分離します。

デフォルトGUIは **日本ソシャゲ風 + 少しポップ** な `jp_soft_pop` です。

GUI実装は `config/developer.yaml` で切り替えます。

```yaml
frontend:
  entrypoint: "fx_channel.frontends.jp_soft_pop:Frontend"
  options:
    theme: "jp_soft_pop"
    locale: "ja-JP"
```

別GUIへ交換する場合は、原則として `frontend.entrypoint` を変更するだけです。

```yaml
frontend:
  entrypoint: "my_fx_gui.frontend:Frontend"
```

GUIは `ApplicationPort` だけを利用し、相場取得・ガチャ抽選・スキル処理・DB等へ直接アクセスしません。

起動例：

```bash
cp config/developer.example.yaml config/developer.yaml
python -m fx_channel.gui_run \
  --operator config/operator.yaml \
  --developer config/developer.yaml \
  --content content
```

組み込みGUIが処理層へ直接依存していないかは、次で確認できます。

```bash
python -m fx_channel.architecture_validate
```

設計の詳細は [Docs/開発者へ/GUI分離.md](Docs/%E9%96%8B%E7%99%BA%E8%80%85%E3%81%B8/GUI%E5%88%86%E9%9B%A2.md) にあります。
