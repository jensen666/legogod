// JSON 安全转换工具：服务端历史记录字段可能缺失 / 类型不合规，
// 解析层一律做防御性转换，绝不因为单条脏数据让整个页面崩溃。

/// 把任意值转成 Map，非 Map 时返回空 Map（只读视图）。
Map<String, dynamic> asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((k, v) => MapEntry(k.toString(), v));
  }
  return const <String, dynamic>{};
}

/// 可空 Map：null 表示字段缺失，便于区分「缺失」与「空对象」。
Map<String, dynamic>? asMapOrNull(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((k, v) => MapEntry(k.toString(), v));
  return null;
}

/// 转成列表；非列表返回空列表。
List<dynamic> asList(Object? value) => value is List ? value : const <dynamic>[];

/// 安全取字符串：数字/布尔也转成字符串；null 返回 fallback。
String asString(Object? value, [String fallback = '']) {
  if (value == null) return fallback;
  if (value is String) return value;
  return value.toString();
}

/// 可空字符串：空字符串与缺失都返回 null，便于 UI 判断「是否有真实值」。
String? asStringOrNull(Object? value) {
  if (value == null) return null;
  final text = value is String ? value : value.toString();
  return text;
}

/// 安全取整数：接受 int / double / 数字字符串；失败返回 fallback。
int asInt(Object? value, [int fallback = 0]) {
  if (value is int) return value;
  if (value is double) return value.isFinite ? value.round() : fallback;
  if (value is String) return int.tryParse(value.trim()) ?? fallback;
  return fallback;
}

/// 可空整数：字段缺失或非法返回 null（用于区分「0」与「没有」）。
int? asIntOrNull(Object? value) {
  if (value is int) return value;
  if (value is double) return value.isFinite ? value.round() : null;
  if (value is String) return int.tryParse(value.trim());
  return null;
}

/// 安全取浮点数。
double asDouble(Object? value, [double fallback = 0]) {
  if (value is double) return value;
  if (value is int) return value.toDouble();
  if (value is String) return double.tryParse(value.trim()) ?? fallback;
  return fallback;
}

/// 可空浮点数。
double? asDoubleOrNull(Object? value) {
  if (value is double) return value;
  if (value is int) return value.toDouble();
  if (value is String) return double.tryParse(value.trim());
  return null;
}

/// 安全取布尔：接受 true/false/1/0/"true"/"false"。
bool asBool(Object? value, [bool fallback = false]) {
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) {
    final text = value.trim().toLowerCase();
    if (text == 'true' || text == '1') return true;
    if (text == 'false' || text == '0') return false;
  }
  return fallback;
}

/// 读时间戳（秒，可能是浮点）；返回可空 double。
double? asTimestamp(Object? value) => asDoubleOrNull(value);
