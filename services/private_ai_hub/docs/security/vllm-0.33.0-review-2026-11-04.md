# vLLM 0.33.0 採用時セキュリティ調査

調査日: 2026-11-04

対象Issue: #26

## 結論

Private AI Hubの最初の実ローカルInferenceBackendとして **vLLM 0.33.0のみ**を採用する。

アプリケーションへvLLMをimportせず、Linux上の別プロセスとして起動し、PrivateAI Gatewayとはprivate Unix domain socketだけで通信する。

vLLMのバージョンはruntime起動時に確認し、**0.33.0以外は起動拒否**する。

将来0.33.1/0.34等へ更新する場合も、自動許可せず `.github/SECURITY_RULES.md` に従って再調査・コード変更・レビューを行う。

## 調査した主な情報源

- vLLM v0.33.0 release: https://github.com/vllm-project/vllm/releases/tag/v0.33.0
- vLLM Security: https://docs.vllm.ai/en/stable/usage/security/
- vLLM 0.33.0 CLI / UDS: https://docs.vllm.ai/en/v0.33.0/cli/serve/
- vLLM endpoint plugin security: https://docs.vllm.ai/en/v0.33.0/design/endpoint_plugins/
- vLLM 0.33.0 env vars: https://docs.vllm.ai/en/v0.33.0/configuration/env_vars/

## 直近Advisory

### GHSA-qrj2-j723-m6w8 — model config path traversal / information disclosure

- 公開: 2026-11-02
- affected: `< 0.33.0`
- patched: `0.33.0`
- https://github.com/vllm-project/vllm/security/advisories/GHSA-qrj2-j723-m6w8

model repositoryのconfigによって別directoryのmodel/tokenizerへ誘導され得る問題。0.33.0未満を拒否する。

PrivateAI側でもModel Store root外のmodel pathとsymlink escapeを拒否し、Model Importer (#28) でquarantine/immutable revision/digest検証を追加する。

### 2026年のmedia/multimodal系RCE

EPS/Ghostscript処理やmultimodal shared-memory cache deserializationを経由する重大問題が報告され、0.32.0で修正された。0.33.0は修正後のversion。

初期PrivateAI backendはtext-onlyとし、`--language-model-only` を強制する。

## vLLM APIを直接公開しない理由

vLLM公式Security文書ではAPI keyだけですべてのendpointを一律保護できるわけではなく、公開配置ではreverse proxy等でendpointを絞ることが推奨されている。

PrivateAIではTCP host/portへbindせず、`--uds` のprivate Unix socketのみを使い、Client/UserからvLLMへ直接接続させない。Gatewayは `/v1/models` と `/v1/chat/completions` だけを利用する。

## Network

Inference WorkerにはInternetを与えない。初期Linux backendは `/usr/bin/unshare --net -- vllm ...` のno-egress network namespaceで起動する。

さらに `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、proxy/Hub token等の不継承、Model Store内local path限定を強制する。

## Remote code / plugin

- `--no-trust-remote-code` を明示
- `VLLM_PLUGINS=""` としてplugin allowlistを空にする
- `VLLM_SERVER_DEV_MODE=0`
- request/output loggingを有効にしない
- development/debug endpointを有効にしない

## Resource limit

- request `n=1` 固定
- `VLLM_MAX_N_SEQUENCES=1`
- `VLLM_MAX_COMPLETION_PROMPTS=1`
- `--max-num-seqs` / `--max-num-active-seqs` / `--max-num-queued-reqs`
- request/response size上限

本格的な複数instance/VRAM schedulingは #41。

## 初期対応範囲

対応: text chat / streaming / local model path / Linux / private UDS / single worker.

非対応: multimodal / remote model download / remote code / vLLM plugin / dynamic LoRA / tool calling / arbitrary endpoint / public TCP / multi-node.

## 比較した候補

### SGLang

2026年にunauthenticated RCE等の重大問題が複数報告され、調査時点でpatched versionが示されていないCritical Advisoryも確認したため初期backendとして採用しない。

- https://nvd.nist.gov/vuln/detail/CVE-2026-7304
- https://github.com/advisories?query=CVE-2026-7304

### Ollama

過去に `/api/pull` path traversalからRCEへ繋がるCritical問題があり修正版は存在する。選択肢として否定しないが、今回はvLLMのUDS・GPU servingをPrivateAI側で隔離して使う。

## 更新ルール

vLLM versionを変えるPRではSecurity Advisory、GitHub Advisory Database、release notes、直近security issue、CLI/API/Model load変更、PrivateAI containmentの有効性を再確認する。

`REVIEWED_VLLM_VERSION` だけを書き換える無調査updateは禁止する。