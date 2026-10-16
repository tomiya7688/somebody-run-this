class MarketQuote {
  const MarketQuote({
    required this.symbol,
    required this.price,
  });

  final String symbol;
  final double price;
}

abstract interface class UserGateway {
  Future<List<MarketQuote>> fetchQuotes();
}

class UserService {
  const UserService(this._gateway);

  final UserGateway _gateway;

  Future<List<MarketQuote>> loadQuotes() => _gateway.fetchQuotes();
}
