// 测试夹具：全部使用真实契约字段（/api/parts、model_*.json、solution_*.json、设计稿快照）
// 构造数据，并统一走生产模型的 fromJson 解析，不使用 mock 替身。
import 'package:legogod_app/models/artifacts.dart';
import 'package:legogod_app/models/design.dart';
import 'package:legogod_app/models/part.dart';
import 'package:legogod_app/three_d/lego_scene.dart';

/// 红色（LEGO bright red）。
const String fixtureRedHex = '#C91A09';

/// 白色。
const String fixtureWhiteHex = '#F4F4F4';

/// 黄色。
const String fixtureYellowHex = '#F2CD37';

/// 构造一个普通砖零件（真实 /api/parts 字段）。
Part fixtureBrick({
  required String id,
  required String name,
  required int w,
  required int d,
  required String hex,
  required String colorName,
  bool hasStuds = true,
  int count = 100,
}) {
  return Part.fromJson(<String, Object?>{
    'id': id,
    'shape': id.replaceAll(RegExp(r'_[A-Z]+$'), ''),
    'name': name,
    'w': w,
    'd': d,
    'h': 1,
    'color': hex,
    'colorName': colorName,
    'colorKey': 'K_$id',
    'count': count,
    'hasStuds': hasStuds,
    'massFactor': 1,
  });
}

/// 构造一个斜坡零件（slope 字符、studMask / rootMask 均为真实契约字段）。
Part fixtureSlope({
  required String id,
  required String name,
  required String slope,
  required int w,
  required int d,
  String hex = fixtureYellowHex,
  String colorName = '黄色',
  bool hasStuds = false,
  List<List<int>>? studMask,
  List<List<int>>? rootMask,
}) {
  return Part.fromJson(<String, Object?>{
    'id': id,
    'shape': id,
    'name': name,
    'w': w,
    'd': d,
    'h': 1,
    'color': hex,
    'colorName': colorName,
    'colorKey': 'K_$id',
    'count': 50,
    'hasStuds': hasStuds,
    'studMask': ?studMask,
    'rootMask': ?rootMask,
    'slope': slope,
    'massFactor': 0.5,
  });
}

/// 夹具零件目录：普通砖 + 正斜坡 + 反斜坡（拼装/模型场景共用）。
PartsCatalog fixtureParts() => PartsCatalog(<Part>[
  fixtureBrick(
    id: 'B2x2_RED',
    name: '2x2 砖',
    w: 2,
    d: 2,
    hex: fixtureRedHex,
    colorName: '红色',
  ),
  fixtureBrick(
    id: 'B2x2_WHITE',
    name: '2x2 砖',
    w: 2,
    d: 2,
    hex: fixtureWhiteHex,
    colorName: '白色',
  ),
  fixtureSlope(
    id: 'SLOPE1_XP',
    name: '1x1 正斜坡(/ 高端在东)',
    slope: '/',
    w: 1,
    d: 1,
  ),
  fixtureSlope(
    id: 'SLOPE1_INV',
    name: '1x1 反斜坡(b 根部在西)',
    slope: 'b',
    w: 1,
    d: 1,
    rootMask: <List<int>>[
      <int>[0, 0],
    ],
  ),
]);

/// 一条拼装步骤的 JSON（真实 solution_*.json 字段）。
Map<String, Object?> fixtureStepJson({
  required int step,
  required int layer,
  required String piece,
  required int x,
  required int z,
  required int w,
  required int d,
  bool rotate = false,
}) {
  return <String, Object?>{
    'step': step,
    'layer': layer,
    'piece': piece,
    'x': x,
    'z': z,
    'w': w,
    'd': d,
    'rotate': rotate,
  };
}

/// 6 步拼装方案：4 块砖 + 正斜坡 + 反斜坡，其中第 3、4 步属于预拼子组件（dockStep = 4）。
SolutionData fixtureSolution() => SolutionData.fromJson(<String, Object?>{
  'model': 'fixture-model',
  'valid': true,
  'attempts': 1,
  'strategy': 'greedy',
  'steps': <Map<String, Object?>>[
    fixtureStepJson(
      step: 1,
      layer: 0,
      piece: 'B2x2_RED',
      x: 0,
      z: 0,
      w: 2,
      d: 2,
    ),
    fixtureStepJson(
      step: 2,
      layer: 0,
      piece: 'B2x2_WHITE',
      x: 2,
      z: 0,
      w: 2,
      d: 2,
    ),
    fixtureStepJson(
      step: 3,
      layer: 1,
      piece: 'B2x2_RED',
      x: 0,
      z: 0,
      w: 2,
      d: 2,
    ),
    fixtureStepJson(
      step: 4,
      layer: 1,
      piece: 'B2x2_WHITE',
      x: 2,
      z: 0,
      w: 2,
      d: 2,
    ),
    fixtureStepJson(
      step: 5,
      layer: 2,
      piece: 'SLOPE1_XP',
      x: 1,
      z: 0,
      w: 1,
      d: 1,
    ),
    fixtureStepJson(
      step: 6,
      layer: 2,
      piece: 'SLOPE1_INV',
      x: 2,
      z: 0,
      w: 1,
      d: 1,
      rotate: true,
    ),
  ],
  'usage': <String, int>{
    'B2x2_RED': 2,
    'B2x2_WHITE': 2,
    'SLOPE1_XP': 1,
    'SLOPE1_INV': 1,
  },
  'colors': <String, int>{'红色': 2, '白色': 2, '黄色': 2},
  'colorFallbacks': <Object?>[],
  'subassemblies': <Map<String, Object?>>[
    <String, Object?>{
      'id': 'sub1',
      'bricks': <int>[3, 4],
      'hangingBricks': <int>[],
      'anchorBricks': <int>[],
      'steps': <int>[3, 4],
    },
  ],
  'residualErrors': <String>[],
  'validation': <String, Object?>{'ok': true},
  'revision': 7,
  'runId': 'run-fixture',
  'modelHash': 'hash-fixture',
  'schemaVersion': 2,
});

/// 4×2 网格、3 层模型（y=2 层含普通体素与两种斜体，用于 ghost 数量断言）。
ModelData fixtureModel() => ModelData.fromJson(<String, Object?>{
  'name': '夹具模型',
  'slug': 'fixture-model',
  'grid': <String, Object?>{'w': 4, 'd': 2},
  'totalVoxels': 19,
  'layers': <Map<String, Object?>>[
    <String, Object?>{
      'y': 0,
      'rows': <String>['####', '####'],
      'module': <String>['车身'],
      'cells': <List<int>>[],
      'count': 8,
    },
    <String, Object?>{
      'y': 1,
      'rows': <String>['####', '####'],
      'module': <String>['车顶'],
      'cells': <List<int>>[],
      'count': 8,
    },
    <String, Object?>{
      'y': 2,
      'rows': <String>['#/b.', '....'],
      'module': <String>['装饰'],
      'cells': <List<int>>[],
      'count': 3,
    },
  ],
  'revision': 3,
  'runId': 'run-fixture',
  'hasVoxelColors': true,
});

/// 实时设计稿快照：2 层、彩色体素（palette + chars + colorRows 均为真实契约字段）。
DesignDraft fixtureDesign() => DesignDraft.fromJson(<String, Object?>{
  'name': '设计稿夹具',
  'slug': 'design-fixture',
  'grid': <String, Object?>{'w': 3, 'd': 2},
  'layers': <Map<String, Object?>>[
    <String, Object?>{
      'y': 0,
      'rows': <String>['##.', '.#.'],
      'color': '红色',
      'colorRows': <String>['A..', '...'],
    },
    <String, Object?>{
      'y': 1,
      'rows': <String>['...', '.#.'],
      'color': '白色',
      'colorRows': null,
    },
  ],
  'totalVoxels': 4,
  'revision': 5,
  'palette': <String, String>{
    '红色': '#C91A09',
    '白色': '#F4F4F4',
    '蓝色': '#0055BF',
  },
  'chars': <String, String>{'A': '蓝色'},
  'stamp': 'stamp-fixture',
});

/// 构造一个「单步」方案（用于斜坡方向/旋转等几何断言）。
SolutionData singleStepSolution({
  required String piece,
  required int w,
  required int d,
  bool rotate = false,
  int layer = 0,
  int x = 0,
  int z = 0,
}) {
  return SolutionData.fromJson(<String, Object?>{
    'valid': true,
    'attempts': 1,
    'steps': <Map<String, Object?>>[
      fixtureStepJson(
        step: 1,
        layer: layer,
        piece: piece,
        x: x,
        z: z,
        w: w,
        d: d,
        rotate: rotate,
      ),
    ],
    'usage': <String, int>{piece: 1},
    'colors': <String, int>{},
    'colorFallbacks': <Object?>[],
    'subassemblies': <Object?>[],
    'residualErrors': <String>[],
    'validation': <String, Object?>{'ok': true},
  });
}

/// 构造一个「单步」模型场景（用于斜坡方向 / 旋转等几何断言）。
Lego3DScene singleStepModel(
  Part part, {
  required int w,
  required int d,
  bool rotate = false,
}) {
  return LegoSceneBuilder.model(
    model: fixtureModel(),
    solution: singleStepSolution(piece: part.id, w: w, d: d, rotate: rotate),
    parts: PartsCatalog(<Part>[part]),
  );
}

/// 是否存在满足条件的面法线（场景几何断言通用工具）。
bool hasFaceNormal(
  LegoMesh mesh,
  bool Function(double nx, double ny, double nz) test,
) {
  final geometry = mesh.geometry;
  for (var face = 0; face < geometry.faceCount; face++) {
    final index = face * 3;
    final nx = geometry.faceNormals[index];
    final ny = geometry.faceNormals[index + 1];
    final nz = geometry.faceNormals[index + 2];
    if (test(nx, ny, nz)) return true;
  }
  return false;
}

/// 某个格子里是否有水平顶面（法线 +y、平面在 [planeY]），用于识别斜坡件里的满格单元。
bool hasHorizontalTopAt(
  LegoMesh mesh,
  double centerX,
  double centerZ, {
  double planeY = legoLayerHeight,
}) {
  final geometry = mesh.geometry;
  for (var face = 0; face < geometry.faceCount; face++) {
    final index = face * 3;
    if ((geometry.faceNormals[index + 1] - 1).abs() > 1e-6) continue;
    if ((geometry.facePlanes[face] - planeY).abs() > 1e-4) continue;
    var sumX = 0.0;
    var sumZ = 0.0;
    for (var corner = 0; corner < 3; corner++) {
      final vertex = (geometry.faceStarts[face] + corner) * 3;
      sumX += geometry.positions[vertex];
      sumZ += geometry.positions[vertex + 2];
    }
    if ((sumX / 3 - centerX).abs() < 0.5 && (sumZ / 3 - centerZ).abs() < 0.5) {
      return true;
    }
  }
  return false;
}
