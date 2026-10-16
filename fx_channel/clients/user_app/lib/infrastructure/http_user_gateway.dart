import 'dart:convert';

import 'package:http/http.dart' as http;

import '../application/user_service.dart';
import 'user_session_store.dart';

class HttpUserGateway implements UserGateway {
  HttpUserGateway({
    required this.baseUrl,
    http.Client? client,
    UserSessionStore? sessionStore,
  })  : _client = client ?? http.Client(),
        _sessionStore = sessionStore ?? UserSessionStore();

  final String baseUrl;
  final http.Client _client;
  final UserSessionStore _sessionStore;

  String? _sessionToken;

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

  Future<String> _ensureSession({bool forceNew = false}) async {
    if (!forceNew && _sessionToken != null) {
      return _sessionToken!;
    }

    if (!forceNew) {
      final saved = await _sessionStore.load(baseUrl);
      if (saved != null) {
        _sessionToken = saved;
        return saved;
      }
    }

    final response = await _client.post(_uri('/api/user/session'));
    final decoded = await _decode(response);
    final token = decoded['token'] as String;

    _sessionToken = token;
    await _sessionStore.save(baseUrl, token);
    return token;
  }

  Future<http.Response> _authorizedGet(Uri uri) async {
    var token = await _ensureSession();
    var response = await _client.get(
      uri,
      headers: {'Authorization': 'Bearer $token'},
    );

    if (response.statusCode == 401) {
      await _sessionStore.clear(baseUrl);
      _sessionToken = null;
      token = await _ensureSession(forceNew: true);
      response = await _client.get(
        uri,
        headers: {'Authorization': 'Bearer $token'},
      );
    }

    return response;
  }

  Future<http.Response> _authorizedPost(
    Uri uri,
    Map<String, dynamic> body,
  ) async {
    var token = await _ensureSession();
    var response = await _client.post(
      uri,
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
      body: jsonEncode(body),
    );

    if (response.statusCode == 401) {
      await _sessionStore.clear(baseUrl);
      _sessionToken = null;
      token = await _ensureSession(forceNew: true);
      response = await _client.post(
        uri,
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
        body: jsonEncode(body),
      );
    }

    return response;
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
    // playerId is intentionally not sent. The signed token is authoritative.
    final response = await _authorizedGet(_uri('/api/user/home'));
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

    final walletRaw = decoded['wallet'] as Map<String, dynamic>;
    final wallet = {
      for (final entry in walletRaw.entries)
        entry.key: (entry.value as num).toInt(),
    };

    final gachaPools = (decoded['gacha_pools'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(GachaPoolView.fromJson)
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
      wallet: wallet,
      gachaPools: gachaPools,
    );
  }

  @override
  Future<ActionResult> postAction({
    required String playerId,
    required String action,
    required Map<String, dynamic> payload,
  }) async {
    // playerId is intentionally not sent. The signed token is authoritative.
    final response = await _authorizedPost(
      _uri('/api/user/action'),
      {
        'action': action,
        'payload': payload,
      },
    );
    final decoded = await _decode(response);

    return ActionResult(
      ok: decoded['ok'] as bool,
      message: decoded['message'] as String,
      data: (decoded['data'] as Map<String, dynamic>?) ?? const {},
    );
  }
}
