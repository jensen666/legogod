// 真实产物模型（/files/<name>）：
// - model_*.json：设计模型（层、模块名、体素字符矩阵、配色行）
// - solution_*.json：可拼装配方案（步骤、用量、颜色、回退、预拼子组件、统一校验结论）
// 作品与步骤统计一律以这两个真实文件为准，快照只用于展示与恢复。
import 'json.dart';
import 'part.dart';

/// 模型层（来自 model_*.json）。
class ModelLayer {
  const ModelLayer({
    required this.y,
    required this.rows,
    required this.cells,
    required this.module,
    required this.color,
    required this.colorRows,
    required this.count,
  });

  final int y;

  /// 体素字符行（历史/兼容轨道的真实来源）。
  final List<String> rows;

  /// 单元格 (x,z) 列表（新旧轨道都有）。
  final List<List<int>> cells;

  /// 模块名列表。
  final List<String> module;

  /// 层设计色。
  final String? color;

  /// 逐体素颜色字符行。
  final List<String>? colorRows;

  /// 层体素数。
  final int count;

  static const ModelLayer empty = ModelLayer(
    y: 0,
    rows: <String>[],
    cells: <List<int>>[],
    module: <String>[],
    color: null,
    colorRows: null,
    count: 0,
  );

  factory ModelLayer.fromJson(Object? raw) {
    final map = asMap(raw);
    return ModelLayer(
      y: asInt(map['y']),
      rows: [for (final row in asList(map['rows'])) asString(row)],
      cells: [
        for (final cell in asList(map['cells']))
          if (cell is List && cell.length >= 2) [asInt(cell[0]), asInt(cell[1])],
      ],
      module: [for (final item in asList(map['module'])) asString(item)],
      color: asStringOrNull(map['color']),
      colorRows: map['colorRows'] == null
          ? null
          : [for (final row in asList(map['colorRows'])) asString(row)],
      count: asInt(map['count']),
    );
  }
}

/// 体素字符的几何语义（与 leogod/geometry.py 保持一致；仅用于 3D 渲染识别）。
class VoxelChar {
  static const empty = '.';
  static const normal = '#';
  static const slopeXp = '/';
  static const slopeXm = r'\';
  static const slopeZm = '^';
  static const slopeZp = 'v';
  static const invSlopeWest = 'b';
  static const invSlopeEast = 'd';
  static const invSlopeNorth = 'p';
  static const invSlopeSouth = 'q';

  static const positiveSlopes = <String>{slopeXp, slopeXm, slopeZm, slopeZp};
  static const inverseSlopes = <String>{invSlopeWest, invSlopeEast, invSlopeNorth, invSlopeSouth};
  static const allSlopes = <String>{...positiveSlopes, ...inverseSlopes};

  /// 是否为实体（非空格）。
  static bool solid(String ch) => ch != empty && ch != ' ' && ch.isNotEmpty;
}

/// 体素坐标（x, y 层, z）。
class VoxelCoord {
  const VoxelCoord(this.x, this.y, this.z);

  final int x;
  final int y;
  final int z;

  @override
  bool operator ==(Object other) =>
      other is VoxelCoord && other.x == x && other.y == y && other.z == z;

  @override
  int get hashCode => Object.hash(x, y, z);
}

/// 设计模型（model_*.json）。
class ModelData {
  const ModelData({
    required this.name,
    required this.slug,
    required this.gridW,
    required this.gridD,
    required this.totalVoxels,
    required this.layers,
    required this.revision,
    required this.runId,
    required this.hasVoxelColors,
  });

  final String? name;
  final String? slug;
  final int gridW;
  final int gridD;
  final int totalVoxels;
  final List<ModelLayer> layers;
  final int? revision;
  final String? runId;
  final bool hasVoxelColors;

  int get layerCount => layers.length;

  /// 普通体素（'#'）。
  List<VoxelCoord> get normalVoxels {
    final out = <VoxelCoord>[];
    for (final layer in layers) {
      final rows = layer.rows;
      if (rows.isNotEmpty) {
        for (var z = 0; z < rows.length; z++) {
          final row = rows[z];
          for (var x = 0; x < row.length; x++) {
            final ch = row[x];
            if (ch == VoxelChar.normal) out.add(VoxelCoord(x, layer.y, z));
          }
        }
      } else {
        for (final cell in layer.cells) {
          if (cell.length >= 2) out.add(VoxelCoord(cell[0], layer.y, cell[1]));
        }
      }
    }
    return out;
  }

  /// 斜面体素：字符 → 坐标列表。
  Map<String, List<VoxelCoord>> get slopeVoxels {
    final out = <String, List<VoxelCoord>>{};
    for (final layer in layers) {
      final rows = layer.rows;
      if (rows.isEmpty) continue;
      for (var z = 0; z < rows.length; z++) {
        final row = rows[z];
        for (var x = 0; x < row.length; x++) {
          final ch = row[x];
          if (VoxelChar.allSlopes.contains(ch)) {
            (out[ch] ??= <VoxelCoord>[]).add(VoxelCoord(x, layer.y, z));
          }
        }
      }
    }
    return out;
  }

  /// 所有体素（普通 + 斜面）。
  List<VoxelCoord> get allVoxels {
    final normal = normalVoxels;
    for (final list in slopeVoxels.values) {
      normal.addAll(list);
    }
    return normal;
  }

  /// 层对象（按 y 索引）。
  ModelLayer? layerAt(int y) {
    for (final layer in layers) {
      if (layer.y == y) return layer;
    }
    return null;
  }

  factory ModelData.fromJson(Object? raw) {
    final map = asMap(raw);
    final grid = asMap(map['grid']);
    return ModelData(
      name: asStringOrNull(map['name']),
      slug: asStringOrNull(map['slug']),
      gridW: asInt(grid['w'], 0),
      gridD: asInt(grid['d'], 0),
      totalVoxels: asInt(map['totalVoxels']),
      layers: [for (final item in asList(map['layers'])) ModelLayer.fromJson(item)],
      revision: asIntOrNull(map['revision']),
      runId: asStringOrNull(map['runId']),
      hasVoxelColors: asBool(map['hasVoxelColors']),
    );
  }
}

/// 一条拼装步骤（solution_*.json 的 steps 项）。
class BrickStep {
  const BrickStep({
    required this.step,
    required this.layer,
    required this.piece,
    required this.x,
    required this.z,
    required this.w,
    required this.d,
    required this.rotate,
  });

  /// 步骤号，从 1 开始。
  final int step;

  /// 所在层 y。
  final int layer;

  /// 零件 ID。
  final String piece;

  /// 覆盖范围起点 x。
  final int x;

  /// 覆盖范围起点 z。
  final int z;

  /// 宽度（stud）。
  final int w;

  /// 深度（stud）。
  final int d;

  /// 是否水平旋转 90°。
  final bool rotate;

  /// x 覆盖范围终点（含）。
  int get xEnd => x + w - 1;

  /// z 覆盖范围终点（含）。
  int get zEnd => z + d - 1;

  /// 坐标范围文案。
  String get rangeText => 'x=$x..$xEnd，z=$z..$zEnd';

  factory BrickStep.fromJson(Object? raw) {
    final map = asMap(raw);
    return BrickStep(
      step: asInt(map['step']),
      layer: asInt(map['layer']),
      piece: asString(map['piece']),
      x: asInt(map['x']),
      z: asInt(map['z']),
      w: asInt(map['w'], 1),
      d: asInt(map['d'], 1),
      rotate: asBool(map['rotate']),
    );
  }
}

/// 预拼子组件（例如悬吊双耳：在主干上成组落位，不能拆成悬空单砖）。
class SubAssembly {
  const SubAssembly({
    required this.id,
    required this.bricks,
    required this.hangingBricks,
    required this.anchorBricks,
    required this.steps,
  });

  final String id;
  final List<int> bricks;
  final List<int> hangingBricks;
  final List<int> anchorBricks;

  /// 子组件成员步骤号（1 起），最后一个是扣合完成步。
  final List<int> steps;

  /// 成组落位步（子组件最后一个步骤）。
  int get dockStep => steps.isEmpty ? 0 : steps.last;

  factory SubAssembly.fromJson(Object? raw) {
    final map = asMap(raw);
    List<int> ints(Object? value) => [for (final item in asList(value)) asInt(item)];
    return SubAssembly(
      id: asString(map['id']),
      bricks: ints(map['bricks']),
      hangingBricks: ints(map['hangingBricks']),
      anchorBricks: ints(map['anchorBricks']),
      steps: ints(map['steps']),
    );
  }
}

/// 颜色回退记录（设计色库存不足时的真实回退事实）。
class ColorFallback {
  const ColorFallback({
    required this.layer,
    required this.target,
    required this.used,
  });

  final int layer;
  final String target;
  final Map<String, int> used;

  /// 展示文案。
  String get text {
    final parts = used.entries.map((e) => '${e.key}×${e.value}').join('、');
    return 'y=$layer 层设计色「$target」库存不足，回退使用 $parts';
  }

  factory ColorFallback.fromJson(Object? raw) {
    final map = asMap(raw);
    final used = <String, int>{};
    for (final entry in asMap(map['used']).entries) {
      used[entry.key] = asInt(entry.value);
    }
    return ColorFallback(
      layer: asInt(map['layer']),
      target: asString(map['target']),
      used: used,
    );
  }
}

/// 方案文件（solution_*.json）。
class SolutionData {
  const SolutionData({
    required this.model,
    required this.valid,
    required this.attempts,
    required this.strategy,
    required this.steps,
    required this.usage,
    required this.colors,
    required this.colorFallbacks,
    required this.subassemblies,
    required this.residualErrors,
    required this.validationOk,
    required this.validationRaw,
    required this.revision,
    required this.runId,
    required this.modelHash,
    required this.schemaVersion,
  });

  final String? model;
  final bool valid;
  final int attempts;
  final String? strategy;
  final List<BrickStep> steps;

  /// 零件 ID → 用量。
  final Map<String, int> usage;

  /// 颜色名 → 块数。
  final Map<String, int> colors;
  final List<ColorFallback> colorFallbacks;
  final List<SubAssembly> subassemblies;
  final List<String> residualErrors;

  /// 统一校验结论（validation.ok；旧方案没有该字段时按方案 valid 处理）。
  final bool validationOk;

  /// 统一校验原始对象（summary/checks/stability 等，用于复盘如实展示）。
  final Map<String, dynamic> validationRaw;
  final int? revision;
  final String? runId;
  final String? modelHash;
  final int? schemaVersion;

  /// 进度上限：步骤总数。
  int get stepCount => steps.length;

  /// 本方案零件总数必须等于步骤数。
  int get usageTotal => usage.values.fold(0, (sum, value) => sum + value);

  /// 用量与步骤数是否一致（不一致时 UI 要如实提示）。
  bool get usageMatchesSteps => usageTotal == stepCount;

  /// 统一校验摘要（如「覆盖通过、库存通过……」）。
  String? get validationSummary => asStringOrNull(validationRaw['summary']);

  /// 稳定性说明（来自统一校验 stability 字段）。
  String? get stabilityDetail {
    final stability = asMap(validationRaw['stability']);
    return asStringOrNull(stability['detail']);
  }

  /// 校验分项：key → (ok, detail)。
  List<MapEntry<String, Map<String, dynamic>>> get validationChecks {
    final checks = asMap(validationRaw['checks']);
    return [for (final entry in checks.entries) MapEntry(entry.key, asMap(entry.value))];
  }

  factory SolutionData.fromJson(Object? raw) {
    final map = asMap(raw);
    final usage = <String, int>{};
    for (final entry in asMap(map['usage']).entries) {
      usage[entry.key] = asInt(entry.value);
    }
    final colors = <String, int>{};
    for (final entry in asMap(map['colors']).entries) {
      colors[entry.key] = asInt(entry.value);
    }
    final validation = asMap(map['validation']);
    return SolutionData(
      model: asStringOrNull(map['model']),
      valid: asBool(map['valid']),
      attempts: asInt(map['attempts']),
      strategy: asStringOrNull(map['strategy']),
      steps: [for (final item in asList(map['steps'])) BrickStep.fromJson(item)],
      usage: usage,
      colors: colors,
      colorFallbacks: [
        for (final item in asList(map['colorFallbacks'])) ColorFallback.fromJson(item)
      ],
      subassemblies: [
        for (final item in asList(map['subassemblies'])) SubAssembly.fromJson(item)
      ],
      residualErrors: [for (final item in asList(map['residualErrors'])) asString(item)],
      validationOk: validation.isEmpty ? asBool(map['valid']) : asBool(validation['ok']),
      validationRaw: validation,
      revision: asIntOrNull(map['revision']),
      runId: asStringOrNull(map['runId']),
      modelHash: asStringOrNull(map['modelHash']),
      schemaVersion: asIntOrNull(map['schemaVersion']),
    );
  }
}

/// 某任务的全部 3D 产物（模型 + 方案 + 零件目录）。
class StudioArtifacts {
  const StudioArtifacts({
    required this.model,
    required this.solution,
    required this.parts,
  });

  final ModelData model;
  final SolutionData solution;
  final PartsCatalog parts;

  /// 拼装模拟的最终步与目标模型逐体素一致性检查：
  /// 每个方案步骤覆盖的格子都必须在模型实体内，且每个模型实体格都必须被某个步骤覆盖。
  /// 返回 null 表示一致，否则返回第一条不一致说明。
  String? verifyModelSolutionConsistency() {
    final expected = <String>{
      for (final voxel in model.allVoxels) '${voxel.x},${voxel.y},${voxel.z}',
    };
    final covered = <String>{};
    for (final step in solution.steps) {
      for (var i = 0; i < step.w; i++) {
        for (var j = 0; j < step.d; j++) {
          final key = '${step.x + i},${step.layer},${step.z + j}';
          if (!expected.contains(key)) return '第 ${step.step} 步覆盖了模型不存在的体素（$key）';
          covered.add(key);
        }
      }
    }
    if (covered.length != expected.length) {
      return '步骤覆盖 ${covered.length} 个体素，目标模型有 ${expected.length} 个体素';
    }
    return null;
  }
}
