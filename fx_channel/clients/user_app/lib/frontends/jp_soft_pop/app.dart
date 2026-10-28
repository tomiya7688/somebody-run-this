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
      _GachaPage(
        service: widget.service,
        playerId: widget.playerId,
      ),
      _RankingPage(
        service: widget.service,
        playerId: widget.playerId,
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
    unawaited(_reload());
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
            _SeasonCard(season: _home!.season),
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
    unawaited(_reload());
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
  String? _symbol;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
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

  Future<void> _useSkill(SkillView skill) async {
    final symbol = _symbol;
    if (symbol == null) return;

    setState(() => _busy = true);
    try {
      final result = await widget.service.useSkill(
        playerId: widget.playerId,
        skillId: skill.id,
        symbol: symbol,
      );
      if (!mounted) return;

      if (!result.ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(result.message)),
        );
        return;
      }

      final title = result.data['title']?.toString() ?? skill.name;
      final rawResult = result.data['result'];
      final detail = rawResult is Map
          ? rawResult.entries
              .map((entry) => '${entry.key}: ${entry.value}')
              .join('\n')
          : '';
      final disclaimer = result.data['disclaimer']?.toString();

      await showDialog<void>(
        context: context,
        builder: (context) {
          return AlertDialog(
            title: Text(title),
            content: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(result.message),
                  if (detail.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    SelectableText(detail),
                  ],
                  if (disclaimer != null && disclaimer.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    Text(
                      disclaimer,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ],
              ),
            ),
            actions: [
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('OK'),
              ),
            ],
          );
        },
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final home = _home;
    if (home == null) {
      return Center(
        child: _error == null
            ? const CircularProgressIndicator()
            : Text('接続エラー: $_error'),
      );
    }

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
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
                  [
                    '所持: ${character.copies}',
                    character.skillIds.isEmpty
                        ? 'スキルなし'
                        : 'スキル: ${character.skillIds.join(", ")}',
                  ].join(' / '),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            'スキル',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          if (home.quotes.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: DropdownButtonFormField<String>(
                initialValue: _symbol,
                decoration: const InputDecoration(
                  labelText: '分析する通貨ペア',
                  border: OutlineInputBorder(),
                ),
                items: home.quotes
                    .map(
                      (quote) => DropdownMenuItem(
                        value: quote.symbol,
                        child: Text(quote.symbol),
                      ),
                    )
                    .toList(growable: false),
                onChanged: _busy
                    ? null
                    : (value) => setState(() => _symbol = value),
              ),
            ),
          if (home.skills.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text('使用できるスキルはありません。'),
              ),
            )
          else
            ...home.skills.map(
              (skill) => Card(
                child: ListTile(
                  leading: const Icon(Icons.psychology_alt_rounded),
                  title: Text(skill.name),
                  subtitle: Text(
                    '${skill.description}\n'
                    'Cooldown: ${skill.cooldownSeconds}s',
                  ),
                  isThreeLine: true,
                  trailing: FilledButton.tonal(
                    onPressed: _busy || _symbol == null
                        ? null
                        : () => _useSkill(skill),
                    child: const Text('使う'),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}


class _GachaPage extends StatefulWidget {
  const _GachaPage({
    required this.service,
    required this.playerId,
  });

  final UserService service;
  final String playerId;

  @override
  State<_GachaPage> createState() => _GachaPageState();
}

class _GachaPageState extends State<_GachaPage> {
  HomeView? _home;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
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

  Future<void> _draw(GachaPoolView pool, int count) async {
    setState(() => _busy = true);
    try {
      final result = await widget.service.drawGacha(
        playerId: widget.playerId,
        gachaId: pool.id,
        count: count,
      );
      if (!mounted) return;

      if (!result.ok) {
        _showMessage(result.message);
        return;
      }

      final rows = (result.data['results'] as List<dynamic>? ?? const [])
          .cast<Map<String, dynamic>>();

      await showDialog<void>(
        context: context,
        builder: (context) {
          return AlertDialog(
            title: Text('$count回ガチャ結果'),
            content: SizedBox(
              width: 420,
              child: ListView(
                shrinkWrap: true,
                children: rows.map((row) {
                  final isNew = row['is_new'] == true;
                  return ListTile(
                    leading: CircleAvatar(
                      child: Text(row['rarity'].toString()),
                    ),
                    title: Text(row['name'].toString()),
                    subtitle: Text(
                      isNew
                          ? 'NEW!'
                          : '所持数 ${row['copies']}',
                    ),
                  );
                }).toList(growable: false),
              ),
            ),
            actions: [
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('OK'),
              ),
            ],
          );
        },
      );

      await _reload();
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

  bool _canDraw(GachaPoolView pool, int count) {
    final balance = _home?.wallet[pool.currency] ?? 0;
    return !_busy && balance >= pool.cost * count;
  }

  @override
  Widget build(BuildContext context) {
    final home = _home;

    if (home == null && _error == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'ガチャ',
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
          if (home != null) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: home.wallet.entries
                      .map(
                        (entry) => Chip(
                          avatar: const Icon(Icons.diamond_rounded, size: 18),
                          label: Text('${entry.key}: ${entry.value}'),
                        ),
                      )
                      .toList(growable: false),
                ),
              ),
            ),
            const Card(
              child: Padding(
                padding: EdgeInsets.all(14),
                child: Text(
                  '有償通貨の購入処理はまだ未接続です。'
                  '現在は運営アプリから付与してテストできます。',
                ),
              ),
            ),
            ...home.gachaPools.map(
              (pool) => Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        pool.name,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 4),
                      Text('1回 ${pool.cost} ${pool.currency}'),
                      const SizedBox(height: 8),
                      ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: const Text('排出率'),
                        children: pool.entries
                            .map(
                              (entry) => ListTile(
                                dense: true,
                                title: Text(
                                  '${entry.rarity}  ${entry.name}',
                                ),
                                trailing: Text(
                                  '${(entry.probability * 100).toStringAsFixed(2)}%',
                                ),
                              ),
                            )
                            .toList(growable: false),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: FilledButton(
                              onPressed: _canDraw(pool, 1)
                                  ? () => _draw(pool, 1)
                                  : null,
                              child: const Text('1回'),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: FilledButton.tonal(
                              onPressed: _canDraw(pool, 10)
                                  ? () => _draw(pool, 10)
                                  : null,
                              child: const Text('10回'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}


class _RankingPage extends StatefulWidget {
  const _RankingPage({
    required this.service,
    required this.playerId,
  });

  final UserService service;
  final String playerId;

  @override
  State<_RankingPage> createState() => _RankingPageState();
}

class _RankingPageState extends State<_RankingPage> {
  List<RankingEntryView>? _ranking;
  String? _serverPlayerId;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
  }

  Future<void> _reload() async {
    try {
      final results = await Future.wait([
        widget.service.loadHome(widget.playerId),
        widget.service.loadRanking(widget.playerId),
      ]);
      final home = results[0] as HomeView;
      final ranking = results[1] as List<RankingEntryView>;
      if (!mounted) return;
      setState(() {
        _serverPlayerId = home.playerId;
        _ranking = ranking;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  String _shortId(String value) {
    if (value.length <= 10) return value;
    return '${value.substring(0, 6)}…${value.substring(value.length - 4)}';
  }

  @override
  Widget build(BuildContext context) {
    final ranking = _ranking;

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Text(
            'ランキング',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          const Text('現在の評価額でサーバーが順位を計算します。'),
          const SizedBox(height: 8),
          if (_error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text('接続エラー: $_error'),
              ),
            )
          else if (ranking == null)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: CircularProgressIndicator(),
              ),
            )
          else if (ranking.isEmpty)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(18),
                child: Text('まだランキング参加者はいません。'),
              ),
            )
          else
            ...ranking.map(
              (entry) {
                final isMe = entry.playerId == _serverPlayerId;
                return Card(
                  child: ListTile(
                    leading: CircleAvatar(
                      child: Text(entry.rank.toString()),
                    ),
                    title: Text(
                      isMe
                          ? 'あなた'
                          : _shortId(entry.playerId),
                    ),
                    subtitle: Text(
                      '利用可能 ${entry.availableBalance.toStringAsFixed(0)} / '
                      '含み損益 ${entry.unrealizedPnl.toStringAsFixed(0)}',
                    ),
                    trailing: Text(
                      entry.equity.toStringAsFixed(0),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                );
              },
            ),
        ],
      ),
    );
  }
}


class _SeasonCard extends StatelessWidget {
  const _SeasonCard({required this.season});

  final SeasonView season;

  String _formatEnd() {
    final raw = season.endAtIso;
    if (raw == null) return '期限なし';

    final parsed = DateTime.tryParse(raw);
    if (parsed == null) return raw;

    final local = parsed.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');
    return '${local.year}/${two(local.month)}/${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.calendar_month_rounded),
        title: Text(
          season.enabled ? season.id : '常設シーズン',
        ),
        subtitle: Text('終了: ${_formatEnd()}'),
      ),
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
            SizedBox(
              width: 260,
              child: SelectableText(
                'Player ID: ${home.playerId}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
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
