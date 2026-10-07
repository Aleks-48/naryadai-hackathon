import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/app_settings.dart';
import '../lib/main.dart';

class _FailingStore extends MemorySettingsStore {
  bool fail = true;
  @override
  Future<void> write(Map<String, String> next) async {
    if (fail) throw StateError('fixture');
    await super.write(next);
  }
}

void main() {
  test('language and theme reload from the store; invalid values fall back', () async {
    final store = MemorySettingsStore();
    final settings = AppSettings(store: store);
    settings.setLanguage('kk');
    settings.setTheme(ThemeMode.dark);
    settings.setLanguage('en');
    await settings.saved;
    expect(store.values, {'language': 'en', 'theme': 'dark'});
    final restored = AppSettings(store: store);
    await restored.load();
    expect(restored.language, 'en');
    expect(restored.themeMode, ThemeMode.dark);
    final invalid = AppSettings(store: MemorySettingsStore({'language': 'xx', 'theme': 'xx'}));
    await invalid.load();
    expect(invalid.language, 'ru');
    expect(invalid.themeMode, ThemeMode.system);
    settings.dispose(); restored.dispose(); invalid.dispose();
  });

  test('failed save is visible and a later successful save clears the warning', () async {
    final store = _FailingStore();
    final settings = AppSettings(store: store);
    settings.setLanguage('kk');
    await settings.saved;
    expect(settings.saveFailed, isTrue);
    expect(settings.language, 'kk');
    store.fail = false;
    settings.setTheme(ThemeMode.light);
    await settings.saved;
    expect(settings.saveFailed, isFalse);
    expect(store.values['language'], 'kk');
    settings.dispose();
  });

  for (final brightness in Brightness.values) {
    test('small-text palette contrast is at least 4.5:1 in ${brightness.name}', () {
      final scheme = enbekTheme(brightness).colorScheme;
      for (final pair in [
        [scheme.onSurface, scheme.surface],
        [scheme.onSurfaceVariant, scheme.surface],
        [scheme.onPrimary, scheme.primary],
        [scheme.onErrorContainer, scheme.errorContainer],
        [scheme.onTertiaryContainer, scheme.tertiaryContainer],
      ]) {
        final a = pair[0].computeLuminance(), b = pair[1].computeLuminance();
        final contrast = ((a > b ? a : b) + .05) / ((a < b ? a : b) + .05);
        expect(contrast, greaterThanOrEqualTo(4.5));
      }
    });
  }

  testWidgets('live language/theme changes preserve login input', (tester) async {
    final settings = AppSettings(store: MemorySettingsStore());
    await tester.pumpWidget(EnbekPlusApp(settings: settings));
    await tester.pumpAndSettle();
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(1), 'unchanged-user');
    await tester.enterText(fields.at(2), ' unchanged password ');
    settings.setLanguage('en');
    settings.setTheme(ThemeMode.dark);
    await tester.pumpAndSettle();
    expect(find.text(settings.translate('Мобильный клиент нарядной системы')), findsOneWidget);
    expect(tester.widget<TextFormField>(fields.at(1)).controller!.text, 'unchanged-user');
    expect(tester.widget<TextFormField>(fields.at(2)).controller!.text, ' unchanged password ');
    expect(Theme.of(tester.element(find.byType(Scaffold))).brightness, Brightness.dark);
    settings.setLanguage('kk');
    await tester.pumpAndSettle();
    expect(find.text(settings.translate('Мобильный клиент нарядной системы')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await settings.saved;
    settings.dispose();
  });

  testWidgets('system theme follows platform brightness without losing locale', (tester) async {
    final settings = AppSettings(store: MemorySettingsStore());
    settings.setLanguage('kk');
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    await tester.pumpWidget(EnbekPlusApp(settings: settings));
    await tester.pumpAndSettle();
    expect(Theme.of(tester.element(find.byType(Scaffold))).brightness, Brightness.dark);
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.light;
    await tester.pumpAndSettle();
    expect(Theme.of(tester.element(find.byType(Scaffold))).brightness, Brightness.light);
    expect(settings.language, 'kk');
    await tester.pumpWidget(const SizedBox.shrink());
    await settings.saved;
    settings.dispose();
  });
}
