# Audit

## 目的

Private AI HubはSecurity AuditとConversation Auditを分離する。

- **Security Audit**: 認証、認可拒否、管理変更、Extension/Model操作などのセキュリティイベント。
- **Conversation Audit**: chat/model/project/token等の会話監査イベントと、明示設定時のみprompt/response本文。

通常のChat HistoryやUser MemoryはAudit Storeとは別のデータ境界である。

## 既定値

```toml
[audit]
security_enabled = true
conversation_enabled = false
store_prompt_content = false
store_response_content = false
retention_days = 180
```

Conversation Audit本文はopt-inであり、既定では保存しない。

Conversation AuditをONにしても、`store_prompt_content` / `store_response_content` を個別にONにしなければ本文は保存されない。

## 権限

### Security Audit

`audit.security.read` が必要。

built-in `admin` roleはこの権限を持つ。

### Conversation Audit

`audit.conversation.read` が必要。

built-in `admin` roleにはこの権限を付与しない。
built-in `compliance-auditor` roleを別に用意する。

したがって「管理者だから他ユーザーの会話本文を読める」という設計にはしない。

## 保存分離

SQLiteではSecurity AuditとConversation Auditを別テーブルに保存する。

- `security_audit_events`
- `conversation_audit_events`

Conversation Audit本文は通常Chat HistoryやUser Memoryのテーブルへ複製しない。

将来別DB/外部監査sinkへ分離しても、AuditService境界を維持する。

## Secret redaction

metadataは保存前に再帰的に検査し、次のようなキーをマスクする。

- password / passwd
- secret / client_secret
- token / access_token / refresh_token
- authorization
- api_key
- cookie
- credential
- private_key

prompt/response本文は一般的な文字列からsecretを正確に判定できないため、本文保存を明示的なopt-inにすることで制御する。

Security Audit eventを作るコードはpasswordやBearer token自体をmetadataへ渡してはいけない。

## Tamper evidence

各Organization・各Audit streamごとにSHA-256 hash chainを作る。

```text
anchor/zero
   |
event 1 hash
   |
event 2 hash
   |
event 3 hash
```

各event hashは前event hashとevent payloadから計算する。

`verify_chain()` で、途中のevent内容・順序・hashの単純改ざんを検出できる。

### 限界

これは**改ざん耐性のある外部署名やWORM storageの代替ではない**。

DB全体を自由に書き換えられる攻撃者がevent・head・anchorをすべて再計算することまでは防げない。
より強い要件では、将来外部immutable audit sinkや署名/attestationを追加する。

## Retention

`retention_days = 0` は自動削除なし。

1以上では、AuditServiceが保持期限を超えた**連続した古いprefix**を削除する。

削除直前event hashを `audit_chain_anchors` に保存し、残ったevent chainを引き続き検証できるようにする。

backdated event等で順序が混在する場合、hash chainを壊さないため途中だけを飛び越えて削除しない。

## Admin changes

`AuditService.record_admin_change()` を、今後の管理APIから共通利用する。

記録する内容:

- actor user
- change type
- target
- before / after（secret redaction後）
- timestamp

Audit設定自体を管理APIから変更できるようにする場合も、この経路を通す。

## HTTP API

- `GET /v1/admin/audit/security?limit=100`
- `GET /v1/admin/audit/conversation?limit=100`

それぞれ別permissionを要求する。

認可拒否自体もSecurity Auditへ記録する。

## Failure behavior

Security Auditが有効な状態で、login成功/失敗や認可拒否のSecurity Audit書込みに失敗した場合は、セキュリティイベントを無記録で通さないためrequestをfail-closedする。

logoutはsession無効化を優先する。logout後のaudit書込み失敗でsessionを復活させることはしない。
