// API 错误对象：区分网络不可达 / 超时（network=true）与服务端业务错误（4xx/5xx），
// 并保留机器可读 code 与 requestId，供界面精确提示与故障关联；绝不包含令牌。

/// LEGOGOD API 调用失败。
class ApiError implements Exception {
  ApiError(
    this.message, {
    this.status = 0,
    this.code,
    this.requestId,
    this.network = false,
    this.kind = ApiErrorKind.server,
  });

  /// 用户可读的中文错误信息（服务端 error 原文或本地网络说明）。
  final String message;

  /// HTTP 状态码；网络错误与超时为 0。
  final int status;

  /// 服务端机器可读错误码（如 unknown_job / unauthorized）。
  final String? code;

  /// 服务端 X-Request-ID 或响应体 requestId，用于与服务器日志关联。
  final String? requestId;

  /// 是否属于网络层失败（不可达、超时、连接中断）。
  final bool network;

  /// 失败类别：网络 / 超时 / 业务 / 响应格式非法。
  final ApiErrorKind kind;

  /// 鉴权失败（401）。
  bool get unauthorized => status == 401;

  /// 任务不存在（404 且 code 为 unknown_job）。
  bool get unknownJob => status == 404 && (code == 'unknown_job' || code == null);

  /// 任务仍在运行导致的操作被拒。
  bool get jobRunning => code == 'job_running';

  /// 请求体超限（413）。
  bool get bodyTooLarge => status == 413 || code == 'body_too_large';

  /// 供日志使用的简短描述：只含状态、code、requestId，不含请求体与令牌。
  String get logLine =>
      'status=$status code=${code ?? '-'} requestId=${requestId ?? '-'} network=$network';

  /// 面向用户的完整展示文案（含 requestId，便于报障）。
  String get displayMessage {
    final buffer = StringBuffer(message);
    if (code != null && code!.isNotEmpty) buffer.write('（code=$code）');
    if (requestId != null && requestId!.isNotEmpty) {
      buffer.write('（requestId=$requestId）');
    }
    return buffer.toString();
  }

  @override
  String toString() => 'ApiError($logLine): $message';
}

/// API 失败类别。
enum ApiErrorKind {
  /// 服务端返回了错误响应。
  server,

  /// 网络不可达 / 连接被拒绝。
  network,

  /// 请求超时。
  timeout,

  /// 响应不是合法 JSON / 结构不符合契约。
  badResponse,
}
