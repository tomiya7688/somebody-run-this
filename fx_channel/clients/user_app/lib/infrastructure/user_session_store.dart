import 'package:shared_preferences/shared_preferences.dart';

class UserSessionStore {
  static const _prefix = 'fx_channel_user_session_';

  String _key(String serverUrl) {
    final normalized = serverUrl.trim().isEmpty ? 'same-origin' : serverUrl.trim();
    return '$_prefix${Uri.encodeComponent(normalized)}';
  }

  Future<String?> load(String serverUrl) async {
    final preferences = await SharedPreferences.getInstance();
    final token = preferences.getString(_key(serverUrl));
    if (token == null || token.trim().isEmpty) {
      return null;
    }
    return token;
  }

  Future<void> save(String serverUrl, String token) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_key(serverUrl), token);
  }

  Future<void> clear(String serverUrl) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_key(serverUrl));
  }
}
