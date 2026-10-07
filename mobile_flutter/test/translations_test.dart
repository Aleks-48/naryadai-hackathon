import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../lib/app_settings.dart';
import '../lib/translations.dart';

List<String> placeholders(String value) {
  final result = RegExp(r'\{[a-zA-Z][a-zA-Z0-9_]*\}')
      .allMatches(value)
      .map((match) => match.group(0)!)
      .toList();
  result.sort();
  return result;
}

void main() {
  group('Translation catalog', () {
    test('every entry has complete Russian, Kazakh and English values', () {
      expect(enbekTranslations.length, greaterThan(300));
      for (final entry in enbekTranslations.entries) {
        expect(entry.value.keys, unorderedEquals(['ru', 'kk', 'en']),
            reason: entry.key);
        expect(entry.value['ru'], entry.key,
            reason: 'Russian source text must not change');
        for (final language in ['ru', 'kk', 'en']) {
          expect(entry.value[language]!.trim(), isNotEmpty,
              reason: '${entry.key}: $language');
        }
      }
    });

    test('named placeholders occur equally often in all languages', () {
      for (final entry in enbekTranslations.entries) {
        final source = placeholders(entry.key);
        for (final language in ['ru', 'kk', 'en']) {
          expect(placeholders(entry.value[language]!), orderedEquals(source),
              reason: '${entry.key}: $language');
        }
      }
    });

    test('all direct literal localization calls have catalog entries', () {
      // Flutter tests run from the application root. Read production source,
      // including new feature files, to catch missing keys in future changes.
      final lib = Directory('lib');
      expect(lib.existsSync(), isTrue);
      final literalCall = RegExp(
        r"""\b(?:tr|translate)\(\s*'((?:\\.|[^'\\])*)'""",
      );
      final missing = <String>[];
      for (final file in lib.listSync(recursive: true).whereType<File>()) {
        if (!file.path.endsWith('.dart') ||
            file.path.endsWith('translations.dart')) {
          continue;
        }
        for (final match in literalCall.allMatches(file.readAsStringSync())) {
          final key = match.group(1)!;
          // Interpolated calls are not literal catalog keys. UI templates use
          // named placeholders instead so that translated word order can vary.
          if (key.contains(r'$')) continue;
          final decoded = key.replaceAll(r"\'", "'").replaceAll(r'\\', String.fromCharCode(92));
          if (!enbekTranslations.containsKey(decoded)) {
            missing.add('${file.path}: $decoded');
          }
        }
      }
      expect(missing, isEmpty, reason: missing.join('\n'));
    });

    test('dynamic enum labels and new feature strings are covered', () {
      const required = <String>[
        // Fixed backend role, work type, priority, and status labels.
        'Мастер', 'Исполнитель', 'Руководитель · просмотр',
        'Плановый', 'Внеплановый', 'Обычный', 'Высокий', 'Аварийный',
        'Выдан', 'Принят', 'Очередь', 'В очереди', 'Отклонён', 'В работе',
        'Приостановлен', 'Исполнено', 'Исполнен', 'Проверка ИИ', 'Проверка',
        'Доработка', 'Закрыт',
        // Theme, language, and count templates.
        'Язык', 'Настройки', 'Тема', 'Светлая', 'Тёмная', 'Как в системе',
        'Активных нарядов: {count} • потяните вниз, чтобы обновить',
        'Срок: {date}', 'Фото ({count})', '{score} из 5',
        'Текущая оценка: {score} из 5',
        // Telegram labels selected dynamically from server enum codes.
        'Уведомления в Telegram', 'Личный чат связан', 'Личный чат не связан',
        'Очередь пуста', 'Повторная отправка', 'Отправляется', 'Доставлено',
        'Ошибка доставки', 'Доставка не подтверждена', 'Отменено',
        'Срок истёк', 'Другой статус', '{status}: {count}',
        'Действует до {time}',
        // Photo viewer and safe client-side error labels.
        'Фото пока нет.', 'Фото', 'До работ', 'После работ', 'Дубликат фото',
        'Открыть фото: {name}', 'Загрузка фото…', 'Не удалось загрузить фото.',
        'Не удалось открыть изображение.', 'Повторить', 'Закрыть',
        'Увеличивайте фото двумя пальцами', 'Фото недоступно.',
        'Сессия истекла. Войдите снова.', 'Нет доступа к фото.',
        'Фото не найдено.', 'Превышено время ожидания фото.',
        'Проверьте подключение к серверу.',
        'Сервер вернул неподдерживаемый формат фото.',
        'Фото превышает допустимый размер.', 'Сервер вернул пустое фото.',
        'Сервер перенаправил запрос фото. Проверьте адрес сервера.',
        'Некорректный идентификатор фото.',
        // Backend templates are safe only with allowlisted status/issue values.
        'Сервер вернул некорректный ответ ({statusCode}).',
        'Ошибка сервера ({statusCode}).',
        'Переход {from} → {to} сейчас недоступен',
        'Нельзя принять наряд: {issues}',
        // Master-only work-order creation and list-refresh outcomes.
        'Выдать наряд', 'Наряд создан',
        'Наряд создан, но список не обновлён. Обновите его вручную.',
        'Новый наряд может выдать только мастер.',
        'Мастер добавляет фото «до», пока наряд выдан или находится в очереди.',
        'Для этой роли доступен только просмотр фотографий.',
        'Добавить фото «до»',
      ];
      for (final key in required) {
        expect(enbekTranslations.containsKey(key), isTrue, reason: key);
      }
    });

    test('master creation dynamic labels and local errors are covered', () {
      const required = <String>[
        // These are passed through variables, ternaries, or helper functions,
        // so direct context.tr literal scanning alone cannot cover them.
        'Работа', 'Место и исполнитель', 'Срок', 'Комментарий и фото',
        'Название: от 4 до 160 символов.',
        'Описание: от 10 до 3000 символов.',
        'Выполняет наряд', 'Есть очередь', 'Есть новый наряд', 'Свободен',
        'Не на смене', 'Загрузка неизвестна',
        'Ожидает загрузки', 'Загружается…', 'Загружено',
        'Не загружено', 'Загрузка не подтверждена',
        'Завершить без оставшихся фото?', 'Отменить создание наряда?',
        'Наряд уже создан. Незагруженные фото будут потеряны при выходе; их можно добавить в карточке, пока это разрешено статусом.',
        'Введённые данные и выбранные фото не сохранятся.',
        'Открыть созданный наряд', 'Выйти',
        'Сначала выберите участок', 'Выберите оборудование',
        'Создаём наряд…', 'Выдать наряд',
        'Завершить без оставшихся фото',
        'Фото больше 4 МБ. Выберите или снимите файл поменьше.',
        'Выберите читаемое фото JPEG, PNG или WebP.',
        'Не удалось открыть фото. Проверьте доступ к камере или галерее и попробуйте снова.',
        'Обновите справочники и выберите участок, оборудование и исполнителя.',
        'Не удалось подтвердить загрузку. Откройте наряд и проверьте фотографии.',
        'Срок должен быть в будущем',
        'Проверьте обязательные поля и срок.',
      ];
      for (final key in required) {
        expect(enbekTranslations.containsKey(key), isTrue, reason: key);
      }
    });

    test('Kazakh industrial terminology is consistent', () {
      const expected = <String, String>{
        'Мастер': 'Шебер',
        'Исполнитель': 'Орындаушы',
        'Наряд': 'Наряд',
        'Наряды': 'Нарядтар',
        'Плановый': 'Жоспарлы',
        'Внеплановый': 'Жоспардан тыс',
        'Оборудование': 'Жабдық',
        'Код неисправности': 'Ақау коды',
        'В работе': 'Орындалуда',
        'Доработка': 'Түзету',
        'Вернуть на доработку': 'Түзетуге қайтару',
        'Снять фото': 'Фото түсіру',
        'Из галереи': 'Галереядан',
        'Уведомления в Telegram': 'Telegram хабарландырулары',
        'Выдать наряд': 'Наряд беру',
      };
      for (final entry in expected.entries) {
        expect(enbekTranslations[entry.key]!['kk'], entry.value,
            reason: entry.key);
      }
      expect(enbekTranslations['Мастер']!['en'], 'Foreman');
      expect(enbekTranslations['Исполнитель']!['en'], 'Technician');
      expect(enbekTranslations['Наряд']!['en'], 'Work order');
    });
  });

  group('Localized formatting', () {
    late AppSettings settings;
    setUp(() => settings = AppSettings(store: MemorySettingsStore()));
    tearDown(() => settings.dispose());

    test('Russian is the default and unknown source content is preserved', () {
      expect(settings.translate('Мастер'), 'Мастер');
      for (final language in ['ru', 'kk', 'en']) {
        settings.language = language;
        const userContent = 'Насос 17 / Арман: заменить уплотнение';
        expect(settings.translate(userContent), userContent);
        expect(settings.translateError(userContent), userContent);
      }
    });

    test('Kazakh can put scores before or after the scale', () {
      settings.language = 'kk';
      expect(settings.translate('{score} из 5', {'score': 4}), '5-тен 4');
      expect(
        settings.translate('Текущая оценка: {score} из 5', {'score': 3}),
        'Қазіргі баға: 5-тен 3',
      );
      settings.language = 'en';
      expect(settings.translate('{score} из 5', {'score': 4}), '4 out of 5');
    });

    test('count labels work for 0, 1, 2, 5, 11, and 21 without declension', () {
      const key = 'Активных нарядов: {count} • потяните вниз, чтобы обновить';
      for (final language in ['ru', 'kk', 'en']) {
        settings.language = language;
        for (final count in [0, 1, 2, 5, 11, 21]) {
          final label = settings.translate(key, {'count': count});
          expect(label, contains('$count'));
          expect(label, isNot(contains('{count}')));
        }
      }
    });

    test('photo names remain untouched when inserted into templates', () {
      settings.language = 'kk';
      const fileName = 'насос_до_работы.jpg';
      expect(settings.translate('Открыть фото: {name}', {'name': fileName}),
          'Фотоны ашу: $fileName');
    });

    test('master creation placeholders preserve names, codes and numbers', () {
      for (final language in ['ru', 'kk', 'en']) {
        settings.language = language;
        const crew = 'Цех №2 / A';
        const orderCode = 'НАР-2026/00042';
        expect(settings.translate('Бригада {name}', {'name': crew}),
            contains(crew));
        expect(settings.translate('Наряд {code} уже создан.', {'code': orderCode}),
            contains(orderCode));
        expect(settings.translate('Фото {number}', {'number': 5}),
            contains('5'));
        expect(settings.translate('Активных: {count}', {'count': 0}),
            contains('0'));
        expect(settings.translate('Рейтинг: {score}', {'score': '—'}),
            contains('—'));
      }
      settings.language = 'kk';
      expect(settings.translate('Фото «до»: {count} из 5', {'count': 3}),
          'Жұмысқа дейінгі фотолар: 5-тен 3');
      expect(settings.translate('Фото загружено: {done} из {total}',
          {'done': 2, 'total': 5}), 'Жүктелген фотолар: 5 ішінен 2');
      settings.language = 'en';
      expect(settings.translate('Фото загружено: {done} из {total}',
          {'done': 2, 'total': 5}), 'Photos uploaded: 2 of 5');
    });

    test('master creation local errors use exact safe catalog matches', () {
      settings.language = 'en';
      expect(settings.translateError('Выберите читаемое фото JPEG, PNG или WebP.'),
          'Select a readable JPEG, PNG, or WebP photo.');
      settings.language = 'kk';
      expect(settings.translateError('Срок должен быть в будущем'),
          'Мерзім болашақта болуы керек');
      const userText = 'Мастер Ерлан: насос №17, заменить уплотнение';
      expect(settings.translateError(userText), userText);
    });


    test('known status transitions translate each fixed status exactly once', () {
      settings.language = 'en';
      expect(
        settings.translateError('Переход Выдан → Закрыт сейчас недоступен'),
        'The transition Issued → Closed is currently unavailable',
      );
      settings.language = 'kk';
      expect(
        settings.translateError('Переход Выдан → Закрыт сейчас недоступен'),
        'Берілді → Жабылды ауысуы қазір қолжетімсіз',
      );
      const unknown = 'Переход авторский статус → Закрыт сейчас недоступен';
      expect(settings.translateError(unknown), unknown);
    });

    test('acceptance reasons translate only entirely allowlisted content', () {
      settings.language = 'en';
      expect(
        settings.translateError(
          'Нельзя принять наряд: нет описания работы; не выбран код неисправности',
        ),
        'Cannot accept the work order: work description missing; no fault code selected',
      );
      // The last fixed reason includes a semicolon inside the reason itself.
      expect(
        settings.translateError(
          'Нельзя принять наряд: не указано время; результат проверки требует доработки; мастер может направить наряд на доработку',
        ),
        'Cannot accept the work order: time not specified; the review result requires rework; the foreman can return the work order for rework',
      );
      const unknown = 'Нельзя принять наряд: нет описания работы; текст пользователя';
      expect(settings.translateError(unknown), unknown);
    });

    test('known HTTP status errors are formatted safely', () {
      settings.language = 'en';
      expect(settings.translateError('Ошибка сервера (503).'),
          'Server error (503).');
      expect(
        settings.translateError('Сервер вернул некорректный ответ (502).'),
        'The server returned an invalid response (502).',
      );
      expect(settings.translateError('Неверный логин или пароль'),
          'Incorrect username or password');
      expect(settings.translateError('Unrecognized backend detail'),
          'Unrecognized backend detail');
    });
  });
}
