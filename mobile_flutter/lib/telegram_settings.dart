import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'app_settings.dart';

/// Existing authenticated notification binding, not a Telegram login flow.
///
/// The API owns session/CSRF handling and the server enforces role permissions.
/// Mount a fresh card (or change its key) when the authenticated user changes.
/// Pairing commands are held only in this State, never logged or persisted.
class TelegramSettingsCard extends StatefulWidget {
  const TelegramSettingsCard({super.key, required this.api});

  final EnbekApi api;

  @override
  State<TelegramSettingsCard> createState() => _TelegramSettingsCardState();
}

class _TelegramSettingsCardState extends State<TelegramSettingsCard>
    with WidgetsBindingObserver {
  _TelegramStatus? _status;
  String? _command;
  DateTime? _expiresAt;
  Timer? _expiryTimer;
  String? _errorKey;
  String? _noticeKey;
  bool _expired = false;
  bool _busy = false;
  bool _confirming = false;
  int _generation = 0;

  bool get _locked => _busy || _confirming;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadStatus();
  }

  @override
  void didUpdateWidget(covariant TelegramSettingsCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.api, widget.api)) {
      ++_generation;
      _clearCommand();
      _status = null;
      _errorKey = null;
      _noticeKey = null;
      _confirming = false;
      _busy = false;
      _loadStatus();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && mounted) {
      final deadline = _expiresAt;
      if (deadline != null && !deadline.isAfter(DateTime.now())) {
        setState(() {
          _clearCommand();
          _expired = true;
        });
      }
    }
  }

  @override
  void dispose() {
    ++_generation;
    WidgetsBinding.instance.removeObserver(this);
    _clearCommand();
    super.dispose();
  }

  bool _current(int generation, EnbekApi api) =>
      mounted && generation == _generation && identical(api, widget.api);

  void _clearCommand() {
    _expiryTimer?.cancel();
    _expiryTimer = null;
    _command = null;
    _expiresAt = null;
    _expired = false;
  }

  void _armExpiration(DateTime expiresAt) {
    _expiryTimer?.cancel();
    final remaining = expiresAt.difference(DateTime.now());
    if (remaining <= Duration.zero) {
      _clearCommand();
      _expired = true;
      return;
    }
    _expiryTimer = Timer(remaining, () {
      if (!mounted || _expiresAt != expiresAt) return;
      setState(() {
        _clearCommand();
        _expired = true;
      });
    });
  }

  String _errorFor(Object error, String fallback) {
    if (error is ApiException) {
      if (error.statusCode == 401) {
        return 'Сессия истекла. Войдите в приложение снова.';
      }
      if (error.statusCode == 409) {
        return 'Telegram выключен или его настройки не заданы.';
      }
      // A 403 can also be a CSRF failure. Only label a role denial when the
      // backend returned that exact documented message; never infer it.
      if (error.statusCode == 403 &&
          error.message == 'Для этой роли привязка недоступна') {
        return 'Для этой роли привязка недоступна.';
      }
    }
    if (error is FormatException) {
      return 'Сервер вернул некорректный ответ Telegram.';
    }
    // Do not render/log raw exception or response text containing secrets.
    return fallback;
  }

  Future<void> _loadStatus() async {
    if (_locked) return;
    final generation = ++_generation;
    final api = widget.api;
    setState(() {
      _busy = true;
      _errorKey = null;
      _noticeKey = null;
    });
    try {
      final status = _TelegramStatus.fromJson(await api.telegramStatus());
      if (!_current(generation, api)) return;
      setState(() {
        _status = status;
        if (!status.enabled || status.paired) _clearCommand();
      });
    } catch (error) {
      if (!_current(generation, api)) return;
      setState(() {
        _status = null;
        _clearCommand();
        _errorKey = _errorFor(
          error,
          'Не удалось загрузить статус. Проверьте соединение и повторите попытку.',
        );
      });
    } finally {
      if (_current(generation, api)) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm({
    required String title,
    required String message,
    required String action,
  }) async {
    if (_locked) return false;
    final generation = _generation;
    final api = widget.api;
    setState(() => _confirming = true);
    try {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(dialogContext.tr(title)),
          content: Text(dialogContext.tr(message)),
          scrollable: true,
          actions: [
            TextButton(
              style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(dialogContext.tr('Отмена')),
            ),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: Text(dialogContext.tr(action)),
            ),
          ],
        ),
      );
      return _current(generation, api) && confirmed == true;
    } finally {
      if (_current(generation, api)) setState(() => _confirming = false);
    }
  }

  Future<void> _pair() async {
    if (_locked || _status?.enabled != true || _status?.paired == true) return;
    final beforeConfirmation = _generation;
    final confirmedApi = widget.api;
    final confirmed = await _confirm(
      title: 'Создать код привязки?',
      message:
          'После отправки команды вашему боту этот Telegram-чат будет получать уведомления и сможет просматривать наряды в пределах вашей роли. Код одноразовый; новый код заменит предыдущий. Продолжить?',
      action: 'Создать код',
    );
    if (!confirmed || !_current(beforeConfirmation, confirmedApi)) return;
    final generation = ++_generation;
    final api = widget.api;
    setState(() {
      _busy = true;
      _errorKey = null;
      _noticeKey = null;
      // Requesting a replacement invalidates the old server-side code.
      // Clear it even if the subsequent response is lost.
      _clearCommand();
    });
    try {
      final result = await api.telegramPair();
      if (!_current(generation, api)) return;
      final command = result['command'];
      final expires = result['expires_at'];
      final expiresAt = expires is String ? DateTime.tryParse(expires) : null;
      if (command is! String ||
          !RegExp(r'^/start [A-F0-9]{12}$').hasMatch(command) ||
          expiresAt == null ||
          !expiresAt.isUtc ||
          result['single_use'] != true) {
        throw const FormatException('Invalid Telegram pairing response');
      }
      setState(() {
        _command = command;
        _expiresAt = expiresAt;
        _armExpiration(expiresAt);
      });
    } catch (error) {
      if (!_current(generation, api)) return;
      setState(() {
        _clearCommand();
        if (error is ApiException && error.statusCode == 401) _status = null;
        _errorKey = _errorFor(
          error,
          'Не удалось получить код. Проверьте соединение и повторите попытку.',
        );
      });
    } finally {
      if (_current(generation, api)) setState(() => _busy = false);
    }
  }

  Future<void> _unpair() async {
    if (_locked || _status?.paired != true) return;
    final beforeConfirmation = _generation;
    final confirmedApi = widget.api;
    final confirmed = await _confirm(
      title: 'Отвязать Telegram?',
      message:
          'Этот чат перестанет получать уведомления и просматривать наряды через бота. Все действующие коды привязки будут отменены.',
      action: 'Отвязать',
    );
    if (!confirmed || !_current(beforeConfirmation, confirmedApi)) return;
    final generation = ++_generation;
    final api = widget.api;
    setState(() {
      _busy = true;
      _errorKey = null;
      _noticeKey = null;
      _clearCommand();
    });
    try {
      final result = await api.telegramUnpair();
      if (!_current(generation, api)) return;
      if (result['ok'] != true) {
        throw const FormatException('Invalid Telegram unpair response');
      }
      setState(() {
        _status = _TelegramStatus(
          enabled: _status!.enabled,
          paired: false,
          deliveryCounts: const {},
        );
        _noticeKey = 'Чат отвязан.';
      });
    } catch (error) {
      if (!_current(generation, api)) return;
      setState(() {
        // The request may have reached the server; force a status read before
        // offering another mutation rather than claiming success or retrying.
        _status = null;
        _errorKey = _errorFor(
          error,
          'Не удалось отвязать чат. Обновите статус перед повторной попыткой.',
        );
      });
    } finally {
      if (_current(generation, api)) setState(() => _busy = false);
    }
  }

  String _deadlineText(DateTime deadline) {
    final local = deadline.toLocal();
    final labels = MaterialLocalizations.of(context);
    final date = labels.formatFullDate(local);
    final time = labels.formatTimeOfDay(
      TimeOfDay.fromDateTime(local),
      alwaysUse24HourFormat: MediaQuery.alwaysUse24HourFormatOf(context),
    );
    return '$date, $time';
  }

  Widget _message(String key, {bool error = false}) {
    final colors = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: error ? colors.errorContainer : colors.secondaryContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          context.tr(key),
          style: TextStyle(
            color: error ? colors.onErrorContainer : colors.onSecondaryContainer,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final status = _status;
    // Guard rendering as well as the timer, including after lifecycle pauses.
    final hasCommand = _command != null &&
        _expiresAt != null &&
        _expiresAt!.isAfter(DateTime.now());
    return Card(
      margin: EdgeInsets.zero,
      color: colors.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: BorderSide(color: colors.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.send_rounded, color: colors.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    context.tr('Уведомления в Telegram'),
                    style: theme.textTheme.titleMedium?.copyWith(
                      color: colors.onSurface,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (_busy) ...[
              const SizedBox(height: 14),
              LinearProgressIndicator(
                semanticsLabel: context.tr('Загрузка статуса…'),
              ),
            ],
            if (status != null) ...[
              const SizedBox(height: 14),
              Text(
                context.tr(!status.enabled
                    ? 'Telegram отключён'
                    : status.paired
                        ? 'Личный чат связан'
                        : 'Личный чат не связан'),
                style: theme.textTheme.titleSmall?.copyWith(color: colors.onSurface),
              ),
              const SizedBox(height: 8),
              if (!status.enabled)
                Text(context.tr(
                  'Доставка отключена. Обратитесь к администратору: токен бота и webhook настраиваются на сервере.',
                ))
              else if (!status.paired && !hasCommand)
                Text(context.tr(
                  'Получите одноразовый код и отправьте команду своему настроенному боту в личном чате.',
                )),
              if (status.enabled && status.paired) ...[
                Text(context.tr('Сводка доставки'), style: theme.textTheme.labelLarge),
                const SizedBox(height: 6),
                if (status.deliveryCounts.isEmpty)
                  Text(context.tr('Очередь пуста'))
                else
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: status.deliveryCounts.entries.map((entry) {
                      return Text(context.tr('{status}: {count}', {
                        'status': context.tr(_deliveryLabel(entry.key)),
                        'count': entry.value.toString(),
                      }));
                    }).toList(),
                  ),
              ],
            ],
            if (hasCommand) ...[
              const SizedBox(height: 16),
              Text(context.tr('Одноразовая команда'), style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              Text(context.tr('Отправьте эту команду своему настроенному боту в личном чате:')),
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: colors.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: colors.outlineVariant),
                ),
                // Plain text deliberately avoids persisting the secret to a
                // system clipboard or creating a bot/deep link not in the API.
                child: Text(
                  _command!,
                  textDirection: TextDirection.ltr,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontFamily: 'monospace',
                    color: colors.onSurface,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Text(context.tr('Действует до {time}', {'time': _deadlineText(_expiresAt!)})),
              const SizedBox(height: 6),
              Text(context.tr('Не пересылайте команду другим. После отправки обновите статус.')),
            ],
            if (_expired) _message('Срок действия кода истёк. Получите новый код.'),
            if (_noticeKey != null) _message(_noticeKey!),
            if (_errorKey != null) _message(_errorKey!, error: true),
            const SizedBox(height: 16),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                if (status != null && !status.enabled)
                  FilledButton(
                    style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
                    onPressed: null,
                    child: Text(context.tr('Подключение недоступно')),
                  )
                else if (status != null && !status.paired)
                  FilledButton.icon(
                    style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
                    onPressed: _locked ? null : _pair,
                    icon: const Icon(Icons.link),
                    label: Text(context.tr(
                      hasCommand || _expired ? 'Получить новый код' : 'Получить код',
                    )),
                  ),
                // Revocation remains available if delivery is disabled after
                // an existing binding; the verified backend permits it.
                if (status?.paired == true)
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
                    onPressed: _locked ? null : _unpair,
                    icon: const Icon(Icons.link_off),
                    label: Text(context.tr('Отвязать чат')),
                  ),
                TextButton.icon(
                  style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                  onPressed: _locked ? null : _loadStatus,
                  icon: const Icon(Icons.refresh),
                  label: Text(context.tr('Обновить статус')),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _TelegramStatus {
  const _TelegramStatus({
    required this.enabled,
    required this.paired,
    required this.deliveryCounts,
  });

  final bool enabled;
  final bool paired;
  final Map<String, int> deliveryCounts;

  factory _TelegramStatus.fromJson(Map<String, dynamic> json) {
    if (json['enabled'] is! bool || json['paired'] is! bool) {
      throw const FormatException('Invalid Telegram status response');
    }
    final counts = <String, int>{};
    final raw = json['delivery_counts'];
    if (raw is Map) {
      for (final entry in raw.entries) {
        if (entry.key is String && entry.value is int && (entry.value as int) >= 0) {
          counts[entry.key as String] = entry.value as int;
        }
      }
    }
    return _TelegramStatus(
      enabled: json['enabled'] as bool,
      paired: json['paired'] as bool,
      deliveryCounts: counts,
    );
  }
}

String _deliveryLabel(String status) => switch (status) {
  'queued_local' => 'В очереди',
  'retrying' => 'Повторная отправка',
  'sending' => 'Отправляется',
  'delivered' => 'Доставлено',
  'failed' => 'Ошибка доставки',
  'uncertain' => 'Доставка не подтверждена',
  'cancelled' => 'Отменено',
  'expired' => 'Срок истёк',
  _ => 'Другой статус',
};
