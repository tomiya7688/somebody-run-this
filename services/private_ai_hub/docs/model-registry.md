# Model Registry

## 目的

Model Registryは、PrivateAIが「知っているモデル」と「ユーザーに使わせてよいモデル」を明確に分離する。

最重要原則:

**Catalogに存在することは利用許可を意味しない。**

## Model Catalog

Catalogは管理者・runtime・Provider側のモデル情報を保持する。

主な情報:

- internal id
- organization
- user-facing model id
- display name
- source kind: local / external
- backend id
- backend側model id
- local path（local modelのみ）
- revision
- SHA-256 digest
- enabled
- capability
- context limit
- health state
- health detail

新規登録モデルのhealthは `unknown`。

Catalog登録だけではユーザーへ表示しない。

## 3つのゲート

ユーザーがモデルを利用するには、最低でも次の3つを満たす。

1. `enabled = true`
2. `health_state = ready`
3. effective model allowlistに含まれる

つまり:

```text
registered
AND enabled
AND healthy
AND organization allowlist
AND group/project policy
= usable
```

## Organization root allowlist

Organization allowlistがroot ceiling。

Organizationにmodel policyがない場合は**0モデル許可**として扱う。

Provider/runtimeがモデルを100個発見しても、Organization allowlistが空ならユーザーには0件。

1モデルだけ許可する構成もfirst-class。

例:

```text
Catalog
  luna
  sol
  astra

Organization allowlist
  luna

User sees
  luna
```

## Group / Project

GroupとProjectはOrganization allowlistをさらに狭められる。

広げることはできない。

例:

```text
Organization
  luna
  sol

Group
  luna

effective
  luna
```

Projectで `luna, sol, astra` と指定しても、Organizationが `luna` だけならeffectiveは `luna`。

Project membership自体は #32 のProject domainが正本。
Model Registryへ渡す `project_id` は、Project domainで認可済みのものだけを利用する。

## Direct model id

ユーザーがAPIへmodel idを直接指定してもallowlistを回避できない。

後続Chat API #29は必ず:

`ModelRegistry.require_allowed_model()`

を通してからbackendを選択する。

未登録・disabled・unhealthy・allowlist外はすべてUser側では同じ「model is not available」として扱い、内部Catalog状態を不要に漏らさない。

## Default model

default modelもallowlist内でなければ設定できない。

解決順:

1. current Project default（許可されている場合）
2. user所属Groupのdefaultが1つに一致する場合
3. Organization default
4. effective modelが1つだけならそのモデル
5. それ以外はdefaultなし

## Health

health:

- unknown
- ready
- unhealthy

health更新はruntime/scheduler内部経路用。
ユーザーAPIから直接healthを変更する機能は提供しない。

disabledとunhealthyは別。

- disabled: 管理者が利用停止
- unhealthy: runtime/workerが現在利用不能

## Capability

Model capability:

- text
- streaming
- vision
- tool calling
- context limit

`ModelCapabilities.to_policy_capabilities()` によりPolicy Engineへ渡す。

たとえば管理者が画像入力を許可していても、選択モデルがvision非対応ならeffective capabilityは有効にならない。

## Local / External

### Local

会社サーバー側Model Storeのmodel。

Registryはabsolute local pathを保持する。
実際にModel Store root内へ閉じ込める最終検証はInferenceBackend (#26) とModel Importer (#28)でも行う。

### External

OpenAI等のProvider Extension経由model。

local pathは持たない。

Providerが列挙したmodel catalogをそのままOrganization allowlistへ追加しない。
管理者が明示的に許可する。

## Permission

Catalog/allowlistの変更には:

`model.manage`

が必要。

built-in adminにはmigrationで追加する。

一般userはCatalog管理APIを持たず、effective model viewだけを利用する。

## Policy revision

Organization / Group / Projectのallowlist変更ごとにrevisionを増やす。

このrevisionは将来のPolicy snapshot、Cache invalidation、Auditへ利用する。

## Security invariant

- 新規モデル = default deny
- runtime/provider catalog != permission
- disabled/unhealthy = 利用不可
- Organization rootをGroup/Projectが広げられない
- direct model idで回避できない
- cross-organization model/policy変更を拒否
- capabilityをmodel実態以上に有効化しない
