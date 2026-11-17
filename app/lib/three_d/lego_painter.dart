// 软渲染画笔：透视投影 + 逐零件视深排序（远→近）+ 逐面背面剔除，
// 把三角面片批量写入复用的 Float32List / Int32List，每个绘制批次只调用一次 canvas.drawVertices。
// 性能约定：
// - 光照与颜色在场景构建期烘焙，渲染期零光照计算；
// - 缓冲区按场景规模一次性扩容后复用，渲染期不 new 顶点/颜色数组；
// - 每个零件只把朝向相机的面写进批处理，隐藏面完全不参与投影与绘制；
// - 无动画时重绘只由 controller.notifyListeners 触发（CustomPainter 的 repaint 参数），不常驻 Ticker。
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart' show CustomPainter;

import 'lego_camera.dart';
import 'lego_scene.dart';

/// 三角面批处理：扩容策略为「按需翻倍」，渲染期只写不分配。
/// 顶点坐标为屏幕空间的 2D 点（每个三角面 3 个顶点 × (x, y) = 6 个 float），
/// 颜色为每个顶点 1 个 ARGB int（与 Vertices.raw 的布局一致）。
class _TriangleBatch {
  Float32List _positions = Float32List(6 * 256);
  Int32List _colors = Int32List(3 * 256);
  int _triangleCount = 0;

  /// 当前批次内三角面数量。
  int get triangleCount => _triangleCount;

  /// 清空本帧数据（不释放缓冲区）。
  void reset() {
    _triangleCount = 0;
  }

  /// 保证能容纳至少 [triangles] 个三角面；容量足够时零分配。
  void ensureCapacity(int triangles) {
    final required = triangles * 6;
    if (required <= _positions.length) return;
    var capacity = _positions.length;
    while (capacity < required) {
      capacity *= 2;
    }
    final positions = Float32List(capacity);
    final colors = Int32List(capacity ~/ 2);
    positions.setRange(0, _triangleCount * 6, _positions);
    colors.setRange(0, _triangleCount * 3, _colors);
    _positions = positions;
    _colors = colors;
  }

  /// 追加一个屏幕空间三角面（顶点顺序无要求，不参与背面剔除判断）。
  void addTriangle(
    double x0,
    double y0,
    double x1,
    double y1,
    double x2,
    double y2,
    int color,
  ) {
    final positionIndex = _triangleCount * 6;
    final positions = _positions;
    positions[positionIndex] = x0;
    positions[positionIndex + 1] = y0;
    positions[positionIndex + 2] = x1;
    positions[positionIndex + 3] = y1;
    positions[positionIndex + 4] = x2;
    positions[positionIndex + 5] = y2;
    final colorIndex = _triangleCount * 3;
    final colors = _colors;
    colors[colorIndex] = color;
    colors[colorIndex + 1] = color;
    colors[colorIndex + 2] = color;
    _triangleCount++;
  }

  /// 生成可绘制的顶点对象（无数据返回 null）。
  ui.Vertices? buildVertices() {
    if (_triangleCount == 0) return null;
    final positions = Float32List.view(
      _positions.buffer,
      _positions.offsetInBytes,
      _triangleCount * 6,
    );
    final colors = Int32List.view(
      _colors.buffer,
      _colors.offsetInBytes,
      _triangleCount * 3,
    );
    return ui.Vertices.raw(ui.VertexMode.triangles, positions, colors: colors);
  }
}

/// LEGO 3D 软渲染画笔。
class LegoPainter extends CustomPainter {
  LegoPainter({required this.controller}) : super(repaint: controller);

  /// 渲染控制器（同时是重绘通知源）。
  final Lego3DController controller;

  final _TriangleBatch _baseplateBatch = _TriangleBatch();
  final _TriangleBatch _ghostBatch = _TriangleBatch();
  final _TriangleBatch _solidBatch = _TriangleBatch();

  final List<int> _order = <int>[];
  List<double> _solidDepths = <double>[];
  List<double> _ghostDepths = <double>[];

  final Float64List _screenX = Float64List(3);
  final Float64List _screenY = Float64List(3);

  final ui.Paint _paint = ui.Paint()
    ..color = const ui.Color(0xFFFFFFFF)
    ..isAntiAlias = false;

  /// 顶点色即最终颜色（BlendMode.dst），半透明 ghost 由顶点 alpha 完成混合。
  static const ui.BlendMode _blendMode = ui.BlendMode.dst;

  int _solidCapacityHint = -1;
  int _ghostCapacityHint = -1;
  int _baseplateCapacityHint = -1;
  int _lastTriangleCount = 0;

  /// 最近一帧实际提交的三角面数量（测试与性能观测用）。
  int get lastTriangleCount => _lastTriangleCount;

  /// 最近一帧可见零件数量（测试与性能观测用）。
  int get lastVisibleMeshCount => _lastVisibleMeshCount;
  int _lastVisibleMeshCount = 0;

  @override
  void paint(ui.Canvas canvas, ui.Size size) {
    final scene = controller.scene;
    if (scene == null || size.width < 1 || size.height < 1) {
      _lastTriangleCount = 0;
      _lastVisibleMeshCount = 0;
      return;
    }
    final frame = controller.camera.frameFor(size);
    _prepareCapacity(scene);
    _baseplateBatch.reset();
    _ghostBatch.reset();
    _solidBatch.reset();
    _lastVisibleMeshCount = 0;

    // 绘制顺序即画家算法顺序：底板 → 目标轮廓 ghost → 实体零件（远→近）。
    final baseplate = scene.baseplate;
    if (baseplate != null) {
      _appendMesh(_baseplateBatch, baseplate, frame, 0);
    }
    if (controller.showGhost && scene.ghostMeshes.isNotEmpty) {
      _appendSorted(
        _ghostBatch,
        scene.ghostMeshes,
        null,
        frame,
        depths: _ghostDepths,
        applyDrop: false,
      );
    }
    _appendSorted(
      _solidBatch,
      scene.meshes,
      controller.visibleStep,
      frame,
      depths: _solidDepths,
      applyDrop: true,
    );

    _lastTriangleCount =
        _baseplateBatch.triangleCount +
        _ghostBatch.triangleCount +
        _solidBatch.triangleCount;
    _drawBatch(canvas, _baseplateBatch);
    _drawBatch(canvas, _ghostBatch);
    _drawBatch(canvas, _solidBatch);
  }

  @override
  bool shouldRepaint(covariant LegoPainter oldDelegate) =>
      oldDelegate.controller != controller;

  /// 按场景规模预扩容缓冲区（只在场景变化时发生，渲染期零分配）。
  void _prepareCapacity(Lego3DScene scene) {
    var solidFaces = 0;
    for (final mesh in scene.meshes) {
      solidFaces += mesh.faceCount;
    }
    if (solidFaces != _solidCapacityHint) {
      _solidCapacityHint = solidFaces;
      _solidBatch.ensureCapacity(solidFaces);
    }
    var ghostFaces = 0;
    for (final mesh in scene.ghostMeshes) {
      ghostFaces += mesh.faceCount;
    }
    if (ghostFaces != _ghostCapacityHint) {
      _ghostCapacityHint = ghostFaces;
      _ghostBatch.ensureCapacity(ghostFaces);
    }
    final baseplateFaces = scene.baseplate?.faceCount ?? 0;
    if (baseplateFaces != _baseplateCapacityHint) {
      _baseplateCapacityHint = baseplateFaces;
      _baseplateBatch.ensureCapacity(baseplateFaces);
    }
  }

  /// 收集可见零件，按相机空间视深从远到近排序后逐件写入批次。
  void _appendSorted(
    _TriangleBatch batch,
    List<LegoMesh> meshes,
    int? visibleStep,
    CameraFrame frame, {
    required bool applyDrop,
    required List<double> depths,
  }) {
    if (depths.length != meshes.length) {
      depths = List<double>.filled(meshes.length, 0);
      if (applyDrop) {
        _solidDepths = depths;
      } else {
        _ghostDepths = depths;
      }
    }
    final forward = frame.forward;
    final offset = forward.dot(frame.position);
    final order = _order..clear();
    for (var i = 0; i < meshes.length; i++) {
      final mesh = meshes[i];
      depths[i] = forward.dot(mesh.center) - offset;
      if (visibleStep == null || mesh.dockStep <= visibleStep) order.add(i);
    }
    // 远→近：深度大的先画
    order.sort((a, b) => depths[b].compareTo(depths[a]));
    final dropOffsets = applyDrop ? controller.dropOffsets : null;
    for (final index in order) {
      final mesh = meshes[index];
      var lift = 0.0;
      if (dropOffsets != null && index < dropOffsets.length) {
        lift = dropOffsets[index];
      }
      _appendMesh(batch, mesh, frame, lift);
    }
    if (applyDrop) {
      _lastVisibleMeshCount = order.length;
    }
  }

  /// 把一个零件所有朝向相机的面投影后写入批次。
  ///
  /// 背面剔除用「面法线点乘相机位置 > 面平面常数」的预计算形式，逐面只做一次点积；
  /// 顶点只做「相机空间投影 + 透视除法」，没有任何矩阵对象分配。
  void _appendMesh(
    _TriangleBatch batch,
    LegoMesh mesh,
    CameraFrame frame,
    double lift,
  ) {
    final geometry = mesh.geometry;
    final positions = geometry.positions;
    final normals = geometry.faceNormals;
    final planes = geometry.facePlanes;
    final faceColors = geometry.faceColors;
    final faceStarts = geometry.faceStarts;
    final faceCount = geometry.faceCount;

    final position = frame.position;
    final camX = position.x;
    final camY = position.y;
    final camZ = position.z;

    final forward = frame.forward;
    final fx = forward.x;
    final fy = forward.y;
    final fz = forward.z;

    final right = frame.right;
    final rx = right.x;
    final ry = right.y;
    final rz = right.z;

    final up = frame.up;
    final ux = up.x;
    final uy = up.y;
    final uz = up.z;

    final focal = frame.focalPixels;
    final halfWidth = frame.halfWidth;
    final halfHeight = frame.halfHeight;
    final near = frame.nearPlane;

    final screenX = _screenX;
    final screenY = _screenY;

    var normalIndex = 0;
    for (var face = 0; face < faceCount; face++) {
      final nx = normals[normalIndex];
      final ny = normals[normalIndex + 1];
      final nz = normals[normalIndex + 2];
      normalIndex += 3;
      // 背面剔除：背面（含侧向不可见面）完全跳过，不参与投影
      if (nx * camX + ny * camY + nz * camZ <= planes[face]) continue;

      var valid = true;
      var vertex = faceStarts[face] * 3;
      for (var corner = 0; corner < 3; corner++) {
        final dx = positions[vertex] - camX;
        final dy = positions[vertex + 1] + lift - camY;
        final dz = positions[vertex + 2] - camZ;
        vertex += 3;
        final depth = fx * dx + fy * dy + fz * dz;
        if (depth <= near) {
          // 该面有顶点越过近裁剪面：整面丢弃（相机距离有最小值，正常取景不会触发）
          valid = false;
          break;
        }
        final factor = focal / depth;
        screenX[corner] = halfWidth + (rx * dx + ry * dy + rz * dz) * factor;
        screenY[corner] = halfHeight - (ux * dx + uy * dy + uz * dz) * factor;
      }
      if (!valid) continue;
      batch.addTriangle(
        screenX[0],
        screenY[0],
        screenX[1],
        screenY[1],
        screenX[2],
        screenY[2],
        faceColors[face],
      );
    }
  }

  /// 提交一个批次：一次 drawVertices 画完，随即释放原生顶点内存。
  void _drawBatch(ui.Canvas canvas, _TriangleBatch batch) {
    final vertices = batch.buildVertices();
    if (vertices == null) return;
    canvas.drawVertices(vertices, _blendMode, _paint);
    vertices.dispose();
  }
}
