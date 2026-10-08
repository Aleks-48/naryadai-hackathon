import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../lib/app_settings.dart';
import '../lib/translations.dart';

void main() {
  test('all analysis UI labels, including dynamic branches, are translated', () {
    final source = File('lib/ai_review_card.dart').readAsStringSync();
    final strings = RegExp(r"'([^'\n]*[А-Яа-яЁё][^'\n]*)'");
    for (final match in strings.allMatches(source)) {
      final text = match.group(1)!;
      if (text.contains(r'$')) continue;
      expect(enbekTranslations.containsKey(text), isTrue, reason: text);
      for (final language in ['ru', 'kk', 'en']) {
        expect(enbekTranslations[text]![language], isNotEmpty, reason: '$language: $text');
      }
    }
  });

  const errors = [
    'Изображение распознано как точный или похожий дубль; файл не сохранён. Выберите другое фото.',
    'Можно приложить не более пяти активных фото каждой фазы. Сначала завершите доработку или замену.',
    'Предыдущие заменённые фото ещё очищаются; повторите загрузку после завершения очистки',
    'В бригаде нет активного исполнителя.',
  ];
  for (final language in ['ru', 'kk', 'en']) {
    test('all four exact backend errors use existing mapping in $language', () {
      final settings = AppSettings(store: MemorySettingsStore())..language = language;
      addTearDown(settings.dispose);
      for (final error in errors) {
        expect(settings.translateError(error), enbekTranslations[error]![language]);
        if (language != 'ru') expect(settings.translateError(error), isNot(error));
      }
    });
  }
}
