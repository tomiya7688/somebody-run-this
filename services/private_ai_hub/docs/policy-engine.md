# Policy Engine

## 目的

Policy Engineは、PrivateAIとAgent Appの全機能で「ユーザー設定は管理者上限を越えない」をサーバー側で強制する。

Policy判定はUIではなくサーバー側を正本とする。

## Policy layers

v1では以下のような複数layerを同じ方法で合成できる。

- Organization
- Group / Role
- Project

Userはpolicy layerではなく「request」を出す側として扱う。

各layerはrevisionを持ち、effective policy snapshotにsource revisionを残す。

## Feature

Featureは次の3状態を持つ。

- `disabled`: OFFのみ許可
- `optional`: ON/OFFの両方を許可
- `required`: ONのみ許可

複数layerの許可集合をintersectionする。

例:

```text
Organization: optional
Project:      disabled
User request: on

effective: off
```

`required` と `disabled` のように許可集合が空になる設定競合は、黙って片方を優先せず `policy_conflict` としてfail-closedする。

未設定Featureは既定で `disabled` とする。

モデルやruntimeがそのFeature capabilityを持たない場合も、Policy Engineがeffective値を制限する。

## Integer limits

数値上限はlayerごとの範囲をintersectionする。

```text
Organization: 0..100
Group:        10..50

effective:    10..50
```

requestが範囲外の場合は設定種別に応じて:

- `reject`
- `clamp`

のどちらかを明示的に選ぶ。

runtime/model側の物理的上限も同じintersectionへ含める。

## Allowed values

モデル・Extension・Runner pool等の選択値はallowlistのintersectionで決める。

モデルの例:

```text
Provider catalog:
  luna
  sol
  astra

Organization allowlist:
  luna
  sol

Project allowlist:
  luna

User-visible/effective:
  luna
```

Provider/runtimeがmodelを認識していることは利用許可を意味しない。

choiceは既定でdefault-denyとするため、管理者allowlistがない新規model/Extensionは自動公開しない。

## Explanation

各decisionは少なくとも以下を返す。

- requested
- effective
- permitted
- denial_code
- reason list
- source policy revisions

これにより管理UIは「なぜこの機能がOFFなのか」「どのlayerで上限が決まったか」を説明できる。

## Engine API

`PolicyEngine.evaluate()` は `PolicyRequest`、policy layers、runtime/model capabilitiesを受け取り、`EffectivePolicySnapshot` を返す。

この段階では認証済みuser contextを受け取るHTTP endpointは公開しない。
HTTPのuser-specific effective policy APIはRBAC/認証 (#23) の後に、この同じPolicy Engineを呼ぶ薄いAPIとして実装する。

## Security invariants

- user requestはpolicyを変更しない
- lower layerは上位allowlistを広げられない
- unknown Featureはdefault disabled
- unknown model/Extensionはdefault denied
- policy conflictはfail-closed
- model/runtime capabilityを管理policyで越えない
- direct API callでもUIと同じ判定を使う
