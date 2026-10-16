import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'application/user_service.dart';
import 'frontends/jp_soft_pop/app.dart';
import 'infrastructure/http_user_gateway.dart';
import 'infrastructure/player_identity.dart';
import 'infrastructure/server_settings.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  const compiledServerUrl = String.fromEnvironment(
    'FX_CHANNEL_SERVER_URL',
    defaultValue: '',
  );
  const frontend = String.fromEnvironment(
    'FX_CHANNEL_USER_FRONTEND',
    defaultValue: 'jp_soft_pop',
  );

  final savedServerUrl = await ServerSettings.load();
  final playerId = await PlayerIdentity.loadOrCreate();
  final initialServerUrl = savedServerUrl.isNotEmpty
      ? savedServerUrl
      : ServerSettings.normalize(compiledServerUrl);

  runApp(
    UserBootstrap(
      initialServerUrl: initialServerUrl,
      frontend: frontend,
      playerId: playerId,
    ),
  );
}

class UserBootstrap extends StatefulWidget {
  const UserBootstrap({
    super.key,
    required this.initialServerUrl,
    required this.frontend,
    required this.playerId,
  });

  final String initialServerUrl;
  final String frontend;
  final String playerId;

  @override
  State<UserBootstrap> createState() => _UserBootstrapState();
}

class _UserBootstrapState extends State<UserBootstrap> {
  late String _serverUrl = widget.initialServerUrl;
  bool _showSetup = false;

  bool get _needsSetup =>
      _showSetup || (!kIsWeb && _serverUrl.trim().isEmpty);

  Future<void> _saveServer(String serverUrl) async {
    final normalized = ServerSettings.normalize(serverUrl);
    await ServerSettings.save(normalized);
    if (!mounted) return;
    setState(() {
      _serverUrl = normalized;
      _showSetup = false;
    });
  }

  Future<void> _changeServer() async {
    if (kIsWeb) return;
    setState(() => _showSetup = true);
  }

  @override
  Widget build(BuildContext context) {
    if (_needsSetup) {
      return MaterialApp(
        title: 'fx_channel setup',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(useMaterial3: true),
        home: ServerSetupPage(
          initialValue: _serverUrl,
          onSave: _saveServer,
        ),
      );
    }

    final service = UserService(
      HttpUserGateway(baseUrl: _serverUrl),
    );

    switch (widget.frontend) {
      case 'jp_soft_pop':
        return JpSoftPopApp(
          service: service,
          playerId: widget.playerId,
          onChangeServer: kIsWeb ? null : _changeServer,
        );
      default:
        throw StateError('Unknown user frontend: ${widget.frontend}');
    }
  }
}

class ServerSetupPage extends StatefulWidget {
  const ServerSetupPage({
    super.key,
    required this.initialValue,
    required this.onSave,
  });

  final String initialValue;
  final Future<void> Function(String value) onSave;

  @override
  State<ServerSetupPage> createState() => _ServerSetupPageState();
}

class _ServerSetupPageState extends State<ServerSetupPage> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.initialValue);
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final value = _controller.text;
    if (!ServerSettings.isValid(value)) {
      setState(() {
        _error = 'http:// または https:// から始まるサーバーURLを入力してください。';
      });
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });

    await widget.onSave(value);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Card(
            margin: const EdgeInsets.all(24),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    '接続する fx_channel サーバー',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '運営者から案内されたURLを入力してください。例: https://game.example.com',
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _controller,
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: 'Server URL',
                      border: const OutlineInputBorder(),
                      errorText: _error,
                    ),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(_saving ? '保存中…' : 'このサーバーで遊ぶ'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
