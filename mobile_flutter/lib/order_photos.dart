import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'api.dart';
import 'app_settings.dart';

/// Authenticated, in-memory photos. Server-supplied URLs are never requested.
class OrderPhotos extends StatefulWidget {
  const OrderPhotos({super.key, required this.api, required this.photos});

  final EnbekApi api;
  final List<Map<String, dynamic>> photos;

  @override
  State<OrderPhotos> createState() => _OrderPhotosState();
}

class _OrderPhotosState extends State<OrderPhotos> {
  final Map<int, _PhotoRequest> _requests = {};
  bool _viewerOpen = false;

  @override
  void initState() {
    super.initState();
    _syncRequests();
  }

  @override
  void didUpdateWidget(covariant OrderPhotos oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncRequests(reset: !identical(oldWidget.api, widget.api));
  }

  void _syncRequests({bool reset = false}) {
    final ids = widget.photos.map((photo) => _photoId(photo['id'])).whereType<int>().toSet();
    for (final id in _requests.keys.toList()) {
      if (reset || !ids.contains(id)) {
        _requests.remove(id)!.retire();
      }
    }
    for (final id in ids) {
      _requests.putIfAbsent(id, () => _PhotoRequest(widget.api, id));
    }
  }

  @override
  void dispose() {
    for (final request in _requests.values) {
      request.retire();
    }
    _requests.clear();
    super.dispose();
  }

  void _open(_PhotoRequest request, String name) {
    if (!request.active || _viewerOpen) return;
    _viewerOpen = true;
    final settings = context.settings;
    // Retain before navigation, including the gap before the route first builds.
    request.retain();
    try {
      Navigator.of(context).push<void>(MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => AppSettingsScope(
          settings: settings,
          child: _FullScreenPhoto(request: request, name: name),
        ),
      )).whenComplete(() {
        _viewerOpen = false;
        request.release();
      });
    } catch (_) {
      _viewerOpen = false;
      request.release();
      rethrow;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.photos.isEmpty) return Text(context.tr('Фото пока нет.'));
    return LayoutBuilder(builder: (context, constraints) {
      final width = constraints.hasBoundedWidth ? constraints.maxWidth : 320.0;
      final columns = width >= 760 ? 3 : width >= 480 ? 2 : 1;
      final tileWidth = ((width - 12 * (columns - 1)) / columns).clamp(0.0, double.infinity).toDouble();
      return Wrap(spacing: 12, runSpacing: 12, children: [
        for (var index = 0; index < widget.photos.length; index++)
          SizedBox(
            key: ValueKey('photo-${widget.photos[index]['id']}-$index'),
            width: tileWidth,
            child: _tile(context, widget.photos[index]),
          ),
      ]);
    });
  }

  Widget _tile(BuildContext context, Map<String, dynamic> photo) {
    final request = _requests[_photoId(photo['id'])];
    final rawName = photo['file_name']?.toString().trim() ?? '';
    final name = rawName.isEmpty ? context.tr('Фото') : rawName;
    final scheme = Theme.of(context).colorScheme;
    final phase = context.tr(photo['phase'] == 'after' ? 'После работ' : 'До работ');
    final date = _uploadDate(context, photo['uploaded_at']);
    final duplicate = photo['duplicate'] == true || photo['duplicate'] == 1;
    final openLabel = context.tr('Открыть фото: {name}', {'name': name});
    return Material(
      color: scheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: scheme.outlineVariant),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Semantics(
          button: request != null,
          label: openLabel,
          child: InkWell(
            onTap: request == null ? null : () => _open(request, name),
            child: AspectRatio(
              aspectRatio: 16 / 10,
              child: ColoredBox(
                color: scheme.surfaceContainerHighest,
                child: request == null
                    ? _PhotoStatus(message: context.tr('Фото недоступно.'))
                    : _PhotoFrame(request: request, fullscreen: false),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
          child: Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name, maxLines: 2, overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 3),
              Text(date.isEmpty ? phase : '$phase • $date',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
            ])),
            if (duplicate)
              Tooltip(message: context.tr('Дубликат фото'),
                  child: Icon(Icons.content_copy_outlined, size: 18, color: scheme.onSurfaceVariant)),
            IconButton(
              tooltip: openLabel,
              onPressed: request == null ? null : () => _open(request, name),
              icon: const Icon(Icons.open_in_full),
            ),
          ]),
        ),
      ]),
    );
  }
}

int? _photoId(Object? value) {
  final id = value is int ? value : value is String ? int.tryParse(value) : null;
  return id != null && id > 0 ? id : null;
}

String _uploadDate(BuildContext context, Object? value) {
  final parsed = DateTime.tryParse(value?.toString() ?? '');
  if (parsed == null) return '';
  final date = parsed.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  final day = context.settings.language == 'en'
      ? '${date.year}-${two(date.month)}-${two(date.day)}'
      : '${two(date.day)}.${two(date.month)}.${date.year}';
  return '$day ${two(date.hour)}:${two(date.minute)}';
}

/// One shared future per photo, used by both the thumbnail and its open viewer.
/// Retained by an open route so removal/logout during a load stays safe.
class _PhotoRequest extends ChangeNotifier {
  _PhotoRequest(this.api, this.id);
  final EnbekApi api;
  final int id;
  Future<Uint8List>? _future;
  final Set<ImageProvider> _providers = {};
  var _owners = 1;
  var _disposed = false;
  var _loading = false;
  bool active = true;

  Future<Uint8List> get future => _future ??= _load();

  Future<Uint8List> _load() async {
    _loading = true;
    try {
      return await api.photoBytes(id);
    } finally {
      _loading = false;
    }
  }

  ImageProvider provider(Uint8List bytes, {required bool fullscreen}) {
    final size = fullscreen ? 3072 : 640;
    final provider = ResizeImage(MemoryImage(bytes), width: size, height: size,
        policy: ResizeImagePolicy.fit);
    _providers.add(provider);
    return provider;
  }

  void retry() {
    if (!active || _loading) return;
    _evict();
    _future = _load();
    notifyListeners();
  }

  void retain() => _owners++;

  void release() {
    _owners--;
    if (_owners == 0) {
      _disposed = true;
      _future = null;
      _evict();
      super.dispose();
    }
  }

  void retire() {
    active = false;
    _future = null;
    _evict();
    // The owning list can change during build; update another Navigator route
    // after that build rather than calling setState on it during this frame.
    scheduleMicrotask(() {
      if (!_disposed) notifyListeners();
    });
    release();
  }

  void _evict() {
    for (final provider in _providers) {
      unawaited(provider.evict());
    }
    _providers.clear();
  }
}

class _PhotoFrame extends StatelessWidget {
  const _PhotoFrame({required this.request, required this.fullscreen});
  final _PhotoRequest request;
  final bool fullscreen;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: request,
    builder: (context, _) {
      if (!request.active) {
        return _PhotoStatus(message: context.tr('Фото недоступно.'));
      }
      return FutureBuilder<Uint8List>(
        future: request.future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return _PhotoStatus(message: context.tr('Загрузка фото…'), loading: true);
          }
          if (snapshot.hasError || snapshot.data == null) {
            return _PhotoStatus(message: _photoError(context, snapshot.error), onRetry: request.retry);
          }
          final picture = Image(
            image: request.provider(snapshot.data!, fullscreen: fullscreen),
            fit: fullscreen ? BoxFit.contain : BoxFit.cover,
            width: double.infinity,
            height: double.infinity,
            excludeFromSemantics: true,
            gaplessPlayback: false,
            errorBuilder: (context, error, stackTrace) => _PhotoStatus(
              message: context.tr('Не удалось открыть изображение.'), onRetry: request.retry,
            ),
          );
          if (!fullscreen) return picture;
          return InteractiveViewer(
            // A new request also resets the previous zoom after an explicit retry.
            key: ObjectKey(request.future),
            minScale: 1,
            maxScale: 5,
            child: SizedBox.expand(child: picture),
          );
        },
      );
    },
  );
}

String _photoError(BuildContext context, Object? error) {
  if (error is ApiException) {
    if (error.statusCode == 401) return context.tr('Сессия истекла. Войдите снова.');
    if (error.statusCode == 403) return context.tr('Нет доступа к фото.');
    if (error.statusCode == 404) return context.tr('Фото не найдено.');
    const visible = {
      'Превышено время ожидания фото.',
      'Проверьте подключение к серверу.',
      'Сервер вернул неподдерживаемый формат фото.',
      'Фото превышает допустимый размер.',
      'Сервер вернул пустое фото.',
      'Сервер перенаправил запрос фото. Проверьте адрес сервера.',
    };
    if (visible.contains(error.message)) return context.tr(error.message);
  }
  return context.tr('Не удалось загрузить фото.');
}

class _PhotoStatus extends StatelessWidget {
  const _PhotoStatus({required this.message, this.loading = false, this.onRetry});
  final String message;
  final bool loading;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Center(child: SingleChildScrollView(
    padding: const EdgeInsets.all(12),
    child: Column(mainAxisSize: MainAxisSize.min, children: [
      if (loading)
        SizedBox(width: 28, height: 28, child: CircularProgressIndicator(
          strokeWidth: 2.5, semanticsLabel: message,
        ))
      else
        Icon(Icons.image_not_supported_outlined, color: Theme.of(context).colorScheme.onSurfaceVariant),
      const SizedBox(height: 8),
      Text(message, textAlign: TextAlign.center,
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      if (onRetry != null)
        TextButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh),
            label: Text(context.tr('Повторить'))),
    ]),
  ));
}

class _FullScreenPhoto extends StatefulWidget {
  const _FullScreenPhoto({required this.request, required this.name});
  final _PhotoRequest request;
  final String name;
  @override
  State<_FullScreenPhoto> createState() => _FullScreenPhotoState();
}

class _FullScreenPhotoState extends State<_FullScreenPhoto> {
  @override
  void initState() {
    super.initState();
    widget.request.retain();
  }

  @override
  void dispose() {
    widget.request.release();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      leading: IconButton(
        tooltip: context.tr('Закрыть'),
        onPressed: () => Navigator.of(context).pop(),
        icon: const Icon(Icons.close),
      ),
      title: Text(widget.name, maxLines: 1, overflow: TextOverflow.ellipsis),
    ),
    body: SafeArea(child: Column(children: [
      Expanded(child: _PhotoFrame(request: widget.request, fullscreen: true)),
      Padding(padding: const EdgeInsets.all(16),
          child: Text(context.tr('Увеличивайте фото двумя пальцами'), textAlign: TextAlign.center)),
    ])),
  );
}
