// 零件目录模型：/api/parts 是唯一数据源，APP 不硬编码零件清单与库存。
import 'json.dart';

/// 一个「形状 × 颜色」零件变体。
class Part {
  const Part({
    required this.id,
    required this.shape,
    required this.name,
    required this.w,
    required this.d,
    required this.h,
    required this.hex,
    required this.colorName,
    required this.colorKey,
    required this.count,
    required this.hasStuds,
    required this.slope,
    required this.studMask,
    required this.rootMask,
    required this.massFactor,
  });

  /// 零件唯一 ID（如 B2x4 / B2x4_LGRAY / SLOPE2_XL）。
  final String id;

  /// 形状 ID（不含颜色），如 B2x4、SLOPE22_XR。
  final String shape;

  /// 中文名称，如「2x4 砖」「2x2 正斜坡(3039, / 高端在东)」。
  final String name;

  /// 宽度（stud）。
  final int w;

  /// 深度（stud）。
  final int d;

  /// 高度（砖层）。
  final int h;

  /// 展示色值（#RRGGBB）。
  final String hex;

  /// 中文颜色名。
  final String colorName;

  /// 颜色 key（WHITE/RED/...）。
  final String colorKey;

  /// 库存数量（服务端统一零件库存）。
  final int count;

  /// 顶面是否有凸点（斜坡砖为 false）。
  final bool hasStuds;

  /// 斜面体素字符（/, \, ^, v, b, d, p, q）；普通砖为 null。
  final String? slope;

  /// 带顶凸点的 (i, j) 列表（多格正斜坡）。
  final List<List<int>>? studMask;

  /// 反斜坡根部承托位 (i, j)。
  final List<List<int>>? rootMask;

  /// 楔形质量系数（0.5 / 0.75；普通砖为 1）。
  final double massFactor;

  /// 是否斜坡件。
  bool get isSlope => slope != null;

  /// 从 API JSON 构造；缺失字段用安全默认值（未知零件不得让整页崩溃）。
  factory Part.fromJson(Object? raw) {
    final map = asMap(raw);
    final id = asString(map['id']);
    return Part(
      id: id,
      shape: asString(map['shape'], id),
      name: asString(map['name'], id.isEmpty ? '未知零件' : id),
      w: asInt(map['w'], 1).clamp(1, 64),
      d: asInt(map['d'], 1).clamp(1, 64),
      h: asInt(map['h'], 1),
      hex: _normalizeHex(asString(map['color'], '#FF00FF')),
      colorName: asString(map['colorName'], '未知颜色'),
      colorKey: asString(map['colorKey']),
      count: asInt(map['count']),
      hasStuds: asBool(map['hasStuds'], true),
      slope: asStringOrNull(map['slope']),
      studMask: _mask(map['studMask']),
      rootMask: _mask(map['rootMask']),
      massFactor: asDouble(map['massFactor'], 1),
    );
  }

  static String _normalizeHex(String raw) {
    final text = raw.trim();
    if (text.startsWith('#') && (text.length == 7 || text.length == 9)) return text;
    return '#FF00FF';
  }

  static List<List<int>>? _mask(Object? value) {
    if (value is! List) return null;
    final out = <List<int>>[];
    for (final item in value) {
      if (item is List && item.length >= 2) {
        out.add(<int>[asInt(item[0]), asInt(item[1])]);
      }
    }
    return out.isEmpty ? null : out;
  }

  /// 序列化（本地缓存用）。
  Map<String, dynamic> toJson() => {
        'id': id,
        'shape': shape,
        'name': name,
        'w': w,
        'd': d,
        'h': h,
        'color': hex,
        'colorName': colorName,
        'colorKey': colorKey,
        'count': count,
        'hasStuds': hasStuds,
        if (slope != null) 'slope': slope,
        if (studMask != null) 'studMask': studMask,
        if (rootMask != null) 'rootMask': rootMask,
        'massFactor': massFactor,
      };
}

/// 零件目录：附带按形状分组的索引，页面与 3D 共用同一解释。
class PartsCatalog {
  PartsCatalog(this.parts);

  final List<Part> parts;

  /// 空目录（服务未返回零件/尚未加载）。
  static final PartsCatalog empty = PartsCatalog(<Part>[]);

  bool get isEmpty => parts.isEmpty;

  /// id → 零件。
  Map<String, Part> get byId => _byId ??= {for (final p in parts) p.id: p};
  Map<String, Part>? _byId;

  /// 按形状分组，保持服务端返回顺序（同形状变体连续）。
  List<ShapeGroup> get groups {
    if (_groups != null) return _groups!;
    final order = <String>[];
    final map = <String, List<Part>>{};
    for (final part in parts) {
      if (!map.containsKey(part.shape)) {
        order.add(part.shape);
        map[part.shape] = <Part>[];
      }
      map[part.shape]!.add(part);
    }
    _groups = [for (final shape in order) ShapeGroup(shape, map[shape]!)];
    return _groups!;
  }

  List<ShapeGroup>? _groups;

  /// 形状数（按 shape 字段去重）。
  int get shapeCount => groups.length;

  /// 变体总数。
  int get variantCount => parts.length;

  /// 总库存。
  int get totalStock => parts.fold(0, (sum, part) => sum + part.count);

  /// 颜色种类数。
  int get colorCount =>
      parts.map((p) => p.colorName).toSet().length;

  /// 按 ID 取零件，未知 ID 返回 null（UI 必须显式提示，不得静默省略）。
  Part? partOf(String id) => byId[id];

  factory PartsCatalog.fromJson(Object? raw) {
    final list = asList(raw);
    return PartsCatalog([
      for (final item in list) Part.fromJson(item),
    ]);
  }

  /// 序列化（本地缓存用）。
  Map<String, dynamic> toJson() => {
        'parts': [for (final part in parts) part.toJson()],
      };
}

/// 形状分组：一个形状及其全部颜色变体。
class ShapeGroup {
  const ShapeGroup(this.shape, this.variants);

  final String shape;
  final List<Part> variants;

  Part get first => variants.first;
}
