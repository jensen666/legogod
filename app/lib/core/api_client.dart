// 统一 API 客户端：页面唯一网络入口。
// - Base URL 规范化、API 路径拼接、产物 URL（/files、/views、/viz）解析；
// - Bearer 令牌只放内存/安全存储，绝不写日志、URL 或证据；
// - 每个请求生成 X-Request-ID，读取 X-LEGOGOD-API-Version 与 X-Request-ID 响应头；
// - 网络错误（不可达/超时）与业务错误（4xx/5xx、body 内 error）统一为 ApiError；
// - 日志只打印方法、无查询串路径、状态码、耗时与 requestId。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/api_error.dart';
import '../models/artifacts.dart';
import '../models/job.dart';
import '../models/part.dart';
import 'service_address.dart';

/// 创建/重试任务的响应。
class CreateJobResult {
  const CreateJobResult({required this.id, required this.mode});

  final String id;
  final String mode;

  factory CreateJobResult.fromJson(Object? raw) {
    final map = raw is Map ? raw : const <String, dynamic>{};
    return CreateJobResult(
      id: map['id']?.toString() ?? '',
      mode: map['mode']?.toString() ?? 'fidelity',
    );
  }
}

/// LEGOGOD API 客户端。
class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String _baseUrl = '';
  String? _token;
  final Random _random = Random();

  /// 最近一次响应头里的 API 版本（仅用于诊断，不参与业务分支）。
  int? lastApiVersion;

  /// 最近一次响应的 requestId（错误消息已单独携带，这里供日志关联）。
  String? lastRequestId;

  static const String apiVersionHeader = 'X-LEGOGOD-API-Version';
  static const String requestIdHeader = 'X-Request-ID';

  /// 当前配置的 Base URL（空串表示未配置）。
  String get baseUrl => _baseUrl;

  /// 是否已配置服务地址。
  bool get configured => _baseUrl.isNotEmpty;

  /// 是否配置了令牌（不返回令牌内容）。
  bool get hasToken => _token != null && _token!.isNotEmpty;

  /// 配置服务地址与令牌；令牌只保存在内存，调用方负责安全持久化。
  void configure({required String baseUrl, String? token}) {
    _baseUrl = baseUrl;
    final trimmed = token?.trim() ?? '';
    _token = trimmed.isEmpty ? null : trimmed;
  }

  /// 清空配置（切换服务前调用，避免把不同服务的数据混用）。
  void clear() {
    _baseUrl = '';
    _token = null;
  }

  /// 释放底层 HTTP 连接。
  void close() {
    _client.close();
  }

  // ---------- URL 解析 ----------
  /// 拼接 API 路径（path 必须以 / 开头）。
  Uri resolve(String path, [Map<String, String>? query]) {
    if (_baseUrl.isEmpty) {
      throw ApiError('尚未配置服务地址', code: 'no_base_url', kind: ApiErrorKind.badResponse);
    }
    final text = '$_baseUrl$path';
    final uri = Uri.tryParse(text);
    if (uri == null) {
      throw ApiError('服务地址无法拼接请求 URL：$path', kind: ApiErrorKind.badResponse);
    }
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: query);
  }

  /// 产物 URL：kind ∈ files|views|viz；name 为服务端下发的相对文件名。
  /// 已是绝对 URL 的值原样返回（历史兼容）；绝不把令牌放进 URL。
  String artifactUrl(String kind, String name) {
    const kinds = {'files', 'views', 'viz'};
    if (!kinds.contains(kind)) {
      throw ArgumentError.value(kind, 'kind', '产物类型必须是 files/views/viz');
    }
    final text = name.trim();
    if (text.isEmpty) throw ArgumentError('产物文件名不能为空');
    if (text.startsWith('http://') || text.startsWith('https://')) return text;
    if (text.contains('/') || text.contains(r'\')) {
      throw ArgumentError('产物文件名只能是服务端返回的相对名称：$name');
    }
    if (_baseUrl.isEmpty) {
      throw ApiError('尚未配置服务地址，无法解析产物地址', kind: ApiErrorKind.badResponse);
    }
    return '$_baseUrl/$kind/${Uri.encodeComponent(text)}';
  }

  /// 把服务端下发的相对产物路径（如 /views/x.png、/files/y.json）解析成绝对 URL。
  /// 已是绝对 http(s) URL 的值保持不变；其它形态按错误处理，不猜测主机。
  String absoluteUrl(String pathOrUrl) {
    final text = pathOrUrl.trim();
    if (text.startsWith('http://') || text.startsWith('https://')) return text;
    if (_baseUrl.isEmpty) {
      throw ApiError('尚未配置服务地址，无法解析产物地址', kind: ApiErrorKind.badResponse);
    }
    if (text.startsWith('/')) return '$_baseUrl$text';
    throw ApiError('产物路径不合法：$pathOrUrl', kind: ApiErrorKind.badResponse);
  }

  /// 评审批量图片请求头：服务端产物路由默认开放，但同源反向代理可能要求令牌，
  /// 因此配置了令牌时一并携带；令牌只进请求头，不进 URL。
  Map<String, String> get artifactHeaders =>
      hasToken ? {'Authorization': 'Bearer $_token'} : const <String, String>{};

  /// 生成合法请求 ID：只用于故障关联，不含需求、模型输出或令牌。
  String newRequestId() {
    final stamp = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
    final rand = List.generate(8, (_) => _random.nextInt(16).toRadixString(16)).join();
    return 'lg-$stamp-$rand';
  }

  // ---------- 业务接口 ----------
  /// 健康检查（公开接口）：网络 / HTTP 状态 / API 版本 / 服务可用性。
  Future<HealthInfo> health() async {
    final stopwatch = Stopwatch()..start();
    final map = await _getJson('/api/health', timeout: const Duration(seconds: 5));
    stopwatch.stop();
    final headerVersion = _headerVersion;
    return HealthInfo.fromJson(
      map,
      headerVersion: headerVersion,
      requestId: lastRequestId,
      latencyMs: stopwatch.elapsedMilliseconds,
    );
  }

  /// 零件目录（公开接口，唯一数据源）。
  Future<PartsCatalog> parts() async {
    final map = await _getJson('/api/parts', timeout: const Duration(seconds: 15));
    return PartsCatalog.fromJson(map['parts']);
  }

  /// 历史任务分页（受令牌保护）。
  Future<HistoryPageData> jobsPage({
    String q = '',
    String status = '',
    String outcome = '',
    int page = 1,
    int pageSize = 20,
  }) async {
    final query = <String, String>{
      'page': '$page',
      'pageSize': '$pageSize',
    };
    if (q.trim().isNotEmpty) query['q'] = q.trim();
    if (status.isNotEmpty) query['status'] = status;
    if (outcome.isNotEmpty) query['outcome'] = outcome;
    final map = await _getJson('/api/jobs', query: query,
        timeout: const Duration(seconds: 10));
    return HistoryPageData.fromJson(map);
  }

  /// 单任务详情（受令牌保护，实时通道按任务独立轮询）。
  Future<JobDetail> job(String id) async {
    final map = await _getJson('/api/job/${Uri.encodeComponent(id)}',
        timeout: const Duration(seconds: 10));
    return JobDetail.fromJson(map);
  }

  /// 创建任务：必须显式提交用户所见 mode（fast|fidelity）。
  Future<CreateJobResult> build({required String desc, required String mode}) async {
    final map = await _postJson(
      '/api/build',
      body: {'desc': desc, 'mode': mode},
      timeout: const Duration(seconds: 30),
    );
    return CreateJobResult.fromJson(map);
  }

  /// 手动重试：新任务由服务端按原任务模式创建。
  Future<CreateJobResult> retry(String jobId) async {
    final map = await _postJson(
      '/api/retry',
      body: {'jobId': jobId},
      timeout: const Duration(seconds: 15),
    );
    return CreateJobResult.fromJson(map);
  }

  /// 取消任务（DELETE /api/job/{id}）。
  Future<void> cancel(String id) async {
    await _delete('/api/job/${Uri.encodeComponent(id)}',
        timeout: const Duration(seconds: 10));
  }

  /// 读取设计模型 JSON（/files/{name}）。
  Future<ModelData> model(String name) async {
    final map = await _getJsonUrl(artifactUrl('files', name),
        timeout: const Duration(seconds: 20));
    return ModelData.fromJson(map);
  }

  /// 读取装配方案 JSON（/files/{name}）。
  Future<SolutionData> solution(String name) async {
    final map = await _getJsonUrl(artifactUrl('files', name),
        timeout: const Duration(seconds: 20));
    return SolutionData.fromJson(map);
  }

  /// 读取任意产物文本（步骤 Markdown / JSON 原文）。
  Future<String> artifactText(String kind, String name) async {
    final bytes = await _getBytes(artifactUrl(kind, name),
        timeout: const Duration(seconds: 30));
    return utf8.decode(bytes, allowMalformed: true);
  }

  /// 读取任意产物字节（下载保存/分享）。
  Future<List<int>> artifactBytes(String kind, String name) =>
      _getBytes(artifactUrl(kind, name), timeout: const Duration(seconds: 30));

  /// 连接测试：健康 → 零件目录 → 鉴权（GET /api/jobs?page=1&pageSize=1）。
  /// 使用传入的地址/令牌，不修改当前客户端配置。
  Future<ConnectionCheck> checkConnection({
    required String baseUrl,
    String? token,
    bool checkParts = true,
  }) async {
    final cleanToken = token?.trim() ?? '';
    final effectiveToken = cleanToken.isEmpty ? null : cleanToken;
    final stopwatch = Stopwatch()..start();
    HealthInfo health;
    try {
      health = await _healthWith(baseUrl, effectiveToken);
    } catch (e) {
      stopwatch.stop();
      return ConnectionCheck(
        baseUrl: baseUrl,
        healthOk: false,
        apiVersion: 0,
        status: '',
        latencyMs: stopwatch.elapsedMilliseconds,
        error: _describe(e),
        apiVersionCompatible: false,
      );
    }
    final versionOk = health.apiVersion == 1 &&
        (health.headerVersion == null || health.headerVersion == 1);
    int? partsCount;
    if (checkParts) {
      try {
        final catalog = await _partsWith(baseUrl, effectiveToken);
        partsCount = catalog.variantCount;
      } catch (e) {
        return ConnectionCheck(
          baseUrl: baseUrl,
          healthOk: true,
          apiVersion: health.apiVersion,
          status: health.status,
          latencyMs: health.latencyMs,
          checkedParts: true,
          error: '零件目录读取失败：${_describe(e)}',
          apiVersionCompatible: versionOk,
        );
      }
    }
    final needsAuth = (effectiveToken != null) || !_isLoopbackHost(baseUrl);
    var authChecked = false;
    var authOk = false;
    String? authError;
    if (needsAuth) {
      authChecked = true;
      try {
        await _jobsProbeWith(baseUrl, effectiveToken);
        authOk = true;
      } catch (e) {
        authError = _describe(e);
      }
    }
    return ConnectionCheck(
      baseUrl: baseUrl,
      healthOk: true,
      apiVersion: health.apiVersion,
      status: health.status,
      latencyMs: health.latencyMs,
      partsCount: partsCount,
      checkedParts: checkParts,
      authChecked: authChecked,
      authOk: authOk,
      authError: authError,
      apiVersionCompatible: versionOk,
      error: versionOk ? null : '服务 API 版本不兼容：需要 v1，实际 v${health.apiVersion}',
    );
  }

  // ---------- 内部实现 ----------
  int? _headerVersion;

  Future<HealthInfo> _healthWith(String baseUrl, String? token) async {
    final stopwatch = Stopwatch()..start();
    final map = await _getJson('/api/health',
        baseUrl: baseUrl, token: token, timeout: const Duration(seconds: 5));
    stopwatch.stop();
    return HealthInfo.fromJson(
      map,
      headerVersion: _headerVersion,
      requestId: lastRequestId,
      latencyMs: stopwatch.elapsedMilliseconds,
    );
  }

  Future<PartsCatalog> _partsWith(String baseUrl, String? token) async {
    final map = await _getJson('/api/parts',
        baseUrl: baseUrl, token: token, timeout: const Duration(seconds: 15));
    return PartsCatalog.fromJson(map['parts']);
  }

  Future<void> _jobsProbeWith(String baseUrl, String? token) async {
    await _getJson('/api/jobs',
        baseUrl: baseUrl,
        token: token,
        query: const {'page': '1', 'pageSize': '1'},
        timeout: const Duration(seconds: 10));
  }

  /// 是否回环主机：复用 ServiceAddress 的 IP 级判断，避免 `127.example.com`
  /// 这类域名被字符串前缀误判为回环而跳过鉴权探测。
  bool _isLoopbackHost(String baseUrl) {
    return ServiceAddress.parse(baseUrl).address?.isLoopback ?? false;
  }

  Future<Map<String, dynamic>> _getJson(
    String path, {
    String? baseUrl,
    String? token,
    Map<String, String>? query,
    required Duration timeout,
  }) async {
    final uri = _buildUri(baseUrl ?? _baseUrl, path, query);
    final body = await _send(
      method: 'GET',
      uri: uri,
      token: token ?? _token,
      timeout: timeout,
    );
    final decoded = _decodeJsonSafe(body, what: '服务端');
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiError('服务端响应不是 JSON 对象（可能不是 LEGOGOD API 服务）',
        kind: ApiErrorKind.badResponse, requestId: lastRequestId);
  }

  Future<Map<String, dynamic>> _getJsonUrl(String url, {required Duration timeout}) async {
    final uri = Uri.tryParse(url);
    if (uri == null) {
      throw ApiError('产物地址不合法：$url', kind: ApiErrorKind.badResponse);
    }
    final body = await _send(method: 'GET', uri: uri, token: _token, timeout: timeout);
    final decoded = _decodeJsonSafe(body, what: '产物');
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiError('产物不是 JSON 对象：$url',
        kind: ApiErrorKind.badResponse, requestId: lastRequestId);
  }

  Future<Map<String, dynamic>> _postJson(
    String path, {
    required Map<String, dynamic> body,
    required Duration timeout,
  }) async {
    final uri = _buildUri(_baseUrl, path, null);
    final bytes = utf8.encode(jsonEncode(body));
    final responseBody = await _send(
      method: 'POST',
      uri: uri,
      token: _token,
      timeout: timeout,
      body: bytes,
      contentType: 'application/json',
    );
    final decoded = _decodeJsonSafe(responseBody, what: '服务端');
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiError('服务端响应不是 JSON 对象',
        kind: ApiErrorKind.badResponse, requestId: lastRequestId);
  }

  Future<void> _delete(String path, {required Duration timeout}) async {
    final uri = _buildUri(_baseUrl, path, null);
    await _send(method: 'DELETE', uri: uri, token: _token, timeout: timeout);
  }

  Future<List<int>> _getBytes(String url, {required Duration timeout}) async {
    final uri = Uri.tryParse(url);
    if (uri == null) {
      throw ApiError('产物地址不合法：$url', kind: ApiErrorKind.badResponse);
    }
    return _send(method: 'GET', uri: uri, token: _token, timeout: timeout);
  }

  Uri _buildUri(String baseUrl, String path, Map<String, String>? query) {
    if (baseUrl.isEmpty) {
      throw ApiError('尚未配置服务地址', code: 'no_base_url', kind: ApiErrorKind.badResponse);
    }
    final uri = Uri.tryParse('$baseUrl$path');
    if (uri == null) throw ApiError('请求地址不合法：$path', kind: ApiErrorKind.badResponse);
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: query);
  }

  /// 统一发送请求：超时/网络错误/HTTP 错误/2xx 内嵌 error 全部转为 ApiError。
  Future<List<int>> _send({
    required String method,
    required Uri uri,
    required String? token,
    required Duration timeout,
    List<int>? body,
    String? contentType,
  }) async {
    final request = http.Request(method, uri);
    final requestId = newRequestId();
    request.headers['Accept'] = 'application/json';
    request.headers[requestIdHeader] = requestId;
    if (token != null && token.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    if (contentType != null) request.headers['Content-Type'] = contentType;
    if (body != null) request.bodyBytes = body;

    final safePath = uri.path;
    final stopwatch = Stopwatch()..start();
    debugPrint('[api] → $method $safePath rid=$requestId');
    http.StreamedResponse response;
    try {
      final streamed = await _client.send(request).timeout(timeout);
      response = streamed;
      final bytes = await response.stream.toBytes().timeout(timeout);
      stopwatch.stop();
      _captureHeaders(response, requestId);
      debugPrint(
          '[api] ← ${response.statusCode} $method $safePath ${stopwatch.elapsedMilliseconds}ms rid=$requestId');
      _throwIfError(response.statusCode, bytes, requestId);
      return bytes;
    } on TimeoutException {
      stopwatch.stop();
      debugPrint('[api] 超时 $method $safePath ${timeout.inMilliseconds}ms rid=$requestId');
      throw ApiError('API 请求超时（${_originLabel(uri)}，${timeout.inMilliseconds}ms）',
          network: true, kind: ApiErrorKind.timeout, requestId: requestId);
    } on SocketException catch (e) {
      stopwatch.stop();
      debugPrint('[api] 网络失败 $method $safePath rid=$requestId: ${e.osError?.message ?? e.message}');
      throw ApiError('无法连接 API 服务（${_originLabel(uri)}）：${e.osError?.message ?? e.message}',
          network: true, kind: ApiErrorKind.network, requestId: requestId);
    } on HandshakeException catch (e) {
      stopwatch.stop();
      debugPrint('[api] TLS 失败 $method $safePath rid=$requestId: $e');
      throw ApiError('HTTPS 证书校验失败（${_originLabel(uri)}）：${e.message}',
          network: true, kind: ApiErrorKind.network, requestId: requestId);
    } on http.ClientException catch (e) {
      stopwatch.stop();
      debugPrint('[api] 连接中断 $method $safePath rid=$requestId: ${e.message}');
      throw ApiError('无法连接 API 服务（${_originLabel(uri)}）：${e.message}',
          network: true, kind: ApiErrorKind.network, requestId: requestId);
    }
  }

  void _captureHeaders(http.StreamedResponse response, String requestId) {
    final version = int.tryParse(_headerValue(response, apiVersionHeader) ?? '');
    _headerVersion = version;
    if (version != null) lastApiVersion = version;
    final rid = _headerValue(response, requestIdHeader);
    lastRequestId = (rid != null && rid.isNotEmpty) ? rid : requestId;
  }

  /// 大小写不敏感地读取响应头（Dart http 包不同实现保留的键大小写不一致）。
  String? _headerValue(http.StreamedResponse response, String name) {
    final direct = response.headers[name];
    if (direct != null) return direct;
    final lower = name.toLowerCase();
    for (final entry in response.headers.entries) {
      if (entry.key.toLowerCase() == lower) return entry.value;
    }
    return null;
  }

  void _throwIfError(int status, List<int> bytes, String requestId) {
    Map<String, dynamic>? body;
    try {
      final decoded = _decodeJson(bytes);
      if (decoded is Map<String, dynamic>) body = decoded;
    } catch (_) {
      body = null;
    }
    final serverError = body?['error'];
    final hasError = serverError is String && serverError.isNotEmpty;
    if (status >= 200 && status < 300 && !hasError) return;
    final code = body?['code'];
    final requestIdInBody = body?['requestId'];
    if (body == null && status < 400) {
      throw ApiError('服务端响应不是合法 JSON（可能不是 LEGOGOD API 服务）',
          status: status,
          code: 'bad_json',
          requestId: requestId,
          kind: ApiErrorKind.badResponse);
    }
    final message = hasError ? serverError : 'HTTP $status';
    throw ApiError(message,
        status: status,
        code: code is String ? code : null,
        requestId: requestIdInBody is String ? requestIdInBody : requestId,
        kind: ApiErrorKind.server);
  }

  Object? _decodeJson(List<int> bytes) {
    if (bytes.isEmpty) return const <String, dynamic>{};
    final text = utf8.decode(bytes, allowMalformed: true);
    if (text.trim().isEmpty) return const <String, dynamic>{};
    return jsonDecode(text);
  }

  /// 安全解码：非法 JSON 统一转成可展示的 ApiError（badResponse），不把 FormatException 抛给页面。
  Object? _decodeJsonSafe(List<int> bytes, {required String what}) {
    try {
      return _decodeJson(bytes);
    } on FormatException catch (e) {
      throw ApiError('$what响应不是合法 JSON（可能不是 LEGOGOD API 服务）：${e.message}',
          kind: ApiErrorKind.badResponse, requestId: lastRequestId);
    }
  }

  String _originLabel(Uri uri) {
    final port = uri.hasPort ? ':${uri.port}' : '';
    return '${uri.scheme}://${uri.host}$port';
  }

  String _describe(Object error) {
    if (error is ApiError) {
      final bits = StringBuffer(error.message);
      if (error.code != null && error.code!.isNotEmpty) {
        bits.write('（${error.code}）');
      }
      return bits.toString();
    }
    return error.toString();
  }
}
