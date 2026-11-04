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
