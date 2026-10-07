import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'app_settings.dart';

/// Non-sensitive display preferences only. Auth/session data stays in memory.
class PreferencesSettingsStore implements SettingsStore {
  PreferencesSettingsStore({SharedPreferencesAsync? preferences})
      : _preferences = preferences ?? SharedPreferencesAsync();
  final SharedPreferencesAsync _preferences;
  static const _key = 'enbekplus.appearance.v1';

  @override
  Future<Map<String, String>> read() async {
    final raw = await _preferences.getString(_key);
    if (raw == null) return {};
    final decoded = jsonDecode(raw);
    if (decoded is! Map<String, dynamic>) return {};
    return {
      if (decoded['language'] is String) 'language': decoded['language'] as String,
      if (decoded['theme'] is String) 'theme': decoded['theme'] as String,
    };
  }

  @override
  Future<void> write(Map<String, String> values) => _preferences.setString(
    _key,
    jsonEncode({'language': values['language'], 'theme': values['theme']}),
  );
}
