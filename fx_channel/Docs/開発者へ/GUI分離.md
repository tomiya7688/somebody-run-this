# GUI・ユーザーアプリ・運営アプリの分離

fx_channel は「GUIと処理を分ける」だけではなく、**ユーザー用アプリと運営用アプリ自体も別物**として扱います。

## 3プロセス

```text
┌────────────────────┐
│ fx-channel-user    │
│ User Frontend      │
└─────────┬──────────┘
          │ User API only
          ▼
┌────────────────────┐
│ fx-channel-server  │
│ Backend Runtime    │
│ Market / Gacha /   │
│ Skill / DB / etc.  │
└─────────┬──────────┘
          │ Operator API only
          ▼
┌────────────────────┐
│ fx-channel-operator│
│ Operator Frontend  │
└────────────────────┘
```

### Server

`server_main.py` が起動点です。

サーバーだけが次へ直接アクセスします。

- `operator.yaml`
- PriceProvider
- キャラクター/スキル/ガチャ定義
- DB
- 外部API
- 運営設定

### User App

`user_main.py` が起動点です。

User Appは、

- `UserApplicationPort`
- User API

だけを利用します。

**OperatorApplicationPort、operator.yaml、PriceProvider、DBへアクセスさせません。**

組み込みGUI：

```text
frontends/user/
└─ jp_soft_pop.py
```

### Operator App

`operator_main.py` が起動点です。

Operator Appは、

- `OperatorApplicationPort`
- 認証済みOperator API

だけを利用します。

組み込みGUI：

```text
frontends/operator/
└─ control_panel.py
```

ユーザー用の華やかなソシャゲUIを運営画面へ流用する必要はありません。

## GUIの責務

どちらのGUIにもゲームロジックを書きません。

GUIがしてよいこと：

- 表示
- 入力受付
- 自分専用のApplication Portを呼ぶ
- DTOを描画する

GUIがしてはいけないこと：

- 損益計算
- 注文成立判定
- ガチャ抽選
- スキル処理
- 相場生成
- PriceProviderへの直接アクセス
- DBへの直接アクセス
- 反対側アプリのPortをimportする

## GUI差し替え

ユーザーGUI：

```yaml
frontend:
  entrypoint: "fx_channel.frontends.user.jp_soft_pop:Frontend"
  options:
    theme: "jp_soft_pop"
```

運営GUI：

```yaml
frontend:
  entrypoint: "fx_channel.frontends.operator.control_panel:Frontend"
  options:
    theme: "operator_control_panel"
```

それぞれ別々に差し替え可能です。

## デフォルトユーザーGUI

`jp_soft_pop` は、

> 日本のスマホソシャゲ風の親しみやすさ + 見やすいFX情報UI + 少しポップ

を基準にします。

- 白〜淡いグレー主体
- 水色・ピンク・黄色・ミントをアクセント
- 角丸カード
- キャラを前面に出す
- ホーム/キャラ/ガチャはポップ
- 取引画面は数字とチャートの可読性優先
- スマホファースト

## 運営GUI

運営画面は別目的なので、可読性・一覧性・事故防止を優先します。

- サーバー状態
- 相場モード
- API状態
- キャラ/スキル/ガチャ登録状況
- シーズン状態
- プレイヤー管理
- ログ/監査

などを扱う想定です。

## アーキテクチャ検証

```bash
python -m fx_channel.architecture_validate
```

組み込みUser Frontendは `fx_channel.user_frontend_api` だけ、Operator Frontendは `fx_channel.operator_frontend_api` だけに依存することを検査します。

**ユーザーアプリと運営アプリを再び1つのApplicationPortへ統合する変更は行わない方針です。**
