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

  Uri _uri(String path) {
    if (baseUrl.isEmpty) {
      return Uri.parse(path);
    }
    return Uri.parse('${baseUrl.replaceAll(RegExp(r"/+$"), "")}$path');
  }

  @override
  Future<List<MarketQuote>> fetchQuotes() async {
    final response = await _client.get(_uri('/api/user/quotes'));
    if (response.statusCode != 200) {
      throw StateError('quote request failed: ${response.statusCode}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    final rows = decoded['quotes'] as List<dynamic>;

    return rows
        .cast<Map<String, dynamic>>()
        .map(
          (row) => MarketQuote(
            symbol: row['symbol'] as String,
            price: (row['price'] as num).toDouble(),
          ),
        )
        .toList(growable: false);
  }
}
