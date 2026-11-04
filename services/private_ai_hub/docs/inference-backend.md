# Inference Backend

## 目的

Private AI Hub本体を特定runtimeへ固定せず、共通InferenceBackend契約の後ろにローカル推論runtimeを置く。

v1の最初の実backendは **vLLM 0.33.0**。

## 共通契約

`private_ai_hub.inference` は以下を定義する。

- start / stop
- health
- chat
- stream_chat
- capability
- bounded ChatRequest / ChatMessage
- TokenUsage

MockInferenceBackendを同じ契約で提供し、Gateway/Policy/Chat層はvLLM固有型へ依存しない。

## vLLM backend

vLLMはPrivateAI Python processへimportしない。

```text
PrivateAI Gateway
   |
   | Unix domain socket
   v
vLLM 0.33.0 Worker
   |
   X direct Internet
```

PrivateAI Client/UserからvLLMへ直接接続する経路は作らない。

### Version

`REVIEWED_VLLM_VERSION = 0.33.0` を完全一致で検査する。

0.32等の古いversionだけでなく、未レビューの0.34等の新しいversionも起動拒否する。

version更新はSecurity Rulesに従う別PRが必要。

### Model path

vLLMへ渡せるのは管理者Model Store root配下へresolveされるlocal directoryだけ。

- remote model idを渡さない
- Model Store外へのsymlink escapeを拒否
- Hub offline
- remote code disabled

Model Importer #28が、download/quarantine/revision/digestを担当する。

### Text-only

初期backendはtext-only。

- `--language-model-only`
- tool calling false
- vision false
- remote mediaなし

画像入力は #35 で別Security Review後に追加する。

### Unix socket

`--uds`だけを使い、`--host` / `--port`は指定しない。

runtime directoryは0700、socketは0600。

PrivateAI Gatewayの内部clientだけが `/v1/models` と `/v1/chat/completions` を利用する。

vLLMに他endpointが存在していてもUser APIへproxyしない。

### No-egress

初期Linux Workerはreviewed launch envelopeとして:

`/usr/bin/unshare --net --`

を必須とする。

vLLM processにはEgressBrokerを渡さない。

また:

- `HF_HUB_OFFLINE=1`
- `TRANSFORMERS_OFFLINE=1`
- proxy不継承
- Hub/API token不継承
- `PYTHONPATH`不継承
- `LD_PRELOAD`不継承
- private HOME/cache/TMP

を適用する。

本番systemd/containerでは #25 の `PrivateNetwork=yes` / `--network none` 等をさらに利用できる。

### Plugin / debug

- `VLLM_PLUGINS=""`
- `VLLM_SERVER_DEV_MODE=0`
- `--no-trust-remote-code`
- `--disable-log-requests`
- `--disable-uvicorn-access-log`

を固定する。

### Resource bounds

PrivateAI Gateway/Rate/Quotaに加え、runtimeにも防御的上限を置く。

- request `n=1`
- `VLLM_MAX_N_SEQUENCES=1`
- `VLLM_MAX_COMPLETION_PROMPTS=1`
- max-num-seqs
- max-num-active-seqs
- max-num-queued-reqs
- response/SSE line size

本格的なVRAM/instance schedulingは #41。

## Streaming

vLLM OpenAI-compatible SSEはUnix socket越しに読み、`data:` JSONだけを処理する。

- line size上限
- JSON型検査
- text contentだけ受理
- `[DONE]`で終了

## OS support

このreviewed vLLM backend v1はLinux専用。

PrivateAIのInferenceBackend契約自体はOS非依存なので、Windows Server向けruntimeは別backendとして追加できる。

Windowsだから安全要件を緩めるのではなく、direct egress禁止・local model path・process isolation・version pinningを同等に満たすbackendだけを採用する。

## Security review

採用時調査の詳細:

`docs/security/vllm-0.33.0-review-2026-11-04.md`

## 今後

- #27 Model Registry
- #41 Instance/VRAM Scheduler
- #28 Model Importer
- #29 Chat API
- #35 Multimodal

がこのbackend abstractionを利用する。