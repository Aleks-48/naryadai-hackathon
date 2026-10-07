import 'package:flutter/material.dart';

import 'translations.dart';

const _supportedLanguages = {'ru', 'kk', 'en'};

abstract class SettingsStore {
  Future<Map<String, String>> read();
  Future<void> write(Map<String, String> values);
}

/// Tests and embedded screens can use this store without platform plugins.
class MemorySettingsStore implements SettingsStore {
  MemorySettingsStore([Map<String, String>? initial]) : values = {...?initial};
  Map<String, String> values;
  @override
  Future<Map<String, String>> read() async => {...values};
  @override
  Future<void> write(Map<String, String> next) async { values = {...next}; }
}

class AppSettings extends ChangeNotifier {
  AppSettings({required this.store});
  static final fallback = AppSettings(store: MemorySettingsStore());
  final SettingsStore store;
  String language = 'ru';
  ThemeMode themeMode = ThemeMode.system;
  bool saveFailed = false;
  bool _disposed = false;
  Future<void> _pendingWrite = Future<void>.value();

  Future<void> load() async {
    try {
      final values = await store.read();
      final storedLanguage = values['language'];
      if (_supportedLanguages.contains(storedLanguage)) {
        language = storedLanguage!;
      }
      themeMode = switch (values['theme']) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
    } catch (_) {
      saveFailed = true;
    }
  }

  void setLanguage(String value) {
    if (!_supportedLanguages.contains(value) || language == value) return;
    language = value;
    notifyListeners();
    _save();
  }

  void setTheme(ThemeMode value) {
    if (themeMode == value) return;
    themeMode = value;
    notifyListeners();
    _save();
  }

  void _save() {
    final snapshot = {'language': language, 'theme': themeMode.name};
    // Serialize rapid changes so an older save cannot overwrite a newer choice.
    _pendingWrite = _pendingWrite.then((_) async {
      try {
        await store.write(snapshot);
        saveFailed = false;
      } catch (_) {
        saveFailed = true;
      }
      if (!_disposed) notifyListeners();
    });
  }

  Future<void> get saved => _pendingWrite;

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  String translate(String source, [Map<String, Object?> values = const {}]) {
    var result = enbekTranslations[source]?[language] ?? source;
    for (final entry in values.entries) {
      result = result.replaceAll('{${entry.key}}', '${entry.value ?? ''}');
    }
    return result;
  }

  String translateError(String source) {
    if (enbekTranslations.containsKey(source)) return translate(source);
    for (final template in const [
      'Сервер вернул некорректный ответ ({statusCode}).',
      'Ошибка сервера ({statusCode}).',
    ]) {
      final pattern = RegExp('^${RegExp.escape(template).replaceFirst(RegExp.escape('{statusCode}'), r'(\d{3})')}\$');
      final match = pattern.firstMatch(source);
      if (match != null) return translate(template, {'statusCode': match.group(1)});
    }
    const statusLabels = {
      'Выдан', 'Принят', 'Очередь', 'Отклонён', 'В работе',
      'Приостановлен', 'Исполнено', 'Проверка ИИ', 'Доработка', 'Закрыт',
    };
    final transition = RegExp(r'^Переход (.+) → (.+) сейчас недоступен$').firstMatch(source);
    if (transition != null && statusLabels.contains(transition.group(1)) && statusLabels.contains(transition.group(2))) {
      return translate('Переход {from} → {to} сейчас недоступен', {
        'from': translate(transition.group(1)!), 'to': translate(transition.group(2)!),
      });
    }
    const acceptancePrefix = 'Нельзя принять наряд: ';
    const acceptanceIssues = [
      'нет описания работы', 'не выбран код неисправности',
      'не указано время', 'не подтверждены материалы',
      'для внепланового наряда нужно фото после выполнения',
      'результат проверки требует доработки; мастер может направить наряд на доработку',
    ];
    if (source.startsWith(acceptancePrefix)) {
      var remaining = source.substring(acceptancePrefix.length);
      final translated = <String>[];
      while (remaining.isNotEmpty) {
        String? found;
        for (final issue in acceptanceIssues) {
          if (remaining == issue || remaining.startsWith('$issue; ')) { found = issue; break; }
        }
        if (found == null) return source; // Unknown content remains verbatim.
        translated.add(translate(found));
        remaining = remaining.length == found.length ? '' : remaining.substring(found.length + 2);
      }
      if (translated.isNotEmpty) return translate('Нельзя принять наряд: {issues}', {'issues': translated.join('; ')});
    }
    if (source.startsWith('SocketException:') || source.startsWith('TimeoutException')) {
      return translate('Требуется подключение к серверу.');
    }
    // Unknown backend messages stay verbatim; never translate arbitrary data.
    return source;
  }
}

class AppSettingsScope extends InheritedNotifier<AppSettings> {
  const AppSettingsScope({required AppSettings settings, required super.child, super.key})
      : super(notifier: settings);
  static AppSettings of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppSettingsScope>()?.notifier ?? AppSettings.fallback;
}

extension EnbekLocalization on BuildContext {
  AppSettings get settings => AppSettingsScope.of(this);
  String tr(String source, [Map<String, Object?> values = const {}]) => settings.translate(source, values);
  String trError(String source) => settings.translateError(source);
}

class AppearanceSettings extends StatelessWidget {
  const AppearanceSettings({super.key, this.compact = false, this.onLanguageChanged});
  final bool compact;
  final VoidCallback? onLanguageChanged;
  @override
  Widget build(BuildContext context) {
    final settings = context.settings;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      DropdownButtonFormField<String>(
        key: ValueKey('language-${settings.language}'),
        initialValue: settings.language,
        isExpanded: true,
        decoration: InputDecoration(labelText: context.tr('Язык'), prefixIcon: const Icon(Icons.language)),
        items: const [
          DropdownMenuItem(value: 'ru', child: Text('Русский')),
          DropdownMenuItem(value: 'kk', child: Text('Қазақша')),
          DropdownMenuItem(value: 'en', child: Text('English')),
        ],
        onChanged: (value) {
          if (value == null) return;
          FocusManager.instance.primaryFocus?.unfocus();
          settings.setLanguage(value);
          // Existing validation text must follow the newly selected language.
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (context.mounted) onLanguageChanged?.call();
          });
        },
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<ThemeMode>(
        key: ValueKey('theme-${settings.themeMode.name}'),
        initialValue: settings.themeMode,
        isExpanded: true,
        decoration: InputDecoration(labelText: context.tr('Тема'), prefixIcon: const Icon(Icons.palette_outlined)),
        items: [
          DropdownMenuItem(value: ThemeMode.system, child: Text(context.tr('Как в системе'))),
          DropdownMenuItem(value: ThemeMode.light, child: Text(context.tr('Светлая'))),
          DropdownMenuItem(value: ThemeMode.dark, child: Text(context.tr('Тёмная'))),
        ],
        onChanged: (value) { if (value != null) settings.setTheme(value); },
      ),
      if (settings.saveFailed) ...[
        const SizedBox(height: 8),
        Text(context.tr('Не удалось сохранить настройки. Выбор действует до закрытия приложения.'),
          style: TextStyle(color: Theme.of(context).colorScheme.error)),
      ] else if (!compact) ...[
        const SizedBox(height: 8),
        Text(context.tr('Язык применяется сразу. Данные нарядов остаются на исходном языке.'),
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      ],
    ]);
  }
}

ThemeData enbekTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: const Color(0xff245d52), brightness: brightness).copyWith(
    primary: dark ? const Color(0xff8ad3bd) : const Color(0xff245d52),
    onPrimary: dark ? const Color(0xff07382d) : Colors.white,
    secondary: dark ? const Color(0xffa8cddf) : const Color(0xff34576a),
    surface: dark ? const Color(0xff15232b) : Colors.white,
    onSurface: dark ? const Color(0xffe1ecf0) : const Color(0xff1d2d36),
    onSurfaceVariant: dark ? const Color(0xffadc0ca) : const Color(0xff50636d),
    error: dark ? const Color(0xffffb4ad) : const Color(0xffa23832),
    errorContainer: dark ? const Color(0xff492d2d) : const Color(0xfffceae8),
    onErrorContainer: dark ? const Color(0xffffc9c3) : const Color(0xff74231f),
    tertiaryContainer: dark ? const Color(0xff3e331d) : const Color(0xfff5ecd5),
    onTertiaryContainer: dark ? const Color(0xffebd8aa) : const Color(0xff4d3d1e),
  );
  final background = dark ? const Color(0xff0f1b22) : const Color(0xfff4f7f7);
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    appBarTheme: AppBarTheme(backgroundColor: background, foregroundColor: scheme.onSurface, centerTitle: false),
    cardTheme: CardThemeData(color: scheme.surface, elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18), side: BorderSide(color: scheme.outlineVariant))),
    inputDecorationTheme: InputDecorationTheme(
      filled: true, fillColor: scheme.surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: scheme.outline)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(
      minimumSize: const Size.fromHeight(50),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)))),
    outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(minimumSize: const Size(48, 50))),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(minimumSize: const Size(48, 48))),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(minimumSize: const Size(48, 48))),
    materialTapTargetSize: MaterialTapTargetSize.padded,
    visualDensity: VisualDensity.standard,
  );
}
