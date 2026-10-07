import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../lib/api.dart';
import '../lib/main.dart';
import '../lib/create_order.dart';

class _Api extends EnbekApi {
  _Api() : super('http://127.0.0.1');
  int creates = 0;
  @override
  Future<Map<String, dynamic>> createOrder(Map<String, dynamic> payload) async {
    creates++;
    return {'order': {'id': 1}};
  }
  @override
  Future<Map<String, dynamic>> bootstrap() async => data;
  static const data = <String, dynamic>{
    'orders': [],
    'constants': {
      'areas': [{'id': 1, 'name': 'Test area'}],
      'equipment': [{'id': 2, 'area_id': 1, 'code': 'EQ-2', 'name': 'Test pump'}],
      'users': [{'id': 3, 'role': 'worker', 'display_name': 'Test worker', 'brigade': 'A'}],
    },
    'free_workers': [{'id': 3, 'display_name': 'Test worker', 'brigade': 'A'}],
  };
}

void main() {
  for (final role in ['worker', 'manager', 'master']) {
    testWidgets('create entry is restricted to master: $role', (tester) async {
      final api = _Api();
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(home: HomeScreen(
        api: api, user: {'id': 1, 'role': role}, initialBootstrap: _Api.data,
        onLogout: () {}, onUserChanged: (_) {},
      )));
      await tester.pumpAndSettle();
      final button = find.byKey(const ValueKey('create-order-button'));
      expect(button, role == 'master' ? findsOneWidget : findsNothing);
      if (role == 'master') {
        await tester.tap(button);
        await tester.pumpAndSettle();
        expect(find.byType(CreateOrderScreen), findsOneWidget);
      }
      expect(api.creates, 0, reason: 'Opening the form never creates an order');
      expect(tester.takeException(), isNull);
    });
  }
}
