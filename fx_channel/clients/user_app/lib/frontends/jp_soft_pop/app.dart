import 'dart:async';

import 'package:flutter/material.dart';

import '../../application/user_service.dart';

class JpSoftPopApp extends StatelessWidget {
  const JpSoftPopApp({
    super.key,
    required this.service,
    required this.playerId,
    this.onChangeServer,
  });

  final UserService service;
  final String playerId;
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
      home: _AppShell(
        service: service,
        playerId: playerId,
        onChangeServer: onChangeServer,
      ),
    );
  }
}

class _AppShell extends StatefulWidget {
  const _AppShell({
    required this.service,
    required this.playerId,
    required this.onChangeServer,
  });

  final UserService service;
  final String playerId;
  final Future<void> Function()? onChangeServer;

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> {
  int _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      _HomePage(
        service: widget.service,
        playerId: widget.playerId,
      ),
      _TradePage(
        service: widget.service,
        playerId: widget.playerId,
      ),
      _CharacterPage(
        service: widget.service,
        playerId: widget.playerId,
      ),
      const _PlaceholderPage(
        icon: Icons.auto_awesome_rounded,
        title: 'ガチャ',
        message: 'ガチャ機能を準備中です。',
      ),
      const _PlaceholderPage(
        icon: Icons.emoji_events_rounded,
        title: 'ランキング',
        message: 'シーズンランキングを準備中です。',
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('fx_channel'),
        actions: [
          if (widget.onChangeServer != null)
            IconButton(
              tooltip: '接続先サーバー',
              onPressed: () => widget.onChangeServer!(),
              icon: const Icon(Icons.dns_rounded),
            ),
        ],
      ),
      body: IndexedStack(
        index: _selectedIndex,
        children: pages,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) {
          setState(() => _selectedIndex = index);
        },
        destinations: const [
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
    );
  }
}

class _HomePage extends StatefulWidget {
  const _HomePage({
    required this.service,
    required this.playerId,
  });

  final UserService service;
  final String playerId;

  @override
  State<_HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<_HomePage> {
  Timer? _timer;
  HomeView? _home;
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
      final home = await widget.service.loadHome(widget.playerId);
      if (!mounted) return;
      setState(() {
        _home = home;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_home == null && _error == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          _HeroCard(onRefresh: _reload),
          if (_error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text('接続エラー: $_error'),
              ),
            ),
          if (_home != null) ...[
            _BalanceCard(home: _home!),
            const SizedBox(height: 8),
            Text(
              'マーケット',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            ..._home!.quotes.map((quote) => _QuoteCard(quote: quote)),
            const SizedBox(height: 8),
            Text(
              '保有ポジション',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            if (_home!.positions.isEmpty)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(18),
                  child: Text('まだポジションはありません。'),
                ),
              )
            else
              ..._home!.positions.map(_PositionCard.new),
          ],
        ],
      ),
    );
  }
}

class _TradePage extends StatefulWidget {
  const _TradePage({
    required this.service,
    required this.playerId,
  });

  final UserService service;
  final String playerId;

  @override
  State<_TradePage> createState() => _TradePageState();
}

class _TradePageState extends State<_TradePage> {
  final _marginController = TextEditingController(text: '100000');
  final _leverageController = TextEditingController(text: '5');

  HomeView? _home;
  String? _symbol;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _marginController.dispose();
    _leverageController.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    try {
      final home = await widget.service.loadHome(widget.playerId);
      if (!mounted) return;
      setState(() {
        _home = home;
        _symbol ??= home.quotes.isEmpty ? null : home.quotes.first.symbol;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  Future<void> _order(String side) async {
    final symbol = _symbol;
    final margin = double.tryParse(_marginController.text);
    final leverage = double.tryParse(_leverageController.text);

    if (symbol == null || margin == null || leverage == null) {
      _showMessage('入力内容を確認してください。');
      return;
    }

    setState(() => _busy = true);
    try {
      final result = await widget.service.placeOrder(
        playerId: widget.playerId,
        symbol: symbol,
        side: side,
        margin: margin,
        leverage: leverage,
      );
      if (!mounted) return;
      _showMessage(result.message);
      if (result.ok) {
        await _reload();
      }
    } catch (error) {
      if (!mounted) return;
      _showMessage(error.toString());
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _close(PositionView position) async {
    setState(() => _busy = true);
    try {
      final result = await widget.service.closePosition(
        playerId: widget.playerId,
        positionId: position.id,
      );
      if (!mounted) return;
      _showMessage(result.message);
      if (result.ok) {
        await _reload();
      }
    } catch (error) {
      if (!mounted) return;
      _showMessage(error.toString());
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final home = _home;

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Text(
          '取引',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        if (_error != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text('接続エラー: $_error'),
            ),
          ),
        if (home == null)
          const Center(
            child: Padding(
              padding: EdgeInsets.all(32),
              child: CircularProgressIndicator(),
            ),
          )
        else ...[
          _BalanceCard(home: home),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DropdownButtonFormField<String>(
                    initialValue: _symbol,
                    decoration: const InputDecoration(
                      labelText: '通貨ペア',
                      border: OutlineInputBorder(),
                    ),
                    items: home.quotes
                        .map(
                          (quote) => DropdownMenuItem(
                            value: quote.symbol,
                            child: Text(
                              '${quote.symbol}  ${quote.price.toStringAsFixed(5)}',
                            ),
                          ),
                        )
                        .toList(growable: false),
                    onChanged: _busy
                        ? null
                        : (value) {
                            setState(() => _symbol = value);
                          },
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _marginController,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: '証拠金',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _leverageController,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: 'レバレッジ',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: _busy ? null : () => _order('buy'),
                          icon: const Icon(Icons.trending_up_rounded),
                          label: const Text('BUY'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton.tonalIcon(
                          onPressed: _busy ? null : () => _order('sell'),
                          icon: const Icon(Icons.trending_down_rounded),
                          label: const Text('SELL'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '保有ポジション',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (home.positions.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(18),
                child: Text('ポジションはありません。'),
              ),
            )
          else
            ...home.positions.map(
              (position) => _PositionCard(
                position,
                onClose: _busy ? null : () => _close(position),
              ),
            ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy ? null : _reload,
            icon: const Icon(Icons.refresh_rounded),
            label: const Text('価格を更新'),
          ),
        ],
      ],
    );
  }
}

class _CharacterPage extends StatefulWidget {
  const _CharacterPage({
    required this.service,
    required this.playerId,
  });

  final UserService service;
  final String playerId;

  @override
  State<_CharacterPage> createState() => _CharacterPageState();
}

class _CharacterPageState extends State<_CharacterPage> {
  HomeView? _home;

  @override
  void initState() {
    super.initState();
    widget.service.loadHome(widget.playerId).then((value) {
      if (mounted) {
        setState(() => _home = value);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final home = _home;
    if (home == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Text(
          'キャラクター',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        ...home.characters.map(
          (character) => Card(
            child: ListTile(
              leading: CircleAvatar(child: Text(character.rarity)),
              title: Text(character.name),
              subtitle: Text(
                character.skillIds.isEmpty
                    ? 'スキルなし'
                    : 'スキル: ${character.skillIds.join(", ")}',
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.home});

  final HomeView home;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Wrap(
          spacing: 24,
          runSpacing: 12,
          children: [
            _Metric(
              label: '利用可能',
              value: home.availableBalance.toStringAsFixed(0),
            ),
            _Metric(
              label: '評価額',
              value: home.equity.toStringAsFixed(0),
            ),
            _Metric(
              label: '拘束証拠金',
              value: home.lockedMargin.toStringAsFixed(0),
            ),
            _Metric(
              label: '含み損益',
              value: home.unrealizedPnl.toStringAsFixed(0),
            ),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 120,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ],
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

class _PositionCard extends StatelessWidget {
  const _PositionCard(
    this.position, {
    this.onClose,
  });

  final PositionView position;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final positive = position.unrealizedPnl >= 0;

    return Card(
      child: ListTile(
        leading: Icon(
          position.side == 'buy'
              ? Icons.trending_up_rounded
              : Icons.trending_down_rounded,
        ),
        title: Text(
          '${position.symbol}  ${position.side.toUpperCase()}',
        ),
        subtitle: Text(
          '証拠金 ${position.margin.toStringAsFixed(0)} / '
          'x${position.leverage.toStringAsFixed(1)}\n'
          '建値 ${position.entryPrice.toStringAsFixed(5)} → '
          '${position.currentPrice.toStringAsFixed(5)}',
        ),
        isThreeLine: true,
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              '${positive ? "+" : ""}${position.unrealizedPnl.toStringAsFixed(0)}',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                color: positive ? Colors.redAccent : Colors.blueAccent,
              ),
            ),
            if (onClose != null)
              TextButton(
                onPressed: onClose,
                child: const Text('決済'),
              ),
          ],
        ),
      ),
    );
  }
}

class _PlaceholderPage extends StatelessWidget {
  const _PlaceholderPage({
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Card(
        margin: const EdgeInsets.all(24),
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 48),
              const SizedBox(height: 12),
              Text(title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(message),
            ],
          ),
        ),
      ),
    );
  }
}
