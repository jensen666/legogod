// 纯 Dart 几何核算层：三角面片累加器 + 乐高基础形体（长方体、六边形凸点、斜坡楔形、底板）。
// 设计要点：
// - 构建期一次性烘焙「面法线、平面距离、明暗后的 ARGB」，渲染期只做投影与背面剔除；
// - 光照是固定方向 Lambert（顶面最亮、侧面次之、背光面最暗），与 Web viewer 顶亮侧暗一致；
// - 凸点规格：6 边形柱面（半径 0.3、高 0.18），与 web/viewer.js 的 STUD_R / STUD_H 一致；
// - 层高 1.2、1 stud = 1 单位，与 web/viewer.js 的 H 完全一致。
// 本文件不依赖 Flutter，可在纯 Dart 测试中直接使用；向量/包围盒与楔形面表拆在同库 part 文件中。
import 'dart:math' as math;
import 'dart:typed_data';

part 'lego_vector_part.dart';
part 'lego_geometry_data.dart';

/// 层高：1 stud = 1 单位，砖层高 1.2（web/viewer.js 的 H）。
const double legoLayerHeight = 1.2;

/// 凸点半径（web/viewer.js 的 STUD_R）。
const double legoStudRadius = 0.3;

/// 凸点高度（web/viewer.js 的 STUD_H）。
const double legoStudHeight = 0.18;

/// 底板厚度：底板顶面 y=0，向下延伸 0.4（web/viewer.js 的底板高度 0.4）。
const double legoBaseplateThickness = 0.4;

/// 底板绿色（web/viewer.js 与 AppColors.baseplate 均为 #237841）。
const int legoBaseplateColor = 0xFF237841;

/// 目标轮廓（ghost）灰色。
const int legoGhostColor = 0xFF9AA4AE;

/// 正斜坡低端高度占比（web/viewer.js：hLow = H * 0.35）。
const double legoSlopeLowRatio = 0.35;

/// 渲染期近裁剪距离。
const double legoNearPlane = 0.06;

/// 光照方向（单位向量，斜上方偏 +x/+z，与 Web viewer 双方向光叠加观感一致）。
const double _lightX = 0.32;
const double _lightY = 0.86;
const double _lightZ = 0.39;

/// 只读三角面片几何：构建完成后不再修改，渲染期零分配地顺序读取。
class MeshGeometry {
  MeshGeometry({
    required this.positions,
    required this.faceStarts,
    required this.faceNormals,
    required this.facePlanes,
    required this.faceColors,
    required this.bounds,
  });

  /// 世界坐标顶点：每个三角面 3 个顶点，共 `faceCount * 9` 个 float。
  final Float32List positions;

  /// 每个三角面第一个顶点在 [positions] 中的下标（每面固定 3 个顶点）。
  final Int32List faceStarts;

  /// 逐面单位法线（3 个 float 一面）。
  final Float32List faceNormals;

  /// 逐面平面常数 `d = n · 面内任意点`，背面剔除时与 `n · 相机位置` 比较。
  final Float32List facePlanes;

  /// 逐面 ARGB 颜色（已烘焙光照系数与透明度）。
  final Int32List faceColors;

  /// 几何包围盒（世界坐标）。
  final Bounds bounds;

  /// 三角面数量。
  int get faceCount => faceStarts.length;

  /// 顶点数量。
  int get vertexCount => positions.length ~/ 3;
}

/// 构建期几何累加器：追加三角面后冻结为 [MeshGeometry]。
/// 只在场景构建时使用，渲染期不产生任何临时对象。
class MeshDraft {
  MeshDraft({required this.baseColor, this.alpha = 1.0});

  /// 基础色（ARGB）。
  final int baseColor;

  /// 整体透明度（ghost 用，1 表示不透明）。
  final double alpha;

  final List<double> _positions = <double>[];
  final List<double> _normals = <double>[];
  final List<double> _planes = <double>[];
  final List<int> _faceColors = <int>[];

  double _minX = double.infinity;
  double _minY = double.infinity;
  double _minZ = double.infinity;
  double _maxX = double.negativeInfinity;
  double _maxY = double.negativeInfinity;
  double _maxZ = double.negativeInfinity;

  /// 已追加的三角面数量。
  int get triangleCount => _faceColors.length;

  /// 当前几何包围盒。
  Bounds get bounds =>
      Bounds(Vec3(_minX, _minY, _minZ), Vec3(_maxX, _maxY, _maxZ));

  /// 追加一个三角面。法线由调用方给出（单位向量、指向物体外侧），顶点顺序不参与剔除判断。
  void addTriangle(
    double ax,
    double ay,
    double az,
    double bx,
    double by,
    double bz,
    double cx,
    double cy,
    double cz,
    double nx,
    double ny,
    double nz,
  ) {
    final length = math.sqrt(nx * nx + ny * ny + nz * nz);
    if (length < 1e-9) return; // 退化面直接丢弃，避免 NaN
    final inv = 1 / length;
    final ux = nx * inv;
    final uy = ny * inv;
    final uz = nz * inv;
    _positions
      ..add(ax)
      ..add(ay)
      ..add(az)
      ..add(bx)
      ..add(by)
      ..add(bz)
      ..add(cx)
      ..add(cy)
      ..add(cz);
    _normals
      ..add(ux)
      ..add(uy)
      ..add(uz);
    _planes.add(ux * ax + uy * ay + uz * az);
    _faceColors.add(_shadedColor(_shadeOf(ux, uy, uz)));
    _includePoint(ax, ay, az);
    _includePoint(bx, by, bz);
    _includePoint(cx, cy, cz);
  }

  /// 轴对齐长方体（6 个面、12 个三角形）。
  void addBox(
    double x0,
    double y0,
    double z0,
    double x1,
    double y1,
    double z1,
  ) {
    // 顶面 / 底面
    _addQuad(x0, y1, z0, x1, y1, z0, x1, y1, z1, x0, y1, z1, 0, 1, 0);
    _addQuad(x0, y0, z0, x0, y0, z1, x1, y0, z1, x1, y0, z0, 0, -1, 0);
    // 前面（-z）/ 后面（+z）
    _addQuad(x0, y0, z0, x1, y0, z0, x1, y1, z0, x0, y1, z0, 0, 0, -1);
    _addQuad(x0, y0, z1, x0, y1, z1, x1, y1, z1, x1, y0, z1, 0, 0, 1);
    // 左面（-x）/ 右面（+x）
    _addQuad(x0, y0, z0, x0, y1, z0, x0, y1, z1, x0, y0, z1, -1, 0, 0);
    _addQuad(x1, y0, z0, x1, y0, z1, x1, y1, z1, x1, y1, z0, 1, 0, 0);
  }

  /// 完整凸点：6 边形柱面（侧面 6 个四边形 + 顶面 6 个三角形，底面被砖体遮挡不生成）。
  void addStud(double centerX, double baseY, double centerZ) {
    final topY = baseY + legoStudHeight;
    final radius = legoStudRadius;
    for (var k = 0; k < 6; k++) {
      final k2 = (k + 1) % 6;
      final x0 = centerX + radius * _hexUnitX[k];
      final z0 = centerZ + radius * _hexUnitZ[k];
      final x1 = centerX + radius * _hexUnitX[k2];
      final z1 = centerZ + radius * _hexUnitZ[k2];
      // 侧面：外向法线取两边中点方向
      final nx = math.cos((k + 0.5) * math.pi / 3);
      final nz = math.sin((k + 0.5) * math.pi / 3);
      _addQuad(
        x0,
        baseY,
        z0,
        x1,
        baseY,
        z1,
        x1,
        topY,
        z1,
        x0,
        topY,
        z0,
        nx,
        0,
        nz,
      );
      // 顶面
      addTriangle(centerX, topY, centerZ, x0, topY, z0, x1, topY, z1, 0, 1, 0);
    }
  }

  /// 只画顶面六边形的凸点（底板大量凸点用，省三角形）。
  void addStudTop(double centerX, double baseY, double centerZ) {
    final topY = baseY + legoStudHeight;
    final radius = legoStudRadius;
    for (var k = 0; k < 6; k++) {
      final k2 = (k + 1) % 6;
      addTriangle(
        centerX,
        topY,
        centerZ,
        centerX + radius * _hexUnitX[k],
        topY,
        centerZ + radius * _hexUnitZ[k],
        centerX + radius * _hexUnitX[k2],
        topY,
        centerZ + radius * _hexUnitZ[k2],
        0,
        1,
        0,
      );
    }
  }

  /// 绿色底板：厚 0.4 的平板 + 每格顶面六边形凸点（凸点只画顶面）。
  void addBaseplate({
    required int cellsX,
    required int cellsZ,
    double offsetX = -3,
    double offsetZ = -3,
  }) {
    addBox(
      offsetX.toDouble(),
      -legoBaseplateThickness,
      offsetZ.toDouble(),
      (offsetX + cellsX).toDouble(),
      0,
      (offsetZ + cellsZ).toDouble(),
    );
    for (var x = 0; x < cellsX; x++) {
      for (var z = 0; z < cellsZ; z++) {
        addStudTop(offsetX + x + 0.5, 0, offsetZ + z + 0.5);
      }
    }
  }

  /// 正斜坡单格楔形（字符 '/'、'\'、'^'、'v'；未知字符按满格方块降级，保证不崩溃）。
  void addSlopeCell(
    double originX,
    double originY,
    double originZ,
    String slopeChar,
  ) {
    final theta = _positiveSlopeRotations[slopeChar];
    if (theta == null) {
      addBox(
        originX,
        originY,
        originZ,
        originX + 1,
        originY + legoLayerHeight,
        originZ + 1,
      );
      return;
    }
    _addCellFaces(_positiveSlopeFaces, theta, originX, originY, originZ);
  }

  /// 反斜坡单格楔形（字符 'b'、'd'、'p'、'q'；未知字符按满格方块降级，保证不崩溃）。
  void addInverseSlopeCell(
    double originX,
    double originY,
    double originZ,
    String slopeChar,
  ) {
    final theta = _inverseSlopeRotations[slopeChar];
    if (theta == null) {
      addBox(
        originX,
        originY,
        originZ,
        originX + 1,
        originY + legoLayerHeight,
        originZ + 1,
      );
      return;
    }
    _addCellFaces(_inverseSlopeFaces, theta, originX, originY, originZ);
  }

  /// 冻结为只读几何。
  MeshGeometry build() {
    final faceCount = _faceColors.length;
    final faceStarts = Int32List(faceCount);
    for (var i = 0; i < faceCount; i++) {
      faceStarts[i] = i * 3;
    }
    return MeshGeometry(
      positions: Float32List.fromList(_positions),
      faceStarts: faceStarts,
      faceNormals: Float32List.fromList(_normals),
      facePlanes: Float32List.fromList(_planes),
      faceColors: Int32List.fromList(_faceColors),
      bounds: bounds,
    );
  }

  /// 追加四边形（两个三角形，共用同一法线）。
  void _addQuad(
    double x0,
    double y0,
    double z0,
    double x1,
    double y1,
    double z1,
    double x2,
    double y2,
    double z2,
    double x3,
    double y3,
    double z3,
    double nx,
    double ny,
    double nz,
  ) {
    addTriangle(x0, y0, z0, x1, y1, z1, x2, y2, z2, nx, ny, nz);
    addTriangle(x0, y0, z0, x2, y2, z2, x3, y3, z3, nx, ny, nz);
  }

  /// 单格楔形：先把局部顶点平移归零、绕 y 轴旋转，再落位到格子原点（与 Web viewer 一致）。
  void _addCellFaces(
    List<_CellFace> faces,
    double theta,
    double originX,
    double originY,
    double originZ,
  ) {
    final cosT = math.cos(theta);
    final sinT = math.sin(theta);
    final centerX = originX + 0.5;
    final centerZ = originZ + 0.5;
    for (final face in faces) {
      final normal = face.normal;
      final nx = normal[0];
      final ny = normal[1];
      final nz = normal[2];
      final rnx = nx * cosT + nz * sinT;
      final rnz = -nx * sinT + nz * cosT;
      final vertices = face.vertices;
      final count = vertices.length ~/ 3;
      // 扇形三角化（3 或 4 顶点多边形）
      for (var i = 1; i + 1 < count; i++) {
        final o0 = 0;
        final o1 = i * 3;
        final o2 = (i + 1) * 3;
        addTriangle(
          _rotateX(vertices[o0], vertices[o0 + 2], cosT, sinT, centerX),
          vertices[o0 + 1] + originY,
          _rotateZ(vertices[o0], vertices[o0 + 2], cosT, sinT, centerZ),
          _rotateX(vertices[o1], vertices[o1 + 2], cosT, sinT, centerX),
          vertices[o1 + 1] + originY,
          _rotateZ(vertices[o1], vertices[o1 + 2], cosT, sinT, centerZ),
          _rotateX(vertices[o2], vertices[o2 + 2], cosT, sinT, centerX),
          vertices[o2 + 1] + originY,
          _rotateZ(vertices[o2], vertices[o2 + 2], cosT, sinT, centerZ),
          rnx,
          ny,
          rnz,
        );
      }
    }
  }

  /// 局部 x → 世界 x（先减格子中心 0.5 再旋转）。
  static double _rotateX(
    double x,
    double z,
    double cosT,
    double sinT,
    double centerX,
  ) => (x - 0.5) * cosT + (z - 0.5) * sinT + centerX;

  /// 局部 z → 世界 z。
  static double _rotateZ(
    double x,
    double z,
    double cosT,
    double sinT,
    double centerZ,
  ) => -(x - 0.5) * sinT + (z - 0.5) * cosT + centerZ;

  /// 固定方向 Lambert 明暗系数：顶面最亮，法线越偏离光照越暗。
  static double _shadeOf(double nx, double ny, double nz) {
    final lambert = nx * _lightX + ny * _lightY + nz * _lightZ;
    final shade = 0.52 + 0.54 * (lambert > 0 ? lambert : 0);
    return shade.clamp(0.52, 1.02).toDouble();
  }

  /// 把明暗系数与整体透明度烘焙到 ARGB。
  int _shadedColor(double shade) {
    final baseAlpha = (baseColor >> 24) & 0xFF;
    final alphaValue = (baseAlpha * alpha).round().clamp(0, 255);
    final red = (((baseColor >> 16) & 0xFF) * shade).round().clamp(0, 255);
    final green = (((baseColor >> 8) & 0xFF) * shade).round().clamp(0, 255);
    final blue = ((baseColor & 0xFF) * shade).round().clamp(0, 255);
    return (alphaValue << 24) | (red << 16) | (green << 8) | blue;
  }

  /// 扩展包围盒以包含一个点。
  void _includePoint(double x, double y, double z) {
    if (x < _minX) _minX = x;
    if (x > _maxX) _maxX = x;
    if (y < _minY) _minY = y;
    if (y > _maxY) _maxY = y;
    if (z < _minZ) _minZ = z;
    if (z > _maxZ) _maxZ = z;
  }
}
