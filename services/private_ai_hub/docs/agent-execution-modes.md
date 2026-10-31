# Agent execution modes

## 目的

Agentのモデル推論場所と、実際にファイルやアプリを操作する場所を分離して設計する。

モデルが会社サーバーに存在していても、Tool executionはユーザーPC上で実行できる。

## 1. Local Runner

Local RunnerはAgent Appを利用している**そのユーザー本人のPC**で動くexecutorである。

```text
User PC
  Local Runner
      ^
      | signed/scoped tool request
      |
Private AI Server
  Agent Orchestrator
  Policy Engine
  Model Runtime
```

### 原則

- Runnerはユーザー本人のidentity/sessionへbindingする。
- User AのAgentからUser BのLocal Runnerを利用できない。
- Local filesystem/app accessは管理者上限とユーザー承認の両方を満たす場合だけ許可する。
- Runnerはモデルではなく、許可された操作だけを実行するexecutorである。
- Serverから渡された任意文字列をshellとして実行する設計にはしない。
- Local Toolごとにread/write/destructive/network等のcapabilityを持つ。

### 代表用途

- ユーザーPCの文書を読む
- ユーザーPC上の許可されたアプリを操作する
- ローカル成果物をユーザーPCへ保存する

## 2. Managed Runner

Managed Runnerは会社が用意したAgent専用Worker/VMで動く。

**管理者の普段使いPCを共有Runnerとして扱わない。**

```text
Private AI Server
  Agent Scheduler
       |
       +-- Managed Worker 01
       +-- Managed Worker 02
       +-- Managed Worker 03
```

### 原則

- WorkerはAgent専用の会社管理環境とする。
- ユーザー個人PCのDesktop/Documentsへ暗黙アクセスしない。
- company storage / project files / installed Extensions等、管理者が許可したresourceだけを利用する。
- Runごとにworkspaceを分離する。
- Worker credentialはユーザーへ露出しない。
- Worker障害が他Runのworkspaceやcredentialへ波及しないよう隔離する。

### 代表用途

- 長時間処理
- ユーザーPCがオフでも継続する処理
- 社内共有データを扱う処理
- 定型バッチや大規模処理

## 3. Hybrid

Local RunnerとManaged Runnerを同一Runで組み合わせる場合、データ転送自体をTool actionとして扱う。

### 必須制約

- Local -> Server upload
- Server -> Local download
- External Providerへの送信

をそれぞれ別capabilityとして判定する。

Hybridは境界が増えるため、v1で実装する場合でもLocal/Managed単独より厳格なapprovalとauditを要求する。

## Policy model

管理者は少なくとも以下を制御できる。

```text
Local Runner
  enabled
  filesystem read/write
  allowed roots
  application automation
  network
  destructive actions

Managed Runner
  enabled
  allowed worker pools
  company storage
  filesystem read/write
  network
  shell/code-execution capability
  max runtime

Hybrid
  enabled
  local-to-server transfer
  server-to-local transfer
  external-provider transfer
```

ユーザー設定は管理者ポリシーを狭めることはできるが、広げることはできない。

## Run selection

Agent Runにはexecution targetを明示的に持たせる。

- `local`
- `managed`
- 将来 `hybrid`

管理者が一方しか許可していない場合、UI/APIで許可されていないexecution targetを選択できない。

## Security invariant

**Agentの実行場所を変えても、他ユーザーの個人会話・User Memory・workspaceへアクセスできるようにはならない。**
