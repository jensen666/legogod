// 组件测试共用底座：可控 MockClient 后端、AppState 装配与常用断言辅助。
// 所有响应均使用真实契约字段（/api/health、/api/parts、/api/jobs、/api/job/{id}、
// /files/{name}、/api/build、/api/retry、DELETE /api/job/{id}），不发真实网络请求。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:legogod_app/app_scope.dart';
import 'package:legogod_app/core/api_client.dart';
import 'package:legogod_app/core/app_state.dart';
import 'package:legogod_app/core/job_snapshot.dart';
import 'package:legogod_app/core/service_address.dart';
import 'package:legogod_app/core/storage.dart';
import 'package:legogod_app/core/theme.dart';
import 'package:legogod_app/models/job.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 测试服务地址（回环地址，无需令牌即可通过连接检查）。
const String testBaseUrl = 'http://127.0.0.1:8600';

/// 统一 JSON 响应头（含 API 版本，便于真实解析路径）。
Map<String, String> jsonHeaders() => <String, String>{
      'content-type': 'application/json; charset=utf-8',
      'x-legogod-api-version': '1',
      'x-request-id': 'test-rid',
    };

/// 任务分页响应（/api/jobs 真实契约字段）。
Map<String, dynamic> jobsPageBody({
  List<Map<String, Object?>> jobs = const <Map<String, Object?>>[],
  int total = 0,
  int page = 1,
  int pages = 1,
  List<Map<String, Object?>> running = const <Map<String, Object?>>[],
}) {
  return <String, dynamic>{
    'jobs': jobs,
    'total': total,
    'page': page,
    'pageSize': 20,
    'pages': pages,
    'running': running,
  };
}

/// 可控测试后端：记录请求，并允许按用例替换真实契约响应。
class TestBackend {
  /// 全部请求（便于断言请求体与路径）。
  final List<http.Request> requests = <http.Request>[];

  /// /api/jobs 请求 URL（搜索/筛选/分页断言用）。
  final List<Uri> jobsRequests = <Uri>[];

  /// /api/job/{id} 调用次数（轮询断言用）。
  final Map<String, int> jobCalls = <String, int>{};

  /// 任务详情响应：id → 真实契约 JSON。
  final Map<String, Map<String, dynamic>> jobDetails =
      <String, Map<String, dynamic>>{};

  /// /files/{name} 产物文本（model/solution JSON 原文、步骤 Markdown 等）。
  final Map<String, String> files = <String, String>{};

  /// /api/parts 响应。
  Map<String, dynamic> partsBody = <String, dynamic>{'parts': <dynamic>[]};

  /// /api/health 响应。
  Map<String, dynamic> healthBody = <String, dynamic>{
    'ok': true,
    'apiVersion': 1,
    'status': 'ok',
  };

  /// /api/jobs 固定响应。
  Map<String, dynamic> jobsBody = jobsPageBody();

  /// /api/jobs 动态响应（优先级高于 jobsBody；按 query 返回服务端真实分页）。
  Map<String, dynamic> Function(Uri uri)? jobsResponder;

  /// POST /api/build 响应。
  Map<String, dynamic> buildBody = <String, dynamic>{
    'id': 'new-job-1',
    'mode': 'fast',
  };

  /// POST /api/retry 响应。
  Map<String, dynamic> retryBody = <String, dynamic>{
    'id': 'retry-job-1',
    'mode': 'fidelity',
  };

  int healthCalls = 0;
  int buildCalls = 0;
  int retryCalls = 0;
  int deleteCalls = 0;

  /// 某任务的详情请求次数。
  int callsFor(String id) => jobCalls[id] ?? 0;

  /// 最近一次 /api/jobs 请求的查询参数。
  Map<String, String> get lastJobsQuery =>
      jobsRequests.isEmpty ? <String, String>{} : jobsRequests.last.queryParameters;

  /// 构造 http.Client（MockClient），由 [_handle] 统一路由。
  http.Client client() => MockClient(_handle);

  Future<http.Response> _handle(http.Request request) async {
    requests.add(request);
    final uri = request.url;
    final path = uri.path;
    if (request.method == 'DELETE' && path.startsWith('/api/job/')) {
      deleteCalls += 1;
      return http.Response('', 200, headers: jsonHeaders());
    }
    if (path == '/api/health') {
      healthCalls += 1;
      return _json(healthBody);
    }
    if (path == '/api/parts') {
      return _json(partsBody);
    }
    if (path == '/api/jobs') {
      jobsRequests.add(uri);
      final responder = jobsResponder;
      return _json(responder != null ? responder(uri) : jobsBody);
    }
    if (path.startsWith('/api/job/')) {
      final id = Uri.decodeComponent(path.substring('/api/job/'.length));
      jobCalls[id] = (jobCalls[id] ?? 0) + 1;
      final detail = jobDetails[id];
      if (detail == null) {
        return http.Response(
          jsonEncode(<String, dynamic>{'error': '任务不存在：$id'}),
          404,
          headers: jsonHeaders(),
        );
      }
      return _json(detail);
    }
    if (path == '/api/build') {
      buildCalls += 1;
      return _json(buildBody);
    }
    if (path == '/api/retry') {
      retryCalls += 1;
      return _json(retryBody);
    }
    if (path.startsWith('/files/')) {
      // pathSegments 已经完成百分号解码（文件名可能含中文）。
      final name = uri.pathSegments.last;
      final text = files[name];
      if (text == null) {
        return http.Response(
          jsonEncode(<String, dynamic>{'error': '产物不存在：$name'}),
          404,
          headers: jsonHeaders(),
        );
      }
      return http.Response(text, 200, headers: <String, String>{
        'content-type': name.endsWith('.json')
            ? 'application/json; charset=utf-8'
            : 'text/plain; charset=utf-8',
        'x-legogod-api-version': '1',
        'x-request-id': 'test-rid',
      });
    }
    return http.Response(
      jsonEncode(
          <String, dynamic>{'error': '测试后端未实现：${request.method} $path'}),
      404,
      headers: jsonHeaders(),
    );
  }

  http.Response _json(Map<String, dynamic> body) =>
      http.Response(jsonEncode(body), 200, headers: jsonHeaders());
}

/// 创建测试 AppState。
/// [configure] 为 false 时保持「未配置服务」状态（首次连接引导用例）。
Future<AppState> createTestApp(
  TestBackend backend, {
  Map<String, Object> prefs = const <String, Object>{},
  bool configure = true,
}) async {
  SharedPreferences.setMockInitialValues(prefs);
  final app = AppState(
    api: ApiClient(client: backend.client()),
    storage: AppStorage(tokenStore: MemoryTokenStore()),
  );
  await app.init();
  if (configure) {
    app.address = ServiceAddress.parse(testBaseUrl).address;
    app.api.configure(baseUrl: testBaseUrl, token: '');
    app.connection = ServiceConnection.online;
  }
  return app;
}

/// 用真实契约 JSON 预置某任务的本地快照（模拟「已有真实数据」的场景）。
void seedJobSnapshot(AppState app, Map<String, dynamic> detailJson) {
  final detail = JobDetail.fromJson(detailJson);
  final JobSnapshot snapshot = app.snapshotOf(detail.id);
  snapshot.detail = detail;
  snapshot.logs = detail.logs;
}

/// 包装页面：注入 AppScope 与主题。
Widget wrapApp(AppState app, Widget home) {
  return AppScope(
    state: app,
    child: MaterialApp(theme: buildTheme(), home: home),
  );
}

/// 让页面内部 600ms / 400ms 去抖落盘定时器全部触发（不影响 900ms 以上的轮询）。
Future<void> flushDebounce(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 800));
}

/// 卸载页面树并泵一帧，确保页面内部 Timer/Ticker 被 dispose（避免残留定时器）。
Future<void> disposePage(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
}

/// 滚动到页面内的某个组件（列表是懒构建的，首屏之外的元素需要滚动才会构建）。
Future<void> reveal(
  WidgetTester tester,
  Finder finder, {
  double delta = 200,
}) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      finder,
      delta,
      scrollable: find.byType(Scrollable).first,
    );
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

/// 匹配 SelectableText 正文（find.textContaining 默认不匹配 RichText 内部文本）。
Finder selectableTextContaining(String pattern) {
  return find.byWidgetPredicate(
    (widget) => widget is SelectableText && (widget.data ?? '').contains(pattern),
    description: 'SelectableText containing "$pattern"',
  );
}
