import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

class PlayerIdentity {
  static const _key = 'fx_channel_player_id';

  static Future<String> loadOrCreate() async {
    final preferences = await SharedPreferences.getInstance();
    final current = preferences.getString(_key);
    if (current != null && current.isNotEmpty) {
      return current;
    }

    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    final id = bytes
        .map((value) => value.toRadixString(16).padLeft(2, '0'))
        .join();

    await preferences.setString(_key, id);
    return id;
  }
}
