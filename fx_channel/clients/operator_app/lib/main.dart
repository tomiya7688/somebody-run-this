import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  const defaultServerUrl = String.fromEnvironment(
    'FX_CHANNEL_SERVER_URL',
    defaultValue: 'http://127.0.0.1:8787',
  );

  runApp(OperatorApp(defaultServerUrl: defaultServerUrl));
}

class OperatorApp extends StatelessWidget {
  const OperatorApp({
    super.key,
    required this.defaultServerUrl,
  });

  final String defaultServerUrl;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'fx_channel Operator',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      ),
      home: OperatorHome(defaultServerUrl: defaultServerUrl),
    );
  }
}

class OperatorHome extends StatefulWidget {
  const OperatorHome({
    super.key,
    required this.defaultServerUrl,
  });

  final String defaultServerUrl;

  @override
  State<OperatorHome> createState() => _OperatorHomeState();
}

class _OperatorHomeState extends State<OperatorHome> {
  late final _serverController =
      TextEditingController(text: widget.defaultServerUrl);
  final _tokenController = TextEditingController();
  final _playerController = TextEditingController();
  final _currencyController = TextEditingController(text: 'premium_gem');
  final _amountController = TextEditingController(text: '3000');

  Map<String, dynamic>? _status;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _serverController.dispose();
    _tokenController.dispose();
    _playerController.dispose();
    _currencyController.dispose();
    _amountController.dispose();
    super.dispose();
  }

  String get _baseUrl =>
      _serverController.text.trim().replaceAll(RegExp(r'/+$'), '');

  Map<String, String> get _operatorHeaders => {
        'Authorization': 'Bearer ${_tokenController.text}',
        'Content-Type': 'application/json',
      };

  Future<void> _loadStatus() async {
    final base = _baseUrl;
    if (base.isEmpty) {
      setState(() => _error = 'Server URLを入力してください。');
      return;
    }

    setState(() => _busy = true);
    try {
      final response = await http.get(
        Uri.parse('$base/api/operator/status'),
        headers: _operatorHeaders,
      );
      if (response.statusCode != 200) {
        throw StateError('HTTP ${response.statusCode}: ${response.body}');
      }
      if (!mounted) return;
      setState(() {
        _status = jsonDecode(response.body) as Map<String, dynamic>;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _status = null;
        _error = error.toString();
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _grantCurrency() async {
    final base = _baseUrl;
    final playerId = _playerController.text.trim();
    final currency = _currencyController.text.trim();
    final amount = int.tryParse(_amountController.text);

    if (base.isEmpty || playerId.isEmpty || currency.isEmpty || amount == null) {
      setState(() => _error = '通貨付与の入力内容を確認してください。');
      return;
    }

    setState(() => _busy = true);
    try {
      final response = await http.post(
        Uri.parse('$base/api/operator/action'),
        headers: _operatorHeaders,
        body: jsonEncode({
          'action': 'grant_currency',
          'payload': {
            'player_id': playerId,
            'currency': currency,
            'amount': amount,
          },
        }),
      );

      if (response.statusCode != 200) {
        throw StateError('HTTP ${response.statusCode}: ${response.body}');
      }

      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      if (decoded['ok'] != true) {
        throw StateError(decoded['message'].toString());
      }

      if (!mounted) return;
      setState(() => _error = null);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('$playerId に $amount $currency を付与しました。'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('fx_channel 運営')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          TextField(
            controller: _serverController,
            decoration: const InputDecoration(
              labelText: 'Server URL',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _tokenController,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Operator Token',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _busy ? null : _loadStatus,
            icon: const Icon(Icons.monitor_heart_rounded),
            label: const Text('サーバー状態を取得'),
          ),
          if (_status != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: SelectableText(
                    const JsonEncoder.withIndent('  ').convert(_status),
                  ),
                ),
              ),
            ),
          const SizedBox(height: 24),
          Text(
            '通貨付与',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _playerController,
            decoration: const InputDecoration(
              labelText: 'Player ID',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _currencyController,
                  decoration: const InputDecoration(
                    labelText: 'Currency',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _amountController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Amount',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          FilledButton.tonalIcon(
            onPressed: _busy ? null : _grantCurrency,
            icon: const Icon(Icons.add_card_rounded),
            label: const Text('通貨を付与'),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(
                'エラー: $_error',
                style: TextStyle(
                  color: Theme.of(context).colorScheme.error,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
