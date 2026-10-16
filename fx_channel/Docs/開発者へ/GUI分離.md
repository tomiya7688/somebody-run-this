# GUIと処理層の完全分離

fx_channel では **GUIとゲーム処理を完全に分離する** ことを基本設計とします。

デフォルトGUIは、日本のスマホソシャゲ風をベースにした少しポップな `jp_soft_pop` です。

ただし、`jp_soft_pop` はゲーム本体ではありません。

GUIを削除・交換しても、

- FX取引
- 相場取得
- キャラクター
- スキル
- ガチャ
- プレイヤー状態
- シーズン
- ランキング

などの処理が壊れない構造にします。

---

# 原則

## GUIにゲームロジックを書かない

GUI側が行うのは次だけです。

- 表示
- 入力受付
- Application Port の呼び出し
- Application Port から返されたDTOの描画

GUI側に、

- 損益計算
- 注文成立判定
- ガチャ抽選
- スキル計算
- 相場生成
- PriceProviderアクセス
- DBへの直接アクセス

を書いてはいけません。

---

# 依存方向

```text
┌─────────────────────────────┐
│        GUI / Frontend       │
│  jp_soft_pop / custom GUI   │
└──────────────┬──────────────┘
               │
               │ ApplicationPort のみ
               ▼
┌─────────────────────────────┐
│      Application Layer      │
│ use case / command / query  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│       Domain / Services     │
│ FX / Skill / Gacha / Season│
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Infrastructure / Providers  │
│ Market / DB / External API  │
└─────────────────────────────┘
```

**下の層からGUIをimportしてはいけません。**

---

# GUIの切り替え

`config/developer.yaml` の `frontend.entrypoint` を変更します。

デフォルト：

```yaml
frontend:
  entrypoint: "fx_channel.frontends.jp_soft_pop:Frontend"
```

別GUI：

```yaml
frontend:
  entrypoint: "my_fx_gui.frontend:Frontend"
```

外部PythonパッケージとしてGUIを実装しても構いません。

fx_channel本体へforkを入れなくてもGUI交換できることを目標にします。

---

# GUI実装が満たすもの

GUIは `fx_channel.frontend_api.Frontend` と同じインターフェースを満たします。

概念上：

```python
class Frontend:
    def run(self, app, options):
        ...
```

GUIへ渡される `app` は `ApplicationPort` です。

GUIは内部のMarketProviderやDBを受け取りません。

---

# DTOを境界にする

GUIへDomain Objectを直接渡さず、画面表示用DTOを返します。

例：

```text
MarketProvider
      ↓
 Domain
      ↓
 Application
      ↓
 MarketView DTO
      ↓
 GUI
```

これにより、GUI側の都合でゲーム処理の内部表現が汚染されることを防ぎます。

---

# デフォルトGUI: jp_soft_pop

デザイン方針：

> 日本のスマホソシャゲ風の親しみやすさに、見やすいFX情報UIを合わせた、少しポップなデザイン。

基本：

- 白〜淡いグレー主体
- 水色・ピンク・黄色・ミント等をアクセント
- 角丸カード
- 柔らかい影
- キャラを前面に出す
- ホーム・キャラ・ガチャはポップ
- 取引画面は情報の読みやすさ優先
- スマホファースト
- FX数値は装飾より可読性を優先
- 誤タップしやすい取引操作は大きく明確にする

---

# テーマとGUI実装は別概念

`frontend.entrypoint` は **GUIそのものの実装** です。

`frontend.options.theme` は **そのGUI内の見た目テーマ** です。

たとえば将来的に、

```yaml
frontend:
  entrypoint: "fx_channel.frontends.web:Frontend"
  options:
    theme: "dark_terminal"
```

のように、同じWeb GUIで見た目だけ変更することもできます。

---

# 新GUIを作る開発者へ

新GUIは原則として、

1. `Frontend.run(app, options)` を実装する
2. `ApplicationPort` だけを使う
3. fx_channel内部モジュールへ直接アクセスしない
4. `developer.yaml` の entrypoint を変更する

だけで動かせることを目標にします。

**GUI交換のためにゲームロジックを書き換える必要がある状態は設計上の不具合とみなします。**
