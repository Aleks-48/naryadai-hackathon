import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/telegram_settings.dart';

// No network, Telegram request, real code generation, or redemption is used.
class _MemoryTelegramApi extends EnbekApi {
  _MemoryTelegramApi() : super('http://127.0.0.1');

  Map<String, dynamic> status = {
    'enabled': true,
    'paired': false,
    'delivery_counts': <String, int>{},
  };
  Future<Map<String, dynamic>> Function()? readStatus;
  Future<Map<String, dynamic>> Function()? pair;
  Future<Map<String, dynamic>> Function()? unpair;
  int statusCalls = 0;
  int pairCalls = 0;
  int unpairCalls = 0;

  @override
  Future<Map<String, dynamic>> telegramStatus() async {
    ++statusCalls;
    return readStatus != null ? await readStatus!() : {...status};
  }

  @override
  Future<Map<String, dynamic>> telegramPair() async {
    ++pairCalls;
    return pair != null ? await pair!() : _pairResult();
  }

  @override
  Future<Map<String, dynamic>> telegramUnpair() async {
    ++unpairCalls;
    if (unpair != null) return unpair!();
    status = {...status, 'paired': false};
    return {'ok': true};
  }
}

Map<String, dynamic> _pairResult({DateTime? deadline}) => {
  // This is a fixed synthetic fixture, not a usable server-issued secret.
  'command': '/start AABBCCDDEEFF',
  'expires_at': (deadline ?? DateTime.now().add(const Duration(minutes: 10)))
      .toUtc()
      .toIso8601String(),
  'single_use': true,
};

Widget _host(
  EnbekApi api, {
  AppSettings? settings,
  Brightness brightness = Brightness.light,
  double textScale = 1,
}) => AppSettingsScope(
  settings: settings ?? AppSettings(store: MemorySettingsStore()),
  child: MaterialApp(
    theme: enbekTheme(brightness),
    home: Scaffold(
      body: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: TelegramSettingsCard(api: api),
        ),
      ),
    ),
  ),
);

Future<void> _tap(WidgetTester tester, String text) async {
  final finder = find.text(text);
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> _generate(WidgetTester tester) async {
  await _tap(tester, 'Получить код');
  await _tap(tester, 'Создать код');
}

void main() {
  testWidgets('disabled server prevents generation and uses disabled state', (tester) async {
    final api = _MemoryTelegramApi()..status['enabled'] = false;
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    expect(find.text('Telegram отключён'), findsOneWidget);
    expect(find.text('Получить код'), findsNothing);
    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNull);
    expect(api.pairCalls, 0);
  });

  testWidgets('code requires confirmation and refreshed pairing clears command', (tester) async {
    final api = _MemoryTelegramApi();
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    expect(api.pairCalls, 0);
    await _tap(tester, 'Получить код');
    expect(find.text('Создать код привязки?'), findsOneWidget);
    expect(api.pairCalls, 0);
    await _tap(tester, 'Отмена');
    expect(api.pairCalls, 0);
    await _generate(tester);
    expect(api.pairCalls, 1);
    expect(find.text('/start AABBCCDDEEFF'), findsOneWidget);
    expect(find.textContaining('Действует до '), findsOneWidget);
    api.status['paired'] = true;
    await _tap(tester, 'Обновить статус');
    expect(find.text('Личный чат связан'), findsOneWidget);
    expect(find.text('/start AABBCCDDEEFF'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('unpair requires confirmation, including when delivery is disabled', (tester) async {
    final api = _MemoryTelegramApi()
      ..status['enabled'] = false
      ..status['paired'] = true;
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _tap(tester, 'Отвязать чат');
    expect(api.unpairCalls, 0);
    await _tap(tester, 'Отмена');
    expect(api.unpairCalls, 0);
    await _tap(tester, 'Отвязать чат');
    await _tap(tester, 'Отвязать');
    expect(api.unpairCalls, 1);
    expect(find.text('Чат отвязан.'), findsOneWidget);
    expect(find.text('Отвязать чат'), findsNothing);
  });

  testWidgets('HTTP failure is safe and generation can be retried explicitly', (tester) async {
    final api = _MemoryTelegramApi()
      ..pair = () async => throw const ApiException('private raw response', statusCode: 503);
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _generate(tester);
    expect(find.text('Не удалось получить код. Проверьте соединение и повторите попытку.'), findsOneWidget);
    expect(find.textContaining('private raw response'), findsNothing);
    expect(api.pairCalls, 1);
    api.pair = null;
    await _generate(tester);
    expect(api.pairCalls, 2);
    expect(find.text('/start AABBCCDDEEFF'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('stale status from previous API cannot replace current state', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final oldApi = _MemoryTelegramApi()..readStatus = () => pending.future;
    final newApi = _MemoryTelegramApi()..status['enabled'] = false;
    addTearDown(oldApi.close);
    addTearDown(newApi.close);
    await tester.pumpWidget(_host(oldApi));
    await tester.pump();
    await tester.pumpWidget(_host(newApi));
    await tester.pumpAndSettle();
    pending.complete({'enabled': true, 'paired': true});
    await tester.pumpAndSettle();
    expect(find.text('Telegram отключён'), findsOneWidget);
    expect(find.text('Личный чат связан'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('in-flight request does not update after disposal or repeat on tap', (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _MemoryTelegramApi()..pair = () => pending.future;
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _tap(tester, 'Получить код');
    await tester.tap(find.text('Создать код'));
    // A progress indicator is intentionally still active; do not settle it.
    await tester.pump(const Duration(milliseconds: 300));
    expect(api.pairCalls, 1);
    final button = tester.widget<FilledButton>(find.byWidgetPredicate((widget) => widget is FilledButton).first);
    expect(button.onPressed, isNull);
    await tester.pumpWidget(const SizedBox());
    pending.complete(_pairResult());
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(api.pairCalls, 1);
  });

  testWidgets('already expired command is never displayed', (tester) async {
    final api = _MemoryTelegramApi()
      ..pair = () async => _pairResult(deadline: DateTime.now().subtract(const Duration(seconds: 1)));
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _generate(tester);
    expect(find.text('/start AABBCCDDEEFF'), findsNothing);
    expect(find.text('Срок действия кода истёк. Получите новый код.'), findsOneWidget);
    expect(find.text('Получить новый код'), findsOneWidget);
  });

  testWidgets('expiration timer removes the command from the widget', (tester) async {
    final api = _MemoryTelegramApi()
      ..pair = () async => _pairResult(deadline: DateTime.now().add(const Duration(seconds: 5)));
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _generate(tester);
    expect(find.text('/start AABBCCDDEEFF'), findsOneWidget);
    await tester.pump(const Duration(seconds: 6));
    expect(find.text('/start AABBCCDDEEFF'), findsNothing);
    expect(find.text('Срок действия кода истёк. Получите новый код.'), findsOneWidget);
  });

  testWidgets('unknown unpair outcome requires a status refresh', (tester) async {
    final api = _MemoryTelegramApi()
      ..status['paired'] = true
      ..unpair = () async => throw TimeoutException('response lost');
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _tap(tester, 'Отвязать чат');
    await _tap(tester, 'Отвязать');
    expect(find.text('Чат отвязан.'), findsNothing);
    expect(find.text('Отвязать чат'), findsNothing);
    expect(find.text('Не удалось отвязать чат. Обновите статус перед повторной попыткой.'), findsOneWidget);
    await _tap(tester, 'Обновить статус');
    expect(find.text('Отвязать чат'), findsOneWidget);
    expect(api.unpairCalls, 1);
  });

  testWidgets('confirmation from a replaced account cannot authorize generation', (tester) async {
    final oldApi = _MemoryTelegramApi();
    final newApi = _MemoryTelegramApi();
    addTearDown(oldApi.close);
    addTearDown(newApi.close);
    await tester.pumpWidget(_host(oldApi));
    await tester.pumpAndSettle();
    await _tap(tester, 'Получить код');
    await tester.pumpWidget(_host(newApi));
    await tester.pumpAndSettle();
    await _tap(tester, 'Создать код');
    expect(oldApi.pairCalls, 0);
    expect(newApi.pairCalls, 0);
    expect(find.text('/start AABBCCDDEEFF'), findsNothing);
  });

  testWidgets('malformed pairing response cannot reveal unvalidated command', (tester) async {
    final api = _MemoryTelegramApi()
      ..pair = () async => {
        ..._pairResult(),
        'command': 'unexpected secret response',
      };
    addTearDown(api.close);
    await tester.pumpWidget(_host(api));
    await tester.pumpAndSettle();
    await _generate(tester);
    expect(find.text('Сервер вернул некорректный ответ Telegram.'), findsOneWidget);
    expect(find.text('unexpected secret response'), findsNothing);
  });

  testWidgets('narrow dark layout supports translated large text', (tester) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _MemoryTelegramApi();
    final settings = AppSettings(store: MemorySettingsStore())..setLanguage('en');
    addTearDown(api.close);
    await tester.pumpWidget(_host(api, settings: settings, brightness: Brightness.dark, textScale: 1.7));
    await tester.pumpAndSettle();
    expect(find.text(settings.translate('Уведомления в Telegram')), findsOneWidget);
    expect(find.text('Уведомления в Telegram'), findsNothing);
    final card = tester.widget<Card>(find.byType(Card));
    expect(card.color, enbekTheme(Brightness.dark).colorScheme.surfaceContainerLow);
    expect(tester.takeException(), isNull);
  });
}
