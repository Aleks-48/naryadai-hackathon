import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/main.dart';

class _Api extends EnbekApi {
  _Api() : super('http://127.0.0.1');
  String status = 'issued';
  bool reject = false;
  int refreshes = 0, mutations = 0;
  Map<String, dynamic> get item => {'id': 1, 'code': 'TEST-1', 'title': 'Original user title', 'status': status};
  @override
  Future<Map<String, dynamic>> order(int id) async => {'order': item};
  @override
  Future<Map<String, dynamic>> bootstrap() async {
    refreshes++;
    return {'orders': [item], 'user': {'role': 'worker'}, 'constants': {}};
  }
  @override
  Future<Map<String, dynamic>> action(int id, String action, {Map<String, dynamic> payload = const {}}) async {
    mutations++;
    if (reject) throw const ApiException('Нет доступа к наряду', statusCode: 403);
    if (action == 'accept') status = 'accepted';
    return {};
  }
}

// Lazy ListView children may not exist yet. Scroll and render each step until
// the target's center is actually reachable, rather than only built offscreen.
Future<void> _scrollTo(WidgetTester tester, Finder target, {double delta = 250}) async {
  final scrollable = tester.state<ScrollableState>(find.byType(Scrollable).first);
  for (var step = 0; step < 40 && target.hitTestable().evaluate().isEmpty; step++) {
    final position = scrollable.position;
    position.jumpTo((position.pixels + delta)
        .clamp(position.minScrollExtent, position.maxScrollExtent).toDouble());
    await tester.pumpAndSettle();
  }
  expect(target.hitTestable(), findsOneWidget);
}

void main() {
  testWidgets('failed action remains visible after its recovery reload', (tester) async {
    final api = _Api()..reject = true;
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: OrderDetailScreen(
      api: api, user: const {'role': 'worker'}, initialOrder: api.item, constants: const {},
    )));
    await tester.pumpAndSettle();
    final accept = find.text('Принять наряд');
    await _scrollTo(tester, accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();
    await _scrollTo(tester, find.text('Нет доступа к наряду'), delta: -250);
    expect(find.text('Нет доступа к наряду'), findsOneWidget);
    expect(api.mutations, 1);
  });

  testWidgets('returning from changed order refreshes the list', (tester) async {
    final api = _Api();
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: HomeScreen(
      api: api, user: const {'role': 'worker'},
      initialBootstrap: {'orders': [api.item], 'constants': {}},
      onLogout: () {}, onUserChanged: (_) {},
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Original user title'));
    await tester.pumpAndSettle();
    final accept = find.text('Принять наряд');
    await _scrollTo(tester, accept);
    await tester.tap(accept);
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(api.refreshes, 1);
    expect(find.text('Принят'), findsOneWidget);
    expect(find.text('Original user title'), findsOneWidget);
  });

  for (final language in ['ru', 'kk', 'en']) {
    testWidgets('manager stays read-only in $language and user content is unchanged', (tester) async {
      final api = _Api()..status = 'ai_review';
      addTearDown(api.close);
      final settings = AppSettings(store: MemorySettingsStore())..setLanguage(language);
      await settings.saved;
      await tester.pumpWidget(AppSettingsScope(settings: settings, child: MaterialApp(
        theme: enbekTheme(Brightness.dark),
        home: OrderDetailScreen(api: api, user: const {'role': 'manager'}, initialOrder: api.item, constants: const {}),
      )));
      await tester.pumpAndSettle();
      expect(find.text('Original user title'), findsOneWidget);
      await _scrollTo(tester, find.text(settings.translate('Режим просмотра')));
      expect(find.text(settings.translate('Режим просмотра')), findsOneWidget);
      expect(find.text(settings.translate('Принять и закрыть')), findsNothing);
      expect(find.text(settings.translate('Вернуть на доработку')), findsNothing);
      expect(api.mutations, 0);
      await tester.pumpWidget(const SizedBox.shrink());
      settings.dispose();
    });
  }
}
