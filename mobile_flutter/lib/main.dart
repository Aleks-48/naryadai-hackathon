import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api.dart';
import 'app_settings.dart';
import 'preferences_store.dart';
import 'telegram_settings.dart';
import 'order_photos.dart';
import 'create_order.dart';
import 'ai_review_card.dart';

const _emulatorBaseUrl = 'http://10.0.2.2:8768';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = AppSettings(store: PreferencesSettingsStore());
  await settings.load();
  runApp(EnbekPlusApp(settings: settings));
}

class EnbekPlusApp extends StatelessWidget {
  const EnbekPlusApp({super.key, this.settings});
  final AppSettings? settings;

  @override
  Widget build(BuildContext context) {
    final current = settings ?? AppSettings.fallback;
    return AppSettingsScope(
      settings: current,
      child: AnimatedBuilder(
        animation: current,
        builder: (context, _) => MaterialApp(
          title: 'EnbekPlus',
          debugShowCheckedModeBanner: false,
          locale: Locale(current.language),
          supportedLocales: const [Locale('ru'), Locale('kk'), Locale('en')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          theme: enbekTheme(Brightness.light),
          darkTheme: enbekTheme(Brightness.dark),
          themeMode: current.themeMode,
          home: const _AppRoot(),
        ),
      ),
    );
  }
}

class _AppRoot extends StatefulWidget {
  const _AppRoot();

  @override
  State<_AppRoot> createState() => _AppRootState();
}

class _AppRootState extends State<_AppRoot> {
  EnbekApi? _api;
  Map<String, dynamic>? _user;
  Map<String, dynamic>? _bootstrap;

  void _enter(
    EnbekApi api,
    Map<String, dynamic> user,
    Map<String, dynamic> bootstrap,
  ) {
    setState(() {
      _api = api;
      _user = Map<String, dynamic>.from(bootstrap['user'] as Map? ?? user);
      _bootstrap = bootstrap;
    });
  }

  void _leave() {
    _api?.close();
    setState(() {
      _api = null;
      _user = null;
      _bootstrap = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final api = _api;
    final user = _user;
    final bootstrap = _bootstrap;
    if (api == null || user == null || bootstrap == null) {
      return LoginScreen(onConnected: _enter);
    }
    return HomeScreen(
      api: api,
      user: user,
      initialBootstrap: bootstrap,
      onLogout: _leave,
      onUserChanged: (updated) => setState(() => _user = updated),
    );
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({required this.onConnected, super.key});

  final void Function(
    EnbekApi api,
    Map<String, dynamic> user,
    Map<String, dynamic> bootstrap,
  )
  onConnected;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _base = TextEditingController(text: _emulatorBaseUrl);
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  bool _validationAttempted = false;
  String? _error;

  @override
  void dispose() {
    _base.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (_busy) return;
    _validationAttempted = true;
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    EnbekApi? api;
    try {
      api = EnbekApi(_base.text);
      final user = await api.login(_username.text, _password.text);
      final bootstrap = await api.bootstrap();
      if (!mounted) { api.close(); return; }
      widget.onConnected(api, user, bootstrap);
    } catch (error) {
      api?.close();
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(22, 28, 22, 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 58,
                      height: 58,
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.primary,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Icon(
                        Icons.handyman_outlined,
                        color: Theme.of(context).colorScheme.onPrimary,
                        size: 30,
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      'EnbekPlus',
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurface,
                        fontSize: 32,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -.7,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      context.tr('Мобильный клиент нарядной системы'),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        fontSize: 16,
                      ),
                    ),
                    const SizedBox(height: 20),
                    AppearanceSettings(
                      compact: true,
                      onLanguageChanged: () {
                        if (_validationAttempted) _formKey.currentState?.validate();
                      },
                    ),
                    const SizedBox(height: 20),
                    TextFormField(
                      controller: _base,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText: context.tr('Адрес сервера'),
                        prefixIcon: const Icon(Icons.dns_outlined),
                      ),
                      validator: (value) =>
                          (value == null || value.trim().isEmpty)
                          ? context.tr('Введите адрес backend')
                          : null,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      context.tr('Эмулятор Android: 10.0.2.2:8768. На телефоне укажите IP компьютера; loopback-адрес Docker может быть доступен только с этого ПК.'),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        height: 1.35,
                      ),
                    ),
                    const SizedBox(height: 20),
                    TextFormField(
                      controller: _username,
                      textInputAction: TextInputAction.next,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText: context.tr('Логин'),
                        prefixIcon: const Icon(Icons.person_outline),
                      ),
                      validator: (value) =>
                          (value == null || value.trim().isEmpty)
                          ? context.tr('Введите логин')
                          : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _password,
                      obscureText: _obscure,
                      onFieldSubmitted: (_) => _busy ? null : _connect(),
                      decoration: InputDecoration(
                        labelText: context.tr('Пароль'),
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          tooltip: _obscure
                              ? context.tr('Показать пароль')
                              : context.tr('Скрыть пароль'),
                          onPressed: () => setState(() => _obscure = !_obscure),
                          icon: Icon(
                            _obscure
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                        ),
                      ),
                      validator: (value) => (value == null || value.isEmpty)
                          ? context.tr('Введите пароль')
                          : null,
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      _ErrorBox(message: _error!),
                    ],
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _busy ? null : _connect,
                      icon: _busy
                          ? SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Theme.of(context).colorScheme.onPrimary,
                              ),
                            )
                          : const Icon(Icons.login),
                      label: Text(_busy ? context.tr('Подключение…') : context.tr('Войти')),
                    ),
                    const SizedBox(height: 16),
                    const _SafetyNotice(compact: true),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.api,
    required this.user,
    required this.initialBootstrap,
    required this.onLogout,
    required this.onUserChanged,
    super.key,
  });

  final EnbekApi api;
  final Map<String, dynamic> user;
  final Map<String, dynamic> initialBootstrap;
  final VoidCallback onLogout;
  final ValueChanged<Map<String, dynamic>> onUserChanged;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Map<String, dynamic> _data;
  int _tab = 0;
  bool _profileVisited = false;
  bool _creatingOrder = false;
  String _filter = 'active';
  bool _refreshing = false;
  Future<void>? _refreshTask;
  String? _error;

  @override
  void initState() {
    super.initState();
    _data = widget.initialBootstrap;
  }

  List<Map<String, dynamic>> get _orders {
    final raw = _data['orders'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<void> _refresh({bool afterPending = false}) {
    if (!mounted) return Future<void>.value();
    final pending = _refreshTask;
    if (pending != null) {
      // A return from create/detail needs a snapshot taken after that action,
      // not merely the completion of a refresh started before it.
      return afterPending ? pending.then((_) => _refresh()) : pending;
    }
    late final Future<void> tracked;
    tracked = _performRefresh().whenComplete(() {
      if (identical(_refreshTask, tracked)) _refreshTask = null;
    });
    _refreshTask = tracked;
    return tracked;
  }

  Future<void> _performRefresh() async {
    if (!mounted) return;
    setState(() {
      _refreshing = true;
      _error = null;
    });
    try {
      final next = await widget.api.bootstrap();
      if (!mounted) return;
      setState(() => _data = next);
      final nextUser = _map(next['user']);
      if (nextUser.isNotEmpty) widget.onUserChanged(nextUser);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

  List<Map<String, dynamic>> get _visibleOrders {
    final active = {
      'issued',
      'accepted',
      'queued',
      'in_progress',
      'paused',
      'rework',
    };
    return _orders.where((order) {
      switch (_filter) {
        case 'active':
          return active.contains(order['status']);
        case 'review':
          return {'executed', 'ai_review'}.contains(order['status']);
        case 'closed':
          return {'closed', 'rejected'}.contains(order['status']);
        default:
          return true;
      }
    }).toList();
  }

  Future<void> _createOrder() async {
    if (!mounted || _creatingOrder || widget.user['role'] != 'master') return;
    setState(() => _creatingOrder = true);
    try {
      final created = await Navigator.of(context).push<Map<String, dynamic>>(
        MaterialPageRoute(
          builder: (_) => CreateOrderScreen(
            api: widget.api,
            user: widget.user,
            bootstrap: _data,
          ),
        ),
      );
      if (!mounted) return;
      // A timed-out response may still have created an order. Refresh on the
      // uncertain/cancelled path without ever repeating the create request.
      if (created == null) {
        await _refresh(afterPending: true);
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(context.tr('Наряд создан'))),
      );
      // Navigate immediately. No delayed refresh may override a newer user
      // navigation. Returning from this detail refreshes the Home list.
      await _openOrder(created);
    } finally {
      if (mounted) setState(() => _creatingOrder = false);
    }
  }

  Future<void> _openOrder(Map<String, dynamic> order) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => OrderDetailScreen(
          api: widget.api,
          user: widget.user,
          initialOrder: order,
          constants: _map(_data['constants']),
        ),
      ),
    );
    if (mounted) await _refresh(afterPending: true);
  }

  @override
  Widget build(BuildContext context) {
    final roleLabel = _roleLabel(context, widget.user);
    final liveCount = _orders
        .where(
          (order) => {
            'issued',
            'accepted',
            'queued',
            'in_progress',
            'paused',
            'rework',
          }.contains(order['status']),
        )
        .length;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 20,
        toolbarHeight: 64.0 * MediaQuery.textScalerOf(context).scale(1).clamp(1.0, 2.5),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'EnbekPlus',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
            ),
            Text(
              roleLabel,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: context.tr('Обновить'),
            onPressed: _refreshing ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: IndexedStack(
        index: _tab,
        children: [
          _ordersBody(liveCount),
          _profileVisited ? _profileBody() : const SizedBox.shrink(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (value) => setState(() {
          _tab = value;
          if (value == 1) _profileVisited = true;
        }),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.assignment_outlined),
            selectedIcon: const Icon(Icons.assignment),
            label: context.tr('Наряды'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.account_circle_outlined),
            selectedIcon: const Icon(Icons.account_circle),
            label: context.tr('Профиль'),
          ),
        ],
      ),
    );
  }

  Widget _ordersBody(int liveCount) => RefreshIndicator(
    onRefresh: _refresh,
    child: ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 28),
      children: [
        if (widget.user['role'] == 'master') ...[
          FilledButton.icon(
            key: const ValueKey('create-order-button'),
            onPressed: _creatingOrder ? null : _createOrder,
            icon: const Icon(Icons.add_task),
            label: Text(context.tr('Выдать наряд')),
          ),
          const SizedBox(height: 18),
        ],
        Text(
          context.tr('Мои наряды'),
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
            fontWeight: FontWeight.w800,
            color: Theme.of(context).colorScheme.onSurface,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          context.tr('Активных нарядов: {count} • потяните вниз, чтобы обновить', {'count': liveCount}),
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
        if (_error != null) ...[
          const SizedBox(height: 14),
          _ErrorBox(message: _error!),
        ],
        const SizedBox(height: 18),
        DropdownButtonFormField<String>(
          isExpanded: true,
          initialValue: _filter,
          decoration: InputDecoration(
            labelText: context.tr('Показать'),
            prefixIcon: const Icon(Icons.filter_list),
          ),
          items: [
            DropdownMenuItem(value: 'active', child: Text(context.tr('Активные'))),
            DropdownMenuItem(value: 'review', child: Text(context.tr('На проверке'))),
            DropdownMenuItem(value: 'closed', child: Text(context.tr('Завершённые'))),
            DropdownMenuItem(value: 'all', child: Text(context.tr('Все наряды'))),
          ],
          onChanged: (value) => setState(() => _filter = value ?? 'active'),
        ),
        const SizedBox(height: 10),
        if (_visibleOrders.isEmpty)
          _EmptyState(
            title: context.tr('Наряды не найдены'),
            subtitle: _filter == 'active'
                ? context.tr('Новые назначения появятся здесь.')
                : context.tr('Попробуйте выбрать другой фильтр.'),
          )
        else
          ..._visibleOrders.map(
            (order) => _OrderCard(order: order, onTap: () => _openOrder(order)),
          ),
        const SizedBox(height: 12),
        const _SafetyNotice(),
      ],
    ),
  );

  Widget _profileBody() {
    final name = widget.user['display_name']?.toString() ?? context.tr('Пользователь');
    final role = _roleLabel(context, widget.user);
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 28),
      children: [
        CircleAvatar(
          radius: 34,
          backgroundColor: Theme.of(context).colorScheme.primary.withValues(alpha: .12),
          foregroundColor: Theme.of(context).colorScheme.primary,
          child: Text(
            _initials(name),
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 20),
          ),
        ),
        const SizedBox(height: 14),
        Text(
          name,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Theme.of(context).colorScheme.onSurface,
            fontWeight: FontWeight.w800,
            fontSize: 22,
          ),
        ),
        Text(
          role,
          textAlign: TextAlign.center,
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 24),
        _InfoCard(title: context.tr('Настройки'), child: const AppearanceSettings()),
        const SizedBox(height: 16),
        TelegramSettingsCard(key: ValueKey('telegram-${widget.user['id']}'), api: widget.api),
        const SizedBox(height: 16),
        const _SafetyNotice(),
        const SizedBox(height: 18),
        OutlinedButton.icon(
          onPressed: () async {
            try {
              await widget.api.logout();
            } finally {
              widget.onLogout();
            }
          },
          icon: const Icon(Icons.logout),
          label: Text(context.tr('Выйти')),
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(50),
          ),
        ),
      ],
    );
  }
}

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order, required this.onTap});

  final Map<String, dynamic> order;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final equipment = _map(order['equipment']);
    final status =
        _statusLabel(context, order['status']?.toString() ?? '');
    final priority = order['priority_label'] == null ? null : context.tr(order['priority_label'].toString());
    final overdue = order['is_overdue'] == true;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      order['code']?.toString() ?? context.tr('Наряд'),
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.primary,
                        fontWeight: FontWeight.w800,
                        letterSpacing: .3,
                      ),
                    ),
                  ),
                  if (overdue)
                    _Pill(
                      label: context.tr('Просрочен'),
                      background: Theme.of(context).colorScheme.errorContainer,
                      foreground: Theme.of(context).colorScheme.onErrorContainer,
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                order['title']?.toString() ?? context.tr('Работа по оборудованию'),
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onSurface,
                  fontWeight: FontWeight.w700,
                  fontSize: 17,
                ),
              ),
              const SizedBox(height: 7),
              Text(
                '${equipment['code'] ?? ''} ${equipment['name'] ?? ''}'.trim(),
                style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _Pill(
                    label: status,
                    background: _statusColor(context,
                      order['status']?.toString(),
                    ).withValues(alpha: .12),
                    foreground: _statusColor(context, order['status']?.toString()),
                  ),
                  if (priority != null && priority.isNotEmpty)
                    _Pill(
                      label: priority,
                      background: Theme.of(context).colorScheme.surfaceContainerHighest,
                      foreground: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  if (order['area'] != null)
                    _Pill(
                      label: order['area'].toString(),
                      background: Theme.of(context).colorScheme.surfaceContainerHighest,
                      foreground: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Icon(
                    Icons.schedule,
                    size: 17,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                  const SizedBox(width: 5),
                  Expanded(
                    child: Text(
                      context.tr('Срок: {date}', {'date': _formatDate(context, order['due_at'])}),
                      style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
                    ),
                  ),
                  Icon(Icons.chevron_right, color: Theme.of(context).colorScheme.primary),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class OrderDetailScreen extends StatefulWidget {
  const OrderDetailScreen({
    required this.api,
    required this.user,
    required this.initialOrder,
    required this.constants,
    super.key,
  });

  final EnbekApi api;
  final Map<String, dynamic> user;
  final Map<String, dynamic> initialOrder;
  final Map<String, dynamic> constants;

  @override
  State<OrderDetailScreen> createState() => _OrderDetailScreenState();
}

class _OrderDetailScreenState extends State<OrderDetailScreen> {
  final _picker = ImagePicker();
  final _work = TextEditingController();
  final _workerComment = TextEditingController();
  final _hours = TextEditingController(text: '1');
  final _pauseReason = TextEditingController();
  final _reviewComment = TextEditingController();
  final _ratingReason = TextEditingController();
  Map<String, dynamic>? _order;
  bool _loading = true;
  bool _busy = false;
  bool _materialsNotUsed = true;
  int? _faultCodeId;
  int? _materialId;
  double _materialQuantity = 1;
  int _rating = 5;
  String? _error;

  int get _id => (widget.initialOrder['id'] as num).toInt();
  String get _role => widget.user['role']?.toString() ?? '';
  String get _status => _order?['status']?.toString() ?? '';
  List<Map<String, dynamic>> get _faultCodes =>
      _listOfMaps(widget.constants['fault_codes']);
  List<Map<String, dynamic>> get _materials =>
      _listOfMaps(widget.constants['materials']);

  @override
  void initState() {
    super.initState();
    _order = Map<String, dynamic>.from(widget.initialOrder);
    _rating = ((widget.initialOrder['rating'] as num?)?.toInt() ?? 5).clamp(
      1,
      5,
    );
    _load();
  }

  @override
  void dispose() {
    _work.dispose();
    _workerComment.dispose();
    _hours.dispose();
    _pauseReason.dispose();
    _reviewComment.dispose();
    _ratingReason.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await widget.api.order(_id);
      if (!mounted) return;
      final next = _map(response['order']);
      setState(() {
        _order = next;
        _loading = false;
        _faultCodeId ??=
            (next['fault_code_id'] as num?)?.toInt() ??
            (_faultCodes.isEmpty
                ? null
                : (_faultCodes.first['id'] as num?)?.toInt());
        _materialId ??= _materials.isEmpty
            ? null
            : (_materials.first['id'] as num?)?.toInt();
      });
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error.toString();
          _loading = false;
        });
      }
    }
  }

  Future<void> _runAction(
    String action, {
    Map<String, dynamic> payload = const {},
    bool runAiCheck = false,
  }) async {
    if (!mounted || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.action(_id, action, payload: payload);
      if (runAiCheck) await widget.api.action(_id, 'ai_check');
      await _load();
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_actionMessage(context, action))));
    } catch (error) {
      final message = error.toString();
      // Completion can succeed even if a later AI-check request fails.
      // Reload first, then retain the actual action error for the user.
      await _load();
      if (mounted) setState(() => _error = message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reasonAction(String action, String title) async {
    _pauseReason.clear();
    final reason = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(context.tr(title)),
        content: TextField(
          controller: _pauseReason,
          minLines: 2,
          maxLines: 4,
          decoration: InputDecoration(
            labelText: context.tr('Причина (не менее 4 символов)'),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(context.tr('Отмена')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, _pauseReason.text.trim()),
            child: Text(context.tr('Продолжить')),
          ),
        ],
      ),
    );
    if (reason != null && reason.trim().length >= 4) {
      await _runAction(action, payload: {'reason': reason.trim()});
    }
  }

  Future<void> _uploadPhoto(ImageSource source) async {
    if (!mounted || _busy) return;
    final phase = _role == 'master' ? 'before' : 'after';
    final allowed = (_role == 'master' && {'issued', 'queued'}.contains(_status)) ||
        (_role == 'worker' && {'in_progress', 'paused'}.contains(_status));
    if (!allowed) return;
    if (_listOfMaps(_order?['photos']).where((photo) => photo['phase'] == phase).length >= 5) {
      setState(() => _error = 'Можно приложить не более пяти фотографий каждой фазы: до и после');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      final file = await _picker.pickImage(
        source: source,
        imageQuality: 80,
        maxWidth: 1800,
        maxHeight: 1800,
      );
      if (file == null || !mounted) return;
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      if (bytes.length > 4000000) {
        setState(
          () =>
              _error = 'Фото больше 4 МБ. Выберите или снимите файл поменьше.',
        );
        return;
      }
      final extension = file.name.toLowerCase().split('.').last;
      final mime = switch (extension) {
        'png' => 'image/png',
        'webp' => 'image/webp',
        'jpg' || 'jpeg' => 'image/jpeg',
        _ => 'image/jpeg',
      };
      setState(() {
        _busy = true;
        _error = null;
      });
      await widget.api.uploadPhoto(
        orderId: _id,
        fileName: file.name,
        mimeType: mime,
        bytes: bytes,
        phase: phase,
      );
      await _load();
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(context.tr('Фото загружено в наряд.'))),
        );
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _completeWork() async {
    final text = _work.text.trim();
    final hours = double.tryParse(_hours.text.replaceAll(',', '.'));
    if (text.length < 20) {
      setState(
        () => _error = 'Опишите выполненную работу: не менее 20 символов.',
      );
      return;
    }
    if (hours == null || hours <= 0 || hours > 72) {
      setState(() => _error = 'Укажите трудозатраты больше 0 и не более 72 часов.');
      return;
    }
    if (_faultCodeId == null) {
      setState(() => _error = 'Выберите код неисправности.');
      return;
    }
    if (!_materialsNotUsed && _materialId == null) {
      setState(() => _error = 'Выберите использованный материал.');
      return;
    }
    final payload = <String, dynamic>{
      'completion_text': text,
      'worker_completion_comment': _workerComment.text.trim(),
      'labor_hours': hours,
      'fault_code_id': _faultCodeId,
      'materials_not_used': _materialsNotUsed,
      'materials': _materialsNotUsed
          ? <Map<String, dynamic>>[]
          : [
              {'material_id': _materialId, 'quantity': _materialQuantity},
            ],
    };
    await _runAction('complete', payload: payload, runAiCheck: true);
  }

  Future<void> _closeOrder() async {
    final comment = _reviewComment.text.trim();
    if (comment.length < 4) {
      setState(
        () => _error = 'Добавьте комментарий мастера (не менее 4 символов).',
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(context.tr('Принять и закрыть наряд?')),
        content: Text(
          context.tr('Закрытие фиксирует решение мастера и оценку в журнале.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(context.tr('Назад')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(context.tr('Закрыть')),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _runAction(
        'close',
        payload: {'closure_comment': comment, 'rating': _rating},
      );
    }
  }

  Future<void> _saveRating() async {
    final reason = _ratingReason.text.trim();
    if (reason.length < 4) {
      setState(() => _error = 'Укажите причину корректировки оценки.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.rateOrder(_id, rating: _rating, reason: reason);
      await _load();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = _order ?? widget.initialOrder;
    final equipment = _map(order['equipment']);
    final isWorker = _role == 'worker';
    final isMaster = _role == 'master';
    final title = order['code']?.toString() ?? context.tr('Наряд');
    return Scaffold(
      appBar: AppBar(
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
      ),
      body: _loading && _order == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 30),
                children: [
                  if (_error != null) ...[
                    _ErrorBox(message: _error!),
                    const SizedBox(height: 12),
                  ],
                  _detailHeader(order, equipment),
                  const SizedBox(height: 12),
                  _detailSummary(order, equipment),
                  if (order['description'] != null &&
                      order['description'].toString().isNotEmpty) ...[
                    const SizedBox(height: 12),
                    _InfoCard(
                      title: context.tr('Описание работ'),
                      child: Text(order['description'].toString()),
                    ),
                  ],
                  if (order['completion_text'] != null &&
                      order['completion_text'].toString().isNotEmpty) ...[
                    const SizedBox(height: 12),
                    _InfoCard(
                      title: context.tr('Отчёт исполнителя'),
                      child: Text(order['completion_text'].toString()),
                    ),
                  ],
                  const SizedBox(height: 12),
                  _photoSection(order, isWorker),
                  const SizedBox(height: 12),
                  AiReviewCard(order: order),
                  const SizedBox(height: 12),
                  if (isWorker) _workerActions(order),
                  if (isMaster) _masterActions(order),
                  if (_role == 'manager')
                    _InfoCard(
                      title: context.tr('Режим просмотра'),
                      child: Text(
                        context.tr('Для этой роли действия с нарядом недоступны.'),
                      ),
                    ),
                  const SizedBox(height: 12),
                  const _SafetyNotice(),
                ],
              ),
            ),
    );
  }

  Widget _detailHeader(
    Map<String, dynamic> order,
    Map<String, dynamic> equipment,
  ) {
    final color = _statusColor(context, _status);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _Pill(
                  label:
                      _statusLabel(context, _status),
                  background: color.withValues(alpha: .12),
                  foreground: color,
                ),
                if (order['is_overdue'] == true)
                  _Pill(
                    label: context.tr('Просрочен'),
                    background: Theme.of(context).colorScheme.errorContainer,
                    foreground: Theme.of(context).colorScheme.onErrorContainer,
                  ),
              ],
            ),
            const SizedBox(height: 14),
            Text(
              order['title']?.toString() ?? context.tr('Работа по оборудованию'),
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurface,
                fontWeight: FontWeight.w800,
                fontSize: 23,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '${equipment['code'] ?? ''} ${equipment['name'] ?? ''}'.trim(),
              style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 15),
            ),
          ],
        ),
      ),
    );
  }

  Widget _detailSummary(
    Map<String, dynamic> order,
    Map<String, dynamic> equipment,
  ) {
    final worker = _map(order['worker']);
    final master = _map(order['master']);
    return _InfoCard(
      title: context.tr('Детали наряда'),
      child: Column(
        children: [
          _FactRow(context.tr('Участок'), order['area']?.toString() ?? '—'),
          _FactRow(context.tr('Оборудование'), equipment['name']?.toString() ?? '—'),
          _FactRow(context.tr('Тип работ'), context.tr(order['work_type_label']?.toString() ?? '—')),
          _FactRow(context.tr('Приоритет'), context.tr(order['priority_label']?.toString() ?? '—')),
          _FactRow(context.tr('Срок'), _formatDate(context, order['due_at'])),
          if (worker.isNotEmpty)
            _FactRow(context.tr('Исполнитель'), worker['display_name']?.toString() ?? '—'),
          if (master.isNotEmpty)
            _FactRow(context.tr('Мастер'), master['display_name']?.toString() ?? '—'),
          if (order['pause_reason'] != null &&
              order['pause_reason'].toString().isNotEmpty)
            _FactRow(context.tr('Причина паузы'), order['pause_reason'].toString()),
          if (order['reject_reason'] != null &&
              order['reject_reason'].toString().isNotEmpty)
            _FactRow(context.tr('Причина возврата'), order['reject_reason'].toString()),
        ],
      ),
    );
  }

  Widget _photoSection(Map<String, dynamic> order, bool isWorker) {
    final photos = _listOfMaps(order['photos']);
    final phase = _role == 'master' ? 'before' : 'after';
    final atLimit = photos.where((photo) => photo['phase'] == phase).length >= 5;
    final canUpload = !atLimit && (
        (isWorker && {'in_progress', 'paused'}.contains(_status)) ||
        (_role == 'master' && {'issued', 'queued'}.contains(_status)));
    return _InfoCard(
      title: context.tr('Фото ({count})', {'count': photos.length}),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          OrderPhotos(api: widget.api, photos: photos),
          const SizedBox(height: 10),
          if (!canUpload)
            Text(
              context.tr(atLimit
                  ? 'Можно приложить не более пяти фотографий каждой фазы: до и после'
                  : _role == 'master'
                      ? 'Мастер добавляет фото «до», пока наряд выдан или находится в очереди.'
                      : isWorker
                          ? 'Фото добавляются после начала работ или во время паузы. В закрытом наряде доступен только просмотр.'
                          : 'Для этой роли доступен только просмотр фотографий.'),
              style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          if (canUpload) ...[
            Text(context.tr(_role == 'master' ? 'Добавить фото «до»' : 'Добавить фото после работы')),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _uploadPhoto(ImageSource.camera),
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: Text(context.tr('Снять фото')),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(48),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _uploadPhoto(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library_outlined),
                    label: Text(context.tr('Из галереи')),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(48),
                    ),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: 6),
          Text(
            context.tr('Фото и их метаданные не доказывают исправность оборудования.'),
            style: TextStyle(
              fontSize: 12,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }

  Widget _workerActions(Map<String, dynamic> order) {
    if (_status == 'issued') {
      return _actionPanel(context.tr('Принятие наряда'), [
        FilledButton.icon(
          onPressed: _busy ? null : () => _runAction('accept'),
          icon: const Icon(Icons.check_circle_outline),
          label: Text(context.tr('Принять наряд')),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: _busy ? null : () => _runAction('queue'),
          icon: const Icon(Icons.queue_outlined),
          label: Text(context.tr('В очередь')),
        ),
        const SizedBox(height: 10),
        TextButton.icon(
          onPressed: _busy
              ? null
              : () => _reasonAction('reject', 'Отказ от наряда'),
          icon: const Icon(Icons.block_outlined),
          label: Text(context.tr('Отказаться с причиной')),
        ),
      ]);
    }
    if (_status == 'queued') {
      return _actionPanel(context.tr('Наряд в очереди'), [
        FilledButton.icon(
          onPressed: _busy ? null : () => _runAction('accept'),
          icon: const Icon(Icons.check_circle_outline),
          label: Text(context.tr('Принять наряд')),
        ),
      ]);
    }
    if (_status == 'accepted' || _status == 'rework') {
      return _actionPanel(context.tr('Начало работ'), [
        FilledButton.icon(
          onPressed: _busy ? null : () => _runAction('start'),
          icon: const Icon(Icons.play_arrow),
          label: Text(context.tr('Начать работу')),
        ),
      ]);
    }
    if (_status == 'paused') {
      return _actionPanel(context.tr('Работа приостановлена'), [
        FilledButton.icon(
          onPressed: _busy ? null : () => _runAction('resume'),
          icon: const Icon(Icons.play_arrow),
          label: Text(context.tr('Продолжить работу')),
        ),
      ]);
    }
    if (_status == 'in_progress') {
      return _actionPanel(context.tr('Отчёт и завершение'), [
        TextFormField(
          controller: _work,
          minLines: 3,
          maxLines: 6,
          decoration: InputDecoration(
            labelText: context.tr('Что выполнено? (не менее 20 символов)'),
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          isExpanded: true,
          initialValue: _faultCodeId,
          decoration: InputDecoration(labelText: context.tr('Код неисправности')),
          items: _faultCodes
              .map(
                (code) => DropdownMenuItem<int>(
                  value: (code['id'] as num).toInt(),
                  child: Text(
                    '${code['code']} · ${code['label']}',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              )
              .toList(),
          onChanged: _busy
              ? null
              : (value) => setState(() => _faultCodeId = value),
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: _hours,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
            labelText: context.tr('Трудозатраты, часы'),
            prefixIcon: const Icon(Icons.timer_outlined),
          ),
        ),
        const SizedBox(height: 8),
        CheckboxListTile(
          value: _materialsNotUsed,
          contentPadding: EdgeInsets.zero,
          controlAffinity: ListTileControlAffinity.leading,
          title: Text(context.tr('Материалы не использовались')),
          onChanged: _busy
              ? null
              : (value) => setState(() => _materialsNotUsed = value ?? true),
        ),
        if (!_materialsNotUsed) ...[
          DropdownButtonFormField<int>(
            isExpanded: true,
            initialValue: _materialId,
            decoration: InputDecoration(labelText: context.tr('Материал')),
            items: _materials
                .map(
                  (item) => DropdownMenuItem<int>(
                    value: (item['id'] as num).toInt(),
                    child: Text(
                      '${item['sku']} · ${item['name']}',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: _busy
                ? null
                : (value) => setState(() => _materialId = value),
          ),
          const SizedBox(height: 12),
          TextFormField(
            initialValue: '1',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: context.tr('Количество материала'),
            ),
            onChanged: (value) => _materialQuantity =
                double.tryParse(value.replaceAll(',', '.')) ?? 0,
          ),
          const SizedBox(height: 12),
        ],
        TextFormField(
          controller: _workerComment,
          minLines: 1,
          maxLines: 3,
          decoration: InputDecoration(
            labelText: context.tr('Комментарий исполнителя (необязательно)'),
          ),
        ),
        const SizedBox(height: 14),
        FilledButton.icon(
          onPressed: _busy ? null : _completeWork,
          icon: const Icon(Icons.task_alt),
          label: Text(context.tr('Сохранить отчёт и передать на проверку')),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () => _reasonAction('pause', 'Приостановить работу'),
          icon: const Icon(Icons.pause_circle_outline),
          label: Text(context.tr('Приостановить с причиной')),
        ),
      ]);
    }
    if (_status == 'executed') {
      return _actionPanel(context.tr('Отчёт сохранён'), [
        FilledButton.icon(
          onPressed: _busy ? null : () => _runAction('ai_check'),
          icon: const Icon(Icons.fact_check_outlined),
          label: Text(context.tr('Передать на проверку')),
        ),
      ]);
    }
    return const SizedBox.shrink();
  }

  Widget _masterActions(Map<String, dynamic> order) {
    if (_status == 'ai_review') {
      return _actionPanel(context.tr('Проверка и окончательная приёмка'), [
        DropdownButtonFormField<int>(
          isExpanded: true,
          initialValue: _rating,
          decoration: InputDecoration(labelText: context.tr('Оценка исполнителю')),
          items: [1, 2, 3, 4, 5]
              .map(
                (score) =>
                    DropdownMenuItem(value: score, child: Text(context.tr('{score} из 5', {'score': score}))),
              )
              .toList(),
          onChanged: (value) => setState(() => _rating = value ?? 5),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _reviewComment,
          minLines: 2,
          maxLines: 4,
          decoration: InputDecoration(
            labelText: context.tr('Комментарий мастера (не менее 4 символов)'),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: _busy ? null : _closeOrder,
          icon: const Icon(Icons.verified_outlined),
          label: Text(context.tr('Принять и закрыть')),
        ),
        OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () => _reasonAction('request_rework', 'Вернуть на доработку'),
          icon: const Icon(Icons.replay),
          label: Text(context.tr('Вернуть на доработку')),
        ),
      ]);
    }
    if (_status == 'closed') {
      return _actionPanel(context.tr('Наряд закрыт'), [
        Text(
          context.tr('Текущая оценка: {score} из 5', {'score': order['rating'] ?? '—'}),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<int>(
          isExpanded: true,
          initialValue: _rating,
          decoration: InputDecoration(labelText: context.tr('Новая оценка')),
          items: [1, 2, 3, 4, 5]
              .map(
                (score) =>
                    DropdownMenuItem(value: score, child: Text(context.tr('{score} из 5', {'score': score}))),
              )
              .toList(),
          onChanged: (value) => setState(() => _rating = value ?? 5),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _ratingReason,
          minLines: 1,
          maxLines: 3,
          decoration: InputDecoration(
            labelText: context.tr('Причина изменения (обязательна)'),
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: _busy ? null : _saveRating,
          icon: const Icon(Icons.edit_note),
          label: Text(context.tr('Сохранить корректировку')),
        ),
      ]);
    }
    return const SizedBox.shrink();
  }

  Widget _actionPanel(String title, List<Widget> children) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface,
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 14),
          ...children,
          if (_busy) ...[
            const SizedBox(height: 12),
            const LinearProgressIndicator(),
          ],
        ],
      ),
    ),
  );
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface,
              fontWeight: FontWeight.w800,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    ),
  );
}

class _FactRow extends StatelessWidget {
  const _FactRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 112,
          child: Text(
            label,
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: TextStyle(color: Theme.of(context).colorScheme.onSurface, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    ),
  );
}

class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.background,
    required this.foreground,
  });

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: background,
      borderRadius: BorderRadius.circular(99),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: foreground,
        fontSize: 12,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _SafetyNotice extends StatelessWidget {
  const _SafetyNotice({this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.all(compact ? 12 : 14),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.tertiaryContainer,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(Icons.info_outline, color: Theme.of(context).colorScheme.onTertiaryContainer),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            context.tr('ИИ и фотографии не дают допуск к опасным работам и не подтверждают исправность. Решение о приёмке принимает мастер.'),
            style: TextStyle(
              color: Theme.of(context).colorScheme.onTertiaryContainer,
              fontSize: compact ? 12 : 13,
              height: 1.4,
            ),
          ),
        ),
      ],
    ),
  );
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(13),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.errorContainer,
      borderRadius: BorderRadius.circular(13),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(Icons.error_outline, color: Theme.of(context).colorScheme.onErrorContainer),
        const SizedBox(width: 9),
        Expanded(
          child: Text(
            context.trError(message),
            style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
          ),
        ),
      ],
    ),
  );
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 48),
    child: Column(
      children: [
        Icon(Icons.assignment_late_outlined, size: 46, color: Theme.of(context).colorScheme.primary),
        const SizedBox(height: 12),
        Text(
          title,
          style: TextStyle(
            fontSize: 17,
            color: Theme.of(context).colorScheme.onSurface,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          subtitle,
          textAlign: TextAlign.center,
          style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
        ),
      ],
    ),
  );
}

Map<String, dynamic> _map(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, value) => MapEntry('$key', value));
  return <String, dynamic>{};
}

List<Map<String, dynamic>> _listOfMaps(Object? value) {
  if (value is! List) return const [];
  return value.whereType<Map>().map((item) => _map(item)).toList();
}

String _initials(String name) {
  final parts = name.trim().split(RegExp(r'\s+'));
  return parts
      .take(2)
      .map((part) => part.isEmpty ? '' : part[0])
      .join()
      .toUpperCase();
}

String _statusLabel(BuildContext context, String status) => switch (status) {
  'issued' => context.tr('Выдан'),
  'accepted' => context.tr('Принят'),
  'queued' => context.tr('В очереди'),
  'rejected' => context.tr('Отклонён'),
  'in_progress' => context.tr('В работе'),
  'paused' => context.tr('Приостановлен'),
  'executed' => context.tr('Исполнен'),
  'ai_review' => context.tr('Проверка'),
  'rework' => context.tr('Доработка'),
  'closed' => context.tr('Закрыт'),
  _ => status,
};

Color _statusColor(BuildContext context, String? status) {
  final dark = Theme.of(context).brightness == Brightness.dark;
  return switch (status) {
    'issued' || 'queued' => dark ? const Color(0xffacc9ef) : const Color(0xff315d8c),
    'accepted' || 'in_progress' => dark ? const Color(0xff98d4b7) : const Color(0xff25654e),
    'paused' || 'rework' => dark ? const Color(0xffe6c58c) : const Color(0xff78591f),
    'executed' || 'ai_review' => dark ? const Color(0xffc9b9e6) : const Color(0xff665087),
    'closed' => dark ? const Color(0xffa7d3bc) : const Color(0xff37664f),
    'rejected' => Theme.of(context).colorScheme.error,
    _ => Theme.of(context).colorScheme.onSurfaceVariant,
  };
}

String _formatDate(BuildContext context, Object? value) {
  if (value == null) return '—';
  final date = DateTime.tryParse(value.toString())?.toLocal();
  if (date == null) return value.toString();
  final day = date.day.toString().padLeft(2, '0');
  final month = date.month.toString().padLeft(2, '0');
  final hour = date.hour.toString().padLeft(2, '0');
  final minute = date.minute.toString().padLeft(2, '0');
  return context.settings.language == 'en'
      ? '${date.year}-$month-$day $hour:$minute'
      : '$day.$month.${date.year} $hour:$minute';
}

String _actionMessage(BuildContext context, String action) => switch (action) {
  'accept' => context.tr('Наряд принят.'),
  'queue' => context.tr('Наряд добавлен в очередь.'),
  'start' => context.tr('Работа начата.'),
  'pause' => context.tr('Работа приостановлена.'),
  'resume' => context.tr('Работа продолжена.'),
  'complete' => context.tr('Отчёт сохранён.'),
  'close' => context.tr('Наряд принят мастером и закрыт.'),
  'request_rework' => context.tr('Наряд возвращён на доработку.'),
  'ai_check' => context.tr('Проверка запущена.'),
  _ => context.tr('Изменение сохранено.'),
};

String _roleLabel(BuildContext context, Map<String, dynamic> user) {
  final label = switch (user['role']) {
    'master' => 'Мастер',
    'worker' => 'Исполнитель',
    'manager' => 'Руководитель · просмотр',
    _ => user['role_label']?.toString() ?? 'Пользователь',
  };
  return context.tr(label);
}
