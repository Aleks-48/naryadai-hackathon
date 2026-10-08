import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/ai_review_card.dart';
import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/main.dart';
import 'ai_review_fixtures.dart';

Widget _host(AppSettings settings, Widget child) => AppSettingsScope(
  settings: settings,
  child: MaterialApp(
    locale: Locale(settings.language),
    supportedLocales: const [Locale('ru'), Locale('kk'), Locale('en')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: enbekTheme(Brightness.light),
    darkTheme: enbekTheme(Brightness.dark),
    themeMode: settings.themeMode,
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(2)),
      child: child!,
    ),
    home: child,
  ),
);

void _narrow(WidgetTester tester) {
  tester.view.physicalSize = const Size(320, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _inspectFullScroll(WidgetTester tester) async {
  final scroll = tester.state<ScrollableState>(find.byType(Scrollable).first);
  while (scroll.position.pixels < scroll.position.maxScrollExtent) {
    scroll.position.jumpTo((scroll.position.pixels + 400)
      .clamp(0.0, scroll.position.maxScrollExtent).toDouble());
    await tester.pump();
    expect(tester.takeException(), isNull);
  }
}

class _ReadOnlyApi implements EnbekApi {
  _ReadOnlyApi(this.item);
  Map<String, dynamic> item;
  int mutations = 0;
  int reads = 0;
  @override
  Future<Map<String, dynamic>> order(int id) async {
    reads++;
    return {'order': item};
  }
  @override
  Future<Map<String, dynamic>> action(int id, String action,
    {Map<String, dynamic> payload = const {}}) async {
    mutations++;
    throw StateError('A read-only card must never mutate a work order.');
  }
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  for (final language in ['ru', 'kk', 'en']) {
    for (final theme in [ThemeMode.light, ThemeMode.dark]) {
      for (final model in [false, true]) {
        testWidgets('320px, 2x text, $language ${theme.name}, model=$model', (tester) async {
          _narrow(tester);
          final settings = AppSettings(store: MemorySettingsStore())
            ..language = language ..themeMode = theme;
          addTearDown(settings.dispose);
          final order = model ? modelFixture() : reviewFixture();
          await tester.pumpWidget(_host(settings, Scaffold(
            body: SingleChildScrollView(padding: const EdgeInsets.all(16),
              child: AiReviewCard(order: order)),
          )));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          expect(find.text(settings.translate(model
            ? 'Модель (по данным сервера)' : 'Только правила (rules-only)')), findsOneWidget);
          expect(find.text(settings.translate('Результат анализа')), findsOneWidget);
          expect(find.text(settings.translate('Проверка материалов')), findsOneWidget);
          expect(find.byType(FilledButton), findsNothing);
          expect(find.byType(OutlinedButton), findsNothing);
          expect(find.byType(TextButton), findsNothing);
          expect(find.byType(IconButton), findsNothing);
          if (model) {
            expect(find.text(settings.translate('{score} из 5', {'score': 2})), findsOneWidget);
            expect(find.text('85%'), findsOneWidget);
          } else {
            expect(find.text(settings.translate('Решение мастера обязательно')), findsOneWidget);
            expect(find.text(settings.translate('Проверка фото')), findsOneWidget);
            expect(find.text(settings.translate('Оценка модели отсутствует')), findsOneWidget);
          }
          for (final hidden in ['hidden-top-level-field', 'hidden-photo-field',
            'hidden-material-field', 'llm:synthetic-test-model']) {
            expect(find.textContaining(hidden), findsNothing);
          }
          await _inspectFullScroll(tester);
          expect(find.text(settings.translate(
            'Анализ носит рекомендательный характер. Окончательная приёмка и решение по наряду остаются за мастером.')).hitTestable(), findsOneWidget);
        });
      }
    }

    for (final raw in [null, '{malformed', '{"unknown_secret":"hidden-value"}']) {
      testWidgets('nullable/malformed/unknown data $language: $raw', (tester) async {
        _narrow(tester);
        final settings = AppSettings(store: MemorySettingsStore())..language = language;
        addTearDown(settings.dispose);
        await tester.pumpWidget(_host(settings, Scaffold(body: SingleChildScrollView(
          child: AiReviewCard(order: {'ai_result': raw, 'ai_mode': 'llm:unverified'}),
        ))));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.textContaining('hidden-value'), findsNothing);
        expect(find.textContaining('{malformed'), findsNothing);
        expect(find.text(settings.translate('Модель (по данным сервера)')), findsNothing);
        await _inspectFullScroll(tester);
      });
    }

    testWidgets('old analysis after resubmission is labeled previous in $language', (tester) async {
      _narrow(tester);
      final settings = AppSettings(store: MemorySettingsStore())..language = language;
      addTearDown(settings.dispose);
      await tester.pumpWidget(_host(settings, Scaffold(body: SingleChildScrollView(
        child: AiReviewCard(order: modelFixture(orderFields: {'status': 'executed'})),
      ))));
      await tester.pumpAndSettle();
      expect(find.text(settings.translate('Предыдущий результат анализа')), findsOneWidget);
      expect(find.text(settings.translate('Оценка прошлого отчёта моделью')), findsOneWidget);
      expect(find.text(settings.translate('Оценка содержания отчёта моделью')), findsNothing);
      await _inspectFullScroll(tester);
    });

    for (final role in ['worker', 'manager', 'master']) {
      testWidgets('closed $role sees master rating/reason in $language without mutation', (tester) async {
        _narrow(tester);
        final settings = AppSettings(store: MemorySettingsStore())..language = language;
        addTearDown(settings.dispose);
        final api = _ReadOnlyApi(modelFixture(orderFields: {
          'status': 'closed', 'rating': 5, 'rating_reason': 'Foreman acceptance rationale.',
          'rated_by': 11,
        }));
        await tester.pumpWidget(_host(settings, OrderDetailScreen(
          api: api, user: {'id': 2, 'role': role}, initialOrder: api.item, constants: const {},
        )));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        // The outer details list builds lazily; reach the new analysis card first.
        await tester.scrollUntilVisible(find.byType(AiReviewCard), 300,
          scrollable: find.byType(Scrollable).first, maxScrolls: 30);
        await tester.pumpAndSettle();
        expect(find.text(settings.translate('Итоговая оценка мастера')), findsOneWidget);
        expect(find.text('Foreman acceptance rationale.'), findsOneWidget);
        expect(find.text(settings.translate('{score} из 5', {'score': 5})), findsOneWidget);
        expect(find.text(settings.translate('{score} из 5', {'score': 2})), findsOneWidget);
        expect(find.text('85%'), findsOneWidget);
        expect(api.mutations, 0);
        expect(api.reads, 1);
      });
    }

    testWidgets('closed master rating survives missing AI result in $language', (tester) async {
      final settings = AppSettings(store: MemorySettingsStore())..language = language;
      addTearDown(settings.dispose);
      await tester.pumpWidget(_host(settings, const Scaffold(body: SingleChildScrollView(
        child: AiReviewCard(order: {'status': 'closed', 'ai_result': null,
          'rating': 4, 'rating_reason': 'Independent master reason.'}),
      ))));
      await tester.pumpAndSettle();
      expect(find.text(settings.translate('Сохранённого результата анализа пока нет.')), findsOneWidget);
      expect(find.text(settings.translate('Итоговая оценка мастера')), findsOneWidget);
      expect(find.text(settings.translate('{score} из 5', {'score': 4})), findsOneWidget);
      expect(find.text('Independent master reason.'), findsOneWidget);
    });
  }

  testWidgets('embedded diagnostics and credential-shaped text never leak', (tester) async {
    final settings = AppSettings(store: MemorySettingsStore());
    addTearDown(settings.dispose);
    await tester.pumpWidget(_host(settings, Scaffold(body: SingleChildScrollView(
      child: AiReviewCard(order: reviewFixture(fields: {
        'summary': 'Diagnostic: {"api_key":"hidden-test-secret"}',
        'issues': ['password="two word secret"', 'token=hidden-test-token'],
      })),
    ))));
    await tester.pumpAndSettle();
    expect(find.textContaining('hidden-test-secret'), findsNothing);
    expect(find.textContaining('two word secret'), findsNothing);
    expect(find.textContaining('hidden-test-token'), findsNothing);
    expect(find.textContaining('Diagnostic:'), findsNothing);
  });
}
