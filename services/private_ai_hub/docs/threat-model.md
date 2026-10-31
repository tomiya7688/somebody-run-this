# Private AI Hub threat model

## Scope

この文書はPrivate AI Hub、Model Importer、Extension Host、Inference Worker、およびAgent AppのLocal/Managed Runnerとの境界を対象とする。

## Security invariants

1. 管理者policyをuser/project/model/extension設定で広げられない。
2. Inference Workerは直接Internetへ出ない。
3. 個人会話・User Memory・個人Agent Runはuser scopeを失わない。
4. Project dataはproject membershipなしに参照できない。
5. Model Importerのdownload権限をInference Workerが再利用できない。
6. Extensionはmanifest/policyを越える権限を持たない。
7. Local Runnerはbindingされた本人ユーザー以外から利用できない。
8. Managed Runnerは管理者の普段使い端末ではなくAgent専用環境とする。

## Threats and required controls

| Threat | Example | Required control |
| --- | --- | --- |
| Direct prompt injection | userがsystem/admin instructionの上書きを要求 | Policy判定をmodel出力から分離し、server側で強制 |
| Indirect prompt injection | Web/文書/Tool resultに操作指示が埋め込まれる | 外部contentをuntrustedとして扱い、Tool実行前に再認可 |
| SSRF | Extensionがlocalhost/private IPへアクセス | Egress Broker、private/link-local/metadata endpoint deny |
| Malicious model repository | custom codeや実行ファイルをmodelとして配布 | quarantine、allowlist形式、custom code default deny、immutable revision |
| Malicious extension | 過剰なnetwork/filesystem権限を要求 | admin-only install、permission manifest、isolated Extension Host |
| Cross-user data leak | User AがUser Bのchat/memory IDを指定 | organization_id + user_id scopeをDAL/index/cache/jobで強制 |
| Cross-project data leak | Project AからProject Bのmemory/fileへアクセス | organization_id + project_id scope + membership check |
| Credential exfiltration | model/toolがAPI keyをpromptへ混入 | credentialをmodel contextへ渡さず、Extension/Worker secret storeで保持 |
| Admin credential compromise | admin tokenが盗まれる | RBAC、session revoke、security audit、high-risk action confirmation |
| Audit leakage | prompt本文を通常adminが横断閲覧 | Conversation Auditを別store/別roleとし、本文保存はopt-in |
| Model runtime compromise | 推論runtimeからhost/networkへ脱出 | Worker isolation、direct egress deny、最小volume/secret |
| Capability escalation | Agentが出力文でTool権限を獲得 | capabilityはPolicy Engineのみが決定し、modelはgrant不能 |
| Excessive resource use | 無限generation/Agent loop | rate/concurrency/quota、max steps/time/tool calls |
| Runner impersonation | User AがUser BのLocal Runnerを選択 | user/session binding、runner registration ownership |
| Workspace escape | Agentが../やsymlinkで外へ出る | workspace root、path normalization、symlink escape防止 |
| Replay/double side effect | retryで同じwrite/deleteを再実行 | idempotency key、approval binding、checkpoint semantics |

## Representative feature policy matrix

| Admin mode | User request | Effective |
| --- | --- | --- |
| disabled | off | off |
| disabled | on | off |
| optional | off | off |
| optional | on | on |
| required | off | on |
| required | on | on |

ユーザーが直接APIを呼んでも同じ結果でなければならない。

## Numeric limit example

管理者が `max_concurrent_generations = 4` とした場合:

- user request 2 -> 2
- user request 4 -> 4
- user request 8 -> clamp 4 または明示reject
- policy上限自体の変更 -> admin権限が必要

clamp/rejectのどちらを使うかは設定種別ごとに固定し、クライアント任せにしない。

## Model allowlist

Provider/runtimeが発見したmodel catalogは**利用許可を意味しない**。

effective model set:

`provider catalog ∩ admin allowlist ∩ group/project policy ∩ model health/capability`

新規検出modelはdefault denyとする。

## Agent execution target

Local RunnerとManaged Runnerは別trust boundaryである。

- Local: user identityにbinding。本人PCの許可resourceだけ。
- Managed: company-controlled dedicated worker。user PCへ暗黙アクセスしない。
- Hybrid: data transferを独立capabilityとして扱う。

execution targetを変えてもuser/project data scopeは変化しない。

## Review stop condition

以下が明確であればbootstrap設計の探索を止め、実装Issueへ進む。

- trust boundary
- data ownership keys
- network egress owners
- policy precedence
- Local/Managed Runner境界
- high-risk threatとrequired control
