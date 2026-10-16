import 'dart:convert';

import 'package:http/http.dart' as http;

import '../application/user_service.dart';

class HttpUserGateway implements UserGateway {
  HttpUserGateway({
    required this.baseUrl,
    http.Client? client,
  }) : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Uri _uri(String path, [Map<String, String>? query]) {
    final uri = baseUrl.isEmpty
        ? Uri.parse(path)
        : Uri.parse('${baseUrl.replaceAll(RegExp(r"/+$"), "")}$path');
    return query == null ? uri : uri.replace(queryParameters: query);
  }

  Future<Map<String, dynamic>> _decode(http.Response response) async {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('HTTP ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw StateError('Server response must be a JSON object.');
    }
    return decoded;
  }

  @override
  Future<List<MarketQuote>> fetchQuotes() async {
    final response = await _client.get(_uri('/api/user/quotes'));
    final decoded = await _decode(response);
    final rows = decoded['quotes'] as List<dynamic>;

    return rows
        .cast<Map<String, dynamic>>()
        .map(MarketQuote.fromJson)
        .toList(growable: false);
  }

  @override
  Future<HomeView> fetchHome(String playerId) async {
    final response = await _client.get(
      _uri('/api/user/home', {'player_id': playerId}),
    );
    final decoded = await _decode(response);
    final player = decoded['player'] as Map<String, dynamic>;
    final portfolio = decoded['portfolio'] as Map<String, dynamic>;

    final quotes = (decoded['quotes'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(MarketQuote.fromJson)
        .toList(growable: false);

    final positions = (decoded['positions'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(PositionView.fromJson)
        .toList(growable: false);

    final characters = (decoded['characters'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(CharacterView.fromJson)
        .toList(growable: false);

    return HomeView(
      playerId: player['player_id'] as String,
      displayName: player['display_name'] as String,
      availableBalance: (portfolio['available_balance'] as num).toDouble(),
      equity: (portfolio['equity'] as num).toDouble(),
      lockedMargin: (portfolio['locked_margin'] as num).toDouble(),
      unrealizedPnl: (portfolio['unrealized_pnl'] as num).toDouble(),
      quotes: quotes,
      positions: positions,
      characters: characters,
    );
  }

  @override
  Future<ActionResult> postAction({
    required String playerId,
    required String action,
    required Map<String, dynamic> payload,
  }) async {
    final response = await _client.post(
      _uri('/api/user/action'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'player_id': playerId,
        'action': action,
        'payload': payload,
      }),
    );
    final decoded = await _decode(response);

    return ActionResult(
      ok: decoded['ok'] as bool,
      message: decoded['message'] as String,
      data: (decoded['data'] as Map<String, dynamic>?) ?? const {},
    );
  }
}
