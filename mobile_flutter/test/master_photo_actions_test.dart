import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import '../lib/api.dart';
import '../lib/main.dart';

class _PhotoApi extends EnbekApi {
  _PhotoApi(this.item) : super('http://127.0.0.1');
  final Map<String, dynamic> item;
  @override
  Future<Map<String, dynamic>> order(int id) async => {'order': item};
  @override
  Future<Uint8List> photoBytes(int id) async => throw const ApiException('fixture');
}

void main() {
  for (final sample in <(String, String, bool)>[
    ('master','issued',true), ('master','queued',true),
    ('master','accepted',false), ('master','closed',false),
    ('worker','in_progress',true), ('worker','paused',true),
    ('worker','issued',false), ('manager','issued',false),
  ]) {
    testWidgets('photo upload permission ${sample.$1}/${sample.$2}', (tester) async {
      final item = <String, dynamic>{'id': 1, 'status': sample.$2, 'title': 'Fixture', 'photos': []};
      final api = _PhotoApi(item);
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(home: OrderDetailScreen(
        api: api, user: {'role': sample.$1}, initialOrder: item, constants: const {},
      )));
      await tester.pumpAndSettle();
      expect(find.text('Снять фото'), sample.$3 ? findsOneWidget : findsNothing);
      if (sample.$1 == 'master' && sample.$3) expect(find.text('Добавить фото «до»'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('five before photos hide further master upload controls', (tester) async {
    final item = <String,dynamic>{'id':1,'status':'issued','photos':[
      for (var id=1; id<=5; id++) {'id':id,'phase':'before','file_name':'fixture-$id.png'},
    ]};
    final api=_PhotoApi(item);
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home:OrderDetailScreen(
      api:api,user:const {'role':'master'},initialOrder:item,constants:const {},
    )));
    await tester.pumpAndSettle();
    expect(find.text('Снять фото'),findsNothing);
    expect(find.text('Из галереи'),findsNothing);
  });
}
