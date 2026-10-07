import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/main.dart';

// Entirely synthetic fixtures. These tests never contact a backend or Telegram.
const _user = <String, dynamic>{
  'id': 1,
  'role': 'worker',
  'display_name': 'Test Technician',
};
const _order = <String, dynamic>{
  'id': 7,
  'code': 'WORK-000007',
  'title': 'Проверка оборудования с длинным названием',
  'status': 'in_progress',
  'work_type_label': 'Внеплановый',
  'priority_label': 'Высокий',
  'area': 'Участок технического обслуживания оборудования',
  'due_at': '2026-10-07T12:30:00Z',
  'equipment': <String, dynamic>{
    'code': 'EQ-0007',
    'name': 'Оборудование с очень длинным техническим названием',
  },
  'photos': <Map<String, dynamic>>[],
};
const _constants = <String, dynamic>{
  'fault_codes': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 1,
      'code': 'FAULT-000001',
      'label': 'Неисправность оборудования с длинным описанием причины',
    },
  ],
  'materials': <Map<String, dynamic>>[
    <String, dynamic>{
      'id': 1,
      'sku': 'MATERIAL-000001',
      'name': 'Материал с длинным полным техническим наименованием',
    },
  ],
};

class _LayoutApi implements EnbekApi {
  @override
  Future<Map<String, dynamic>> order(int id) async => {'order': _order};

  @override
  Future<Map<String, dynamic>> telegramStatus() async => {
    'enabled': false,
    'paired': false,
    'delivery_counts': <String, int>{},
  };

  @override
  Future<Map<String, dynamic>> bootstrap() async => {
    'user': _user,
    'orders': [_order],
    'constants': _constants,
  };

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _host(AppSettings settings, Widget child) => AppSettingsScope(
  settings: settings,
  child: AnimatedBuilder(
    animation: settings,
    builder: (context, _) => MaterialApp(
      locale: Locale(settings.language),
      supportedLocales: const [Locale('ru'), Locale('kk'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: enbekTheme(Brightness.light),
      darkTheme: enbekTheme(Brightness.dark),
      themeMode: settings.themeMode,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: const TextScaler.linear(2),
        ),
        child: child!,
      ),
      home: child,
    ),
  ),
);

void _useNarrowViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(320, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _scrollToHittable(WidgetTester tester, Finder target) async {
  final scrollable = tester.state<ScrollableState>(find.byType(Scrollable).first);
  for (var step = 0; step < 40 && target.hitTestable().evaluate().isEmpty; step++) {
    final position = scrollable.position;
    position.jumpTo((position.pixels + 250)
        .clamp(position.minScrollExtent, position.maxScrollExtent).toDouble());
    await tester.pumpAndSettle();
  }
  expect(target.hitTestable(), findsOneWidget);
}

void main() {
  for (final language in ['ru', 'kk', 'en']) {
    for (final mode in [ThemeMode.light, ThemeMode.dark]) {
      testWidgets('320px home/profile, 2x text: $language ${mode.name}',
          (tester) async {
        _useNarrowViewport(tester);
        final settings = AppSettings(store: MemorySettingsStore())
          ..language = language
          ..themeMode = mode;
        final api = _LayoutApi();
        await tester.pumpWidget(_host(settings, HomeScreen(
          api: api,
          user: _user,
          initialBootstrap: {
            'user': _user,
            'orders': [_order],
            'constants': _constants,
          },
          onLogout: () {},
          onUserChanged: (_) {},
        )));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.tap(find.text(settings.translate('Профиль')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.scrollUntilVisible(
          find.text(settings.translate('Уведомления в Telegram')),
          300,
          scrollable: find.byType(Scrollable).first,
          maxScrolls: 30,
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
        settings.dispose();
      });
    }

    testWidgets('320px detail and long dropdown labels, 2x text: $language',
        (tester) async {
      _useNarrowViewport(tester);
      final settings = AppSettings(store: MemorySettingsStore())
        ..language = language;
      await tester.pumpWidget(_host(settings, OrderDetailScreen(
        api: _LayoutApi(),
        user: _user,
        initialOrder: _order,
        constants: _constants,
      )));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      final materials = find.byType(CheckboxListTile);
      await _scrollToHittable(tester, materials);
      expect(tester.widget<CheckboxListTile>(materials).value, isTrue);
      await tester.tap(materials);
      await tester.pumpAndSettle();
      expect(tester.widget<CheckboxListTile>(materials).value, isFalse);
      expect(tester.takeException(), isNull);
      final materialDropdown = find.byWidgetPredicate((widget) =>
          widget is DropdownButtonFormField<int> &&
          widget.decoration.labelText == settings.translate('Материал'));
      expect(materialDropdown, findsOneWidget);
      await _scrollToHittable(tester, materialDropdown);
      expect(tester.takeException(), isNull);
      await tester.tap(materialDropdown);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      // Dismiss the popup before disposing its route.
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox.shrink());
      settings.dispose();
    });
  }
}
