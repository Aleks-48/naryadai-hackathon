import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

/// Authenticated client for the existing EnbekPlus HTTP API.
/// The opaque HttpOnly session cookie and CSRF token stay in memory only.
class EnbekApi {
  EnbekApi(String baseUrl, {HttpClient? client})
    : baseUri = _normalizeBaseUrl(baseUrl),
      _client = client ?? HttpClient() {
    _client.connectionTimeout = const Duration(seconds: 12);
  }

  final Uri baseUri;
  final HttpClient _client;
  String? _sessionCookie;
  String? _csrf;
  bool _disposed = false;

  static Uri _normalizeBaseUrl(String input) {
    final raw = input.trim();
    final parsed = Uri.tryParse(raw);
    if (parsed == null ||
        !parsed.hasAuthority ||
        (parsed.scheme != 'http' && parsed.scheme != 'https') ||
        parsed.userInfo.isNotEmpty) {
      throw const ApiException(
        'Укажите адрес сервера, например http://10.0.2.2:8768',
      );
    }
    return parsed.replace(path: parsed.path == '/' ? '' : parsed.path);
  }

  Future<Map<String, dynamic>> login(String username, String password) async {
    _sessionCookie = null;
    _csrf = null;
    final result = await _request(
      '/api/login',
      method: 'POST',
      body: {'username': username.trim(), 'password': password},
      allowUnauthenticated: true,
    );
    final user = _asMap(result['user']);
    _csrf = user['csrf'] as String?;
    if (_sessionCookie == null || _csrf == null || _csrf!.isEmpty) {
      throw const ApiException(
        'Сервер не вернул сессию. Проверьте адрес backend.',
      );
    }
    return user;
  }

  Future<Map<String, dynamic>> bootstrap() => _request('/api/bootstrap');

  Future<Map<String, dynamic>> createOrder(Map<String, dynamic> payload) =>
      _request('/api/orders', method: 'POST', body: payload);

  Future<Map<String, dynamic>> telegramStatus() => _request('/api/telegram/status');

  Future<Map<String, dynamic>> telegramPair() => _request(
    '/api/telegram/pair', method: 'POST', body: const {},
  );

  Future<Map<String, dynamic>> telegramUnpair() => _request(
    '/api/telegram/unpair', method: 'POST', body: const {},
  );


  Future<Uint8List> photoBytes(int photoId) async {
    if (_disposed) throw const ApiException('Сетевой клиент закрыт.');
    if (photoId <= 0) {
      throw const ApiException('Некорректный идентификатор фото.');
    }
    final session = _sessionCookie;
    if (session == null) {
      throw const ApiException(
        'Сессия истекла. Войдите снова.', statusCode: 401,
      );
    }

    // Never use a photo['url'] or follow a redirect with the session cookie.
    final uri = baseUri.resolve('/api/photos/$photoId');
    const limit = 6_000_000;
    HttpClientRequest? request;
    StreamIterator<List<int>>? chunks;
    var abandoned = false;
    var completed = false;
    try {
      request = await _client.openUrl('GET', uri).then((opened) {
        // Opening a socket can finish after its timeout or after logout.
        if (abandoned || _disposed || _sessionCookie != session) {
          opened.abort();
        }
        return opened;
      }).timeout(const Duration(seconds: 15));
      if (_disposed || _sessionCookie != session) {
        throw const ApiException(
          'Сессия истекла. Войдите снова.', statusCode: 401,
        );
      }
      request.followRedirects = false;
      request.maxRedirects = 0;
      request.headers.set(HttpHeaders.acceptHeader, 'image/jpeg,image/png,image/webp');
      request.headers.set(HttpHeaders.cacheControlHeader, 'no-store');
      request.headers.set(HttpHeaders.cookieHeader, session);
      final response = await request.close().timeout(const Duration(seconds: 20));
      chunks = StreamIterator<List<int>>(response);
      final status = response.statusCode;
      if (status == 401) {
        // A late response from an old session must not log out a newer one.
        if (_sessionCookie == session) {
          _sessionCookie = null;
          _csrf = null;
        }
        throw const ApiException(
          'Сессия истекла. Войдите снова.', statusCode: 401,
        );
      }
      if (status >= 300 && status < 400) {
        throw ApiException(
          'Сервер перенаправил запрос фото. Проверьте адрес сервера.',
          statusCode: status,
        );
      }
      if (status != HttpStatus.ok) {
        throw ApiException(
          status == 403 ? 'Нет доступа к фото.'
              : status == 404 ? 'Фото не найдено.'
              : 'Не удалось загрузить фото.',
          statusCode: status,
        );
      }
      final mime = response.headers.contentType?.mimeType.toLowerCase();
      if (!const {'image/jpeg', 'image/png', 'image/webp'}.contains(mime)) {
        throw const ApiException('Сервер вернул неподдерживаемый формат фото.');
      }
      if (response.contentLength > limit) {
        throw const ApiException('Фото превышает допустимый размер.');
      }
      final buffer = BytesBuilder(copy: false);
      final bodyTimer = Stopwatch()..start();
      // A total body deadline prevents indefinitely slow/trickling downloads.
      while (true) {
        final remaining = const Duration(seconds: 30) - bodyTimer.elapsed;
        if (remaining <= Duration.zero) throw TimeoutException('photo');
        if (!await chunks.moveNext().timeout(remaining)) break;
        final chunk = chunks.current;
        if (buffer.length + chunk.length > limit) {
          throw const ApiException('Фото превышает допустимый размер.');
        }
        buffer.add(chunk);
      }
      if (buffer.isEmpty) {
        throw const ApiException('Сервер вернул пустое фото.');
      }
      if (_disposed || _sessionCookie != session) {
        throw const ApiException(
          'Сессия истекла. Войдите снова.', statusCode: 401,
        );
      }
      final bytes = buffer.takeBytes();
      // Reject obvious content-type mismatches before the image decoder.
      final valid = switch (mime) {
        'image/jpeg' => bytes.length >= 3 && bytes[0] == 0xff &&
            bytes[1] == 0xd8 && bytes[2] == 0xff,
        'image/png' => bytes.length >= 8 && bytes[0] == 0x89 &&
            bytes[1] == 0x50 && bytes[2] == 0x4e && bytes[3] == 0x47 &&
            bytes[4] == 0x0d && bytes[5] == 0x0a && bytes[6] == 0x1a && bytes[7] == 0x0a,
        'image/webp' => bytes.length >= 12 && bytes[0] == 0x52 &&
            bytes[1] == 0x49 && bytes[2] == 0x46 && bytes[3] == 0x46 &&
            bytes[8] == 0x57 && bytes[9] == 0x45 && bytes[10] == 0x42 && bytes[11] == 0x50,
        _ => false,
      };
      if (!valid) {
        throw const ApiException('Сервер вернул неподдерживаемый формат фото.');
      }
      completed = true;
      return bytes;
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw const ApiException('Превышено время ожидания фото.');
    } on IOException {
      throw const ApiException('Проверьте подключение к серверу.');
    } catch (_) {
      throw const ApiException('Не удалось загрузить фото.');
    } finally {
      abandoned = true;
      if (!completed) request?.abort();
      await chunks?.cancel();
    }
  }

  Future<Map<String, dynamic>> order(int id) => _request('/api/orders/$id');

  Future<Map<String, dynamic>> action(
    int id,
    String action, {
    Map<String, dynamic> payload = const {},
  }) => _request(
    '/api/orders/$id/action',
    method: 'POST',
    body: {'action': action, ...payload},
  );

  Future<Map<String, dynamic>> uploadPhoto({
    required int orderId,
    required String fileName,
    required String mimeType,
    required List<int> bytes,
    String phase = 'after',
  }) {
    final encoded = base64Encode(bytes);
    return _request(
      '/api/orders/$orderId/photos',
      method: 'POST',
      body: {
        'phase': phase,
        'file_name': fileName,
        'data_url': 'data:$mimeType;base64,$encoded',
      },
    );
  }

  Future<Map<String, dynamic>> rateOrder(
    int id, {
    required int rating,
    required String reason,
  }) => _request(
    '/api/orders/$id/rating',
    method: 'POST',
    body: {'rating': rating, 'reason': reason},
  );

  Future<void> logout() async {
    if (_sessionCookie == null) return;
    try {
      await _request('/api/logout', method: 'POST', body: const {});
    } finally {
      _sessionCookie = null;
      _csrf = null;
    }
  }

  Future<Map<String, dynamic>> _request(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
    bool allowUnauthenticated = false,
  }) async {
    if (_disposed) throw const ApiException('Сетевой клиент закрыт.');
    final request = await _client
        .openUrl(method, baseUri.resolve(path))
        .timeout(const Duration(seconds: 15));
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.cacheControlHeader, 'no-store');
    if (body != null) {
      request.headers.contentType = ContentType.json;
    }
    if (_sessionCookie != null) {
      request.headers.set(HttpHeaders.cookieHeader, _sessionCookie!);
    }
    if (!allowUnauthenticated && method != 'GET' && _csrf != null) {
      request.headers.set('X-CSRF-Token', _csrf!);
    }
    if (body != null) {
      final encodedBody = utf8.encode(jsonEncode(body));
      // The backend reads Content-Length and does not decode chunked bodies.
      // Count UTF-8 bytes, not Dart string code units (e.g. Cyrillic text).
      request.contentLength = encodedBody.length;
      request.add(encodedBody);
    }

    final response = await request.close().timeout(const Duration(seconds: 20));
    for (final cookie in response.cookies) {
      if (cookie.name == 'naryadai_session') {
        _sessionCookie = '${cookie.name}=${cookie.value}';
      }
    }
    final raw = await response.transform(utf8.decoder).join();
    Map<String, dynamic> decoded = const {};
    if (raw.isNotEmpty) {
      try {
        decoded = _asMap(jsonDecode(raw));
      } on FormatException {
        throw ApiException(
          'Сервер вернул некорректный ответ (${response.statusCode}).',
          statusCode: response.statusCode,
        );
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final message =
          decoded['error']?.toString() ??
          'Ошибка сервера (${response.statusCode}).';
      if (response.statusCode == 401 && !allowUnauthenticated) {
        _sessionCookie = null;
        _csrf = null;
      }
      throw ApiException(message, statusCode: response.statusCode);
    }
    return decoded;
  }

  static Map<String, dynamic> _asMap(Object? value) {
    if (value is Map<String, dynamic>) return value;
    if (value is Map) return value.map((key, value) => MapEntry('$key', value));
    return <String, dynamic>{};
  }

  void close() {
    _disposed = true;
    _sessionCookie = null;
    _csrf = null;
    _client.close(force: true);
  }
}
