// AppState 状态与请求去重回归测试：
// - 同一任务重试在途时复用 Future（防连点创建多个真实任务）；
// - 同一任务详情并发加载只发一次请求（selectJob/JobPage 不重复请求）；
// - 任务状态变化时终态必须落盘（adopt 之后比较不再恒等）。
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:legogod_app/core/api_client.dart';
import 'package:legogod_app/core/app_state.dart';
import 'package:legogod_app/core/service_address.dart';
import 'package:legogod_app/core/storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, String> _jsonHeaders() => {
      'content-type': 'application/json; charset=utf-8',
      'x-legogod-api-version': '1',
      'x-request-id': 'test-rid',
    };

String _emptyJobs() => jsonEncode({
      'jobs': [],
      'total': 0,
      'page': 1,
      'pageSize': 20,
      'pages': 1,
      'running': [],
    });

Map<String, dynamic> _jobJson(String status) => {
      'id': 'j1',
      'status': status,
      'logs': [],
      'desc': '一座小房子',
      'startedAt': 1,
      'mode': 'fast',
      'stage': {},
      'views': {},
    };

/// 记录落盘调用的存储替身。
class _SpyStorage extends AppStorage {
  _SpyStorage() : super(tokenStore: MemoryTokenStore());

  final List<Map<String, dynamic>> savedDetails = [];

  @override
  Future<void> saveCachedJobDetail(String id, Map<String, dynamic> raw) async {
    savedDetails.add(raw);
  }
}

Future<AppState> _newApp(http.Client client, AppStorage storage) async {
  SharedPreferences.setMockInitialValues(<String, Object>{});
  final app = AppState(api: ApiClient(client: client), storage: storage);
  await app.init();
  app.address = ServiceAddress.parse('http://127.0.0.1:8600').address;
  app.api.configure(baseUrl: 'http://127.0.0.1:8600', token: '');
  return app;
}

void main() {
  test('重试在途时复用 Future：连点只创建一次真实任务', () async {
    var retryCalls = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/api/retry') {
        retryCalls += 1;
        await Future<void>.delayed(const Duration(milliseconds: 40));
        return http.Response(jsonEncode({'id': 'new1', 'mode': 'fast'}), 200,
            headers: _jsonHeaders());
      }
      if (request.url.path == '/api/jobs') {
        return http.Response(_emptyJobs(), 200, headers: _jsonHeaders());
      }
      return http.Response('{}', 200, headers: _jsonHeaders());
    });
    final storage = _SpyStorage();
    final app = await _newApp(client, storage);
    addTearDown(app.dispose);

    final first = app.retryJob('old1');
    final second = app.retryJob('old1');
    final ids = await Future.wait<String>(<Future<String>>[first, second]);
    await pumpEventQueue();

    expect(retryCalls, 1);
    expect(ids[0], 'new1');
    expect(ids[1], 'new1');
  });

  test('同一任务详情并发加载只发一次请求', () async {
    var jobCalls = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/api/job/abc') {
        jobCalls += 1;
        await Future<void>.delayed(const Duration(milliseconds: 40));
        return http.Response(
            jsonEncode({'error': {'code': 'boom', 'message': '加载失败'}}), 500,
            headers: _jsonHeaders());
      }
      if (request.url.path == '/api/jobs') {
        return http.Response(_emptyJobs(), 200, headers: _jsonHeaders());
      }
      return http.Response('{}', 200, headers: _jsonHeaders());
    });
    final app = await _newApp(client, _SpyStorage());
    addTearDown(app.dispose);

    final results = await Future.wait<void>(<Future<void>>[
      app.ensureJobLoaded('abc').catchError((Object _) {}),
      app.ensureJobLoaded('abc').catchError((Object _) {}),
    ]);
    await pumpEventQueue();
    expect(results.length, 2);
    expect(jobCalls, 1);
  });

  test('状态变化时终态立即落盘（不受 5 秒节流与 adopt 恒等影响）', () async {
    var calls = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/api/job/j1') {
        calls += 1;
        final status = calls == 1 ? 'running' : 'done';
        return http.Response(jsonEncode(_jobJson(status)), 200,
            headers: _jsonHeaders());
      }
      if (request.url.path == '/api/jobs') {
        return http.Response(_emptyJobs(), 200, headers: _jsonHeaders());
      }
      return http.Response('{}', 200, headers: _jsonHeaders());
    });
    final storage = _SpyStorage();
    final app = await _newApp(client, storage);
    addTearDown(app.dispose);

    await app.fetchJob('j1');
    // 第二次在 5 秒节流窗口内，但状态从 running → done，必须落盘。
    await app.fetchJob('j1');
    // fetchJob 终态会触发后台刷新（refreshRunning / refreshRecentDone / refreshDoneWorks），
    // 等待它们在 AppState 销毁前完成，避免「dispose 后 notifyListeners」的异步噪音。
    await pumpEventQueue();

    final statuses = storage.savedDetails.map((d) => d['status']).toList();
    expect(statuses, contains('running'));
    expect(statuses, contains('done'));
  });
}
