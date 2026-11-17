// 服务地址解析/校验单元测试：
// - 支持主机端口与 http/https，非法值明确报错；
// - 非回环服务必须配置令牌；
// - 安全约束：公网服务必须 HTTPS，仅回环/局域网地址允许 http；
//   回环判断必须按 IP 解析，不能把 127.example.com 当回环。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/service_address.dart';

void main() {
  group('ServiceAddress.parse 基础', () {
    test('主机:端口 自动补 http，并保留端口', () {
      final result = ServiceAddress.parse('192.168.0.2:8600');
      expect(result.ok, isTrue);
      expect(result.address!.url, 'http://192.168.0.2:8600');
      expect(result.address!.port, 8600);
      expect(result.address!.isLoopback, isFalse);
      expect(result.address!.isPrivateLan, isTrue);
    });

    test('完整 https 地址与路径前缀保留', () {
      final result = ServiceAddress.parse('https://example.com/legogod/');
      expect(result.ok, isTrue);
      expect(result.address!.url, 'https://example.com/legogod');
      expect(result.address!.scheme, 'https');
      expect(result.address!.isHttps, isTrue);
    });

    test('非法协议被拒绝', () {
      final result = ServiceAddress.parse('ftp://example.com');
      expect(result.ok, isFalse);
      expect(result.error, contains('http'));
    });

    test('带账号口令被拒绝', () {
      final result = ServiceAddress.parse('https://user:pass@example.com:8600');
      expect(result.ok, isFalse);
      expect(result.error, contains('账号口令'));
    });

    test('带查询串或片段被拒绝', () {
      expect(ServiceAddress.parse('https://example.com/?a=1').ok, isFalse);
      expect(ServiceAddress.parse('https://example.com/#x').ok, isFalse);
    });

    test('空输入有明确提示', () {
      final result = ServiceAddress.parse('   ');
      expect(result.ok, isFalse);
      expect(result.error, contains('请输入服务地址'));
    });

    test('端口非法被拒绝', () {
      expect(ServiceAddress.parse('https://example.com:99999').ok, isFalse);
    });

    test('规范化后无结尾斜杠且作为缓存键', () {
      final a = ServiceAddress.parse('http://192.168.0.2:8600/').address!;
      final b = ServiceAddress.parse('http://192.168.0.2:8600').address!;
      expect(a.url, b.url);
      expect(a.cacheKey, b.cacheKey);
    });
  });

  group('回环判断（IP 级，防域名前缀误判）', () {
    test('localhost / 127.0.0.1 / ::1 是回环', () {
      expect(ServiceAddress.parse('localhost:8600').address!.isLoopback, isTrue);
      expect(ServiceAddress.parse('127.0.0.1:8600').address!.isLoopback, isTrue);
      expect(ServiceAddress.parse('127.9.9.9:8600').address!.isLoopback, isTrue);
      expect(ServiceAddress.parse('[::1]:8600').address!.isLoopback, isTrue);
    });

    test('127.example.com 不是回环（避免跳过鉴权探测）', () {
      // https 才能通过公网明文限制；这里只验证回环判定本身。
      final address = ServiceAddress.parse('https://127.example.com:8600').address!;
      expect(address.isLoopback, isFalse);
      expect(ServiceAddress.parse('127.example.com:8600').ok, isFalse);
    });
  });

  group('安全约束：公网必须 HTTPS', () {
    test('公网 http 被拒绝并提示 https', () {
      for (final raw in <String>[
        'http://example.com:8600',
        'http://api.example.com',
        'http://8.8.8.8:8600',
        'example.com:8600',
      ]) {
        final result = ServiceAddress.parse(raw);
        expect(result.ok, isFalse, reason: raw);
        expect(result.error, contains('https'), reason: raw);
      }
    });

    test('公网 https 允许', () {
      expect(ServiceAddress.parse('https://example.com:8600').ok, isTrue);
      expect(ServiceAddress.parse('https://api.example.com').ok, isTrue);
    });

    test('局域网 http 允许（RFC1918 / 链路本地 / 局域网主机名）', () {
      for (final raw in <String>[
        'http://192.168.0.2:8600',
        'http://10.1.2.3:8600',
        'http://172.20.0.1:8600',
        'http://169.254.1.2:8600',
        'http://build-server:8600',
        'http://legogod.local:8600',
      ]) {
        expect(ServiceAddress.parse(raw).ok, isTrue, reason: raw);
      }
    });

    test('回环 http 允许', () {
      expect(ServiceAddress.parse('http://127.0.0.1:8600').ok, isTrue);
      expect(ServiceAddress.parse('http://localhost:8600').ok, isTrue);
      expect(ServiceAddress.parse('http://[::1]:8600').ok, isTrue);
    });

    test('公网 http 不会静默改写为 https', () {
      final result = ServiceAddress.parse('http://example.com:8600');
      expect(result.ok, isFalse);
      expect(result.address, isNull);
    });
  });

  group('令牌要求', () {
    test('非回环服务缺少令牌时报错，回环服务允许空令牌', () {
      final lan = ServiceAddress.parse('192.168.0.2:8600').address!;
      expect(lan.tokenRequirementError(hasToken: false), isNotNull);
      expect(lan.tokenRequirementError(hasToken: true), isNull);
      final local = ServiceAddress.parse('127.0.0.1:8600').address!;
      expect(local.tokenRequirementError(hasToken: false), isNull);
    });
  });
}
