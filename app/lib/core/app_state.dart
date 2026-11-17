// 应用状态单例：服务连接、草稿、进行中任务、最近任务、历史查询、零件目录、
// 每任务快照/轮询、3D 产物缓存与界面状态恢复。
//
// 设计约束：
// - 每个任务独立缓存与轮询，后台任务不得抢占当前视图；APP 切后台不取消服务端任务；
// - 服务切址后清空任务/产物/零件缓存，禁止跨服务混用；
// - 网络失败保留已缓存界面并明确标记，恢复后先同步快照再恢复轮询；
// - 所有网络调用经 ApiClient（唯一入口），状态变化通过 notifyListeners 通知页面。
import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';

import '../models/api_error.dart';
import '../models/artifacts.dart';
import '../models/job.dart';
import '../models/part.dart';
import 'api_client.dart';
import 'format.dart';
import 'job_snapshot.dart';
import 'service_address.dart';
import 'storage.dart';

/// 服务连接状态（网络层）。
enum ServiceConnection { unknown, online, offline }

/// 3D 产物缓存条目。
class _ArtifactEntry {
  _ArtifactEntry(this.key, this.artifacts);

  final String key;
  final StudioArtifacts artifacts;
}

/// 全局应用状态。
class AppState extends ChangeNotifier {
  AppState({ApiClient? api, AppStorage? storage})
    : api = api ?? ApiClient(),
      storage = storage ?? AppStorage();

  final ApiClient api;
  final AppStorage storage;

  static const String appVersion = '1.0.0 (1)';

  bool _disposed = false;
  bool _foreground = true;
  bool _initStarted = false;

  /// 初始化完成（读取本地配置/缓存后）。
  bool booted = false;

  // ---------- 服务连接 ----------
  ServiceAddress? address;
  String _token = '';
  ServiceConnection connection = ServiceConnection.unknown;
  String? lastNetworkError;
  ConnectionCheck? lastCheck;
  bool validated = false;
  String? configError;

  bool get configured => address != null;

  bool get hasToken => _token.isNotEmpty;

  String get tokenForInput => _token;

  // ---------- 草稿 ----------
  String draftDesc = '';
  String draftMode = 'fast';

  // ---------- 零件目录 ----------
  PartsCatalog parts = PartsCatalog.empty;
  bool partsLoading = false;
  String? partsError;
  bool partsFromCache = false;
  double? partsUpdatedAt;

  // ---------- 进行中任务 ----------
  List<JobSummary> runningJobs = const <JobSummary>[];
  int? totalJobs;
  double? lastSyncAt;
  String? listError;

  /// 底部「作品」角标：真实进行中数量，为 0 时隐藏。
  int get runningCount => runningJobs.length;

  /// 当前是否有进行中任务（创作页摘要与作品页默认分段使用）。
  bool get hasRunning => runningJobs.isNotEmpty;

  // ---------- 任务快照 ----------
  final Map<String, JobSnapshot> jobs = <String, JobSnapshot>{};
  final Map<String, JobPoller> _pollers = <String, JobPoller>{};
  String? selectedJobId;
  List<String> recentIds = <String>[];

  // ---------- 历史任务 ----------
  HistoryQueryState historyQuery = const HistoryQueryState();
  HistoryPageData? historyData;
  bool historyLoading = false;
  String? historyError;
  bool historyFromCache = false;

  /// 是否已经拿到过一次历史数据（页面首帧据此决定显示加载态还是静默刷新）。
  bool get historyDataLoaded => historyData != null;

  // ---------- 3D 产物缓存 ----------
  final Map<String, _ArtifactEntry> _artifactCache = <String, _ArtifactEntry>{};
  final Map<String, Future<StudioArtifacts>> _artifactRequests =
      <String, Future<StudioArtifacts>>{};

  // ---------- 界面状态 ----------
  /// 作品页分段：running / done / all（保留用户上次选择）。
  String worksSegment = 'running';

  /// 用户是否已主动选择过分段（未选择时启动后按真实数据落到默认分段）。
  bool worksSegmentRestored = false;
  final Map<String, StudioUiState> _studioStates = <String, StudioUiState>{};

  // ---------- 定时器 ----------
  Timer? _runningTimer;
  Timer? _draftSaveTimer;
  Timer? _uiStateSaveTimer;
  final Map<String, double> _lastDetailPersist = <String, double>{};

  /// 已落盘的状态字符串（用于识别状态变化，避免 adopt 后再比较导致恒等）。
  final Map<String, String> _lastPersistedStatus = <String, String>{};

  /// 同一任务的详情加载去重（selectJob/JobPage 同时触发时只发一次请求）。
  final Map<String, Future<void>> _jobLoadRequests = <String, Future<void>>{};

  /// 同一任务的重试去重（防连点创建多个真实任务）。
  final Map<String, Future<String>> _retryRequests = <String, Future<String>>{};

  /// 调试日志（不含令牌/需求内容），供设置页与真机证据使用。
  final List<String> debugLog = <String>[];

  // ============================================================
  // 初始化与生命周期
  // ============================================================
  /// 读取本地配置与缓存，完成后再异步校准服务端数据。
  Future<void> init() async {
    if (_initStarted) return;
    _initStarted = true;
    await storage.init();

    final draft = storage.draft;
    if (draft != null) {
      draftDesc = (draft['desc'] ?? '').toString();
      draftMode = _normalizeMode(draft['mode']?.toString());
    }
    recentIds = List<String>.from(storage.recentJobIds);
    selectedJobId = storage.selectedJobId;
    historyQuery = storage.historyQuery;
    _loadUiState(storage.uiState);

    final baseUrl = storage.baseUrl;
    final savedToken = await storage.readToken() ?? '';
    if (baseUrl != null && baseUrl.isNotEmpty) {
      final parsed = ServiceAddress.parse(baseUrl);
      if (parsed.ok) {
        address = parsed.address;
        _token = savedToken;
        api.configure(baseUrl: address!.url, token: _token);
        await _restoreCaches(storage.cachedServiceKey);
      } else {
        configError = '已保存的服务地址不合法：${parsed.error ?? '未知原因'}';
      }
    }
    booted = true;
    _log(
      '启动完成：configured=$configured cachedJobs=${jobs.length} parts=${parts.parts.length}',
    );
    notifyListeners();
    if (configured) {
      unawaited(_startupSync());
      _startRunningTimer();
    }
  }

  /// 从本地缓存恢复（仅在服务标识一致时）。
  Future<void> _restoreCaches(String? cachedServiceKey) async {
    final currentKey = address?.cacheKey;
    if (currentKey == null) return;
    if (cachedServiceKey != null && cachedServiceKey != currentKey) {
      await storage.clearServiceCaches();
      return;
    }
    final rawParts = storage.cachedParts;
    if (rawParts != null) {
      try {
        parts = PartsCatalog.fromJson(rawParts['parts']);
        partsFromCache = parts.parts.isNotEmpty;
        partsUpdatedAt = (rawParts['fetchedAt'] as num?)?.toDouble();
        _log('缓存零件已恢复：${parts.parts.length} 个变体');
      } catch (e) {
        debugPrint('[state] 缓存零件解析失败：$e');
      }
    }
    final rawHistory = storage.cachedHistory;
    if (rawHistory != null) {
      try {
        historyData = HistoryPageData.fromJson(rawHistory);
        historyFromCache = true;
      } catch (e) {
        debugPrint('[state] 缓存历史解析失败：$e');
      }
    }
    final cachedDetails = storage.cachedDetails;
    for (final entry in cachedDetails.entries) {
      final raw = entry.value;
      final detailRaw = raw is Map ? raw['detail'] : null;
      if (detailRaw is! Map) continue;
      try {
        final detail = JobDetail.fromJson(detailRaw);
        snapshotOf(detail.id).adoptFromCache(detail);
      } catch (e) {
        debugPrint('[state] 缓存任务解析失败：${entry.key}');
      }
    }
    if (partsFromCache || historyFromCache || jobs.isNotEmpty) {
      _log('已从本地缓存恢复界面（等待服务端校准）');
    }
    lastSyncAt = storage.lastSyncAt;
  }

  Future<void> _startupSync() async {
    if (!configured) return;
    await refreshRunning(silent: true);
    if (!worksSegmentRestored) {
      // 首次进入：有进行中默认「进行中」，否则「已完成」。
      worksSegment = defaultWorksSegment;
    }
    final id = selectedJobId;
    if (id != null) {
      try {
        await fetchJob(id);
      } catch (e) {
        _log('启动同步选中任务失败：${describeError(e)}');
      }
    }
    if (parts.parts.isEmpty) {
      await refreshParts();
    }
    if (worksSegment == 'done') {
      await refreshDoneWorks(silent: true);
    } else if (worksSegment == 'all') {
      await refreshHistory(silent: true);
    }
    if (recentDone.isEmpty) {
      await refreshRecentDone();
    }
    _syncPollers();
  }

  /// 前台/后台切换：后台不轮询、不取消服务端任务；回前台先同步再恢复轮询。
  void onLifecycleChanged(AppLifecycleState state) {
    final foreground = state == AppLifecycleState.resumed;
    if (foreground == _foreground) return;
    _foreground = foreground;
    if (!foreground) {
      _runningTimer?.cancel();
      _runningTimer = null;
      _pausePollers();
      _log('APP 进入后台：暂停轮询（不取消服务端任务）');
      return;
    }
    _log('APP 回到前台：同步任务快照后恢复轮询');
    if (configured) {
      unawaited(_resumeSync());
      _startRunningTimer();
    }
  }

  Future<void> _resumeSync() async {
    await refreshRunning(silent: true);
    final id = selectedJobId;
    if (id != null) {
      try {
        await fetchJob(id);
      } catch (_) {
        // 恢复失败保留缓存，轮询器会在下次成功时校准
      }
    }
    for (final job in runningJobs) {
      ensurePolling(job.id);
    }
    _syncPollers();
  }

  @override
  void dispose() {
    _disposed = true;
    _runningTimer?.cancel();
    _draftSaveTimer?.cancel();
    _uiStateSaveTimer?.cancel();
    for (final poller in _pollers.values) {
      poller.dispose();
    }
    _pollers.clear();
    api.close();
    super.dispose();
  }

  // ============================================================
  // 服务连接与设置
  // ============================================================
  /// 测试连接（不修改当前配置）：健康 → 零件 → 鉴权。
  Future<ConnectionCheck> testConnection({
    required String rawUrl,
    required String token,
    bool checkParts = true,
  }) async {
    final parsed = ServiceAddress.parse(rawUrl);
    if (!parsed.ok) {
      return ConnectionCheck(
        baseUrl: rawUrl.trim(),
        healthOk: false,
        apiVersion: 0,
        status: '',
        latencyMs: 0,
        error: parsed.error,
        apiVersionCompatible: false,
      );
    }
    final addr = parsed.address!;
    final tokenError = addr.tokenRequirementError(
      hasToken: token.trim().isNotEmpty,
    );
    if (tokenError != null) {
      return ConnectionCheck(
        baseUrl: addr.url,
        healthOk: false,
        apiVersion: 0,
        status: '',
        latencyMs: 0,
        error: tokenError,
        apiVersionCompatible: false,
      );
    }
    return api.checkConnection(
      baseUrl: addr.url,
      token: token,
      checkParts: checkParts,
    );
  }

  /// 保存服务地址与令牌；地址变化时清空跨服务缓存并重新拉取。
  Future<ConnectionCheck> applyService({
    required String rawUrl,
    required String token,
  }) async {
    final parsed = ServiceAddress.parse(rawUrl);
    if (!parsed.ok) {
      return ConnectionCheck(
        baseUrl: rawUrl.trim(),
        healthOk: false,
        apiVersion: 0,
        status: '',
        latencyMs: 0,
        error: parsed.error,
        apiVersionCompatible: false,
      );
    }
    final addr = parsed.address!;
    final tokenError = addr.tokenRequirementError(
      hasToken: token.trim().isNotEmpty,
    );
    if (tokenError != null) {
      return ConnectionCheck(
        baseUrl: addr.url,
        healthOk: false,
        apiVersion: 0,
        status: '',
        latencyMs: 0,
        error: tokenError,
        apiVersionCompatible: false,
      );
    }
    final check = await api.checkConnection(baseUrl: addr.url, token: token);
    final changed = address?.cacheKey != addr.cacheKey;
    if (changed) {
      await storage.clearServiceCaches();
    }
    address = addr;
    _token = token.trim();
    api.configure(baseUrl: addr.url, token: _token);
    await storage.saveBaseUrl(addr.url);
    await storage.saveCachedServiceKey(addr.cacheKey);
    await storage.saveToken(_token.isEmpty ? null : _token);
    if (changed) {
      _resetServiceState();
    }
    lastCheck = check;
    validated = check.ok;
    configError = check.ok ? null : check.error;
    connection = check.healthOk
        ? ServiceConnection.online
        : ServiceConnection.offline;
    lastNetworkError = check.healthOk ? null : check.error;
    notifyListeners();
    _log(
      '服务配置已保存：${addr.url} 健康=${check.healthOk} 鉴权=${check.authChecked ? check.authOk : '未检查'}',
    );
    unawaited(_afterServiceChange());
    return check;
  }

  Future<void> _afterServiceChange() async {
    await refreshRunning(silent: true);
    // 运行中才配置服务（首次连接）时同样按真实数据落默认分段。
    if (!worksSegmentRestored) {
      worksSegment = defaultWorksSegment;
    }
    await refreshParts();
    if (worksSegment == 'done') {
      await refreshDoneWorks(silent: true);
    } else if (worksSegment == 'all') {
      await refreshHistory(silent: true);
    }
    final id = selectedJobId;
    if (id != null) {
      try {
        await fetchJob(id);
      } catch (_) {
        // 保留错误状态供页面展示
      }
    }
    _syncPollers();
    _startRunningTimer();
  }

  /// 清空与旧服务有关的任务/产物/缓存状态（保留草稿与筛选偏好）。
  void _resetServiceState() {
    for (final poller in _pollers.values) {
      poller.dispose();
    }
    _pollers.clear();
    jobs.clear();
    runningJobs = const <JobSummary>[];
    totalJobs = null;
    recentIds = <String>[];
    selectedJobId = null;
    parts = PartsCatalog.empty;
    partsFromCache = false;
    partsError = null;
    partsUpdatedAt = null;
    historyData = null;
    historyFromCache = false;
    historyError = null;
    historyQuery = historyQuery.copyWith(page: 1);
    doneData = null;
    doneError = null;
    doneLoading = false;
    donePage = 1;
    _artifactCache.clear();
    _artifactRequests.clear();
    _lastDetailPersist.clear();
    lastSyncAt = null;
  }

  /// 解除服务配置（回到首次连接引导）。
  Future<void> disconnectService() async {
    for (final poller in _pollers.values) {
      poller.dispose();
    }
    _pollers.clear();
    _runningTimer?.cancel();
    _runningTimer = null;
    await storage.clearServiceCaches();
    await storage.saveBaseUrl(null);
    await storage.saveToken(null);
    await storage.saveSelectedJobId(null);
    await storage.saveRecentJobIds(const <String>[]);
    api.clear();
    address = null;
    _token = '';
    connection = ServiceConnection.unknown;
    lastCheck = null;
    validated = false;
    configError = null;
    lastNetworkError = null;
    _resetServiceState();
    notifyListeners();
  }

  // ============================================================
  // 零件目录 / 进行中列表 / 历史
  // ============================================================
  /// 拉取零件目录（唯一数据源）。
  Future<void> refreshParts({bool silent = false}) async {
    if (!configured) return;
    partsLoading = true;
    if (!silent) {
      partsError = null;
      notifyListeners();
    }
    try {
      final catalog = await api.parts();
      parts = catalog;
      partsFromCache = false;
      partsUpdatedAt = DateTime.now().millisecondsSinceEpoch / 1000;
      _markOnline();
      await storage.saveCachedParts({
        'parts': catalog.toJson()['parts'],
        'fetchedAt': partsUpdatedAt,
      });
    } catch (e) {
      partsError = describeError(e);
      if (e is ApiError && e.network) _markOffline(e.message);
    } finally {
      partsLoading = false;
      notifyListeners();
    }
  }

  /// 拉取进行中任务与总数（导航角标/进行中专区/轮询调度共用）。
  Future<void> refreshRunning({bool silent = true}) async {
    if (_disposed || !configured) return;
    try {
      final page = await api.jobsPage(page: 1, pageSize: 1);
      runningJobs = page.running;
      totalJobs = page.total;
      lastSyncAt = DateTime.now().millisecondsSinceEpoch / 1000;
      listError = null;
      _markOnline();
      await storage.saveLastSyncAt(lastSyncAt);
      _syncPollers();
    } catch (e) {
      listError = describeError(e);
      if (e is ApiError && e.network) _markOffline(e.message);
    }
    // 请求期间 AppState 可能已 dispose（如页面/测试收尾），不再通知已销毁的监听者。
    if (_disposed) return;
    notifyListeners();
  }

  /// 拉取历史分页（保留筛选/页码；当前页越界时回退到有效页）。
  Future<void> refreshHistory({bool silent = false}) async {
    if (!configured) return;
    historyLoading = true;
    if (!silent) {
      historyError = null;
      notifyListeners();
    }
    try {
      var data = await api.jobsPage(
        q: historyQuery.q,
        status: historyQuery.status,
        outcome: historyQuery.outcome,
        page: historyQuery.page,
        pageSize: 20,
      );
      if (data.page > data.pages && data.pages >= 1) {
        // 数据刷新后当前页已不存在：回退到有效页并重新请求，不伪造记录。
        historyQuery = historyQuery.copyWith(page: data.pages);
        await storage.saveHistoryQuery(historyQuery);
        data = await api.jobsPage(
          q: historyQuery.q,
          status: historyQuery.status,
          outcome: historyQuery.outcome,
          page: historyQuery.page,
          pageSize: 20,
        );
      }
      historyData = data;
      historyFromCache = false;
      historyError = null;
      _markOnline();
      await storage.saveCachedHistory(data.toJson());
    } catch (e) {
      if (!silent || historyData == null) {
        historyError = describeError(e);
      }
      if (e is ApiError && e.network) _markOffline(e.message);
    } finally {
      historyLoading = false;
      notifyListeners();
    }
  }

  /// 修改历史筛选并重新请求；筛选变化回到第 1 页。
  Future<void> setHistoryFilter({
    String? q,
    String? status,
    String? outcome,
    int? page,
  }) async {
    final next = historyQuery.copyWith(
      q: q,
      status: status,
      outcome: outcome,
      page:
          page ??
          (q != null || status != null || outcome != null
              ? 1
              : historyQuery.page),
    );
    if (next.q == historyQuery.q &&
        next.status == historyQuery.status &&
        next.outcome == historyQuery.outcome &&
        next.page == historyQuery.page) {
      return;
    }
    historyQuery = next;
    await storage.saveHistoryQuery(historyQuery);
    notifyListeners();
    await refreshHistory(silent: true);
  }

  /// 重置搜索与筛选。
  Future<void> resetHistoryFilter() async {
    historyQuery = const HistoryQueryState();
    await storage.saveHistoryQuery(historyQuery);
    notifyListeners();
    await refreshHistory();
  }

  void _syncPollers() {
    for (final job in runningJobs) {
      ensurePolling(job.id);
    }
    final id = selectedJobId;
    if (id != null && jobs[id]?.detail?.isRunning == true) {
      ensurePolling(id);
    }
  }

  void _startRunningTimer() {
    _runningTimer?.cancel();
    if (!_foreground || !configured) return;
    _runningTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (!_foreground) return;
      unawaited(refreshRunning(silent: true));
    });
  }

  // ============================================================
  // 任务操作
  // ============================================================
  JobSnapshot snapshotOf(String id) {
    var snapshot = jobs[id];
    if (snapshot == null) {
      snapshot = JobSnapshot(id);
      jobs[id] = snapshot;
    }
    return snapshot;
  }

  JobSnapshot? get selectedSnapshot =>
      selectedJobId == null ? null : jobs[selectedJobId!];

  /// 创建任务：必须显式提交用户所见模式。
  Future<String> createJob({required String desc, required String mode}) async {
    // 只记录长度与空白特征，不把需求原文写进日志（便于 E2E 核对「请求原文 vs 服务端 desc」）。
    final trimmed = desc.trim();
    _log(
      '提交需求：原文字符数=${desc.length}，裁剪后=${trimmed.length}，'
      '首尾有空白=${desc.length != trimmed.length}，内部换行=${'\n'.allMatches(desc).length}',
    );
    final result = await api.build(desc: desc, mode: mode);
    final id = result.id;
    if (id.isEmpty) {
      throw ApiError('服务端没有返回任务 ID', kind: ApiErrorKind.badResponse);
    }
    final now = DateTime.now().millisecondsSinceEpoch / 1000;
    final snapshot = snapshotOf(id);
    snapshot.detail = JobDetail(
      id: id,
      status: JobStatus.running,
      live: null,
      logs: const <LogEntry>[],
      result: null,
      desc: desc,
      startedAt: now,
      mode: result.mode.isEmpty ? mode : result.mode,
      modeSource: ModeSource.job,
      retryOf: null,
      outcome: null,
      outcomeSource: OutcomeSource.none,
      design: null,
      progress: null,
      stage: StageInfo.empty,
      views: const <String, String>{},
      thinking: null,
    );
    snapshot.logs = const <LogEntry>[];
    selectedJobId = id;
    await _rememberRecent(id);
    await storage.saveSelectedJobId(id);
    _markOnline();
    notifyListeners();
    snapshot.notifyListeners();
    ensurePolling(id);
    unawaited(refreshRunning(silent: true));
    return id;
  }

  /// 取消单个任务（不影响其他任务）；成功后立即更新本地状态。
  Future<void> cancelJob(String id) async {
    await api.cancel(id);
    snapshotOf(id).markCancelledLocally();
    _log('取消任务 $id');
    notifyListeners();
    unawaited(refreshRunning(silent: true));
  }

  /// 手动重试：服务端按原任务模式创建新任务。
  /// 同一任务的重试请求在途时会复用同一个 Future，避免快速连点创建多个真实任务。
  Future<String> retryJob(String id) {
    final inFlight = _retryRequests[id];
    if (inFlight != null) return inFlight;
    final future = _retryJobOnce(id);
    _retryRequests[id] = future;
    unawaited(
      future.then<void>(
        (_) => _retryRequests.remove(id),
        onError: (Object _) => _retryRequests.remove(id),
      ),
    );
    return future;
  }

  Future<String> _retryJobOnce(String id) async {
    final result = await api.retry(id);
    if (result.id.isEmpty) {
      throw ApiError('服务端没有返回新任务 ID', kind: ApiErrorKind.badResponse);
    }
    final newId = result.id;
    final source = jobs[id]?.detail;
    final snapshot = snapshotOf(newId);
    snapshot.detail = JobDetail(
      id: newId,
      status: JobStatus.running,
      live: null,
      logs: const <LogEntry>[],
      result: null,
      desc: source?.desc ?? '',
      startedAt: DateTime.now().millisecondsSinceEpoch / 1000,
      mode: result.mode.isEmpty ? (source?.mode ?? 'fidelity') : result.mode,
      modeSource: ModeSource.job,
      retryOf: id,
      outcome: null,
      outcomeSource: OutcomeSource.none,
      design: null,
      progress: null,
      stage: StageInfo.empty,
      views: const <String, String>{},
      thinking: null,
    );
    snapshot.logs = const <LogEntry>[];
    selectedJobId = newId;
    await _rememberRecent(newId);
    await storage.saveSelectedJobId(newId);
    notifyListeners();
    snapshot.notifyListeners();
    ensurePolling(newId);
    unawaited(refreshRunning(silent: true));
    _log('重试任务 $id → $newId mode=${result.mode}');
    return newId;
  }

  /// 拉取单个任务详情（不吞异常，供页面展示错误）。
  Future<JobDetail> fetchJob(String id) async {
    final snapshot = snapshotOf(id);
    snapshot.markLoading();
    notifyListeners();
    try {
      final detail = await api.job(id);
      snapshot.adopt(detail);
      snapshot.markFetched();
      _markOnline();
      if (detail.isRunning) {
        ensurePolling(id);
      } else {
        _stopPoller(id);
        unawaited(refreshRunning(silent: true));
        unawaited(refreshRecentDone());
        unawaited(refreshDoneWorks(silent: true));
      }
      _maybePersistDetail(detail);
      notifyListeners();
      return detail;
    } catch (e) {
      snapshot.markFetchError(e);
      if (e is ApiError && e.network) _markOffline(e.message);
      notifyListeners();
      rethrow;
    }
  }

  /// 确保任务详情已加载（同一任务并发调用只发一次请求，失败交给调用方展示）。
  Future<void> ensureJobLoaded(String id) {
    final existing = _jobLoadRequests[id];
    if (existing != null) return existing;
    final future = _loadJobOnce(id);
    _jobLoadRequests[id] = future;
    return future;
  }

  Future<void> _loadJobOnce(String id) async {
    try {
      await fetchJob(id);
    } finally {
      _jobLoadRequests.remove(id);
    }
  }

  /// 切换当前查看的任务（最近查看最多 5 个）。
  Future<void> selectJob(String? id) async {
    selectedJobId = id;
    await storage.saveSelectedJobId(id);
    if (id != null) {
      await _rememberRecent(id);
      final snapshot = jobs[id];
      if (snapshot == null || snapshot.detail == null || snapshot.stale) {
        unawaited(_loadJobQuietly(id));
      } else if (snapshot.detail!.isRunning) {
        ensurePolling(id);
      }
    }
    notifyListeners();
  }

  /// 后台安静加载（错误只记日志；快照 error 由页面展示，不产生未处理异步异常）。
  Future<void> _loadJobQuietly(String id) async {
    try {
      await ensureJobLoaded(id);
    } catch (e) {
      _log('加载任务 $id 失败：${describeError(e)}');
    }
  }

  Future<void> _rememberRecent(String id) async {
    recentIds.remove(id);
    recentIds.insert(0, id);
    if (recentIds.length > 5) recentIds = recentIds.sublist(0, 5);
    await storage.saveRecentJobIds(recentIds);
  }

  /// 最近查看任务（进行中任务单独分组，这里的列表仅「最近查看」）。
  List<JobSummary> get recentSummaries {
    final out = <JobSummary>[];
    for (final id in recentIds) {
      final detail = jobs[id]?.detail;
      if (detail != null) {
        out.add(JobSummary.fromDetail(detail));
      } else if (runningJobs.any((job) => job.id == id)) {
        out.add(runningJobs.firstWhere((job) => job.id == id));
      }
    }
    return out;
  }

  /// 需要展示的「最近 3 个已完成作品」。
  List<JobSummary> get recentDoneSummaries =>
      recentDone.take(3).toList(growable: false);

  /// 最近完成作品缓存（创作页空态用；失败时保留旧值并给出可重试错误）。
  List<JobSummary> recentDone = const <JobSummary>[];
  bool recentDoneLoading = false;
  String? recentDoneError;

  /// 拉取最近 3 个已完成作品（真实 /api/jobs 查询，不伪造）。
  Future<void> refreshRecentDone() async {
    if (!configured) return;
    recentDoneLoading = true;
    notifyListeners();
    try {
      final page = await api.jobsPage(
        status: JobStatus.done,
        page: 1,
        pageSize: 3,
      );
      recentDone = page.jobs;
      recentDoneError = null;
      _markOnline();
    } catch (e) {
      recentDoneError = describeError(e);
      if (e is ApiError && e.network) _markOffline(e.message);
    } finally {
      recentDoneLoading = false;
      notifyListeners();
    }
  }

  // ============================================================
  // 轮询
  // ============================================================
  /// 确保任务在轮询（每个任务独立轮询器，仅前台运行）。
  void ensurePolling(String id) {
    if (_disposed || !_foreground || !configured) return;
    if (_pollers.containsKey(id)) return;
    final snapshot = snapshotOf(id);
    final poller = JobPoller(
      id: id,
      fetch: () => api.job(id),
      onUpdate: (detail) {
        snapshot.adopt(detail);
        snapshot.markFetched();
        _markOnline();
        if (selectedJobId == id) {
          _maybePersistDetail(detail);
        }
        notifyListeners();
        if (detail.status != JobStatus.running) {
          unawaited(refreshRunning(silent: true));
          unawaited(refreshRecentDone());
          unawaited(refreshDoneWorks(silent: true));
        }
      },
      onError: (message) {
        snapshot.markFetchError(ApiError(message, network: true));
        _log('任务 $id 轮询停止：$message');
        notifyListeners();
      },
      onStop: () {
        _pollers.remove(id);
      },
    );
    _pollers[id] = poller;
    poller.start();
  }

  void _stopPoller(String id) {
    final poller = _pollers.remove(id);
    poller?.dispose();
  }

  void _pausePollers() {
    for (final poller in _pollers.values) {
      poller.dispose();
    }
    _pollers.clear();
  }

  void _maybePersistDetail(JobDetail detail) {
    final now = DateTime.now().millisecondsSinceEpoch / 1000;
    final last = _lastDetailPersist[detail.id] ?? 0;
    // 与“上一次落盘的状态”比较：adopt() 先更新了 jobs 里的状态，
    // 若再与缓存 detail 比较会恒等，导致终态不落盘。
    final changedState = _lastPersistedStatus[detail.id] != detail.status;
    if (!changedState && now - last < 5) return;
    _lastDetailPersist[detail.id] = now;
    _lastPersistedStatus[detail.id] = detail.status;
    unawaited(storage.saveCachedJobDetail(detail.id, detail.toJson()));
  }

  // ============================================================
  // 3D 产物
  // ============================================================
  /// 加载任务 3D 产物（模型 + 方案 + 零件目录），带缓存与并发去重。
  Future<StudioArtifacts> loadStudioArtifacts(String jobId) async {
    final inFlight = _artifactRequests[jobId];
    if (inFlight != null) return inFlight;
    final future = _loadStudioArtifactsImpl(jobId);
    _artifactRequests[jobId] = future;
    try {
      return await future;
    } finally {
      _artifactRequests.remove(jobId);
    }
  }

  Future<StudioArtifacts> _loadStudioArtifactsImpl(String jobId) async {
    final detail = jobs[jobId]?.detail;
    if (detail == null) {
      throw ApiError('任务详情尚未加载，请稍后重试', kind: ApiErrorKind.badResponse);
    }
    final result = detail.result;
    final modelPath = result?.modelPath;
    final solutionPath = result?.solutionPath;
    if (result == null || modelPath == null || solutionPath == null) {
      throw ApiError('该任务没有可展示的 3D 产物', kind: ApiErrorKind.badResponse);
    }
    final key = '$modelPath|$solutionPath|${parts.parts.length}';
    final cached = _artifactCache[jobId];
    if (cached != null && cached.key == key) return cached.artifacts;
    if (parts.parts.isEmpty) {
      await refreshParts();
      if (parts.parts.isEmpty) {
        throw ApiError(
          '零件目录为空：/api/parts 不可用，无法解算 3D 零件外观',
          kind: ApiErrorKind.badResponse,
        );
      }
    }
    final model = await api.model(modelPath);
    final solution = await api.solution(solutionPath);
    final artifacts = StudioArtifacts(
      model: model,
      solution: solution,
      parts: parts,
    );
    _artifactCache[jobId] = _ArtifactEntry(key, artifacts);
    _markOnline();
    notifyListeners();
    return artifacts;
  }

  /// 任务产物路径变化时使缓存失效（重新生成任务不会混用旧文件）。
  void invalidateArtifacts(String jobId) {
    _artifactCache.remove(jobId);
  }

  // ============================================================
  // 草稿与界面状态
  // ============================================================
  /// 更新需求草稿（内存立即生效，本地落盘去抖）。
  void setDraftDesc(String text) {
    draftDesc = text;
    _draftSaveTimer?.cancel();
    _draftSaveTimer = Timer(const Duration(milliseconds: 600), () {
      unawaited(storage.saveDraft(desc: draftDesc, mode: draftMode));
    });
  }

  /// 切换生成模式（只影响下一次新任务）。
  void setDraftMode(String mode) {
    draftMode = _normalizeMode(mode);
    notifyListeners();
    unawaited(storage.saveDraft(desc: draftDesc, mode: draftMode));
  }

  String _normalizeMode(String? mode) {
    final text = (mode ?? '').trim().toLowerCase();
    return (text == 'fast' || text == 'fidelity') ? text : 'fast';
  }

  // ============================================================
  // 作品页分段（进行中 / 已完成 / 全部记录）
  // ============================================================
  /// 分段默认值：有进行中任务默认「进行中」，否则「已完成」。
  String get defaultWorksSegment => hasRunning ? 'running' : 'done';

  /// 切换分段并保留用户上次选择。
  void setWorksSegment(String segment) {
    final next = switch (segment) {
      'running' || 'done' || 'all' => segment,
      _ => defaultWorksSegment,
    };
    worksSegmentRestored = true;
    if (next == worksSegment) {
      _saveUiStateDebounced();
      return;
    }
    worksSegment = next;
    _saveUiStateDebounced();
    notifyListeners();
  }

  /// 已完成分段数据（固定 status=done，独立分页）。
  HistoryPageData? doneData;
  bool doneLoading = false;
  String? doneError;
  int donePage = 1;

  /// 拉取「已完成」分页（真实 /api/jobs?status=done）。
  Future<void> refreshDoneWorks({bool silent = false}) async {
    if (_disposed || !configured) return;
    doneLoading = true;
    if (!silent) {
      doneError = null;
      notifyListeners();
    }
    try {
      var data = await api.jobsPage(
        status: JobStatus.done,
        page: donePage,
        pageSize: 20,
      );
      if (data.page > data.pages && data.pages >= 1) {
        // 当前页已不存在：回退到有效页重新请求，不伪造记录。
        donePage = data.pages;
        _saveUiStateDebounced();
        data = await api.jobsPage(
          status: JobStatus.done,
          page: donePage,
          pageSize: 20,
        );
      }
      doneData = data;
      doneError = null;
      _markOnline();
    } catch (e) {
      if (!silent || doneData == null) doneError = describeError(e);
      if (e is ApiError && e.network) _markOffline(e.message);
    } finally {
      doneLoading = false;
      if (!_disposed) notifyListeners();
    }
  }

  /// 切换「已完成」分段页码（边界按服务端真实 pages 判定）。
  Future<void> setDoneWorksPage(int page) async {
    final target = page < 1 ? 1 : page;
    if (target == donePage) return;
    donePage = target;
    _saveUiStateDebounced();
    notifyListeners();
    await refreshDoneWorks(silent: true);
  }

  /// 按当前分段刷新对应数据（作品页下拉刷新与分段切换共用）。
  Future<void> refreshWorksForSegment({bool silent = false}) async {
    switch (worksSegment) {
      case 'running':
        await refreshRunning(silent: silent);
      case 'done':
        await refreshDoneWorks(silent: silent);
      case 'all':
        await refreshHistory(silent: silent);
    }
  }

  // ============================================================
  // 拼装指导界面状态（视图 + 步数，按任务隔离并持久化）
  // ============================================================
  StudioUiState studioStateOf(String jobId) =>
      _studioStates[jobId] ?? const StudioUiState();

  void setStudioState(String jobId, StudioUiState state) {
    _studioStates[jobId] = state;
    _saveUiStateDebounced();
  }

  void _saveUiStateDebounced() {
    _uiStateSaveTimer?.cancel();
    _uiStateSaveTimer = Timer(const Duration(milliseconds: 400), () {
      final state = <String, dynamic>{
        'worksSegment': worksSegment,
        'donePage': donePage,
        'studio': {
          for (final entry in _studioStates.entries)
            entry.key: entry.value.toJson(),
        },
      };
      unawaited(storage.saveUiState(state));
    });
  }

  void _loadUiState(Map<String, dynamic> raw) {
    final segment = raw['worksSegment']?.toString();
    if (segment == 'running' || segment == 'done' || segment == 'all') {
      worksSegment = segment!;
      worksSegmentRestored = true;
    }
    final rawDonePage = raw['donePage'];
    if (rawDonePage is int && rawDonePage >= 1) {
      donePage = rawDonePage;
    } else if (rawDonePage is String) {
      final parsed = int.tryParse(rawDonePage);
      if (parsed != null && parsed >= 1) donePage = parsed;
    }
    final studio = raw['studio'];
    if (studio is Map) {
      for (final entry in studio.entries) {
        _studioStates[entry.key.toString()] = StudioUiState.fromJson(
          entry.value,
        );
      }
    }
  }

  // ============================================================
  // 连接状态与调试
  // ============================================================
  void _markOnline() {
    final changed =
        connection != ServiceConnection.online || lastNetworkError != null;
    connection = ServiceConnection.online;
    lastNetworkError = null;
    if (changed) notifyListeners();
  }

  void _markOffline(String message) {
    connection = ServiceConnection.offline;
    lastNetworkError = message;
    notifyListeners();
  }

  void _log(String message) {
    final line = '[${DateTime.now().toIso8601String()}] $message';
    debugLog.add(line);
    if (debugLog.length > 200) debugLog.removeAt(0);
    debugPrint('[state] $message');
  }

  /// 生成本地诊断摘要（设置页展示；不含令牌与需求内容）。
  String get diagnostics {
    final buffer = StringBuffer()
      ..writeln('服务地址：${address?.url ?? '未配置'}')
      ..writeln('鉴权：${hasToken ? '已配置令牌' : '未配置令牌'}')
      ..writeln('连接状态：${connection.name}')
      ..writeln('API 版本：${api.lastApiVersion ?? '-'}')
      ..writeln('最近同步：${lastSyncAt == null ? '-' : fmtDateTime(lastSyncAt)}')
      ..writeln('进行中任务：${runningJobs.length}')
      ..writeln('任务快照缓存：${jobs.length}')
      ..writeln('零件变体：${parts.parts.length}');
    return buffer.toString();
  }

  /// 编码调试日志（设置页导出/证据用）。
  String exportDebugLog() => debugLog.join('\n');

  // 兼容导出：部分页面按需使用 jsonEncode（例如复制诊断信息）。
  String encodeJson(Object? value) => jsonEncode(value);
}
