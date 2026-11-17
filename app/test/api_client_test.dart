// API 客户端契约测试：URL/产物解析、请求头（X-Request-ID/Bearer）、JSON 错误语义、
// 健康检查与鉴权区分、非法响应与网络错误。
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:legogod_app/core/api_client.dart';
import 'package:legogod_app/models/api_error.dart';

Map<String, String> jsonHeaders({int status = 200}) => {
      'content-type': 'application/json; charset=utf-8',
      'x-legogod-api-version': '1',
      'x-request-id': 'rid-from-server',
    };

void main() {
  group('URL 与产物解析', () {
    test('resolve 拼接 Base URL 与查询串', () {
      final api = ApiClient(client: MockClient((_) async => http.Response('{}', 200)))
        ..configure(baseUrl: 'http://example.com:8600', token: '');
      final uri = api.resolve('/api/jobs', {'page': '1', 'pageSize': '20'});
      expect(uri.toString(), 'http://example.com:8600/api/jobs?page=1&pageSize=20');
    });

    test('artifactUrl 生成 /files /views /viz 地址并编码文件名', () {
      final api = ApiClient(client: MockClient((_) async => http.Response('{}', 200)))
        ..configure(baseUrl: 'http://host:8600', token: '');
      expect(api.artifactUrl('files', 'model_a.json'),
          'http://host:8600/files/model_a.json');
      expect(api.artifactUrl('views', 'a b.png'),
          'http://host:8600/views/a%20b.png');
      expect(api.artifactUrl('viz', 'lego_x.html'),
          'http://host:8600/viz/lego_x.html');
      expect(() => api.artifactUrl('bad', 'x'), throwsArgumentError);
      expect(() => api.artifactUrl('files', ''), throwsArgumentError);
      expect(() => api.artifactUrl('files', '../etc/passwd'), throwsArgumentError);
    });

    test('absoluteUrl 支持相对路径与绝对 URL，拒绝其它形态', () {
      final api = ApiClient(client: MockClient((_) async => http.Response('{}', 200)))
        ..configure(baseUrl: 'http://host:8600', token: '');
      expect(api.absoluteUrl('/views/a.png'), 'http://host:8600/views/a.png');
      expect(api.absoluteUrl('https://cdn/a.png'), 'https://cdn/a.png');
      expect(() => api.absoluteUrl('views/a.png'), throwsA(isA<ApiError>()));
    });
  });

  group('健康检查与请求头', () {
    test('健康检查解析 body 与响应头，发送合法 X-Request-ID 与 Bearer', () async {
      String? sentRequestId;
      String? sentAuth;
      final api = ApiClient(client: MockClient((request) async {
        sentRequestId = request.headers['X-Request-ID'];
        sentAuth = request.headers['Authorization'];
        return http.Response(
          jsonEncode({'ok': true, 'apiVersion': 1, 'status': 'ok', 'role': 'api'}),
          200,
          headers: jsonHeaders(),
        );
      }))
        ..configure(baseUrl: 'http://host:8600', token: 'secret-token');
      final health = await api.health();
      expect(health.ok, isTrue);
      expect(health.apiVersion, 1);
      expect(health.headerVersion, 1);
      expect(health.requestId, 'rid-from-server');
      expect(health.role, 'api');
      expect(sentRequestId, isNotNull);
      expect(RegExp(r'^[A-Za-z0-9._-]{1,64}$').hasMatch(sentRequestId!), isTrue);
      expect(sentAuth, 'Bearer secret-token');
      expect(api.lastApiVersion, 1);
      expect(api.lastRequestId, 'rid-from-server');
    });
  });

  group('错误语义', () {
    test('401 错误体带 code/requestId 转为 ApiError', () async {
      final api = ApiClient(client: MockClient((request) async {
        return http.Response(
          jsonEncode({
            'error': '缺少或非法访问令牌',
            'code': 'unauthorized',
            'requestId': 'rid-401',
          }),
          401,
          headers: jsonHeaders(status: 401),
        );
      }))
        ..configure(baseUrl: 'http://host:8600', token: 'bad');
      await expectLater(
        api.jobsPage(),
        throwsA(isA<ApiError>()
            .having((e) => e.status, 'status', 401)
            .having((e) => e.code, 'code', 'unauthorized')
            .having((e) => e.requestId, 'requestId', 'rid-401')
            .having((e) => e.unauthorized, 'unauthorized', isTrue)),
      );
    });

    test('非 JSON 响应（例如误连静态服务）给出明确错误而不是崩溃', () async {
      final api = ApiClient(client: MockClient((request) async {
        return http.Response('<html>not api</html>', 200,
            headers: {'content-type': 'text/html'});
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      await expectLater(
        api.health(),
        throwsA(isA<ApiError>()
            .having((e) => e.kind, 'kind', ApiErrorKind.badResponse)
            .having((e) => e.message, 'message', contains('不是合法 JSON'))),
      );
    });

    test('网络失败映射为 network=true', () async {
      final api = ApiClient(client: MockClient((request) async {
        throw http.ClientException('Connection refused');
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      await expectLater(
        api.health(),
        throwsA(isA<ApiError>()
            .having((e) => e.network, 'network', isTrue)
            .having((e) => e.kind, 'kind', ApiErrorKind.network)),
      );
    });

    test('2xx 且 body 带 error 字符串仍视为失败（服务端兼容约定）', () async {
      final api = ApiClient(client: MockClient((request) async {
        return http.Response(jsonEncode({'error': '内部异常'}), 200, headers: jsonHeaders());
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      await expectLater(
        api.job('abc'),
        throwsA(isA<ApiError>().having((e) => e.message, 'message', '内部异常')),
      );
    });
  });

  group('任务接口', () {
    test('创建任务显式提交原文 desc 与 mode，Content-Type 为 JSON', () async {
      String? body;
      String? contentType;
      final api = ApiClient(client: MockClient((request) async {
        body = request.body;
        contentType = request.headers['Content-Type'];
        return http.Response(jsonEncode({'id': 'newjob1', 'mode': 'fast'}), 200,
            headers: jsonHeaders());
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      final raw = '一只小狗：\n 四条腿、垂耳 🐶  ';
      final result = await api.build(desc: raw, mode: 'fast');
      expect(result.id, 'newjob1');
      expect(result.mode, 'fast');
      expect(contentType, 'application/json');
      final decoded = jsonDecode(body!) as Map<String, dynamic>;
      expect(decoded['desc'], raw);
      expect(decoded['mode'], 'fast');
    });

    test('重试与取消使用正确的方法与路径', () async {
      final calls = <String>[];
      final api = ApiClient(client: MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/api/retry') {
          return http.Response(jsonEncode({'id': 'retry1', 'mode': 'fidelity'}), 200,
              headers: jsonHeaders());
        }
        return http.Response(jsonEncode({'cancelling': true}), 200, headers: jsonHeaders());
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      final retried = await api.retry('old-job');
      expect(retried.id, 'retry1');
      await api.cancel('old-job');
      expect(calls, ['POST /api/retry', 'DELETE /api/job/old-job']);
    });

    test('历史分页只拼接非空筛选参数', () async {
      Uri? sent;
      final api = ApiClient(client: MockClient((request) async {
        sent = request.url;
        return http.Response(
          jsonEncode({
            'jobs': [],
            'total': 0,
            'page': 1,
            'pageSize': 20,
            'pages': 1,
            'running': [],
          }),
          200,
          headers: jsonHeaders(),
        );
      }))
        ..configure(baseUrl: 'http://host:8600', token: '');
      await api.jobsPage(page: 2, pageSize: 20, status: 'running', q: '小狗');
      expect(sent!.queryParameters['page'], '2');
      expect(sent!.queryParameters['pageSize'], '20');
      expect(sent!.queryParameters['status'], 'running');
      expect(sent!.queryParameters['q'], '小狗');
      expect(sent!.queryParameters.containsKey('outcome'), isFalse);
    });
  });

  group('连接测试', () {
    test('健康 + 零件 + 鉴权全部通过', () async {
      final api = ApiClient(client: MockClient((request) async {
        switch (request.url.path) {
          case '/api/health':
            return http.Response(
                jsonEncode({'ok': true, 'apiVersion': 1, 'status': 'ok'}),
                200,
                headers: jsonHeaders());
          case '/api/parts':
            return http.Response(
                jsonEncode({
                  'parts': [
                    {'id': 'B1x1', 'shape': 'B1x1', 'color': '#237841', 'count': 1}
                  ]
                }),
                200,
                headers: jsonHeaders());
          case '/api/jobs':
            return http.Response(
                jsonEncode({'jobs': [], 'total': 0, 'page': 1, 'pageSize': 1, 'pages': 1, 'running': []}),
                200,
                headers: jsonHeaders());
        }
        return http.Response('{}', 404);
      }));
      final check = await api.checkConnection(
          baseUrl: 'http://192.168.0.2:8600', token: 'token');
      expect(check.ok, isTrue);
      expect(check.apiVersion, 1);
      expect(check.partsCount, 1);
      expect(check.authChecked, isTrue);
      expect(check.authOk, isTrue);
    });

    test('错误令牌时区分鉴权失败但健康可达', () async {
      final api = ApiClient(client: MockClient((request) async {
        if (request.url.path == '/api/health') {
          return http.Response(
              jsonEncode({'ok': true, 'apiVersion': 1, 'status': 'ok'}),
              200,
              headers: jsonHeaders());
        }
        if (request.url.path == '/api/parts') {
          return http.Response(jsonEncode({'parts': []}), 200, headers: jsonHeaders());
        }
        return http.Response(
            jsonEncode({'error': '缺少或非法访问令牌', 'code': 'unauthorized'}),
            401,
            headers: jsonHeaders(status: 401));
      }));
      final check = await api.checkConnection(
          baseUrl: 'http://192.168.0.2:8600', token: 'wrong');
      expect(check.healthOk, isTrue);
      expect(check.authChecked, isTrue);
      expect(check.authOk, isFalse);
      expect(check.authError, contains('access'.isEmpty ? '' : '缺少或非法访问令牌'));
      expect(check.ok, isFalse);
    });

    test('服务不可达时给出网络错误且不抛异常', () async {
      final api = ApiClient(client: MockClient((request) async {
        throw http.ClientException('Connection refused');
      }));
      final check = await api.checkConnection(
          baseUrl: 'http://192.168.0.2:8600', token: 'token');
      expect(check.healthOk, isFalse);
      expect(check.ok, isFalse);
      expect(check.error, contains('无法连接'));
    });

    test('API 版本不兼容被判失败', () async {
      final api = ApiClient(client: MockClient((request) async {
        if (request.url.path == '/api/health') {
          return http.Response(
              jsonEncode({'ok': true, 'apiVersion': 2, 'status': 'ok'}),
              200,
              headers: jsonHeaders());
        }
        return http.Response(
            jsonEncode({'parts': []}), 200,
            headers: jsonHeaders());
      }));
      final check = await api.checkConnection(
          baseUrl: 'http://host:8600', token: 't');
      expect(check.apiVersionCompatible, isFalse);
      expect(check.ok, isFalse);
      expect(check.error, contains('版本不兼容'));
    });
  });
}
