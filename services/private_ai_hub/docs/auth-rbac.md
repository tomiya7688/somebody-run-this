# Authentication and RBAC

## 目的

Private AI Hubの認証・認可は、認証Provider固有情報とアプリケーションUserを分離する。

v1ではlocal accountを実装し、将来OIDC / LDAP / SAML等を同じProvider境界へ追加する。

## Domain boundary

`User` は以下のようなアプリケーション主体だけを持つ。

- user id
- organization id
- username
- display name
- enabled

password hash、salt、外部IdP token等はUser domainへ持ち込まない。

Providerは認証成功後にdomain `User` を返す。

## Local authentication

local passwordはPython標準ライブラリの `hashlib.scrypt` を使う。

- per-user random salt
- password hashだけを保存
- scrypt parametersもcredential recordへ保存
- login時は保存パラメータを安全範囲検証
- 生passwordは保存しない

初期管理者はコマンドラインから作成する。

```bash
PYTHONPATH=src python -m private_ai_hub \
  --config config.example.toml \
  --create-admin \
  --organization-id default \
  --organization-name "Example Company" \
  --username admin
```

passwordは引数に渡さず `getpass` で入力する。

## Sessions

login成功時にランダムBearer tokenを発行する。

DBにはtoken生値ではなくSHA-256 digestだけを保存する。

- expiry
- revoke current session
- revoke all sessions
- disabled userのsessionは即時無効
- RBAC permission/group/roleはsession作成時に固定せず、request認証ごとに現在値を再取得

このためgroup/role変更は既存sessionにも次requestから反映される。

## Built-in roles

### user

- `chat.use`

### admin

- `chat.use`
- `admin.manage`
- `user.manage`
- `policy.read`
- `policy.write`
- `project.manage`
- `audit.security.read`

**adminには `audit.conversation.read` を含めない。**

### compliance-auditor

- `audit.conversation.read`

Conversation Audit本文を保存・閲覧する場合も、通常admin権限とは分離する。

## Personal content

個人Chat HistoryやUser Memoryの所有権はRBACのadmin権限とは別に扱う。

admin roleだけを理由に他ユーザーの個人Chat/User Memory本文を取得できるAPIは作らない。

Conversation Auditを有効化した組織では、通常データとは別store/別権限の監査経路を使う。

## HTTP bootstrap API

現在の最小API:

- `POST /v1/auth/login`
- `POST /v1/auth/logout`
- `POST /v1/auth/logout-all`
- `GET /v1/me`
- `GET /v1/admin/ping`

Bearer tokenを使用し、cookie sessionには依存しない。

login bodyは最大16KiB。
loginにはIP単位の最小レート制限を適用する。
より一般的な階層Rate Limitは #43 で実装する。

## Network

bootstrap HTTP serverは既定 `127.0.0.1` bindである。

公開/社内LAN配置ではTLS reverse proxyを前段に置くことを前提とし、平文HTTPを信頼できないネットワークへ直接公開しない。

## Policy integration

Authenticated `Principal` は以下を持つ。

- user
- permissions
- current group IDs
- current role IDs

後続のeffective policy APIは、このPrincipalからOrganization / Group-Role / Project PolicyLayerを構築し、#22のPolicy Engineで評価する。
