import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/api.dart';
import '../lib/app_settings.dart';
import '../lib/order_photos.dart';

final _png = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
);

Map<String, dynamic> _photo(Object id, [String name = 'work.png']) => {
  'id': id,
  'file_name': name,
  'phase': 'after',
  'uploaded_at': '2026-10-07T12:30:00Z',
  // A malicious/stale URL must never influence the request destination.
  'url': 'https://untrusted.invalid/photo.png',
};

class _FakeApi implements EnbekApi {
  _FakeApi(this.answer);
  final Future<Uint8List> Function(int) answer;
  final List<int> calls = [];
  @override
  Future<Uint8List> photoBytes(int id) {
    calls.add(id);
    return answer(id);
  }
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _host(_FakeApi api, List<Map<String, dynamic>> photos, {
  AppSettings? settings,
  ThemeData? theme,
}) => AppSettingsScope(
  settings: settings ?? AppSettings(store: MemorySettingsStore()),
  child: MaterialApp(
    theme: theme,
    home: Scaffold(body: SingleChildScrollView(child: Padding(
      padding: const EdgeInsets.all(16),
      child: OrderPhotos(key: const ValueKey('photos'), api: api, photos: photos),
    ))),
  ),
);

// A pending image deliberately keeps a progress indicator animating, so
// pumpAndSettle is inappropriate. First install the route/start its ticker,
// then advance the transition and process its completion frame.
Future<void> _pumpNavigation(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 500));
  await tester.pump();
}

void main() {
  group('OrderPhotos without networking', () {
    testWidgets('empty and invalid IDs never call the API', (tester) async {
      final api = _FakeApi((_) async => _png);
      await tester.pumpWidget(_host(api, []));
      expect(find.text('Фото пока нет.'), findsOneWidget);
      await tester.pumpWidget(_host(api, [_photo('not-an-id'), _photo(-1)]));
      expect(find.text('Фото недоступно.'), findsNWidgets(2));
      expect(api.calls, isEmpty);
    });

    testWidgets('one future per ID survives theme and locale rebuilds', (tester) async {
      final response = Completer<Uint8List>();
      final api = _FakeApi((_) => response.future);
      final settings = AppSettings(store: MemorySettingsStore());
      await tester.pumpWidget(_host(api, [_photo(1)], settings: settings));
      expect(find.text('Загрузка фото…'), findsOneWidget);
      expect(api.calls, [1]);
      settings.setLanguage('en');
      await tester.pump();
      await tester.pumpWidget(_host(api, [_photo(1)], settings: settings, theme: ThemeData.dark()));
      expect(api.calls, [1]);
      response.complete(_png);
      await tester.pumpAndSettle();
      expect(find.byType(Image), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('new IDs load once and duplicate IDs share a future', (tester) async {
      final api = _FakeApi((_) async => _png);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpAndSettle();
      await tester.pumpWidget(_host(api, [_photo(1), _photo(2), _photo(2, 'duplicate.png')]));
      await tester.pumpAndSettle();
      expect(api.calls, [1, 2]);
      expect(find.byType(Image), findsNWidgets(3));
    });

    testWidgets('full-screen reuses bytes and supports close and reopening', (tester) async {
      final api = _FakeApi((_) async => _png);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpAndSettle();
      for (var repeat = 0; repeat < 2; repeat++) {
        await tester.tap(find.byTooltip('Открыть фото: work.png'));
        await tester.pumpAndSettle();
        expect(find.byType(InteractiveViewer), findsOneWidget);
        expect(api.calls, [1]);
        await tester.tap(find.byTooltip('Закрыть'));
        await tester.pumpAndSettle();
        expect(find.byType(InteractiveViewer), findsNothing);
      }
      expect(tester.takeException(), isNull);
    });

    testWidgets('closing full-screen during a load is safe', (tester) async {
      final response = Completer<Uint8List>();
      final api = _FakeApi((_) => response.future);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.tap(find.byTooltip('Открыть фото: work.png'));
      await _pumpNavigation(tester);
      await tester.tap(find.byTooltip('Закрыть'));
      await _pumpNavigation(tester);
      response.complete(_png);
      await tester.pumpAndSettle();
      expect(api.calls, [1]);
      expect(find.byType(InteractiveViewer), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('errors wait for one explicit retry and do not expose raw details', (tester) async {
      var attempts = 0;
      final api = _FakeApi((_) async {
        attempts++;
        if (attempts == 1) throw const ApiException('private debug URL', statusCode: 500);
        return _png;
      });
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpAndSettle();
      expect(find.text('Не удалось загрузить фото.'), findsOneWidget);
      expect(find.text('private debug URL'), findsNothing);
      await tester.pump(const Duration(seconds: 30));
      expect(api.calls, [1]);
      await tester.tap(find.text('Повторить'));
      await tester.pumpAndSettle();
      expect(api.calls, [1, 1]);
      expect(find.byType(Image), findsOneWidget);
    });

    testWidgets('decode failure offers an explicit retry', (tester) async {
      var attempts = 0;
      final api = _FakeApi((_) async => ++attempts == 1
          ? Uint8List.fromList([1, 2, 3]) : _png);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpAndSettle();
      expect(find.text('Не удалось открыть изображение.'), findsOneWidget);
      expect(api.calls, [1]);
      await tester.tap(find.text('Повторить'));
      await tester.pumpAndSettle();
      expect(api.calls, [1, 1]);
      expect(find.text('Не удалось открыть изображение.'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('rapid repeated open taps create only one viewer', (tester) async {
      final response = Completer<Uint8List>();
      final api = _FakeApi((_) => response.future);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      final open = find.byTooltip('Открыть фото: work.png');
      final openAgain = tester.widget<IconButton>(find.byWidgetPredicate(
        (widget) => widget is IconButton && widget.tooltip == 'Открыть фото: work.png',
      )).onPressed!;
      await tester.tap(open);
      // Deliver the second already-queued callback to the same control. A
      // second finder tap would instead hit the newly inserted route barrier.
      openAgain();
      await _pumpNavigation(tester);
      expect(find.byTooltip('Закрыть'), findsOneWidget);
      await tester.tap(find.byTooltip('Закрыть'));
      await _pumpNavigation(tester);
      expect(find.byTooltip('Закрыть'), findsNothing);
      expect(find.byTooltip('Открыть фото: work.png'), findsOneWidget);
      response.complete(_png);
      await tester.pumpAndSettle();
      expect(api.calls, [1]);
      expect(tester.takeException(), isNull);
    });

    testWidgets('401 explains reauthentication without automatic retries', (tester) async {
      final api = _FakeApi((_) async {
        throw const ApiException('server response', statusCode: 401);
      });
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpAndSettle();
      expect(find.text('Сессия истекла. Войдите снова.'), findsOneWidget);
      expect(api.calls, [1]);
    });

    testWidgets('replacing API does not display old-session photo bytes', (tester) async {
      final oldApi = _FakeApi((_) async => _png);
      final response = Completer<Uint8List>();
      final newApi = _FakeApi((_) => response.future);
      await tester.pumpWidget(_host(oldApi, [_photo(1)]));
      await tester.pumpAndSettle();
      await tester.pumpWidget(_host(newApi, [_photo(1)]));
      expect(find.byType(Image), findsNothing);
      expect(find.text('Загрузка фото…'), findsOneWidget);
      expect(oldApi.calls, [1]);
      expect(newApi.calls, [1]);
      response.complete(_png);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('removing an open photo during loading safely retires its viewer', (tester) async {
      final response = Completer<Uint8List>();
      final api = _FakeApi((_) => response.future);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.tap(find.byTooltip('Открыть фото: work.png'));
      await _pumpNavigation(tester);
      await tester.pumpWidget(_host(api, []));
      await tester.pump();
      expect(find.text('Фото недоступно.'), findsOneWidget);
      response.complete(_png);
      await tester.pumpAndSettle();
      expect(find.byType(Image), findsNothing);
      await tester.tap(find.byTooltip('Закрыть'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('disposing the whole screen during a failed request is safe', (tester) async {
      final response = Completer<Uint8List>();
      final api = _FakeApi((_) => response.future);
      await tester.pumpWidget(_host(api, [_photo(1)]));
      await tester.pumpWidget(const SizedBox.shrink());
      response.completeError(const ApiException('offline'));
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  });

  group('photoBytes with an in-memory HttpClient', () {
    test('uses only same-origin ID route and session cookie with redirects disabled', () async {
      final client = _HttpClient([_loginResponse(), _imageResponse(_png)]);
      final api = EnbekApi('https://unit.invalid/prefix?unused=1#fragment', client: client);
      await api.login('test', 'test');
      expect(await api.photoBytes(7), _png);
      final request = client.requests.last;
      expect(request.uri.toString(), 'https://unit.invalid/api/photos/7');
      expect(request.method, 'GET');
      expect(request.followRedirects, isFalse);
      expect(request.maxRedirects, 0);
      expect(request.headers.value(HttpHeaders.cookieHeader), 'naryadai_session=fake-test-session');
      api.close();
    });

    test('redirect response is rejected without following the new origin', () async {
      final redirect = _Response([], status: 302, mime: 'text/html');
      redirect.headers.set(HttpHeaders.locationHeader, 'https://untrusted.invalid/');
      final client = _HttpClient([_loginResponse(), redirect]);
      final api = EnbekApi('https://unit.invalid', client: client);
      await api.login('test', 'test');
      await expectLater(api.photoBytes(1), throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'status', 302)));
      expect(client.requests, hasLength(2));
      expect(client.requests.last.aborted, isTrue);
      api.close();
    });

    test('401 clears session; next photo attempt does not send a stale cookie', () async {
      final client = _HttpClient([_loginResponse(), _Response([], status: 401)]);
      final api = EnbekApi('https://unit.invalid', client: client);
      await api.login('test', 'test');
      final unauthorized = throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 401));
      await expectLater(api.photoBytes(1), unauthorized);
      await expectLater(api.photoBytes(1), unauthorized);
      expect(client.requests, hasLength(2));
      api.close();
    });

    test('invalid IDs are rejected before opening a request', () async {
      final client = _HttpClient([]);
      final api = EnbekApi('https://unit.invalid', client: client);
      await expectLater(api.photoBytes(0), throwsA(isA<ApiException>()));
      expect(client.requests, isEmpty);
      api.close();
    });

    for (final entry in <String, _Response>{
      'non-image content type': _Response([utf8.encode('<html>login</html>')], mime: 'text/html'),
      'empty image': _imageResponse(Uint8List(0)),
      'mismatched bytes': _imageResponse(Uint8List.fromList([1, 2, 3])),
      'oversized content length': _Response([_png], mime: 'image/png', length: 6000001),
      'oversized chunked body': _Response([Uint8List(6000001)], mime: 'image/png', length: -1),
    }.entries) {
      test('rejects ${entry.key}', () async {
        final client = _HttpClient([_loginResponse(), entry.value]);
        final api = EnbekApi('https://unit.invalid', client: client);
        await api.login('test', 'test');
        final expectedMessage = entry.key.startsWith('oversized')
            ? 'Фото превышает допустимый размер.'
            : entry.key == 'empty image' ? 'Сервер вернул пустое фото.'
            : 'Сервер вернул неподдерживаемый формат фото.';
        await expectLater(api.photoBytes(1), throwsA(isA<ApiException>()
            .having((error) => error.message, 'message', expectedMessage)));
        expect(client.requests.last.aborted, isTrue);
        api.close();
      });
    }
  });
}

// These doubles have no sockets, plugins, test-only dependencies, or external calls.
_Response _loginResponse() => _Response([
  utf8.encode(jsonEncode({'user': {'csrf': 'fake-csrf'}})),
], cookies: [Cookie('naryadai_session', 'fake-test-session')]);
_Response _imageResponse(Uint8List bytes) => _Response([bytes], mime: 'image/png');

class _HttpClient implements HttpClient {
  _HttpClient(this.responses);
  final List<_Response> responses;
  final List<_Request> requests = [];
  @override
  Duration? connectionTimeout;
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    final request = _Request(method, url, responses.removeAt(0));
    requests.add(request);
    return request;
  }
  @override
  void close({bool force = false}) {}
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Headers implements HttpHeaders {
  final Map<String, Object> values = {};
  @override
  ContentType? contentType;
  @override
  void set(String name, Object value, {bool preserveHeaderCase = false}) {
    values[name.toLowerCase()] = value;
  }
  @override
  String? value(String name) => values[name.toLowerCase()]?.toString();
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Request implements HttpClientRequest {
  _Request(this.method, this.uri, this.response);
  @override
  final String method;
  @override
  final Uri uri;
  final _Response response;
  @override
  final _Headers headers = _Headers();
  @override
  bool followRedirects = true;
  @override
  int maxRedirects = 5;
  @override
  int contentLength = -1;
  @override
  Encoding encoding = utf8;
  bool aborted = false;
  @override
  void add(List<int> data) {}
  @override
  Future<HttpClientResponse> close() async => response;
  @override
  void abort([Object? exception, StackTrace? stackTrace]) => aborted = true;
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Response extends Stream<List<int>> implements HttpClientResponse {
  _Response(this.chunks, {
    int status = 200,
    String mime = 'application/json',
    int? length,
    this.cookies = const [],
  }) : statusCode = status,
       contentLength = length ?? chunks.fold<int>(0, (sum, bytes) => sum + bytes.length) {
    headers.contentType = ContentType.parse(mime);
  }
  final List<List<int>> chunks;
  @override
  final int statusCode;
  @override
  final int contentLength;
  @override
  final List<Cookie> cookies;
  @override
  final _Headers headers = _Headers();
  @override
  StreamSubscription<List<int>> listen(void Function(List<int>)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) => Stream<List<int>>.fromIterable(chunks).listen(onData,
      onError: onError, onDone: onDone, cancelOnError: cancelOnError);
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
