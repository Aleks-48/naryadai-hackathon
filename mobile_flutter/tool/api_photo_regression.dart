// Run: dart run tool/api_photo_regression.dart
// Loopback-only HTTP fixtures; no credentials or tokens are printed.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import '../lib/api.dart';

void check(bool value, String message) { if (!value) throw StateError(message); }

Future<void> main() async {
  final source = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  final other = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  var otherRequests = 0, sourceRequests = 0;
  final serverErrors = <String>[];
  final png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=');
  other.listen((request) async {
    otherRequests++;
    request.response.statusCode = 500;
    await request.response.close();
  });
  source.listen((request) async {
    sourceRequests++;
    try {
      if (request.uri.path == '/api/login') {
        await request.drain<void>();
        request.response.cookies.add(Cookie('naryadai_session', 'fixture-session'));
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'user': {'csrf': 'fixture-csrf'}}));
      } else {
        check(request.method == 'GET', 'Photo endpoint must be read-only');
        check(request.headers.value(HttpHeaders.cookieHeader) == 'naryadai_session=fixture-session', 'Photo request lost session');
        final id = int.parse(request.uri.path.split('/').last);
        switch (id) {
          case 1:
            request.response.headers.contentType = ContentType('image', 'png');
            request.response.add(png);
          case 2:
            request.response.statusCode = 302;
            request.response.headers.set(HttpHeaders.locationHeader, 'http://127.0.0.1:${other.port}/forbidden');
          case 3:
            request.response.statusCode = 403;
          case 4:
            request.response.statusCode = 404;
          case 5:
            request.response.headers.contentType = ContentType.html;
            request.response.write('<html>gateway</html>');
          case 6:
            request.response.headers.contentType = ContentType('image', 'png');
            request.response.add([1, 2, 3]); // Incorrect signature.
          case 7:
            request.response.statusCode = 401;
          case 8:
            request.response.headers.contentType = ContentType('image', 'png');
            request.response.contentLength = 6000001;
            request.response.add(Uint8List(6000001));
          default:
            throw StateError('Unexpected fixture path');
        }
      }
    } catch (_) {
      serverErrors.add('Fixture request failed');
      request.response.statusCode = 500;
    } finally {
      // Rejecting oversized or invalid images may intentionally abort the socket.
      try { await request.response.close(); } on IOException { /* Expected abort. */ }
    }
  });
  final client = HttpClient()..findProxy = (_) => 'DIRECT';
  final api = EnbekApi('http://127.0.0.1:${source.port}', client: client);
  Future<void> rejected(int id, {int? status}) async {
    try {
      await api.photoBytes(id);
      throw StateError('Unsafe photo response unexpectedly accepted');
    } on ApiException catch (error) {
      if (status != null) check(error.statusCode == status, 'Wrong photo failure status');
    }
  }
  try {
    await api.login('fixture-user', 'fixture-password');
    final received = await api.photoBytes(1);
    check(base64Encode(received) == base64Encode(png), 'Photo bytes changed');
    final beforeInvalidId = sourceRequests;
    await rejected(-1);
    check(sourceRequests == beforeInvalidId, 'Invalid ID sent a request');
    await rejected(2, status: 302);
    await rejected(3, status: 403);
    await rejected(4, status: 404);
    await rejected(5);
    await rejected(6);
    await rejected(8);
    await rejected(7, status: 401);
    final afterExpiry = sourceRequests;
    await rejected(1, status: 401);
    check(sourceRequests == afterExpiry, 'Expired session still requested media');
    check(otherRequests == 0, 'A media redirect leaked a request to another origin');
    check(serverErrors.isEmpty, serverErrors.join('; '));
    stdout.writeln('PASS protected media: cookie, bytes, ID validation, redirect rejection, 403/404/401, MIME, signature, size');
  } finally {
    api.close();
    await source.close(force: true);
    await other.close(force: true);
  }
}
