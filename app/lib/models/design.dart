// 实时设计稿（服务端 design 通道：彩色体素，不含算子与部位数据）。
import 'json.dart';

/// 一层的字符矩阵与配色。
class DesignLayer {
  const DesignLayer({
    required this.y,
    required this.rows,
    required this.color,
    required this.colorRows,
  });

  final int y;

  /// 每行一个字符串，'.' 表示空。
  final List<String> rows;

  /// 层设计色（中文颜色名）。
  final String? color;

  /// 逐体素颜色字符行（与 rows 同形）。
  final List<String>? colorRows;

  factory DesignLayer.fromJson(Object? raw) {
    final map = asMap(raw);
    return DesignLayer(
      y: asInt(map['y']),
      rows: [for (final row in asList(map['rows'])) asString(row)],
      color: asStringOrNull(map['color']),
      colorRows: map['colorRows'] == null
          ? null
          : [for (final row in asList(map['colorRows'])) asString(row)],
    );
  }

  Map<String, dynamic> toJson() => {
        'y': y,
        'rows': rows,
        'color': color,
        'colorRows': colorRows,
      };
}

/// 实时设计稿。
class DesignDraft {
  const DesignDraft({
    required this.name,
    required this.slug,
    required this.gridW,
    required this.gridD,
    required this.layers,
    required this.totalVoxels,
    required this.revision,
    required this.palette,
    required this.chars,
    required this.stamp,
  });

  final String? name;
  final String? slug;
  final int? gridW;
  final int? gridD;
  final List<DesignLayer> layers;
  final int? totalVoxels;
  final int? revision;

  /// 颜色名 → #RRGGBB。
  final Map<String, String> palette;

  /// 颜色字符 → 颜色名。
  final Map<String, String> chars;

  /// 内容哈希（换稿识别：stamp 变了才重建场景，用户视角不重置）。
  final String stamp;

  bool get isEmpty => layers.isEmpty;

  /// 体素数（服务端缺失时从字符矩阵统计）。
  int get voxelCount {
    final total = totalVoxels;
    if (total != null && total > 0) return total;
    var count = 0;
    for (final layer in layers) {
      for (final row in layer.rows) {
        for (final ch in row.split('')) {
          if (ch != '.' && ch != ' ') count++;
        }
      }
    }
    return count;
  }

  /// 设计稿渲染用的彩色体素：返回 (x, y, z, 颜色名)。
  List<DesignVoxel> get voxels {
    final out = <DesignVoxel>[];
    for (final layer in layers) {
      final colorRows = layer.colorRows;
      for (var z = 0; z < layer.rows.length; z++) {
        final row = layer.rows[z];
        final colorRow = colorRows != null && z < colorRows.length ? colorRows[z] : null;
        for (var x = 0; x < row.length; x++) {
          final ch = row[x];
          if (ch == '.' || ch == ' ') continue;
          var colorName = layer.color ?? '';
          if (colorRow != null && x < colorRow.length) {
            final code = colorRow[x];
            if (code != '.' && code.isNotEmpty) {
              colorName = chars[code] ?? colorName;
            }
          }
          out.add(DesignVoxel(x: x, y: layer.y, z: z, colorName: colorName));
        }
      }
    }
    return out;
  }

  /// 取颜色名对应的 hex（缺省返回中性灰，绝不因未知颜色崩溃）。
  String hexOf(String colorName) => palette[colorName] ?? '#A0A5A9';

  factory DesignDraft.fromJson(Object? raw) {
    final map = asMap(raw);
    final palette = <String, String>{};
    for (final entry in asMap(map['palette']).entries) {
      final value = asStringOrNull(entry.value);
      if (value != null) palette[entry.key] = value;
    }
    final chars = <String, String>{};
    for (final entry in asMap(map['chars']).entries) {
      final value = asStringOrNull(entry.value);
      if (value != null) chars[entry.key] = value;
    }
    final grid = asMap(map['grid']);
    return DesignDraft(
      name: asStringOrNull(map['name']),
      slug: asStringOrNull(map['slug']),
      gridW: asIntOrNull(grid['w']),
      gridD: asIntOrNull(grid['d']),
      layers: [for (final item in asList(map['layers'])) DesignLayer.fromJson(item)],
      totalVoxels: asIntOrNull(map['totalVoxels']),
      revision: asIntOrNull(map['revision']),
      palette: palette,
      chars: chars,
      stamp: asString(map['stamp']),
    );
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'slug': slug,
        'grid': {'w': gridW, 'd': gridD},
        'layers': [for (final layer in layers) layer.toJson()],
        'totalVoxels': totalVoxels,
        'revision': revision,
        'palette': palette,
        'chars': chars,
        'stamp': stamp,
      };
}

/// 设计稿单个彩色体素。
class DesignVoxel {
  const DesignVoxel({
    required this.x,
    required this.y,
    required this.z,
    required this.colorName,
  });

  final int x;
  final int y;
  final int z;
  final String colorName;
}
