class MarketQuote {
  const MarketQuote({
    required this.symbol,
    required this.price,
  });

  factory MarketQuote.fromJson(Map<String, dynamic> json) {
    return MarketQuote(
      symbol: json['symbol'] as String,
      price: (json['price'] as num).toDouble(),
    );
  }

  final String symbol;
  final double price;
}

class PositionView {
  const PositionView({
    required this.id,
    required this.symbol,
    required this.side,
    required this.margin,
    required this.leverage,
    required this.exposure,
    required this.entryPrice,
    required this.currentPrice,
    required this.unrealizedPnl,
  });

  factory PositionView.fromJson(Map<String, dynamic> json) {
    return PositionView(
      id: json['id'] as String,
      symbol: json['symbol'] as String,
      side: json['side'] as String,
      margin: (json['margin'] as num).toDouble(),
      leverage: (json['leverage'] as num).toDouble(),
      exposure: (json['exposure'] as num).toDouble(),
      entryPrice: (json['entry_price'] as num).toDouble(),
      currentPrice: (json['current_price'] as num).toDouble(),
      unrealizedPnl: (json['unrealized_pnl'] as num).toDouble(),
    );
  }

  final String id;
  final String symbol;
  final String side;
  final double margin;
  final double leverage;
  final double exposure;
  final double entryPrice;
  final double currentPrice;
  final double unrealizedPnl;
}

class CharacterView {
  const CharacterView({
    required this.id,
    required this.name,
    required this.rarity,
    required this.skillIds,
    required this.copies,
  });

  factory CharacterView.fromJson(Map<String, dynamic> json) {
    return CharacterView(
      id: json['id'] as String,
      name: json['name'] as String,
      rarity: json['rarity'] as String,
      skillIds: (json['skill_ids'] as List<dynamic>)
          .map((value) => value.toString())
          .toList(growable: false),
      copies: (json['copies'] as num?)?.toInt() ?? 1,
    );
  }

  final String id;
  final String name;
  final String rarity;
  final List<String> skillIds;
  final int copies;
}

class SkillView {
  const SkillView({
    required this.id,
    required this.name,
    required this.type,
    required this.description,
    required this.cooldownSeconds,
  });

  factory SkillView.fromJson(Map<String, dynamic> json) {
    return SkillView(
      id: json['id'] as String,
      name: json['name'] as String,
      type: json['type'] as String,
      description: json['description'] as String,
      cooldownSeconds: (json['cooldown_seconds'] as num).toInt(),
    );
  }

  final String id;
  final String name;
  final String type;
  final String description;
  final int cooldownSeconds;
}

class GachaEntryView {
  const GachaEntryView({
    required this.characterId,
    required this.name,
    required this.rarity,
    required this.probability,
  });

  factory GachaEntryView.fromJson(Map<String, dynamic> json) {
    return GachaEntryView(
      characterId: json['character_id'] as String,
      name: json['name'] as String,
      rarity: json['rarity'] as String,
      probability: (json['probability'] as num).toDouble(),
    );
  }

  final String characterId;
  final String name;
  final String rarity;
  final double probability;
}

class GachaPoolView {
  const GachaPoolView({
    required this.id,
    required this.name,
    required this.currency,
    required this.cost,
    required this.entries,
  });

  factory GachaPoolView.fromJson(Map<String, dynamic> json) {
    return GachaPoolView(
      id: json['id'] as String,
      name: json['name'] as String,
      currency: json['currency'] as String,
      cost: (json['cost'] as num).toInt(),
      entries: (json['entries'] as List<dynamic>)
          .cast<Map<String, dynamic>>()
          .map(GachaEntryView.fromJson)
          .toList(growable: false),
    );
  }

  final String id;
  final String name;
  final String currency;
  final int cost;
  final List<GachaEntryView> entries;
}

class HomeView {
  const HomeView({
    required this.playerId,
    required this.displayName,
    required this.availableBalance,
    required this.equity,
    required this.lockedMargin,
    required this.unrealizedPnl,
    required this.quotes,
    required this.positions,
    required this.characters,
    required this.skills,
    required this.wallet,
    required this.gachaPools,
  });

  final String playerId;
  final String displayName;
  final double availableBalance;
  final double equity;
  final double lockedMargin;
  final double unrealizedPnl;
  final List<MarketQuote> quotes;
  final List<PositionView> positions;
  final List<CharacterView> characters;
  final List<SkillView> skills;
  final Map<String, int> wallet;
  final List<GachaPoolView> gachaPools;
}

class ActionResult {
  const ActionResult({
    required this.ok,
    required this.message,
    required this.data,
  });

  final bool ok;
  final String message;
  final Map<String, dynamic> data;
}

abstract interface class UserGateway {
  Future<List<MarketQuote>> fetchQuotes();
  Future<HomeView> fetchHome(String playerId);

  Future<ActionResult> postAction({
    required String playerId,
    required String action,
    required Map<String, dynamic> payload,
  });
}

class UserService {
  const UserService(this._gateway);

  final UserGateway _gateway;

  Future<List<MarketQuote>> loadQuotes() => _gateway.fetchQuotes();

  Future<HomeView> loadHome(String playerId) => _gateway.fetchHome(playerId);

  Future<ActionResult> placeOrder({
    required String playerId,
    required String symbol,
    required String side,
    required double margin,
    required double leverage,
  }) {
    return _gateway.postAction(
      playerId: playerId,
      action: 'place_order',
      payload: {
        'symbol': symbol,
        'side': side,
        'margin': margin,
        'leverage': leverage,
      },
    );
  }

  Future<ActionResult> closePosition({
    required String playerId,
    required String positionId,
  }) {
    return _gateway.postAction(
      playerId: playerId,
      action: 'close_position',
      payload: {'position_id': positionId},
    );
  }

  Future<ActionResult> useSkill({
    required String playerId,
    required String skillId,
    required String symbol,
  }) {
    return _gateway.postAction(
      playerId: playerId,
      action: 'use_skill',
      payload: {
        'skill_id': skillId,
        'symbol': symbol,
      },
    );
  }

  Future<ActionResult> drawGacha({
    required String playerId,
    required String gachaId,
    required int count,
  }) {
    return _gateway.postAction(
      playerId: playerId,
      action: 'draw_gacha',
      payload: {
        'gacha_id': gachaId,
        'count': count,
      },
    );
  }
}
