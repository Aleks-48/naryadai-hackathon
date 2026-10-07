// Run: dart run tool/api_transport_regression.dart
// Loopback only. No credentials, response bodies, cookies or tokens are logged.
import 'dart:convert';
import 'dart:io';
import '../lib/api.dart';

void check(bool ok, String message) {
  if (!ok) throw StateError(message);
}

Future<void> main() async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  const cookie = 'synthetic-session';
  const csrf = 'synthetic-csrf';
  final failures = <String>[];
  var calls = 0;
  var loginCalls = 0;
  server.listen((request) async {
    try {
      calls++;
      final bytes = await request.fold<List<int>>(
        <int>[], (buffer, chunk) => buffer..addAll(chunk),
      );
      Map<String, dynamic> body = {};
      if (request.method == 'POST') {
        check(request.contentLength == bytes.length, 'Wrong UTF-8 Content-Length');
        check(!request.headers.chunkedTransferEncoding, 'Chunked JSON body');
        check(request.headers.contentType?.mimeType == 'application/json', 'Not JSON');
        body = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      } else {
        check(bytes.isEmpty, 'Unexpected GET body');
      }
      final path = request.uri.path;
      request.response.headers.contentType = ContentType.json;
      if (path == '/api/login') {
        loginCalls++;
        check(request.headers.value(HttpHeaders.cookieHeader) == null, 'Stale login cookie');
        check(request.headers.value('X-CSRF-Token') == null, 'Stale login CSRF');
        if (loginCalls == 2) {
          check(body['username'] == 'мастер🔧', 'Username must be trimmed');
          check(body['password'] == ' пароль🔐 ', 'Password must remain exact');
        } else {
          check(body['username'] == 'master01', 'Username changed');
        }
        if (body['password'] == 'wrong') {
          request.response.statusCode = 401;
          request.response.write(jsonEncode({'error': 'Неверный логин или пароль'}));
        } else if (body['password'] == 'gateway-fixture') {
          request.response.statusCode = 502;
          request.response.write('<html>Bad gateway</html>');
        } else {
          if (loginCalls != 2) check(body['password'] == 'demo123', 'Password changed');
          request.response.cookies.add(Cookie('naryadai_session', cookie)..httpOnly = true);
          request.response.write(jsonEncode({'user': {'id': 1, 'csrf': csrf}}));
        }
      } else {
        check(request.headers.value(HttpHeaders.cookieHeader) == 'naryadai_session=$cookie', 'Missing session cookie');
        if (request.method == 'POST') {
          check(request.headers.value('X-CSRF-Token') == csrf, 'Missing CSRF header');
        }
        switch (path) {
          case '/api/orders':
            check(body['title'] == 'Проверка узла' && body['worker_id'] == 3 && body['norm_hours'] == 8, 'Create payload changed');
          case '/api/bootstrap':
            check(request.method == 'GET', 'Bootstrap method changed');
          case '/api/orders/7/action':
            check(body['action'] == 'pause' && body['reason'] == 'Проверка 🔧', 'Unicode action changed');
          case '/api/orders/7/rating':
            check(body['rating'] == 4 && body['reason'] == 'Повторная проверка', 'Rating changed');
          case '/api/orders/7/photos':
            check(body['file_name'] == 'ремонт.png', 'Filename changed');
            check(body['data_url'] == 'data:image/png;base64,${base64Encode(List<int>.generate(8192, (i) => i % 256))}', 'Photo changed');
          case '/api/logout':
            check(bytes.length == 2 && body.isEmpty, 'Logout must send two-byte empty JSON');
          default:
            throw StateError('Unexpected endpoint');
        }
        request.response.write('{}');
      }
    } catch (error) {
      failures.add(error.toString());
      request.response.statusCode = 500;
      request.response.write('{}');
    } finally {
      await request.response.close();
    }
  });
  final client = HttpClient()..findProxy = (_) => 'DIRECT';
  final api = EnbekApi('http://127.0.0.1:${server.port}', client: client);
  try {
    await api.login('  master01  ', 'demo123');
    await api.bootstrap();
    await api.action(7, 'pause', payload: {'reason': 'Проверка 🔧'});
    await api.rateOrder(7, rating: 4, reason: 'Повторная проверка');
    await api.uploadPhoto(orderId: 7, fileName: 'ремонт.png', mimeType: 'image/png', bytes: List<int>.generate(8192, (i) => i % 256));
    await api.createOrder({'title': 'Проверка узла', 'description': 'Проверить узел оборудования', 'work_type': 'planned', 'priority': 'normal', 'area_id': 1, 'equipment_id': 2, 'worker_id': 3, 'norm_hours': 8});
    await api.logout();
    await api.logout();
    await api.login('  мастер🔧  ', ' пароль🔐 ');
    try {
      await api.login('master01', 'wrong');
      throw StateError('Incorrect password succeeded');
    } on ApiException catch (error) {
      check(error.statusCode == 401, '401 status was lost');
      check(error.message == 'Неверный логин или пароль', 'Backend error message changed');
    }
    await api.logout(); // Failed relogin must have cleared the previous session.
    try {
      await api.login('master01', 'gateway-fixture');
      throw StateError('Gateway failure succeeded');
    } on ApiException catch (error) {
      check(error.statusCode == 502, 'Gateway status was lost');
      check(error.message.contains('некорректный ответ'), 'Gateway error misclassified');
    }
    check(failures.isEmpty, failures.join('; '));
    check(calls == 10, 'Unexpected request count');
    stdout.writeln('PASS 10 loopback requests including master creation: framing, UTF-8, credentials, cookie/CSRF, writes, logout, 401, gateway');
  } finally {
    api.close();
    await server.close(force: true);
  }
}
