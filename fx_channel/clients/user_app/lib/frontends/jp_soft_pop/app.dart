import 'dart:async';

import 'package:flutter/material.dart';

import '../../application/user_service.dart';

class JpSoftPopApp extends StatelessWidget {
  const JpSoftPopApp({
    super.key,
    required this.service,
    this.onChangeServer,
  });

  final UserService service;
  final Future<void> Function()? onChangeServer;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'fx_channel',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF66B8FF),
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF7F8FC),
        cardTheme: const CardThemeData(
          elevation: 1,
          margin: EdgeInsets.all(8),
        ),
      ),
      home: _HomePage(
        service: service,
        onChangeServer: onChangeServer,
      ),
    );
  }
}

class _HomePage extends StatefulWidget {
  const _HomePage({
    required this.service,
    required this.onChangeServer,
  });

  final UserService service;
  final Future<void> Function()? onChangeServer;

  @override
  State<_HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<_HomePage> {
  Timer? _timer;
  List<MarketQuote> _quotes = const [];
  String? _error;

  @override
  void initState() {
    super.initState();
    _reload();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _reload());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _reload() async {
    try {
      final quotes = await widget.service.loadQuotes();
      if (!mounted) return;
      setState(() {
        _quotes = quotes;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('fx_channel'),
        actions: [
          IconButton(
            tooltip: '更新',
            onPressed: _reload,
            icon: const Icon(Icons.refresh_rounded),
          ),
          if (widget.onChangeServer != null)
            IconButton(
              tooltip: '接続先サーバー',
              onPressed: () => widget.onChangeServer!(),
              icon: const Icon(Icons.dns_rounded),
            ),
        ],
      ),
      bottomNavigationBar: const NavigationBar(
        selectedIndex: 0,
        destinations: [
          NavigationDestination(
            icon: Icon(Icons.home_rounded),
            label: 'ホーム',
          ),
          NavigationDestination(
            icon: Icon(Icons.show_chart_rounded),
            label: '取引',
          ),
          NavigationDestination(
            icon: Icon(Icons.people_alt_rounded),
            label: 'キャラ',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_awesome_rounded),
            label: 'ガチャ',
          ),
          NavigationDestination(
            icon: Icon(Icons.emoji_events_rounded),
            label: 'ランキング',
          ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _HeroCard(onRefresh: _reload),
            const SizedBox(height: 8),
            Text(
              'マーケット',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            if (_error != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text('接続エラー: $_error'),
                ),
              )
            else if (_quotes.isEmpty)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(32),
                  child: CircularProgressIndicator(),
                ),
              )
            else
              ..._quotes.map((quote) => _QuoteCard(quote: quote)),
          ],
        ),
      ),
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            const CircleAvatar(
              radius: 34,
              child: Icon(Icons.auto_graph_rounded, size: 34),
            ),
            const SizedBox(width: 16),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '今日も相場を見てみよう！',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(height: 4),
                  Text('予測スキルはヒント。未来を確定するものではありません。'),
                ],
              ),
            ),
            FilledButton(
              onPressed: onRefresh,
              child: const Text('更新'),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuoteCard extends StatelessWidget {
  const _QuoteCard({required this.quote});

  final MarketQuote quote;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.currency_exchange_rounded),
        title: Text(
          quote.symbol,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        trailing: Text(
          quote.price.toStringAsFixed(5),
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
    );
  }
}
