// 服务地址解析与校验：
// - 支持主机、端口与 HTTP/HTTPS；未写协议时按 http:// 补全（不静默改写到其他服务）；
// - 非法地址在提交前提示，不修改用户输入指向别的地址；
// - 回环服务允许不配置令牌；非回环服务必须配置访问令牌；
// - 产品安全约束：公网服务必须 HTTPS，仅回环/局域网地址允许 http，
//   避免访问令牌在公网明文传输。该校验在 Dart 层执行，不能依赖 Android
//   network_security_config（Dart 的 socket 不受该 XML 约束，真机已验证非白名单 LAN HTTP 可访问）。
import 'dart:io';

/// 解析后的服务地址。
class ServiceAddress {
  const ServiceAddress({
    required this.url,
    required this.scheme,
    required this.host,
    required this.port,
    required this.path,
  });

  /// 规范化后的完整 Base URL（无结尾斜杠），如 http://example.com:8600。
  final String url;

  /// http / https。
  final String scheme;
  final String host;

  /// 显式端口；null 表示使用协议默认端口。
  final int? port;

  /// 路径前缀（无结尾斜杠，可能为空串）。
  final String path;

  bool get isHttps => scheme == 'https';

  InternetAddress? get _ip => InternetAddress.tryParse(host);

  static bool _isIpv6Loopback(InternetAddress ip) {
    final bytes = ip.rawAddress;
    if (bytes.length != 16) return false;
    for (var i = 0; i < 15; i++) {
      if (bytes[i] != 0) return false;
    }
    return bytes[15] == 1;
  }

  /// 是否回环地址：localhost / 127.0.0.0/8 / ::1。
  /// 用 IP 解析而非字符串前缀，避免 `127.example.com` 被误判为回环。
  bool get isLoopback {
    final h = host.toLowerCase();
    if (h == 'localhost' || h.endsWith('.localhost')) return true;
    final ip = _ip;
    if (ip == null) return false;
    if (ip.type == InternetAddressType.IPv4) {
      return ip.rawAddress.isNotEmpty && ip.rawAddress.first == 127;
    }
    return _isIpv6Loopback(ip);
  }

  /// 是否私网/局域网地址（RFC1918、链路本地、IPv6 ULA/链路本地、局域网主机名）。
  /// 该判断同时用于：http 允许范围（安全约束）与 cleartext 提示。
  bool get isPrivateLan {
    final ip = _ip;
    if (ip != null) {
      if (ip.type == InternetAddressType.IPv4) {
        final b = ip.rawAddress;
        if (b.length < 4) return false;
        if (b[0] == 10) return true;
        if (b[0] == 172 && b[1] >= 16 && b[1] <= 31) return true;
        if (b[0] == 192 && b[1] == 168) return true;
        if (b[0] == 169 && b[1] == 254) return true;
        return false;
      }
      final b = ip.rawAddress;
      if (b.length == 16) {
        // fc00::/7（唯一本地地址）与 fe80::/10（链路本地）。
        if ((b[0] & 0xfe) == 0xfc) return true;
        if (b[0] == 0xfe && (b[1] & 0xc0) == 0x80) return true;
        if (_isIpv6Loopback(ip)) return true;
      }
      return false;
    }
    final h = host.toLowerCase();
    if (h.endsWith('.local') ||
        h.endsWith('.lan') ||
        h.endsWith('.home') ||
        h.endsWith('.internal')) {
      return true;
    }
    // 单标签主机名（如 build-server）按局域网主机处理；带点的公网域名必须 HTTPS。
    return !h.contains('.');
  }

  /// 是否允许明文 http（回环或局域网）。
  bool get allowsCleartext => isLoopback || isPrivateLan;

  /// 展示用地址（不含任何凭据）。
  String get display => url;

  /// 唯一键：切换服务时用于清空任务/零件缓存。
  String get cacheKey => url;

  @override
  String toString() => url;

  /// 解析用户输入；非法返回 null，并通过 [ServiceAddressError] 给出原因。
  static ServiceAddressResult parse(String raw) {
    var text = raw.trim();
    if (text.isEmpty) {
      return const ServiceAddressResult.failure('请输入服务地址（例如 <电脑局域网 IP>:8600）');
    }
    // 未写协议时补全 http://（用户输入主机:端口是合法形态；只补协议，不改主机/端口）。
    if (!text.contains('://')) text = 'http://$text';
    final uri = Uri.tryParse(text);
    if (uri == null) return const ServiceAddressResult.failure('服务地址格式不合法');
    final scheme = uri.scheme.toLowerCase();
    if (scheme != 'http' && scheme != 'https') {
      return const ServiceAddressResult.failure('协议只支持 http 或 https');
    }
    if (uri.host.isEmpty) return const ServiceAddressResult.failure('服务地址缺少主机名或 IP');
    if (uri.userInfo.isNotEmpty) {
      return const ServiceAddressResult.failure('服务地址不能包含账号口令（@ 前的内容）');
    }
    if (uri.hasQuery || uri.hasFragment) {
      return const ServiceAddressResult.failure('服务地址不能包含 ? 或 # 后面的内容');
    }
    int? port;
    if (uri.hasPort) {
      port = uri.port;
      if (port < 1 || port > 65535) {
        return const ServiceAddressResult.failure('端口必须是 1-65535 之间的整数');
      }
    }
    var path = uri.path;
    if (path == '/') path = '';
    while (path.endsWith('/')) {
      path = path.substring(0, path.length - 1);
    }
    if (path.isNotEmpty && !path.startsWith('/')) path = '/$path';
    final normalized = Uri(
      scheme: scheme,
      host: uri.host,
      port: port,
      path: path.isEmpty ? '' : path,
    ).toString();
    final address = ServiceAddress(
      url: normalized.endsWith('/') ? normalized.substring(0, normalized.length - 1) : normalized,
      scheme: scheme,
      host: uri.host,
      port: port,
      path: path,
    );
    if (!address.isHttps && !address.allowsCleartext) {
      return const ServiceAddressResult.failure(
        '公网服务必须使用 https://（仅回环/局域网地址允许 http，防止访问令牌明文传输）',
      );
    }
    return ServiceAddressResult.success(address);
  }

  /// 校验凭据要求：非回环服务必须配置令牌。
  String? tokenRequirementError({required bool hasToken}) {
    if (!hasToken && !isLoopback) {
      return '非回环服务必须配置访问令牌（Authorization: Bearer）';
    }
    return null;
  }
}

/// 地址解析结果：成功带地址，失败带可展示原因。
class ServiceAddressResult {
  const ServiceAddressResult._({this.address, this.error});

  const ServiceAddressResult.success(ServiceAddress address) : this._(address: address);

  const ServiceAddressResult.failure(String error) : this._(error: error);

  final ServiceAddress? address;
  final String? error;

  bool get ok => address != null;
}
