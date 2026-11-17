// 本地存储：只保存服务地址、必要凭据、草稿、缓存与少量界面状态。
// - 令牌只进系统安全存储（Android Keystore），绝不进普通偏好、日志或证据；
// - 缓存带服务标识，切换服务后必须清空，禁止把不同服务的任务/产物混用；
// - 所有读取对损坏数据容错，升级字段用版本化 key。
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 历史查询状态（页面切换/重启后恢复）。
class HistoryQueryState {
  const HistoryQueryState({
    this.q = '',
    this.status = '',
    this.outcome = '',
    this.page = 1,
  });

  final String q;
  final String status;
  final String outcome;
  final int page;

  HistoryQueryState copyWith({
    String? q,
    String? status,
    String? outcome,
    int? page,
  }) {
    return HistoryQueryState(
      q: q ?? this.q,
      status: status ?? this.status,
      outcome: outcome ?? this.outcome,
      page: page ?? this.page,
    );
  }

  Map<String, dynamic> toJson() => {
    'q': q,
    'status': status,
    'outcome': outcome,
    'page': page,
  };

  factory HistoryQueryState.fromJson(Object? raw) {
    if (raw is! Map) return const HistoryQueryState();
    int page = 1;
    final rawPage = raw['page'];
    if (rawPage is int) page = rawPage;
    if (rawPage is String) page = int.tryParse(rawPage) ?? 1;
    return HistoryQueryState(
      q: raw['q']?.toString() ?? '',
      status: raw['status']?.toString() ?? '',
      outcome: raw['outcome']?.toString() ?? '',
      page: page < 1 ? 1 : page,
    );
  }
}

/// 拼装指导界面状态（视图 + 当前步数，按任务隔离并持久化）。
class StudioUiState {
  const StudioUiState({this.tab = 'sim', this.step = 0});

  /// 视图：sim（模拟）/ steps（分层步骤）。
  final String tab;
  final int step;

  Map<String, dynamic> toJson() => {'tab': tab, 'step': step};

  factory StudioUiState.fromJson(Object? raw) {
    if (raw is! Map) return const StudioUiState();
    final step = raw['step'];
    // 兼容旧版本持久化值：work/model/build 归入「模拟」，steps 归入「分层步骤」。
    final rawTab = raw['tab']?.toString() ?? 'sim';
    final tab = switch (rawTab) {
      'steps' => 'steps',
      'sim' || 'work' || 'model' || 'build' => 'sim',
      _ => 'sim',
    };
    return StudioUiState(
      tab: tab,
      step: step is int ? step : (step is String ? int.tryParse(step) ?? 0 : 0),
    );
  }
}

/// 访问令牌存储抽象：生产环境用系统安全存储；测试可注入内存实现，
/// 避免测试环境没有平台插件时挂起（令牌仍不会落明文偏好）。
abstract class TokenStore {
  Future<String?> read();
  Future<bool> write(String? token);
}

/// 系统安全存储实现（Android Keystore / iOS Keychain）。
class SecureTokenStore implements TokenStore {
  SecureTokenStore({FlutterSecureStorage? secure})
    : _secure = secure ?? const FlutterSecureStorage();

  static const _kToken = 'legogod.v1.apiToken';
  final FlutterSecureStorage _secure;

  @override
  Future<String?> read() async {
    try {
      final value = await _secure.read(key: _kToken);
      return (value == null || value.isEmpty) ? null : value;
    } catch (e) {
      debugPrint('[storage] 安全存储读取失败（令牌不可用，不会回退到明文存储）');
      return null;
    }
  }

  @override
  Future<bool> write(String? token) async {
    try {
      if (token == null || token.isEmpty) {
        await _secure.delete(key: _kToken);
      } else {
        await _secure.write(key: _kToken, value: token);
      }
      return true;
    } catch (e) {
      debugPrint('[storage] 安全存储写入失败（令牌只保留在本次运行内存中）');
      return false;
    }
  }
}

/// 纯内存令牌存储（仅用于测试）。
class MemoryTokenStore implements TokenStore {
  MemoryTokenStore([this._token]);

  String? _token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<bool> write(String? token) async {
    _token = token;
    return true;
  }
}

/// 本地存储门面。
class AppStorage {
  AppStorage({FlutterSecureStorage? secure, TokenStore? tokenStore})
    : _tokenStore = tokenStore ?? SecureTokenStore(secure: secure);

  static const _p = 'legogod.v1.';
  static const _kBaseUrl = '${_p}baseUrl';
  static const _kDraft = '${_p}draft';
  static const _kRecent = '${_p}recent';
  static const _kSelected = '${_p}selectedJob';
  static const _kHistoryQuery = '${_p}historyQuery';
  static const _kCachedHistory = '${_p}cachedHistory';
  static const _kCachedParts = '${_p}cachedParts';
  static const _kCachedDetails = '${_p}cachedDetails';
  static const _kUiState = '${_p}uiState';
  static const _kServiceKey = '${_p}serviceKey';
  static const _kLastSync = '${_p}lastSyncAt';

  final TokenStore _tokenStore;
  SharedPreferences? _prefs;

  /// 缓存详情保留的任务数上限（控制存储与启动恢复成本）。
  static const int maxCachedDetails = 3;

  /// 初始化偏好存储；安全存储按需惰性访问。
  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  SharedPreferences get _store {
    final prefs = _prefs;
    if (prefs == null) throw StateError('AppStorage 尚未初始化');
    return prefs;
  }

  String? _readString(String key) => _store.getString(key);

  Future<void> _writeString(String key, String? value) async {
    if (value == null || value.isEmpty) {
      await _store.remove(key);
    } else {
      await _store.setString(key, value);
    }
  }

  Map<String, dynamic>? _readMap(String key) {
    final raw = _readString(key);
    if (raw == null || raw.isEmpty) return null;
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (e) {
      debugPrint('[storage] 缓存 JSON 损坏，已忽略：$key');
      return null;
    }
  }

  Future<void> _writeMap(String key, Map<String, dynamic>? value) async {
    await _writeString(key, value == null ? null : jsonEncode(value));
  }

  // ---------- 服务地址与令牌 ----------
  String? get baseUrl => _readString(_kBaseUrl);

  Future<void> saveBaseUrl(String? url) => _writeString(_kBaseUrl, url);

  /// 缓存当前服务标识（用于识别缓存是否属于同一个服务）。
  String? get cachedServiceKey => _readString(_kServiceKey);

  Future<void> saveCachedServiceKey(String? key) =>
      _writeString(_kServiceKey, key);

  /// 读取访问令牌（安全存储）；失败返回 null 并记录不含令牌的警告。
  Future<String?> readToken() => _tokenStore.read();

  /// 写入/清除访问令牌（安全存储）；失败时只影响持久化，运行时内存仍可用。
  Future<bool> saveToken(String? token) => _tokenStore.write(token);

  // ---------- 创作草稿 ----------
  Map<String, dynamic>? get draft => _readMap(_kDraft);

  Future<void> saveDraft({required String desc, required String mode}) =>
      _writeMap(_kDraft, {'desc': desc, 'mode': mode});

  // ---------- 最近查看与选中任务 ----------
  List<String> get recentJobIds {
    final raw = _readString(_kRecent);
    if (raw == null || raw.isEmpty) return const <String>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const <String>[];
      return [for (final item in decoded) item.toString()];
    } catch (e) {
      return const <String>[];
    }
  }

  Future<void> saveRecentJobIds(List<String> ids) =>
      _writeString(_kRecent, jsonEncode(ids.take(5).toList()));

  String? get selectedJobId => _readString(_kSelected);

  Future<void> saveSelectedJobId(String? id) => _writeString(_kSelected, id);

  // ---------- 历史查询状态 ----------
  HistoryQueryState get historyQuery =>
      HistoryQueryState.fromJson(_readMap(_kHistoryQuery));

  Future<void> saveHistoryQuery(HistoryQueryState query) =>
      _writeMap(_kHistoryQuery, query.toJson());

  // ---------- 数据缓存（带服务标识） ----------
  Map<String, dynamic>? get cachedHistory => _readMap(_kCachedHistory);

  Future<void> saveCachedHistory(Map<String, dynamic>? raw) =>
      _writeMap(_kCachedHistory, raw);

  Map<String, dynamic>? get cachedParts => _readMap(_kCachedParts);

  Future<void> saveCachedParts(Map<String, dynamic>? raw) =>
      _writeMap(_kCachedParts, raw);

  Map<String, dynamic> get cachedDetails =>
      _readMap(_kCachedDetails) ?? const {};

  /// 保存单个任务详情缓存（保留最近 [maxCachedDetails] 个）。
  Future<void> saveCachedJobDetail(String id, Map<String, dynamic> raw) async {
    final all = <String, dynamic>{...cachedDetails};
    all.remove(id);
    all[id] = {'savedAt': DateTime.now().millisecondsSinceEpoch, 'detail': raw};
    final sorted = all.entries.toList()
      ..sort((a, b) {
        final ta = (a.value is Map ? a.value['savedAt'] : 0) as num? ?? 0;
        final tb = (b.value is Map ? b.value['savedAt'] : 0) as num? ?? 0;
        return tb.compareTo(ta);
      });
    final kept = <String, dynamic>{
      for (final entry in sorted.take(maxCachedDetails)) entry.key: entry.value,
    };
    await _writeMap(_kCachedDetails, kept);
  }

  double? get lastSyncAt {
    final raw = _readString(_kLastSync);
    if (raw == null) return null;
    return double.tryParse(raw);
  }

  Future<void> saveLastSyncAt(double? ts) =>
      _writeString(_kLastSync, ts?.toString());

  // ---------- 界面状态 ----------
  Map<String, dynamic> get uiState => _readMap(_kUiState) ?? const {};

  Future<void> saveUiState(Map<String, dynamic> state) =>
      _writeMap(_kUiState, state);

  /// 切换服务时清空该服务相关的缓存与选中状态（保留用户草稿）。
  Future<void> clearServiceCaches() async {
    await _writeString(_kCachedHistory, null);
    await _writeString(_kCachedParts, null);
    await _writeString(_kCachedDetails, null);
    await _writeString(_kSelected, null);
    await _writeString(_kRecent, null);
    await _writeString(_kLastSync, null);
    await _writeString(_kHistoryQuery, null);
    await _writeString(_kUiState, null);
    await _writeString(_kServiceKey, null);
  }
}
