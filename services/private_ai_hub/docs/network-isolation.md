# Network isolation and egress policy

## 原則

Private AI Hubでは、**モデル推論プロセスへ直接Internet accessを与えない。**

外向き通信が必要な機能は、推論Workerとは別のtrust boundaryで動かす。

- Model Importer
- Extension Host / Provider Extension
- Web Search Extension

それぞれが専用のEgress Brokerを使い、管理者policyを満たした宛先だけへ接続する。

## Deployment profiles

### offline

```toml
[network]
profile = "offline"
```

- Egress BrokerはDNS解決前に拒否する。
- Model Importerのremote downloadを使わない。
- external Provider Extensionを使わない。
- Web Searchを使わない。
- 既にlocal Model Storeへ存在するモデルだけで運用する。

### restricted-egress

```toml
[network]
profile = "restricted-egress"
```

profileを切り替えただけでは通信は許可されない。

各Importer/Extensionに対し、さらに次を明示する。

- enabled
- allowed domains
- allowed ports
- allowed HTTP methods
- HTTPS/HTTP
- request/response byte limit
- timeout
- redirect limit
- 必要な場合だけexplicit private CIDR

つまり:

```text
restricted-egress
AND component enabled
AND destination allowlist
AND DNS/IP validation
AND request policy
= outbound request
```

## Egress Broker

`private_ai_hub.egress.EgressBroker` がアプリケーション管理下の外向き通信境界。

### URL

- HTTP/HTTPS以外を拒否
- URL埋め込みusername/passwordを拒否
- control characterを拒否
- callerによるHost/Content-Length/Connection上書きを拒否
- plain HTTPはdefault禁止

### Domain

宛先hostnameはadmin allowlist必須。

subdomain許可はpolicyで明示する。

Provider/runtimeが返したURLだから自動的に信頼する、という扱いにはしない。

### DNS/IP

DNS結果を取得した後、**接続前に全IPを検査する。**

defaultで拒否:

- loopback
- link-local
- cloud metadata系link-local address
- multicast
- unspecified
- reserved
- その他non-global address

private/internal addressが本当に必要な企業向けExtensionでは、管理者がCIDRを個別許可できる。

ただしloopback/link-local/multicastはCIDR指定でも許可しない。

DNS回答にpublic IPとprivate IPが混在する場合はrequest全体を拒否する。

検証したnumeric IPへ直接connectし、HTTP client側にhostnameを再解決させない。
HTTPSでは元hostnameをSNI/certificate validationへ使う。

### Redirect

redirect先は新しいrequestとして再検査する。

別originへredirectする場合:

- Authorization
- Cookie
- Proxy-Authorization

を引き継がない。

GET/HEAD以外のredirectは自動追従しない。

## Inference Worker

Inference WorkerへEgress Brokerを渡さない。

さらにアプリケーション設計だけに依存せず、OS/コンテナでも外向きnetworkを遮断する。

### Linux

推奨:

- systemd `PrivateNetwork=yes`
- container `--network none`
- dedicated network namespace
- 必要に応じて追加seccomp/capability制限

`deploy/linux/run-no-egress.sh` はnetwork namespaceでcommandを起動する最小補助。

本番ではsystemd/container orchestratorのnetwork policyを正本にしてよい。

### Windows Server

Windows向けの最終配布では、Inference Worker executable/serviceに対するoutbound firewall ruleを生成・検証する。

Windows Firewall配布設定は #40 のdeployment整備で追加する。
Inference runtime実装 #26 は、Windowsでも「direct egressを必要としない」ことを必須とする。

## Model Importer

Model ImporterはInference Workerとは別process/service identityとする。

- Import用credentialをInferenceへ渡さない
- Importer専用allowed domains
- quarantine
- immutable revision
- digest

を使う。

## Extension Host

ExtensionごとにEgress Policyを分離する。

OpenAI Provider ExtensionのcredentialをWeb Search Extensionや別Provider Extensionへ共有しない。

## Web Search

ユーザーがWeb SearchをONにしても次のいずれかがfalseなら通信しない。

- Organization policy
- Project/Group policy
- Extension installed/enabled
- restricted-egress profile
- Extension egress policy
- conversation/user request

Inference Worker自身が検索サイトへ接続することはない。

## Audit

Egress Auditには以下だけを記録する。

- organization
- actor
- component id
- purpose
- method
- scheme
- hostname
- port
- allow/deny reason

URL path/queryは記録しない。
API keyやAuthorization headerも記録しない。

## Defense in depth

Egress BrokerはSSRF/DNS rebinding/redirectを抑えるアプリ層の防御であり、OS firewall/network namespaceの代替ではない。

最終構成は:

```text
Inference Worker
  └─ OS network deny
       └─ direct Internet: impossible

Importer / Extension Host
  └─ OS network boundary
       └─ Egress Broker
            └─ admin allowlist
                 └─ validated destination
```

とする。
