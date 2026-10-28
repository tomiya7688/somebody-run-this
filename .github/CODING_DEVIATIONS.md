# Coding deviations

MISRA-inspired coding rulesからの承認済み逸脱を記録します。

## DEV-0001 — server test runtime double

- 対象: `fx_channel/tests/test_server.py` の `FakeRuntime()` を `create_app()` に渡す箇所
- ルール: SRT-M018
- 抑制: `# type: ignore[arg-type]`
- 理由: テストダブルはHTTP層が実際に使用するRuntime surfaceのみを意図的に実装しており、完全な `FxChannelRuntime` の構築を避けてHTTP認証境界を単体テストするため
- リスク: Runtime interface変更時にテストダブルの型不整合をmypyが検出できない可能性
- 代替防御: APIテスト実行と `create_app` の利用箇所レビュー
- 承認PR: この規約を導入したPR
- 再確認条件: `create_app` の引数をProtocol化した場合、またはRuntime public interface変更時
