import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  const serverUrl = String.fromEnvironment(
    'FX_CHANNEL_SERVER_URL',
    defaultValue: 'http://127.0.0.1:8787',
  );

  runApp(OperatorApp(serverUrl: serverUrl));
}

class OperatorApp extends StatelessWidget {
  const OperatorApp({
    super.key,
    required this.serverUrl,
  });

  final String serverUrl;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'fx_channel Operator',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      ),
      home: OperatorHome(serverUrl: serverUrl),
    );
  }
}

class OperatorHome extends StatefulWidget {
  const OperatorHome({
    super.key,
    required this.serverUrl,
  });

  final String serverUrl;

  @override
  State<OperatorHome> createState() => _OperatorHomeState();
}

class _OperatorHomeState extends State<OperatorHome> {
  final _tokenController = TextEditingController();
  Map<String, dynamic>? _status;
  String? _error;

  @override
  void dispose() {
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _loadStatus() async {
    final base = widget.serverUrl.replaceAll(RegExp(r'/+$'), '');
    try {
      final response = await http.get(
        Uri.parse('$base/api/operator/status'),
        headers: {
          'Authorization': 'Bearer ${_tokenController.text}',
        },
      );
      if (response.statusCode != 200) {
        throw StateError('HTTP ${response.statusCode}');
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
            controller: _tokenController,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Operator Token',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _loadStatus,
            child: const Text('サーバー状態を取得'),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text('エラー: $_error'),
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
        ],
      ),
    );
  }
}
