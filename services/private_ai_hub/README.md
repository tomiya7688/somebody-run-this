# Private AI Hub

企業・組織が自社サーバー上で自社モデルまたはOSSモデルを運用し、ユーザーがPCから利用するセルフホストAI基盤です。

このディレクトリは現在 bootstrap 段階です。最初の実装では外部依存を追加せず、設定・永続化・migration・health/readiness・管理者ポリシーの基本型だけを実装しています。

## 現在の起動方法

Linux/macOS:

```bash
cd services/private_ai_hub
PYTHONPATH=src python -m private_ai_hub --config config.example.toml
```

PowerShell:

```powershell
cd services/private_ai_hub
$env:PYTHONPATH = "src"
python -m private_ai_hub --config config.example.toml
```

既定では `127.0.0.1:8787` で待ち受けます。

- `GET /healthz` — プロセスがHTTP応答可能か
- `GET /readyz` — SQLite schemaが現在のmigration targetまで適用済みか
- `GET /v1/info` — bootstrap service情報

## テスト

```bash
cd services/private_ai_hub
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 重要な設計原則

- 管理者ポリシーが最上位で、ユーザー設定はその上限を超えません。
- 推論Workerへ直接Internet accessを与えません。
- Model ImporterとExtension Hostは推論Workerと権限・network境界を分離します。
- 個人会話・User Memory・Agent Run等は `organization_id + user_id` を所有境界として扱います。
- Agent Appは通常チャットとは別アプリです。
- Agentの実行場所は Local Runner（ユーザーPC）と Managed Runner（会社管理Worker）を明確に分けます。

詳細は `docs/architecture.md` と `docs/agent-execution-modes.md` を参照してください。

## Policy Engine

階層Policy Engineは `src/private_ai_hub/policy_engine.py` にあります。

- Organization / Group-Role / Project policyをintersection
- User requestは管理者policyを広げない
- 未設定Featureはdefault disabled
- model/Extension等のchoiceはdefault deny
- 数値上限は最も厳しい範囲を適用
- runtime/model capabilityも上限として適用
- policy conflictはfail-closed
- effective decisionには理由とsource revisionを含める

詳細は `docs/policy-engine.md` を参照してください。

認証済みユーザー向けHTTP effective-policy endpointは、RBAC/認証 (#23) を実装した後に公開します。Policy判定ロジック自体はHTTPから独立させ、通常Chat、Agent App、管理UIのすべてから同じEngineを使います。

## 認証 / RBAC

v1の最小認証はlocal accountです。初期管理者はpasswordをコマンドライン引数へ載せず、対話入力で作成します。

```bash
PYTHONPATH=src python -m private_ai_hub \
  --config config.example.toml \
  --create-admin \
  --organization-id default \
  --organization-name "Example Company" \
  --username admin
```

最小API:

- `POST /v1/auth/login`
- `POST /v1/auth/logout`
- `POST /v1/auth/logout-all`
- `GET /v1/me`
- `GET /v1/admin/ping`

sessionはBearer tokenで、DBにはtokenのSHA-256 digestだけを保存します。

built-in `admin` roleはPolicy/User/Project/Security Audit管理権限を持ちますが、**Conversation Audit本文閲覧権限は持ちません**。本文監査は別の `compliance-auditor` roleへ分離します。

認証Provider固有のpassword/credentialはUser domainへ入れません。将来OIDC/LDAP/SAML等を追加しても同じUser/RBACを利用します。

詳細は `docs/auth-rbac.md` を参照してください。

## 監査

Security AuditとConversation Auditは分離しています。

既定値:

- Security Audit: ON
- Conversation Audit: OFF
- Prompt本文保存: OFF
- Response本文保存: OFF

`admin` はSecurity Auditを読めますが、Conversation Audit本文は読めません。
Conversation Audit本文には別の `compliance-auditor` 権限が必要です。

Security event metadataはpassword/token/API key等を保存前にマスクし、イベントはOrganization/stream単位のhash chainで改ざん検知できます。

詳細は `docs/audit.md` を参照してください。

## Network / Egress

既定network profileは `offline` です。

```toml
[network]
profile = "offline"
```

`restricted-egress` に変更しても全通信が許可されるわけではありません。Model ImporterやExtensionごとに専用 `EgressPolicy` とdomain/port/method allowlistが必要です。

Inference WorkerにはEgress Brokerを渡さず、Linuxではnetwork namespace/systemd `PrivateNetwork=yes`/container `--network none` 等でも直接Egressを遮断します。

Egress BrokerはDNS解決後のIPも検証し、loopback、link-local/metadata、multicast、reserved、未許可private networkを拒否します。redirect先も毎回再検証し、別originへAuthorization/Cookieを持ち越しません。

詳細は `docs/network-isolation.md` を参照してください。

## Inference Backend

共通契約は `src/private_ai_hub/inference.py`、最初の実backendは `src/private_ai_hub/vllm_backend.py` です。

初期runtimeは **vLLM 0.33.0のみ**をreview済みとして許可します。

- vLLMをPrivateAI processへimportしない
- Linux別process
- private Unix domain socketのみ
- Model Store内local pathのみ
- `--no-trust-remote-code`
- `--language-model-only`
- vLLM plugins無効
- Hub offline
- request/output logging無効
- `/usr/bin/unshare --net --` でWorker direct egressを禁止
- versionが0.33.0と完全一致しなければ起動拒否

vLLM APIをUser/Clientへ直接公開しません。Gateway内部から `/v1/models` と `/v1/chat/completions` だけをUnix socket越しに使います。

詳細:
- `docs/inference-backend.md`
- `docs/security/vllm-0.33.0-review-2026-11-04.md`

vLLM更新時はSecurity Rulesに従い、必ずその時点の最新Security Advisory等を再調査してください。

## Model Registry

モデルCatalogとユーザー利用許可は別管理です。

新しく登録・発見したモデルは自動許可されません。

ユーザーが使えるモデルは:

```text
enabled
∩ ready
∩ Organization allowlist
∩ Group / Project policy
```

です。

管理者が1モデルだけ許可すれば、ユーザー一覧にもその1モデルだけが出ます。Provider/runtimeが知っているmodel idを直接APIへ指定してもallowlistは回避できません。

Catalog/allowlist変更には `model.manage` が必要です。

詳細は `docs/model-registry.md` を参照してください。
