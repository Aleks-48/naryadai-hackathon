import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';

import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/create_order.dart';

const _bootstrap = <String, dynamic>{
  'constants': {
    'areas': [ {'id': 10, 'name': 'North workshop'}, {'id': 20, 'name': 'South workshop'} ],
    'equipment': [
      {'id': 100, 'area_id': 10, 'code': 'N-1', 'name': 'Pump'},
      {'id': 101, 'area_id': 10, 'code': 'N-2', 'name': 'Fan'},
      {'id': 200, 'area_id': 20, 'code': 'S-1', 'name': 'Conveyor'},
    ],
    'users': [
      {'id': 7, 'display_name': 'Worker Seven', 'role': 'worker', 'brigade': 'A'},
      {'id': 8, 'display_name': 'Worker Eight', 'role': 'worker', 'brigade': 'B'},
      {'id': 9, 'display_name': 'Manager Nine', 'role': 'manager'},
    ],
  },
  'free_workers': [
    {'id': 7, 'display_name': 'Worker Seven', 'brigade': 'A', 'active_orders': 2,
      'availability': 'busy', 'rating_detail': {'score': 4.5}},
  ],
};

class _Api extends EnbekApi {
  _Api() : super('http://127.0.0.1');
  final creates = <Map<String, dynamic>>[];
  final uploads = <Map<String, dynamic>>[];
  Object? createError;
  Object? uploadError;
  int? failUploadAttempt;
  bool malformedCreate = false;
  Completer<Map<String, dynamic>>? createGate;
  Completer<Map<String, dynamic>>? uploadGate;
  Map<String, dynamic>? fetchedOrder;
  Map<String, dynamic> refreshedBootstrap = _bootstrap;
  int reads = 0;
  @override
  Future<Map<String, dynamic>> createOrder(Map<String, dynamic> payload) async {
    creates.add(Map<String, dynamic>.from(payload));
    if (createGate != null) return createGate!.future;
    if (createError != null) throw createError!;
    if (malformedCreate) return {};
    return {'order': {'id': 44, 'code': 'NA-TEST-44', 'title': payload['title']}};
  }
  @override
  Future<Map<String, dynamic>> uploadPhoto({required int orderId, required String fileName,
    required String mimeType, required List<int> bytes, String phase = 'after'}) async {
    uploads.add({'orderId': orderId, 'fileName': fileName, 'mimeType': mimeType,
      'length': bytes.length, 'phase': phase});
    if (uploadGate != null) return uploadGate!.future;
    if (failUploadAttempt == uploads.length) throw uploadError ?? const ApiException('Rejected photo', statusCode: 400);
    return {'photo': {'id': uploads.length + 100}};
  }
  @override
  Future<Map<String, dynamic>> order(int id) async {
    reads++;
    return {'order': fetchedOrder ?? {'id': 44, 'code': 'NA-TEST-44', 'photos': []}};
  }
  @override
  Future<Map<String, dynamic>> bootstrap() async => refreshedBootstrap;
}

class _Picker extends ImagePicker {
  final queue = <XFile?>[];
  final sources = <ImageSource>[];
  final qualities = <int?>[];
  Completer<XFile?>? gate;
  @override
  Future<XFile?> pickImage({required ImageSource source, double? maxWidth,
    double? maxHeight, int? imageQuality, CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true}) async {
    sources.add(source);
    qualities.add(imageQuality);
    if (gate != null) return gate!.future;
    return queue.isEmpty ? null : queue.removeAt(0);
  }
}

Uint8List get _png => base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGOUjHJjYGBgYmBgYGBgAAAIqQC98ApKJwAAAABJRU5ErkJggg==');

// XFile.fromData ignores its name argument on native platforms.
// Keep the fixture filename explicit while retaining in-memory image bytes.
class _NamedPhoto extends XFile {
  _NamedPhoto(this._name) : super.fromData(_png, mimeType: 'image/png');

  final String _name;

  @override
  String get name => _name;
}

XFile _photo(String name) => _NamedPhoto(name);

Future<void> _open(WidgetTester tester, _Api api, {
  Map<String, dynamic> bootstrap = _bootstrap,
  String role = 'master', _Picker? picker, AppSettings? settings,
  ValueChanged<Map<String, dynamic>?>? onResult,
}) async {
  final chosenSettings = settings ?? AppSettings(store: MemorySettingsStore());
  await tester.pumpWidget(AppSettingsScope(settings: chosenSettings,
    child: AnimatedBuilder(animation: chosenSettings, builder: (context, _) => MaterialApp(
      locale: Locale(chosenSettings.language), supportedLocales: const [Locale('ru'), Locale('kk'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: enbekTheme(Brightness.light), darkTheme: enbekTheme(Brightness.dark),
      themeMode: chosenSettings.themeMode,
      home: Builder(builder: (context) => Scaffold(body: Center(child: FilledButton(
        onPressed: () async {
          final result = await Navigator.push<Map<String, dynamic>>(context, MaterialPageRoute(
            builder: (_) => CreateOrderScreen(api: api, user: {'role': role}, bootstrap: bootstrap, picker: picker)));
          onResult?.call(result);
        }, child: const Text('Launch form'))))),
    ))));
  await tester.tap(find.text('Launch form'));
  await tester.pumpAndSettle();
}

Finder _keyPrefix(String prefix) => find.byWidgetPredicate((widget) =>
    widget.key is ValueKey<String> && (widget.key! as ValueKey<String>).value.startsWith(prefix));

Future<void> _tap(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> _choose(WidgetTester tester, Finder dropdown, String text) async {
  await _tap(tester, dropdown);
  await tester.ensureVisible(find.text(text).last);
  await tester.tap(find.text(text).last);
  await tester.pumpAndSettle();
}

Future<void> _fill(WidgetTester tester, {bool brigade = false}) async {
  await tester.enterText(find.byKey(const Key('create-title')), 'Replace pump bearings');
  await tester.enterText(find.byKey(const Key('create-description')), 'Inspect the pump and replace worn bearings safely.');
  await _choose(tester, _keyPrefix('create-area-'), 'North workshop');
  await _choose(tester, _keyPrefix('create-equipment-'), 'N-1 · Pump');
  await _choose(tester, _keyPrefix('create-assignee-'), brigade ? 'Бригада A' : 'Worker Seven');
}

Future<void> _addPhoto(WidgetTester tester) => _tap(tester, find.byKey(const Key('create-gallery')));

void main() {
  testWidgets('worker and manager cannot access creation controls', (tester) async {
    final api = _Api(); addTearDown(api.close);
    for (final role in ['worker', 'manager']) {
      await _open(tester, api, role: role);
      expect(find.text('Создавать наряды может только мастер.'), findsOneWidget);
      expect(find.byKey(const Key('create-submit')), findsNothing);
      expect(api.creates, isEmpty);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('empty catalogs are actionable and never invent IDs', (tester) async {
    final api = _Api(); addTearDown(api.close);
    await _open(tester, api, bootstrap: const {'constants': {}});
    expect(find.textContaining('Обновите справочники.'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('create-submit'))).onPressed, isNull);
    await _tap(tester, find.byKey(const Key('create-refresh-catalog')));
    expect(find.textContaining('Обновите справочники.'), findsNothing);
    await _fill(tester);
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates.single['equipment_id'], 100);
  });

  testWidgets('valid submit creates once without embedded photos and returns order', (tester) async {
    final api = _Api(); addTearDown(api.close);
    Map<String, dynamic>? result;
    await _open(tester, api, onResult: (value) => result = value);
    await _fill(tester);
    await tester.enterText(find.byKey(const Key('create-comment')), 'Keep this user comment unchanged.');
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates, hasLength(1));
    final sent = api.creates.single;
    expect(sent['worker_id'], 7);
    expect(sent.containsKey('brigade'), isFalse);
    expect(sent['norm_hours'], 8);
    expect(sent['priority'], 'normal');
    expect(sent['work_type'], 'unscheduled');
    expect(sent['issuance_comment'], 'Keep this user comment unchanged.');
    expect(sent.containsKey('before_photo'), isFalse);
    expect(sent.containsKey('before_photos'), isFalse);
    expect(api.uploads, isEmpty);
    expect(result?['id'], 44);
    expect(find.text('Launch form'), findsOneWidget);
  });

  testWidgets('brigade payload is exclusive and contains known brigade', (tester) async {
    final api = _Api(); addTearDown(api.close);
    await _open(tester, api);
    await _fill(tester, brigade: true);
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates.single['brigade'], 'A');
    expect(api.creates.single.containsKey('worker_id'), isFalse);
  });

  testWidgets('area change resets equipment and filters incompatible options', (tester) async {
    final api = _Api(); addTearDown(api.close);
    await _open(tester, api);
    await _fill(tester);
    await _choose(tester, _keyPrefix('create-area-'), 'South workshop');
    await _tap(tester, _keyPrefix('create-equipment-'));
    expect(find.text('N-1 · Pump'), findsNothing);
    expect(find.text('S-1 · Conveyor'), findsOneWidget);
    await tester.tap(find.text('S-1 · Conveyor'));
    await tester.pumpAndSettle();
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates.single['area_id'], 20);
    expect(api.creates.single['equipment_id'], 200);
  });

  testWidgets('title description comment and finite hour bounds are validated', (tester) async {
    final api = _Api(); addTearDown(api.close);
    await _open(tester, api);
    await _fill(tester);
    await tester.enterText(find.byKey(const Key('create-title')), 'abc');
    await tester.enterText(find.byKey(const Key('create-description')), 'too short');
    await tester.enterText(find.byKey(const Key('create-comment')), List.filled(1001, 'x').join());
    await tester.enterText(find.byKey(const Key('create-hours')), 'NaN');
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(find.text('Название: от 4 до 160 символов.'), findsOneWidget);
    expect(find.text('Описание: от 10 до 3000 символов.'), findsOneWidget);
    expect(find.text('Комментарий: не больше 1000 символов.'), findsOneWidget);
    expect(find.text('Укажите число часов больше 0 и не больше 720.'), findsOneWidget);
    expect(api.creates, isEmpty);
    await tester.enterText(find.byKey(const Key('create-title')), List.filled(161, 'x').join());
    await tester.enterText(find.byKey(const Key('create-description')), List.filled(3001, 'x').join());
    await tester.pumpAndSettle();
    expect(find.text('Название: от 4 до 160 символов.'), findsOneWidget);
    expect(find.text('Описание: от 10 до 3000 символов.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('create-title')), 'Valid title');
    await tester.enterText(find.byKey(const Key('create-description')), 'Valid longer description');
    await tester.enterText(find.byKey(const Key('create-comment')), '');
    for (final hours in ['0', '-1', '720.1', 'Infinity']) {
      await tester.enterText(find.byKey(const Key('create-hours')), hours);
      await _tap(tester, find.byKey(const Key('create-submit')));
      expect(api.creates, isEmpty);
    }
    await tester.enterText(find.byKey(const Key('create-hours')), '0,5');
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates.single['norm_hours'], 0.5);
  });

  testWidgets('date mode sends future UTC due_at without norm_hours', (tester) async {
    final api = _Api(); addTearDown(api.close);
    await _open(tester, api);
    await _fill(tester);
    await _choose(tester, _keyPrefix('create-deadline-mode-'), 'Выбрать дату и время');
    expect(find.byKey(const Key('create-date')), findsOneWidget);
    expect(find.byKey(const Key('create-time')), findsOneWidget);
    await _tap(tester, find.byKey(const Key('create-submit')));
    final sent = api.creates.single;
    expect(sent.containsKey('norm_hours'), isFalse);
    expect('${sent['due_at']}', endsWith('Z'));
    expect(DateTime.parse(sent['due_at'] as String).isAfter(DateTime.now()), isTrue);
  });

  testWidgets('double tap and Back cannot interrupt create; known rejection is recoverable', (tester) async {
    final api = _Api()..createGate = Completer<Map<String, dynamic>>(); addTearDown(api.close);
    await _open(tester, api);
    await _fill(tester);
    final submit = find.byKey(const Key('create-submit'));
    await tester.ensureVisible(submit);
    await tester.tap(submit);
    await tester.tap(submit);
    await tester.pump();
    expect(api.creates, hasLength(1));
    await tester.binding.handlePopRoute();
    await tester.pump();
    expect(find.byType(CreateOrderScreen), findsOneWidget);
    api.createGate!.completeError(const ApiException('Explicit validation error', statusCode: 400));
    api.createGate = null;
    await tester.pumpAndSettle();
    expect(find.text('Explicit validation error'), findsOneWidget);
    expect(tester.widget<TextFormField>(find.byKey(const Key('create-title'))).controller!.text, 'Replace pump bearings');
    await _tap(tester, submit);
    expect(api.creates, hasLength(2));
  });

  for (final failure in ['timeout', 'server', 'malformed']) {
    testWidgets('$failure create response blocks second create', (tester) async {
      final api = _Api(); addTearDown(api.close);
      if (failure == 'timeout') api.createError = TimeoutException('response lost');
      if (failure == 'server') api.createError = const ApiException('Server failure', statusCode: 500);
      if (failure == 'malformed') api.malformedCreate = true;
      await _open(tester, api);
      await _fill(tester);
      await _tap(tester, find.byKey(const Key('create-submit')));
      expect(api.creates, hasLength(1));
      expect(find.textContaining('Наряд мог быть создан.'), findsOneWidget);
      expect(find.byKey(const Key('create-submit')), findsNothing);
      await _tap(tester, find.byKey(const Key('create-check-list')));
      expect(api.creates, hasLength(1));
      expect(find.text('Launch form'), findsOneWidget);
    });
  }

  testWidgets('picker cancel invalid image and oversized image do not attach', (tester) async {
    final api = _Api(); final picker = _Picker(); addTearDown(api.close);
    picker.queue.addAll([null,
      XFile.fromData(Uint8List.fromList([1, 2, 3]), name: 'fake.jpg'),
      XFile.fromData(Uint8List(4000001), name: 'large.png')]);
    await _open(tester, api, picker: picker);
    await _addPhoto(tester);
    expect(find.text('Фото «до»: 0 из 5'), findsOneWidget);
    await _addPhoto(tester);
    expect(find.text('Выберите читаемое фото JPEG, PNG или WebP.'), findsOneWidget);
    await _addPhoto(tester);
    expect(find.text('Фото больше 4 МБ. Выберите или снимите файл поменьше.'), findsOneWidget);
    expect(find.text('Фото «до»: 0 из 5'), findsOneWidget);
    expect(api.creates, isEmpty);
  });

  testWidgets('five-photo cap compression and removal apply before submit', (tester) async {
    final api = _Api(); final picker = _Picker(); addTearDown(api.close);
    picker.queue.addAll(List.generate(5, (i) => _photo('photo-$i.png')));
    await _open(tester, api, picker: picker);
    for (var i = 0; i < 5; i++) { await _addPhoto(tester); }
    expect(find.text('Фото «до»: 5 из 5'), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('create-gallery'))).onPressed, isNull);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('create-camera'))).onPressed, isNull);
    expect(picker.qualities, everyElement(80));
    expect(picker.sources, everyElement(ImageSource.gallery));
    await _tap(tester, find.byKey(const Key('create-remove-photo-0')));
    expect(find.text('Фото «до»: 4 из 5'), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('create-gallery'))).onPressed, isNotNull);
    expect(api.uploads, isEmpty);
  });

  testWidgets('partial uploads retry only failed and unattempted photos; never create twice', (tester) async {
    final api = _Api()..failUploadAttempt = 2;
    final picker = _Picker()..queue.addAll([_photo('one.png'), _photo('two.png'), _photo('three.png')]);
    addTearDown(api.close);
    Map<String, dynamic>? result;
    await _open(tester, api, picker: picker, onResult: (value) => result = value);
    await _fill(tester);
    for (var i = 0; i < 3; i++) { await _addPhoto(tester); }
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates, hasLength(1));
    expect(api.uploads, hasLength(2));
    expect(find.text('Наряд NA-TEST-44 уже создан.'), findsOneWidget);
    expect(find.text('Фото загружено: 1 из 3'), findsOneWidget);
    expect(api.uploads, everyElement(containsPair('phase', 'before')));
    expect(api.uploads, everyElement(containsPair('mimeType', 'image/png')));
    final firstName = api.uploads.first['fileName'];
    final failedName = api.uploads.last['fileName'];
    await _tap(tester, find.byKey(const Key('create-retry-photos')));
    expect(api.creates, hasLength(1));
    expect(api.uploads, hasLength(4));
    expect(api.uploads.where((item) => item['fileName'] == firstName), hasLength(1));
    expect(api.uploads[2]['fileName'], failedName);
    expect(result?['id'], 44);
  });

  testWidgets('Back stays blocked during upload and completion returns once', (tester) async {
    final api = _Api()..uploadGate = Completer<Map<String, dynamic>>();
    final picker = _Picker()..queue.add(_photo('one.png')); addTearDown(api.close);
    var returns = 0;
    await _open(tester, api, picker: picker, onResult: (_) => returns++);
    await _fill(tester); await _addPhoto(tester);
    final submit = find.byKey(const Key('create-submit'));
    await tester.ensureVisible(submit); await tester.tap(submit); await tester.pump();
    expect(api.creates, hasLength(1)); expect(api.uploads, hasLength(1));
    await tester.binding.handlePopRoute(); await tester.pump();
    expect(find.byType(CreateOrderScreen), findsOneWidget);
    expect(find.byKey(const Key('create-finish-without-photos')), findsNothing);
    api.uploadGate!.complete({'photo': {'id': 101}});
    await tester.pumpAndSettle();
    expect(returns, 1); expect(api.creates, hasLength(1));
    expect(find.text('Launch form'), findsOneWidget);
  });

  testWidgets('ambiguous photo absence does not authorize reupload', (tester) async {
    final api = _Api()..failUploadAttempt = 1..uploadError = TimeoutException('upload response lost');
    final picker = _Picker()..queue.add(_photo('one.png')); addTearDown(api.close);
    await _open(tester, api, picker: picker);
    await _fill(tester); await _addPhoto(tester);
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(find.byKey(const Key('create-retry-photos')), findsNothing);
    await _tap(tester, find.byKey(const Key('create-check-photos')));
    expect(api.reads, 1);
    expect(api.uploads, hasLength(1));
    expect(api.creates, hasLength(1));
    expect(find.byKey(const Key('create-check-photos')), findsOneWidget);
    expect(find.byKey(const Key('create-retry-photos')), findsNothing);
  });

  testWidgets('ambiguous photo presence is reconciled without uploading it again', (tester) async {
    final api = _Api()..failUploadAttempt = 1..uploadError = TimeoutException('upload response lost');
    final picker = _Picker()..queue.addAll([_photo('one.png'), _photo('two.png')]); addTearDown(api.close);
    await _open(tester, api, picker: picker);
    await _fill(tester); await _addPhoto(tester); await _addPhoto(tester);
    await _tap(tester, find.byKey(const Key('create-submit')));
    api.fetchedOrder = {'id': 44, 'code': 'NA-TEST-44', 'photos': [
      {'id': 101, 'phase': 'before', 'file_name': api.uploads.first['fileName'], 'size_bytes': _png.length},
    ]};
    await _tap(tester, find.byKey(const Key('create-check-photos')));
    expect(api.uploads, hasLength(2));
    expect(api.uploads.first['fileName'], isNot(api.uploads.last['fileName']));
    expect(api.creates, hasLength(1));
    expect(find.text('Launch form'), findsOneWidget);
  });

  testWidgets('explicit finish after failed upload returns existing order', (tester) async {
    final api = _Api()..failUploadAttempt = 1;
    final picker = _Picker()..queue.add(_photo('one.png')); addTearDown(api.close);
    Map<String, dynamic>? result;
    await _open(tester, api, picker: picker, onResult: (value) => result = value);
    await _fill(tester); await _addPhoto(tester);
    await _tap(tester, find.byKey(const Key('create-submit')));
    await _tap(tester, find.byKey(const Key('create-finish-without-photos')));
    expect(find.text('Завершить без оставшихся фото?'), findsOneWidget);
    await tester.tap(find.text('Открыть созданный наряд'));
    await tester.pumpAndSettle();
    expect(result?['id'], 44);
    expect(api.creates, hasLength(1));
    expect(api.uploads, hasLength(1));
  });

  testWidgets('language and theme changes preserve text selections and photos at 320px', (tester) async {
    tester.view.physicalSize = const Size(320, 800); tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api = _Api(); final settings = AppSettings(store: MemorySettingsStore());
    final picker = _Picker()..queue.add(_photo('Original photo name.png')); addTearDown(api.close);
    await _open(tester, api, picker: picker, settings: settings);
    await _fill(tester); await _addPhoto(tester);
    for (final language in ['kk', 'en', 'ru']) {
      settings.setLanguage(language); settings.setTheme(ThemeMode.dark);
      await tester.pumpAndSettle();
      expect(tester.widget<TextFormField>(find.byKey(const Key('create-title'))).controller!.text, 'Replace pump bearings');
      expect(find.text('Original photo name.png'), findsOneWidget);
      expect(tester.takeException(), isNull);
    }
    await _tap(tester, find.byKey(const Key('create-submit')));
    expect(api.creates.single['worker_id'], 7);
    expect(api.creates.single['equipment_id'], 100);
    expect(api.uploads, hasLength(1));
    await tester.pumpWidget(const SizedBox.shrink()); settings.dispose();
  });

  testWidgets('late picker cancellation after screen disposal is safe', (tester) async {
    final api = _Api(); final picker = _Picker()..gate = Completer<XFile?>(); addTearDown(api.close);
    await _open(tester, api, picker: picker);
    final camera = find.byKey(const Key('create-camera'));
    await tester.ensureVisible(camera); await tester.tap(camera); await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    picker.gate!.complete(null); await tester.pump();
    expect(picker.sources, [ImageSource.camera]);
    expect(tester.takeException(), isNull);
    expect(api.creates, isEmpty);
  });
}
