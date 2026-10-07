import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/api.dart';
import '../lib/main.dart';

// Actual application widgets with an in-memory API. No server, image-picker
// invocation, or network request is involved. Requires Flutter 3.35 or newer.
const _constants = <String, dynamic>{
  'fault_codes': [
    {'id': 1, 'code': 'F1', 'label': 'Первый код'},
    {'id': 2, 'code': 'F2', 'label': 'Второй код'},
  ],
  'materials': [
    {'id': 10, 'sku': 'M1', 'name': 'Первый материал'},
    {'id': 20, 'sku': 'M2', 'name': 'Второй материал'},
  ],
};

Map<String, dynamic> _order(String status, {int rating = 4}) => {
  'id': 1,
  'code': 'TEST-1',
  'title': 'Тестовый наряд',
  'status': status,
  'rating': rating,
  'fault_code_id': 1,
};

class _MemoryApi extends EnbekApi {
  _MemoryApi(this.currentOrder) : super('http://127.0.0.1');

  final Map<String, dynamic> currentOrder;
  Map<String, dynamic> bootstrapData = {};
  final actions = <Map<String, dynamic>>[];
  int? savedRating;
  String? savedReason;

  @override
  Future<Map<String, dynamic>> order(int id) async => {
    'order': Map<String, dynamic>.from(currentOrder),
  };

  @override
  Future<Map<String, dynamic>> bootstrap() async => bootstrapData;

  @override
  Future<Map<String, dynamic>> telegramStatus() async => {'enabled': false, 'paired': false, 'delivery_counts': {}};

  @override
  Future<Map<String, dynamic>> action(
    int id,
    String action, {
    Map<String, dynamic> payload = const {},
  }) async {
    actions.add({'id': id, 'action': action, 'payload': payload});
    return {};
  }

  @override
  Future<Map<String, dynamic>> rateOrder(
    int id, {
    required int rating,
    required String reason,
  }) async {
    savedRating = rating;
    savedReason = reason;
    return {};
  }
}

Finder _dropdown<T>(String label) => find.byWidgetPredicate(
  (widget) => widget is DropdownButtonFormField<T> &&
      widget.decoration.labelText == label,
);

void _expectValue<T>(WidgetTester tester, String label, T value) {
  expect(tester.state<FormFieldState<T>>(_dropdown<T>(label)).value, value);
}

Future<void> _pick<T>(
  WidgetTester tester,
  String label,
  String option,
) async {
  await tester.ensureVisible(_dropdown<T>(label));
  await tester.tap(_dropdown<T>(label));
  await tester.pumpAndSettle();
  await tester.tap(find.text(option).last);
  await tester.pumpAndSettle();
}

Future<void> _tap(WidgetTester tester, Finder target) async {
  await tester.ensureVisible(target);
  await tester.tap(target);
  await tester.pumpAndSettle();
}

Future<void> _refresh(WidgetTester tester) async {
  await tester.widget<RefreshIndicator>(find.byType(RefreshIndicator)).onRefresh();
  await tester.pumpAndSettle();
}

Future<void> _pumpOrder(
  WidgetTester tester,
  _MemoryApi api,
  String role,
) async {
  await tester.pumpWidget(MaterialApp(
    home: OrderDetailScreen(
      api: api,
      user: {'role': role},
      initialOrder: api.currentOrder,
      constants: _constants,
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('order filter survives refresh and profile navigation', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1000, 2200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _MemoryApi(_order('in_progress'));
    addTearDown(api.close);
    final user = <String, dynamic>{'role': 'worker'};
    api.bootstrapData = {
      'user': user,
      'orders': [
        {..._order('in_progress'), 'title': 'Активная работа'},
        {..._order('closed'), 'id': 2, 'title': 'Закрытая работа'},
      ],
      'constants': _constants,
    };
    await tester.pumpWidget(MaterialApp(
      home: HomeScreen(
        api: api,
        user: user,
        initialBootstrap: api.bootstrapData,
        onLogout: () {},
        onUserChanged: (_) {},
      ),
    ));
    await tester.pumpAndSettle();
    _expectValue(tester, 'Показать', 'active');
    expect(find.text('Активная работа'), findsOneWidget);
    expect(find.text('Закрытая работа'), findsNothing);

    await _pick<String>(tester, 'Показать', 'Завершённые');
    _expectValue(tester, 'Показать', 'closed');
    expect(find.text('Активная работа'), findsNothing);
    expect(find.text('Закрытая работа'), findsOneWidget);
    await _refresh(tester);
    _expectValue(tester, 'Показать', 'closed');
    await _tap(tester, find.text('Профиль'));
    await _tap(tester, find.text('Наряды'));
    _expectValue(tester, 'Показать', 'closed');
    expect(find.text('Закрытая работа'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('fault and material selections survive rebuilds and reach report', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1000, 2200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _MemoryApi(_order('in_progress'));
    addTearDown(api.close);
    await _pumpOrder(tester, api, 'worker');
    _expectValue(tester, 'Код неисправности', 1);
    await _pick<int>(tester, 'Код неисправности', 'F2 · Второй код');
    _expectValue(tester, 'Код неисправности', 2);

    await _tap(tester, find.byType(CheckboxListTile));
    _expectValue(tester, 'Материал', 10);
    await _pick<int>(tester, 'Материал', 'M2 · Второй материал');
    _expectValue(tester, 'Материал', 20);
    await _tap(tester, find.byType(CheckboxListTile));
    expect(_dropdown<int>('Материал'), findsNothing);
    await _tap(tester, find.byType(CheckboxListTile));
    _expectValue(tester, 'Материал', 20);
    await _refresh(tester);
    _expectValue(tester, 'Код неисправности', 2);
    _expectValue(tester, 'Материал', 20);

    await tester.enterText(
      find.widgetWithText(TextFormField, 'Что выполнено? (не менее 20 символов)'),
      'Выполнена проверка и замена тестового узла оборудования.',
    );
    await _tap(tester, find.text('Сохранить отчёт и передать на проверку'));
    final completed = api.actions.singleWhere((item) => item['action'] == 'complete');
    final payload = completed['payload'] as Map<String, dynamic>;
    expect(payload['fault_code_id'], 2);
    expect(payload['materials_not_used'], isFalse);
    expect(payload['materials'], [{'material_id': 20, 'quantity': 1.0}]);
    expect(api.actions.map((item) => item['action']), ['complete', 'ai_check']);
    expect(tester.takeException(), isNull);
  });

  testWidgets('acceptance rating survives refresh and reaches confirmed close', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1000, 2200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _MemoryApi(_order('ai_review'));
    addTearDown(api.close);
    await _pumpOrder(tester, api, 'master');
    _expectValue(tester, 'Оценка исполнителю', 4);
    await _pick<int>(tester, 'Оценка исполнителю', '2 из 5');
    await _refresh(tester);
    _expectValue(tester, 'Оценка исполнителю', 2);
    await tester.enterText(
      find.widgetWithText(TextField, 'Комментарий мастера (не менее 4 символов)'),
      'Проверено мастером',
    );
    await _tap(tester, find.text('Принять и закрыть'));
    expect(find.text('Принять и закрыть наряд?'), findsOneWidget);
    expect(api.actions, isEmpty);
    await _tap(tester, find.text('Назад'));
    expect(api.actions, isEmpty);
    _expectValue(tester, 'Оценка исполнителю', 2);
    await _tap(tester, find.text('Принять и закрыть'));
    await _tap(tester, find.text('Закрыть'));
    expect(api.actions.single['action'], 'close');
    expect(api.actions.single['payload'], {
      'closure_comment': 'Проверено мастером',
      'rating': 2,
    });
    expect(tester.takeException(), isNull);
  });

  testWidgets('closed-order rating survives refresh and reaches correction', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1000, 2200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _MemoryApi(_order('closed'));
    addTearDown(api.close);
    await _pumpOrder(tester, api, 'master');
    _expectValue(tester, 'Новая оценка', 4);
    await _pick<int>(tester, 'Новая оценка', '3 из 5');
    await _refresh(tester);
    _expectValue(tester, 'Новая оценка', 3);
    await tester.enterText(
      find.widgetWithText(TextField, 'Причина изменения (обязательна)'),
      'Повторная проверка',
    );
    await _tap(tester, find.text('Сохранить корректировку'));
    expect(api.savedRating, 3);
    expect(api.savedReason, 'Повторная проверка');
    expect(tester.takeException(), isNull);
  });
}
