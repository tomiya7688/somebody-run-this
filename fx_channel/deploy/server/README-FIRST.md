# fx_channel Server — FIRST RUN

このディレクトリはRelease用サーバーバンドルの雛形です。

1. `config/operator.example.yaml` を `config/operator.yaml` にコピー
2. `FX_CHANNEL_OPERATOR_TOKEN` 環境変数を設定
3. OSに合う起動スクリプトを実行

Linux:

```bash
./start-server.sh
```

Windows Server:

```powershell
.\start-server.ps1
```

詳細はリポジトリの `Docs/運営者へ/サーバー設置.md` を参照してください。
