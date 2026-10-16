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
