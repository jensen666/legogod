// lego_geometry.dart 的 part 文件：斜坡楔形面表、方向字符映射、6 边形圆顶点。
// 数据与主文件同属一个库；拆开只为单文件保持在 500 行以内。
part of 'lego_geometry.dart';

/// 单格楔形的一个平面（3 或 4 个局部顶点 + 法线）。
class _CellFace {
  const _CellFace(this.vertices, this.normal);

  final List<double> vertices;
  final List<double> normal;
}

final double _slopeLowHeight = legoLayerHeight * legoSlopeLowRatio;
final double _slopeHighHeight = legoLayerHeight;

/// 正斜坡标准姿态：低边在 -x、高边在 +x（web/viewer.js slopeGeo）。
final List<_CellFace> _positiveSlopeFaces = <_CellFace>[
  // 斜面（低边 -x → 高边 +x）
  _CellFace(
    <double>[
      0, _slopeLowHeight, 0, //
      0, _slopeLowHeight, 1,
      1, _slopeHighHeight, 1,
      1, _slopeHighHeight, 0,
    ],
    <double>[-(_slopeHighHeight - _slopeLowHeight), 1, 0],
  ),
  // 底面
  _CellFace(<double>[0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1], <double>[0, -1, 0]),
  // 高侧竖面（+x）
  _CellFace(
    <double>[
      1, 0, 0, //
      1, _slopeHighHeight, 0,
      1, _slopeHighHeight, 1,
      1, 0, 1,
    ],
    <double>[1, 0, 0],
  ),
  // 低侧竖面（-x）
  _CellFace(
    <double>[0, 0, 0, 0, 0, 1, 0, _slopeLowHeight, 1, 0, _slopeLowHeight, 0],
    <double>[-1, 0, 0],
  ),
  // z=0 侧
  _CellFace(
    <double>[0, 0, 0, 0, _slopeLowHeight, 0, 1, _slopeHighHeight, 0, 1, 0, 0],
    <double>[0, 0, -1],
  ),
  // z=1 侧
  _CellFace(
    <double>[0, 0, 1, 1, 0, 1, 1, _slopeHighHeight, 1, 0, _slopeLowHeight, 1],
    <double>[0, 0, 1],
  ),
];

/// 反斜坡标准姿态：根部在 -x 边、顶端在 +x 边（web/viewer.js invSlopeGeo）。
final List<_CellFace> _inverseSlopeFaces = <_CellFace>[
  // 顶面（平）
  _CellFace(
    <double>[
      0, _slopeHighHeight, 0, //
      1, _slopeHighHeight, 0,
      1, _slopeHighHeight, 1,
      0, _slopeHighHeight, 1,
    ],
    <double>[0, 1, 0],
  ),
  // 根部竖面（-x，满高）
  _CellFace(
    <double>[0, 0, 0, 0, 0, 1, 0, _slopeHighHeight, 1, 0, _slopeHighHeight, 0],
    <double>[-1, 0, 0],
  ),
  // 底面斜挑（从根底到尖端顶）
  _CellFace(
    <double>[0, 0, 0, 1, _slopeHighHeight, 0, 1, _slopeHighHeight, 1, 0, 0, 1],
    <double>[_slopeHighHeight, -1, 0],
  ),
  // z=0 侧
  _CellFace(
    <double>[0, 0, 0, 0, _slopeHighHeight, 0, 1, _slopeHighHeight, 0, 1, 0, 0],
    <double>[0, 0, -1],
  ),
  // z=1 侧
  _CellFace(
    <double>[0, 0, 1, 1, 0, 1, 1, _slopeHighHeight, 1, 0, _slopeHighHeight, 1],
    <double>[0, 0, 1],
  ),
];

/// 正斜坡字符 → 绕 y 轴旋转角（web/viewer.js：'/'→XP，'\'→XM，'^'→ZM，'v'→ZP）。
const Map<String, double> _positiveSlopeRotations = <String, double>{
  '/': 0,
  r'\': math.pi,
  '^': math.pi / 2,
  'v': -math.pi / 2,
};

/// 反斜坡字符 → 绕 y 轴旋转角（web/viewer.js：b→W，d→E，p→N，q→S）。
const Map<String, double> _inverseSlopeRotations = <String, double>{
  'b': 0,
  'd': math.pi,
  'p': -math.pi / 2,
  'q': math.pi / 2,
};

/// 6 边形单位圆顶点（凸点柱面用）。
final Float64List _hexUnitX = Float64List.fromList(<double>[
  for (var k = 0; k < 6; k++) math.cos(k * math.pi / 3),
]);
final Float64List _hexUnitZ = Float64List.fromList(<double>[
  for (var k = 0; k < 6; k++) math.sin(k * math.pi / 3),
]);
