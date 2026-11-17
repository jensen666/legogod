// 服务健康检查与连接自检 DTO（HealthInfo/ConnectionCheck）。
import 'api_error.dart';
import 'json.dart';

/// 健康检查响应（GET /api/health）。
class HealthInfo {
  const HealthInfo({
    required this.ok,
    required this.apiVersion,
    required this.status,
    required this.role,
    required this.headerVersion,
    required this.requestId,
    required this.latencyMs,
  });

  final bool ok;
  final int apiVersion;
  final String status;
  final String? role;

  /// 响应头 X-LEGOGOD-API-Version 的值（缺失为 null）。
  final int? headerVersion;
  final String? requestId;
  final int latencyMs;

  factory HealthInfo.fromJson(
    Object? raw, {
    int? headerVersion,
    String? requestId,
    int latencyMs = 0,
  }) {
    final map = asMap(raw);
    return HealthInfo(
      ok: asBool(map['ok']),
      apiVersion: asInt(map['apiVersion']),
      status: asString(map['status']),
      role: asStringOrNull(map['role']),
      headerVersion: headerVersion,
      requestId: requestId,
      latencyMs: latencyMs,
    );
  }
}

/// 连接测试结果（先真实请求健康接口，再按需要验证零件与鉴权）。
class ConnectionCheck {
  const ConnectionCheck({
    required this.baseUrl,
    required this.healthOk,
    required this.apiVersion,
    required this.status,
    required this.latencyMs,
    this.partsCount,
    this.authChecked = false,
    this.authOk = false,
    this.authError,
    this.requestId,
    this.checkedParts = false,
    this.error,
    this.apiVersionCompatible = true,
  });

  final String baseUrl;
  final bool healthOk;
  final int apiVersion;
  final String status;
  final int latencyMs;

  /// /api/parts 返回的零件变体数量（未检查为 null）。
  final int? partsCount;
  final bool checkedParts;
  final bool authChecked;
  final bool authOk;
  final String? authError;
  final String? requestId;

  /// 健康检查失败时的可展示错误（网络/HTTP/格式）。
  final String? error;

  /// 服务 API 版本是否兼容（要求 1）。
  final bool apiVersionCompatible;

  /// 是否所有被要求的检查都通过。
  bool get ok =>
      healthOk && apiVersionCompatible && (!authChecked || authOk);

  /// 摘要文案（用于设置页与 E2E 证据）。
  String get summary {
    final bits = <String>[
      healthOk ? '服务可达' : '服务不可达',
      'API v$apiVersion',
      '${latencyMs}ms',
    ];
    if (checkedParts) bits.add('零件 ${partsCount ?? 0} 个变体');
    if (authChecked) bits.add(authOk ? '鉴权通过' : '鉴权失败');
    return bits.join(' · ');
  }
}

/// 错误码 → 中文提示（只用于补充说明；服务端原始 error 始终优先展示）。
String describeApiCode(String? code) {
  switch (code) {
    case 'unknown_job':
      return '任务不存在或已清理';
    case 'empty_desc':
      return '需求描述不能为空';
    case 'missing_desc':
      return '原任务缺少需求描述，无法重试';
    case 'invalid_mode':
      return '生成模式不合法';
    case 'job_running':
      return '任务仍在进行中，结束后才能重试';
    case 'invalid_params':
      return '查询参数不合法';
    case 'unauthorized':
      return '访问令牌缺失或不正确';
    case 'cross_origin':
      return '请求来源被服务端拒绝';
    case 'content_type':
      return '请求类型不被服务端接受';
    case 'body_too_large':
      return '需求内容超过服务端 64KB 上限';
    case 'not_found':
      return '接口不存在';
    default:
      return '';
  }
}

/// 把异常统一转成可直接展示的中文文案。
String describeError(Object error) {
  if (error is ApiError) {
    final hint = describeApiCode(error.code);
    if (hint.isNotEmpty && !error.message.contains(hint)) {
      return '${error.message}（$hint）';
    }
    return error.message;
  }
  final text = error.toString();
  return text.startsWith('Exception: ') ? text.substring(11) : text;
}
