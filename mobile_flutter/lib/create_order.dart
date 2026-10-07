import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'app_settings.dart';

/// Native issue form. Creating an order and uploading its photos are separate
/// server transactions. A successful create is never repeated by this screen.
class CreateOrderScreen extends StatefulWidget {
  const CreateOrderScreen({
    super.key,
    required this.api,
    required this.user,
    required this.bootstrap,
    this.picker,
  });

  final EnbekApi api;
  final Map<String, dynamic> user;
  final Map<String, dynamic> bootstrap;
  final ImagePicker? picker;

  @override
  State<CreateOrderScreen> createState() => _CreateOrderScreenState();
}

enum _PhotoState { pending, uploading, uploaded, failed, uncertain }

class _PendingPhoto {
  _PendingPhoto({required this.name, required this.uploadName,
    required this.mime, required this.bytes});
  final String name;
  final String uploadName;
  final String mime;
  final Uint8List bytes;
  _PhotoState state = _PhotoState.pending;
  String? error;
}

class _CreateOrderScreenState extends State<CreateOrderScreen> {
  final _formKey = GlobalKey<FormState>();
  final _scroll = ScrollController();
  final _title = TextEditingController();
  final _description = TextEditingController();
  final _comment = TextEditingController();
  final _hours = TextEditingController(text: '8');
  final List<_PendingPhoto> _photos = [];
  late final ImagePicker _picker;
  late Map<String, dynamic> _user;
  List<Map<String, dynamic>> _areas = [];
  List<Map<String, dynamic>> _equipment = [];
  List<Map<String, dynamic>> _workers = [];
  int? _areaId, _equipmentId;
  String? _assignee;
  String _workType = 'unscheduled', _priority = 'normal';
  String _deadlineMode = 'hours';
  late DateTime _deadline;
  String? _error, _lastLanguage;
  bool _busy = false, _picking = false, _refreshing = false;
  bool _dirty = false, _validated = false, _closing = false;
  bool _allowPop = false, _uncertainCreate = false;
  Map<String, dynamic>? _createdOrder;
  int _photoSequence = 0;
  final String _photoBatch = DateTime.now().microsecondsSinceEpoch.toString();

  bool get _isMaster => _user['role'] == 'master';
  bool get _locked => _busy || _picking || _refreshing || _closing;
  bool get _editable => !_locked && _createdOrder == null && !_uncertainCreate;
  bool get _catalogReady => _areas.isNotEmpty && _equipment.isNotEmpty && _workers.isNotEmpty;
  bool get _hasUncertainPhoto => _photos.any((p) => p.state == _PhotoState.uncertain);
  int get _remaining => _photos.where((p) => p.state != _PhotoState.uploaded).length;
  List<Map<String, dynamic>> get _areaEquipment => _equipment
      .where((item) => _id(item['area_id']) == _areaId).toList();
  List<String> get _brigades => const ['A', 'B', 'C']
      .where((brigade) => _workers.any((worker) => worker['brigade'] == brigade)).toList();

  @override
  void initState() {
    super.initState();
    _picker = widget.picker ?? ImagePicker();
    _user = Map<String, dynamic>.from(widget.user);
    _deadline = DateTime.now().add(const Duration(hours: 8));
    _readCatalog(widget.bootstrap);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final language = context.settings.language;
    if (_lastLanguage != language && _validated) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _createdOrder == null && !_uncertainCreate) {
          _formKey.currentState?.validate();
        }
      });
    }
    _lastLanguage = language;
  }

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? value.map((key, value) => MapEntry('$key', value)) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(Object? value) => value is List
      ? value.whereType<Map>().map((item) => _map(item)).toList() : [];
  static int? _id(Object? value) {
    final parsed = int.tryParse('$value');
    return parsed != null && parsed > 0 ? parsed : null;
  }

  void _readCatalog(Map<String, dynamic> bootstrap) {
    final constants = _map(bootstrap['constants']);
    final areas = <int, Map<String, dynamic>>{};
    for (final item in _maps(constants['areas'])) {
      final id = _id(item['id']);
      if (id != null) areas[id] = item;
    }
    _areas = areas.values.toList();
    final equipment = <int, Map<String, dynamic>>{};
    for (final item in _maps(constants['equipment'])) {
      final id = _id(item['id']);
      if (id != null && areas.containsKey(_id(item['area_id']))) equipment[id] = item;
    }
    _equipment = equipment.values.toList();
    final workers = <int, Map<String, dynamic>>{};
    for (final item in [..._maps(constants['users']), ..._maps(bootstrap['users'])]) {
      final id = _id(item['id']);
      if (id != null && item['role'] == 'worker' && item['is_active'] != 0 && item['is_active'] != false) {
        workers[id] = item;
      }
    }
    // free_workers is the backend's worker-only availability list; role can be absent.
    for (final item in _maps(bootstrap['free_workers'])) {
      final id = _id(item['id']);
      if (id != null && (item['role'] == null || item['role'] == 'worker') &&
          item['is_active'] != 0 && item['is_active'] != false) {
        workers[id] = {...?workers[id], ...item};
      }
    }
    _workers = workers.values.toList();
    if (!_areas.any((item) => _id(item['id']) == _areaId)) _areaId = null;
    if (!_areaEquipment.any((item) => _id(item['id']) == _equipmentId)) _equipmentId = null;
    if (!_assigneeValues.contains(_assignee)) _assignee = null;
  }

  Set<String> get _assigneeValues => {
    for (final worker in _workers) 'worker:${_id(worker['id'])}',
    for (final brigade in _brigades) 'brigade:$brigade',
  };

  Future<void> _refreshCatalog() async {
    if (_locked || _createdOrder != null || _uncertainCreate) return;
    setState(() { _refreshing = true; _error = null; });
    try {
      final result = await widget.api.bootstrap().timeout(const Duration(seconds: 45));
      if (!mounted) return;
      setState(() {
        final user = _map(result['user']);
        if (user.isNotEmpty) _user = user;
        _readCatalog(result);
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

  String? _lengthError(String? value, int min, int max, String key) {
    final count = (value ?? '').trim().runes.length;
    return count < min || count > max ? context.tr(key) : null;
  }

  Future<void> _pickPhoto(ImageSource source) async {
    if (!_editable || _photos.length >= 5) return;
    setState(() { _picking = true; _error = null; });
    try {
      final file = await _picker.pickImage(source: source, imageQuality: 80,
        maxWidth: 1800, maxHeight: 1800);
      if (!mounted || file == null) return;
      // Check before and after reading. A platform returning an oversized PNG
      // must not be silently accepted just because compression was requested.
      if (await file.length() > 4000000) {
        if (mounted) setState(() => _error = 'Фото больше 4 МБ. Выберите или снимите файл поменьше.');
        return;
      }
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      if (bytes.length > 4000000) {
        setState(() => _error = 'Фото больше 4 МБ. Выберите или снимите файл поменьше.');
        return;
      }
      final mime = _imageMime(bytes);
      // Platform MIME/extension can describe the source before image_picker
      // recompression. The actual byte signature determines the upload MIME.
      if (mime == null) {
        setState(() => _error = 'Выберите читаемое фото JPEG, PNG или WebP.');
        return;
      }
      final extension = switch (mime) { 'image/png' => 'png', 'image/webp' => 'webp', _ => 'jpg' };
      setState(() {
        _photos.add(_PendingPhoto(name: file.name, mime: mime, bytes: bytes,
          uploadName: 'before-$_photoBatch-${_photoSequence++}.$extension'));
        _dirty = true;
      });
    } catch (_) {
      if (mounted) setState(() => _error = 'Не удалось открыть фото. Проверьте доступ к камере или галерее и попробуйте снова.');
    } finally {
      if (mounted) {
        setState(() => _picking = false);
        if (_error != null) _revealMessage();
      }
    }
  }

  static String? _imageMime(Uint8List bytes) {
    if (bytes.length >= 3 && bytes[0] == 0xff && bytes[1] == 0xd8 && bytes[2] == 0xff) return 'image/jpeg';
    const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    if (bytes.length >= 8 && List.generate(8, (i) => bytes[i] == png[i]).every((value) => value)) return 'image/png';
    if (bytes.length >= 12 && bytes[0] == 0x52 && bytes[1] == 0x49 && bytes[2] == 0x46 && bytes[3] == 0x46 &&
        bytes[8] == 0x57 && bytes[9] == 0x45 && bytes[10] == 0x42 && bytes[11] == 0x50) return 'image/webp';
    return null;
  }

  Future<void> _pickDate() async {
    if (!_editable) return;
    final now = DateTime.now();
    final picked = await showDatePicker(context: context,
      locale: Locale(context.settings.language),
      initialDate: _deadline.isBefore(now) ? now : _deadline,
      firstDate: DateUtils.dateOnly(now), lastDate: DateTime(now.year + 10, 12, 31),
      helpText: context.tr('Дата дедлайна'), cancelText: context.tr('Отмена'),
      confirmText: context.tr('Выбрать'));
    if (!mounted || picked == null || !_editable) return;
    setState(() {
      _deadline = DateTime(picked.year, picked.month, picked.day, _deadline.hour, _deadline.minute);
      _dirty = true;
    });
  }

  Future<void> _pickTime() async {
    if (!_editable) return;
    final picked = await showTimePicker(context: context,
      initialTime: TimeOfDay.fromDateTime(_deadline),
      helpText: context.tr('Время дедлайна'), cancelText: context.tr('Отмена'),
      confirmText: context.tr('Выбрать'),
      builder: (context, child) => Localizations.override(context: context,
        locale: Locale(this.context.settings.language), child: child!));
    if (!mounted || picked == null || !_editable) return;
    setState(() {
      _deadline = DateTime(_deadline.year, _deadline.month, _deadline.day, picked.hour, picked.minute);
      _dirty = true;
    });
  }

  // A validation/auth rejection is definitive. Timeouts, network failures,
  // server errors, redirects and malformed successes may follow a DB commit.
  static bool _definitelyRejected(Object error) => error is ApiException &&
      error.statusCode != null && error.statusCode! >= 400 &&
      error.statusCode! < 500 && error.statusCode != 408;

  Future<void> _submit() async {
    if (!_editable || !_isMaster || !_catalogReady) return;
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() { _validated = true; _error = null; });
    if (!(_formKey.currentState?.validate() ?? false)) {
      setState(() => _error = 'Проверьте обязательные поля и срок.');
      _revealMessage();
      return;
    }
    if (!_assigneeValues.contains(_assignee) ||
        !_areaEquipment.any((item) => _id(item['id']) == _equipmentId)) {
      setState(() => _error = 'Обновите справочники и выберите участок, оборудование и исполнителя.');
      return;
    }
    if (_deadlineMode == 'date' && !_deadline.isAfter(DateTime.now())) {
      setState(() => _error = 'Срок должен быть в будущем');
      return;
    }
    final assignee = _assignee!.split(':');
    final payload = <String, dynamic>{
      'title': _title.text.trim(), 'description': _description.text.trim(),
      'issuance_comment': _comment.text.trim(), 'work_type': _workType,
      'priority': _priority, 'area_id': _areaId, 'equipment_id': _equipmentId,
      if (assignee.first == 'worker') 'worker_id': int.parse(assignee.last)
      else 'brigade': assignee.last,
      if (_deadlineMode == 'hours') 'norm_hours': double.parse(_hours.text.trim().replaceAll(',', '.'))
      else 'due_at': _deadline.toUtc().toIso8601String(),
    };
    // Intentionally omit BOTH before_photo and before_photos. Older servers
    // ignore before_photos, silently losing attachments embedded in create.
    setState(() => _busy = true);
    try {
      final result = await widget.api.createOrder(payload).timeout(const Duration(seconds: 45));
      if (!mounted) return;
      final order = _map(result['order']);
      if (_id(order['id']) == null) {
        setState(() { _uncertainCreate = true; _busy = false; });
        return;
      }
      setState(() => _createdOrder = order);
      await _uploadRemaining();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        if (_createdOrder == null) {
          if (_definitelyRejected(error)) { _error = error.toString(); }
          else { _uncertainCreate = true; }
        } else {
          _error = error.toString();
        }
      });
    } finally {
      if (mounted && !_allowPop) {
        setState(() => _busy = false);
        _revealMessage();
      }
    }
  }

  Future<void> _uploadRemaining() async {
    final orderId = _id(_createdOrder?['id']);
    if (orderId == null || _hasUncertainPhoto) return;
    for (final photo in _photos) {
      if (!mounted) return;
      if (photo.state == _PhotoState.uploaded) continue;
      setState(() { photo.state = _PhotoState.uploading; photo.error = null; });
      try {
        final result = await widget.api.uploadPhoto(orderId: orderId,
          fileName: photo.uploadName, mimeType: photo.mime, bytes: photo.bytes,
          phase: 'before').timeout(const Duration(seconds: 45));
        if (!mounted) return;
        if (_id(_map(result['photo'])['id']) == null) {
          setState(() => photo.state = _PhotoState.uncertain);
          return;
        }
        setState(() => photo.state = _PhotoState.uploaded);
      } catch (error) {
        if (!mounted) return;
        setState(() {
          photo.state = _definitelyRejected(error) ? _PhotoState.failed : _PhotoState.uncertain;
          photo.error = error.toString();
        });
        return; // Preserve successes; never recreate or resend those photos.
      }
    }
    if (mounted) _finish(_createdOrder);
  }

  Future<void> _retryPhotos() async {
    if (_locked || _createdOrder == null || _hasUncertainPhoto) return;
    setState(() { _busy = true; _error = null; });
    try { await _uploadRemaining(); }
    finally { if (mounted && !_allowPop) setState(() => _busy = false); }
  }

  Future<void> _checkPhotos() async {
    if (_locked || _createdOrder == null) return;
    setState(() { _busy = true; _error = null; });
    try {
      final result = await widget.api.order(_id(_createdOrder!['id'])!)
          .timeout(const Duration(seconds: 45));
      if (!mounted) return;
      final order = _map(result['order']);
      if (_id(order['id']) != _id(_createdOrder!['id']) || order['photos'] is! List) {
        setState(() => _error = 'Не удалось подтвердить загрузку. Откройте наряд и проверьте фотографии.');
        return;
      }
      final remote = _maps(order['photos']);
      setState(() {
        _createdOrder = order;
        for (final photo in _photos.where((p) => p.state == _PhotoState.uncertain)) {
          if (remote.any((item) => item['phase'] == 'before' && item['file_name'] == photo.uploadName &&
              item['size_bytes'] == photo.bytes.length)) {
            photo.state = _PhotoState.uploaded;
            photo.error = null;
          }
        }
        if (_hasUncertainPhoto) {
          _error = 'Не удалось подтвердить загрузку. Откройте наряд и проверьте фотографии.';
        }
      });
      if (!_hasUncertainPhoto) await _uploadRemaining();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted && !_allowPop) setState(() => _busy = false);
    }
  }

  void _revealMessage() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !_allowPop && _scroll.hasClients) {
        _scroll.animateTo(0, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  void _finish(Map<String, dynamic>? result) {
    if (!mounted || _allowPop) return;
    setState(() { _busy = false; _allowPop = true; });
    // PopScope must rebuild before a programmatic pop can succeed.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.of(context).pop(result);
    });
  }

  Future<void> _requestClose() async {
    if (_locked || _allowPop) return;
    if (_createdOrder != null && _remaining == 0) { _finish(_createdOrder); return; }
    if (_uncertainCreate || (!_dirty && _createdOrder == null)) { _finish(null); return; }
    setState(() => _closing = true);
    final created = _createdOrder != null;
    final leave = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: Text(context.tr(created ? 'Завершить без оставшихся фото?' : 'Отменить создание наряда?')),
      content: Text(context.tr(created
          ? 'Наряд уже создан. Незагруженные фото будут потеряны при выходе; их можно добавить в карточке, пока это разрешено статусом.'
          : 'Введённые данные и выбранные фото не сохранятся.')),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text(context.tr('Остаться'))),
        TextButton(onPressed: () => Navigator.pop(context, true), child: Text(context.tr(created ? 'Открыть созданный наряд' : 'Выйти'))),
      ],
    ));
    if (!mounted) return;
    setState(() => _closing = false);
    if (leave == true) _finish(_createdOrder);
  }

  Future<void> _appearance() async {
    if (_locked) return;
    await showModalBottomSheet<void>(context: context, isScrollControlled: true,
      builder: (context) => SafeArea(child: SingleChildScrollView(
        padding: const EdgeInsets.all(20), child: Column(mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(context.tr('Язык и тема'), style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            const AppearanceSettings(compact: true),
            const SizedBox(height: 16),
            TextButton(onPressed: () => Navigator.pop(context), child: Text(context.tr('Готово'))),
          ]))));
  }

  @override
  void dispose() {
    _title.dispose(); _description.dispose(); _comment.dispose(); _hours.dispose();
    _scroll.dispose();
    _photos.clear();
    super.dispose();
  }

  Widget _notice(String text, {bool error = false, IconData icon = Icons.info_outline}) {
    final colors = Theme.of(context).colorScheme;
    return Container(width: double.infinity, padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: error ? colors.errorContainer : colors.secondaryContainer,
        borderRadius: BorderRadius.circular(14)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: error ? colors.onErrorContainer : colors.onSecondaryContainer),
        const SizedBox(width: 12), Expanded(child: Text(text,
          style: TextStyle(color: error ? colors.onErrorContainer : colors.onSecondaryContainer))),
      ]));
  }

  Widget _section(String title, List<Widget> children) => Card(
    margin: const EdgeInsets.only(bottom: 16), child: Padding(padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(context.tr(title), style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 16), ...children,
      ])));

  Widget _pair(Widget first, Widget second) => LayoutBuilder(builder: (context, box) => box.maxWidth >= 560
      ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: first), const SizedBox(width: 16), Expanded(child: second)])
      : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [first, const SizedBox(height: 16), second]));

  String _workerName(Map<String, dynamic> worker) =>
      '${worker['display_name'] ?? worker['username'] ?? worker['id']}';

  String _availability(Map<String, dynamic> worker) {
    final key = switch (worker['availability']) {
      'busy' => 'Выполняет наряд', 'queued' => 'Есть очередь',
      'offered' => 'Есть новый наряд', 'free' => 'Свободен',
      'off_shift' => 'Не на смене', _ => 'Загрузка неизвестна',
    };
    return context.tr(key);
  }

  String _workerDetails(Map<String, dynamic> worker) {
    final rating = _map(worker['rating_detail'])['score'];
    final active = worker['active_orders'];
    return '${_availability(worker)} · ${context.tr('Активных: {count}', {'count': active ?? '—'})} · '
        '${context.tr('Рейтинг: {score}', {'score': rating ?? '—'})}';
  }

  Widget _assignment() {
    final options = <(String, String, String)>[
      for (final worker in _workers) ('worker:${_id(worker['id'])}', _workerName(worker), _workerDetails(worker)),
      for (final brigade in _brigades) ('brigade:$brigade', context.tr('Бригада {name}', {'name': brigade}), context.tr('Сервер выберет наименее занятого исполнителя')),
    ];
    final selected = options.where((item) => item.$1 == _assignee).firstOrNull;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      DropdownButtonFormField<String>(key: ValueKey('create-assignee-${_assignee ?? ''}'),
        initialValue: _assignee, isExpanded: true, itemHeight: null,
        decoration: InputDecoration(labelText: context.tr('Исполнитель или бригада')),
        hint: Text(context.tr('Выберите исполнителя или бригаду.')),
        items: [for (final item in options) DropdownMenuItem(value: item.$1,
          child: Padding(padding: const EdgeInsets.symmetric(vertical: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(item.$2, maxLines: 2, overflow: TextOverflow.ellipsis),
              Text(item.$3, maxLines: 3, overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall),
            ])))],
        selectedItemBuilder: (_) => [for (final item in options) Align(alignment: AlignmentDirectional.centerStart,
          child: Text(item.$2, maxLines: 1, overflow: TextOverflow.ellipsis))],
        onChanged: _editable ? (value) => setState(() { _assignee = value; _dirty = true; }) : null,
        validator: (value) => _assigneeValues.contains(value) ? null : context.tr('Выберите исполнителя или бригаду.'),
      ),
      if (selected != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(selected.$3,
        style: Theme.of(context).textTheme.bodySmall)),
    ]);
  }

  Widget _deadlineFields() {
    final material = MaterialLocalizations.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      DropdownButtonFormField<String>(key: ValueKey('create-deadline-mode-$_deadlineMode'),
        initialValue: _deadlineMode, isExpanded: true,
        decoration: InputDecoration(labelText: context.tr('Как задать срок')),
        items: [
          DropdownMenuItem(value: 'hours', child: Text(context.tr('Через указанное число часов'))),
          DropdownMenuItem(value: 'date', child: Text(context.tr('Выбрать дату и время'))),
        ],
        onChanged: _editable ? (value) => setState(() { _deadlineMode = value!; _dirty = true; }) : null),
      const SizedBox(height: 16),
      if (_deadlineMode == 'hours') TextFormField(key: const Key('create-hours'),
        controller: _hours, enabled: _editable,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: context.tr('Срок до дедлайна, часы'),
          helperText: context.tr('Больше 0 и не больше 720 часов'), helperMaxLines: 2),
        validator: (value) {
          final hours = double.tryParse((value ?? '').trim().replaceAll(',', '.'));
          return hours == null || !hours.isFinite || hours <= 0 || hours > 720
              ? context.tr('Укажите число часов больше 0 и не больше 720.') : null;
        })
      else ...[
        _pair(
          OutlinedButton.icon(key: const Key('create-date'), onPressed: _editable ? _pickDate : null,
            icon: const Icon(Icons.calendar_today_outlined),
            label: Text(context.tr('Дата: {date}', {'date': material.formatMediumDate(_deadline)}))),
          OutlinedButton.icon(key: const Key('create-time'), onPressed: _editable ? _pickTime : null,
            icon: const Icon(Icons.schedule),
            label: Text(context.tr('Время: {time}', {'time': material.formatTimeOfDay(TimeOfDay.fromDateTime(_deadline), alwaysUse24HourFormat: true)}))),
        ),
        const SizedBox(height: 10),
        Text(context.tr('Время на этом устройстве ({zone}). На сервер будет отправлено UTC.', {'zone': _deadline.timeZoneName}),
          style: Theme.of(context).textTheme.bodySmall),
      ],
      const SizedBox(height: 12),
      Text(context.tr('Дедлайн — срок заявки, не норма труда; фактические часы фиксируются отдельно.'),
        style: Theme.of(context).textTheme.bodySmall),
    ]);
  }

  Widget _photoList() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    for (var index = 0; index < _photos.length; index++) _photoTile(_photos[index], index),
  ]);

  Widget _photoTile(_PendingPhoto photo, int index) {
    final status = switch (photo.state) {
      _PhotoState.pending => 'Ожидает загрузки', _PhotoState.uploading => 'Загружается…',
      _PhotoState.uploaded => 'Загружено', _PhotoState.failed => 'Не загружено',
      _PhotoState.uncertain => 'Загрузка не подтверждена',
    };
    return Padding(padding: const EdgeInsets.only(bottom: 12), child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.memory(photo.bytes,
            width: 56, height: 56, fit: BoxFit.cover, cacheWidth: 160,
            semanticLabel: context.tr('Фото {number}', {'number': index + 1}),
            errorBuilder: (_, _, _) => const SizedBox(width: 56, height: 56, child: Icon(Icons.image_not_supported_outlined)))),
          const SizedBox(width: 12),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(photo.name, maxLines: 2, overflow: TextOverflow.ellipsis),
            Text(context.tr(status), style: Theme.of(context).textTheme.bodySmall),
          ])),
          if (_createdOrder == null) IconButton(key: ValueKey('create-remove-photo-$index'),
            constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            tooltip: context.tr('Удалить фото {number}', {'number': index + 1}),
            onPressed: _editable ? () => setState(() { _photos.removeAt(index); _dirty = true; }) : null,
            icon: const Icon(Icons.close)),
          if (photo.state == _PhotoState.uploaded) const Padding(padding: EdgeInsets.all(12), child: Icon(Icons.check_circle_outline)),
        ]),
        if (photo.error != null) Padding(padding: const EdgeInsets.only(top: 6),
          child: Text(context.trError(photo.error!), style: TextStyle(color: Theme.of(context).colorScheme.error))),
      ]));
  }

  Widget _form() => Form(key: _formKey,
    autovalidateMode: _validated ? AutovalidateMode.onUserInteraction : AutovalidateMode.disabled,
    onChanged: () { _dirty = true; },
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _section('Работа', [
        TextFormField(key: const Key('create-title'), controller: _title, enabled: _editable,
          textCapitalization: TextCapitalization.sentences, maxLength: 160,
          maxLengthEnforcement: MaxLengthEnforcement.none,
          decoration: InputDecoration(labelText: context.tr('Название наряда'),
            hintText: context.tr('Кратко: что произошло')),
          validator: (value) => _lengthError(value, 4, 160, 'Название: от 4 до 160 символов.')),
        const SizedBox(height: 12),
        TextFormField(key: const Key('create-description'), controller: _description, enabled: _editable,
          minLines: 3, maxLines: 7, maxLength: 3000, maxLengthEnforcement: MaxLengthEnforcement.none,
          textCapitalization: TextCapitalization.sentences,
          decoration: InputDecoration(labelText: context.tr('Описание проблемы'),
            hintText: context.tr('Опишите наблюдение и требуемую работу')),
          validator: (value) => _lengthError(value, 10, 3000, 'Описание: от 10 до 3000 символов.')),
        const SizedBox(height: 12),
        _pair(
          DropdownButtonFormField<String>(key: const Key('create-work-type'), initialValue: _workType, isExpanded: true,
            decoration: InputDecoration(labelText: context.tr('Тип работы')),
            items: [
              DropdownMenuItem(value: 'unscheduled', child: Text(context.tr('Внеплановый'))),
              DropdownMenuItem(value: 'planned', child: Text(context.tr('Плановый'))),
            ], onChanged: _editable ? (value) => setState(() { _workType = value!; _dirty = true; }) : null),
          DropdownButtonFormField<String>(key: const Key('create-priority'), initialValue: _priority, isExpanded: true,
            decoration: InputDecoration(labelText: context.tr('Приоритет')),
            items: [
              DropdownMenuItem(value: 'planned', child: Text(context.tr('Плановый'))),
              DropdownMenuItem(value: 'normal', child: Text(context.tr('Обычный'))),
              DropdownMenuItem(value: 'high', child: Text(context.tr('Высокий'))),
              DropdownMenuItem(value: 'emergency', child: Text(context.tr('Аварийный'))),
            ], onChanged: _editable ? (value) => setState(() { _priority = value!; _dirty = true; }) : null),
        ),
      ]),
      _section('Место и исполнитель', [
        DropdownButtonFormField<int>(key: ValueKey('create-area-${_areaId ?? ''}'),
          initialValue: _areaId, isExpanded: true,
          decoration: InputDecoration(labelText: context.tr('Участок')),
          hint: Text(context.tr('Выберите участок')),
          items: [for (final area in _areas) DropdownMenuItem(value: _id(area['id']),
            child: Text('${area['name'] ?? area['id']}', maxLines: 1, overflow: TextOverflow.ellipsis))],
          onChanged: _editable ? (value) => setState(() { _areaId = value; _equipmentId = null; _dirty = true; }) : null,
          validator: (value) => value == null ? context.tr('Выберите участок') : null),
        const SizedBox(height: 16),
        DropdownButtonFormField<int>(key: ValueKey('create-equipment-${_areaId ?? ''}-${_equipmentId ?? ''}'),
          initialValue: _equipmentId, isExpanded: true,
          decoration: InputDecoration(labelText: context.tr('Оборудование')),
          hint: Text(context.tr(_areaId == null ? 'Сначала выберите участок' : 'Выберите оборудование')),
          items: [for (final item in _areaEquipment) DropdownMenuItem(value: _id(item['id']),
            child: Text([item['code'], item['name']].where((value) => value != null && '$value'.isNotEmpty).join(' · '),
              maxLines: 1, overflow: TextOverflow.ellipsis))],
          onChanged: _editable && _areaId != null ? (value) => setState(() { _equipmentId = value; _dirty = true; }) : null,
          validator: (value) => value == null ? context.tr('Выберите оборудование') : null),
        if (_areaId != null && _areaEquipment.isEmpty) Padding(padding: const EdgeInsets.only(top: 10),
          child: Text(context.tr('На этом участке нет оборудования. Выберите другой участок или обновите справочники.'))),
        const SizedBox(height: 16), _assignment(),
      ]),
      _section('Срок', [_deadlineFields()]),
      _section('Комментарий и фото', [
        TextFormField(key: const Key('create-comment'), controller: _comment, enabled: _editable,
          minLines: 2, maxLines: 5, maxLength: 1000, maxLengthEnforcement: MaxLengthEnforcement.none,
          decoration: InputDecoration(labelText: context.tr('Комментарий мастера'),
            helperText: context.tr('Необязательно, до 1000 символов')),
          validator: (value) => (value ?? '').runes.length > 1000 ? context.tr('Комментарий: не больше 1000 символов.') : null),
        const SizedBox(height: 16),
        Text(context.tr('Фото «до»: {count} из 5', {'count': _photos.length}), style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Text(context.tr('Необязательно. JPEG, PNG или WebP, до 4 МБ после сжатия.')),
        const SizedBox(height: 12), _photoList(),
        Wrap(spacing: 12, runSpacing: 12, children: [
          OutlinedButton.icon(key: const Key('create-camera'),
            onPressed: _editable && _photos.length < 5 ? () => _pickPhoto(ImageSource.camera) : null,
            icon: const Icon(Icons.photo_camera_outlined), label: Text(context.tr('Снять фото'))),
          OutlinedButton.icon(key: const Key('create-gallery'),
            onPressed: _editable && _photos.length < 5 ? () => _pickPhoto(ImageSource.gallery) : null,
            icon: const Icon(Icons.photo_library_outlined), label: Text(context.tr('Из галереи'))),
        ]),
        if (_picking) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
      ]),
      _notice(context.tr('Сначала создаётся наряд, затем отдельно загружаются фото. Если загрузка прервётся, наряд останется созданным; можно повторить только незагруженные фото.')),
      const SizedBox(height: 16),
      FilledButton.icon(key: const Key('create-submit'),
        onPressed: _editable && _catalogReady ? _submit : null,
        icon: _busy ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.add_task),
        label: Text(context.tr(_busy ? 'Создаём наряд…' : 'Выдать наряд'))),
      if (_busy) Padding(padding: const EdgeInsets.only(top: 12),
        child: Text(context.tr('Дождитесь ответа сервера. Повторная отправка заблокирована.'))),
    ]));

  Widget _createdView() {
    final label = '${_createdOrder!['code'] ?? _createdOrder!['id']}';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _notice(context.tr('Наряд {code} уже создан.', {'code': label}), icon: Icons.check_circle_outline),
      const SizedBox(height: 16),
      Text(context.tr('Фото загружено: {done} из {total}', {'done': _photos.length - _remaining, 'total': _photos.length}),
        style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 16), _photoList(),
      if (_busy) ...[
        const LinearProgressIndicator(), const SizedBox(height: 12),
        Text(context.tr('Дождитесь окончания загрузки. Наряд повторно не создаётся.')),
      ] else ...[
        if (_hasUncertainPhoto) ...[
          _notice(context.tr('Ответ о загрузке фото не получен. Оно могло сохраниться. Сначала проверьте сервер; повторная отправка этого фото заблокирована.'), error: true),
          const SizedBox(height: 16),
          FilledButton.icon(key: const Key('create-check-photos'), onPressed: _checkPhotos,
            icon: const Icon(Icons.refresh), label: Text(context.tr('Проверить загрузку фото'))),
        ] else if (_remaining > 0)
          FilledButton.icon(key: const Key('create-retry-photos'), onPressed: _retryPhotos,
            icon: const Icon(Icons.cloud_upload_outlined), label: Text(context.tr('Повторить загрузку оставшихся фото'))),
        const SizedBox(height: 12),
        OutlinedButton(key: const Key('create-finish-without-photos'), onPressed: _requestClose,
          child: Text(context.tr(_remaining > 0 ? 'Завершить без оставшихся фото' : 'Открыть созданный наряд'))),
      ],
    ]);
  }

  @override
  Widget build(BuildContext context) => PopScope<Map<String, dynamic>>(
    canPop: _allowPop,
    onPopInvokedWithResult: (didPop, result) { if (!didPop) _requestClose(); },
    child: Scaffold(
      appBar: AppBar(title: Text(context.tr('Новый наряд')), automaticallyImplyLeading: false,
        leading: IconButton(tooltip: context.tr('Назад'), onPressed: _locked ? null : _requestClose,
          icon: const Icon(Icons.arrow_back)),
        actions: [IconButton(tooltip: context.tr('Язык и тема'), onPressed: _locked ? null : _appearance,
          icon: const Icon(Icons.tune))]),
      body: SafeArea(child: SingleChildScrollView(controller: _scroll, padding: const EdgeInsets.all(16),
        child: Align(alignment: Alignment.topCenter, child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (!_isMaster) _notice(context.tr('Создавать наряды может только мастер.'), error: true, icon: Icons.lock_outline)
            else if (_uncertainCreate) ...[
              _notice(context.tr('Ответ сервера не получен или не распознан. Наряд мог быть создан. Повторная отправка заблокирована: вернитесь к списку и проверьте последние наряды, прежде чем создавать новый.'), error: true),
              const SizedBox(height: 16),
              FilledButton(key: const Key('create-check-list'), onPressed: () => _finish(null), child: Text(context.tr('Вернуться к списку и проверить'))),
            ] else ...[
              if (_error != null) ...[_notice(context.trError(_error!), error: true), const SizedBox(height: 16)],
              if (_createdOrder != null) _createdView()
              else ...[
                if (!_catalogReady) ...[
                  _notice(context.tr('Не удалось получить участки, оборудование или исполнителей. Обновите справочники. Если список остаётся пустым, обратитесь к администратору.'), error: true),
                  const SizedBox(height: 12),
                ],
                Align(alignment: AlignmentDirectional.centerEnd, child: TextButton.icon(
                  key: const Key('create-refresh-catalog'), onPressed: _editable ? _refreshCatalog : null,
                  icon: _refreshing ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.refresh),
                  label: Text(context.tr('Обновить справочники')))),
                const SizedBox(height: 8), _form(),
              ],
            ],
          ]))))),
    ),
  );
}
