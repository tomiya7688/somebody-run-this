import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ServerSettings {
  static const _key = 'fx_channel_server_url';

  static Future<String> load() async {
    if (kIsWeb) {
      return '';
    }

    final preferences = await SharedPreferences.getInstance();
    return preferences.getString(_key)?.trim() ?? '';
  }

  static Future<void> save(String value) async {
    if (kIsWeb) {
      return;
    }

    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_key, normalize(value));
  }

  static Future<void> clear() async {
    if (kIsWeb) {
      return;
    }

    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_key);
  }

  static String normalize(String value) {
    return value.trim().replaceAll(RegExp(r'/+$'), '');
  }

  static bool isValid(String value) {
    final uri = Uri.tryParse(normalize(value));
    return uri != null &&
        (uri.scheme == 'http' || uri.scheme == 'https') &&
        uri.host.isNotEmpty;
  }
}
