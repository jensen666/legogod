// 轨道相机 + 透视投影 + 3D 渲染控制器。
// - 相机用球面坐标（yaw / pitch / distance）围绕 target，Y 轴向上，透视投影；
// - 所有输入都有边界 clamp，非法值直接忽略，绝不产生 NaN；
// - 控制器只在状态变化时 notifyListeners；渲染层用 `repaint: controller` 按需重绘，
//   因此没有动画时不会常驻 Ticker。
// 本文件依赖 Flutter foundation（ChangeNotifier）与 dart:ui 的 Offset/Size，不依赖渲染层。
import 'dart:math' as math;
import 'dart:ui' show Offset, Size;

import 'package:flutter/foundation.dart';

import 'lego_scene.dart';

/// 透视相机的一帧基向量与投影参数（渲染期每个 paint 计算一次，逐顶点复用）。
class CameraFrame {
  CameraFrame();

  /// 相机位置（世界坐标）。
  Vec3 position = Vec3.zero;

  /// 视线方向（单位向量，指向 target）。
  Vec3 forward = const Vec3(0, 0, -1);

  /// 相机右方向（单位向量）。
  Vec3 right = const Vec3(1, 0, 0);

  /// 相机上方向（单位向量）。
  Vec3 up = const Vec3(0, 1, 0);

  /// 焦距（像素）：`halfHeight / tan(fov/2)`。
  double focalPixels = 1;

  /// 视口半宽（像素）。
  double halfWidth = 0;

  /// 视口半高（像素）。
  double halfHeight = 0;

  /// 近裁剪距离。
  final double nearPlane = legoNearPlane;

  /// 点到相机的视深（正数表示在相机前方）。
  double depthOf(Vec3 point) =>
      forward.x * (point.x - position.x) +
      forward.y * (point.y - position.y) +
      forward.z * (point.z - position.z);

  /// 世界坐标 → 屏幕坐标；在近裁剪面之后返回 null。
  Offset? project(Vec3 point) {
    final dx = point.x - position.x;
    final dy = point.y - position.y;
    final dz = point.z - position.z;
    final depth = forward.x * dx + forward.y * dy + forward.z * dz;
    if (depth <= nearPlane) return null;
    final cameraX = right.x * dx + right.y * dy + right.z * dz;
    final cameraY = up.x * dx + up.y * dy + up.z * dz;
    final factor = focalPixels / depth;
    return Offset(halfWidth + cameraX * factor, halfHeight - cameraY * factor);
  }

  /// 按相机与视口刷新本帧基向量。
  void update(Lego3DCamera camera, Size viewport) {
    position = camera.position;
    forward = (camera.target - position).normalized;
    if (forward.length < 1e-9) forward = const Vec3(0, 0, -1);
    var rightVector = forward.cross(const Vec3(0, 1, 0));
    if (rightVector.length < 1e-6) rightVector = const Vec3(1, 0, 0);
    right = rightVector.normalized;
    up = right.cross(forward);
    halfWidth = viewport.width / 2;
    halfHeight = viewport.height / 2;
    focalPixels = halfHeight / math.tan(camera.halfFovRadians);
  }
}

/// 轨道相机：yaw / pitch / distance / target + 透视投影。
class Lego3DCamera {
  Lego3DCamera({
    this.yaw = defaultYaw,
    this.pitch = defaultPitch,
    this.distance = 24,
    Vec3? target,
    this.fovDegrees = 40,
  }) : target = target ?? Vec3.zero;

  /// 默认朝向：与 web/viewer.js fitCam 的 (0.55, 0.82, 0.92) 方向一致。
  static const double defaultYaw = 0.539;
  static const double defaultPitch = 0.653;

  /// pitch 下限（约 -80°）。
  static const double minPitch = -1.4;

  /// pitch 上限（约 +80°）。
  static const double maxPitch = 1.4;

  /// 每像素 yaw 旋转灵敏度。
  static const double yawPerPixel = 0.008;

  /// 每像素 pitch 旋转灵敏度。
  static const double pitchPerPixel = 0.006;

  /// 水平旋转角（弧度）。
  double yaw;

  /// 俯仰角（弧度，clamp 在 [minPitch, maxPitch]）。
  double pitch;

  /// 相机到 target 的距离。
  double distance;

  /// 观察目标点。
  Vec3 target;

  /// 垂直视场角（度）。
  double fovDegrees;

  /// 最近距离（随场景包围盒更新）。
  double minDistance = 1.0;

  /// 最远距离（随场景包围盒更新）。
  double maxDistance = 400.0;

  final CameraFrame _frame = CameraFrame();

  /// 垂直半视场角（弧度）。
  double get halfFovRadians => fovDegrees * math.pi / 360;

  /// 相机世界坐标。
  Vec3 get position {
    final cosPitch = math.cos(pitch);
    return target +
        Vec3(
              math.sin(yaw) * cosPitch,
              math.sin(pitch),
              math.cos(yaw) * cosPitch,
            ) *
            distance;
  }

  /// 复用的本帧基向量（先调用 [frameFor] 刷新）。
  CameraFrame get frame => _frame;

  /// 刷新并返回本帧基向量（渲染期每帧一次，无对象分配）。
  CameraFrame frameFor(Size viewport) {
    _frame.update(this, viewport);
    return _frame;
  }

  /// 单指拖动旋转：水平拖动改 yaw、垂直拖动改 pitch，pitch 超出 [-1.4, 1.4] 自动 clamp。
  void rotateBy(Offset delta) {
    if (!delta.dx.isFinite || !delta.dy.isFinite) return;
    yaw = _wrapAngle(yaw - delta.dx * yawPerPixel);
    pitch = (pitch + delta.dy * pitchPerPixel)
        .clamp(minPitch, maxPitch)
        .toDouble();
  }

  /// 双指缩放：scale > 1 拉近（distance 变小），distance 始终有最小值。
  void zoomBy(double scale) {
    if (!scale.isFinite || scale <= 0) return;
    distance = (distance / scale).clamp(minDistance, maxDistance).toDouble();
  }

  /// 双指平移：内容跟随手指移动。
  void panBy(Offset delta, {Size viewport = const Size(400, 400)}) {
    if (!delta.dx.isFinite || !delta.dy.isFinite) return;
    final current = frameFor(viewport);
    final height = math.max(1.0, viewport.height);
    final worldPerPixel = 2 * distance * math.tan(halfFovRadians) / height;
    target =
        target -
        current.right * (delta.dx * worldPerPixel) +
        current.up * (delta.dy * worldPerPixel);
  }

  /// 按场景包围盒更新 distance 上下限（换场景保留视角时也要保证缩放边界正确）。
  void applyBoundsLimits(Bounds bounds) {
    if (bounds.isEmpty) {
      minDistance = 1.0;
      maxDistance = 400.0;
      distance = distance.clamp(minDistance, maxDistance).toDouble();
      return;
    }
    final radius = math.max(0.6, bounds.radius);
    // 下限取包围球半径，避免缩放时相机钻进模型内部导致整面被近裁剪丢弃
    minDistance = math.max(0.8, radius * 1.02);
    maxDistance = math.max(60.0, radius * 12);
    distance = distance.clamp(minDistance, maxDistance).toDouble();
  }

  /// 按包围盒自动取景：target 取盒中心，distance 按 Web preview 的比例计算。
  void fitTo(Bounds bounds, {bool resetAngles = false}) {
    applyBoundsLimits(bounds);
    if (bounds.isEmpty) {
      target = Vec3.zero;
      distance = 24.0.clamp(minDistance, maxDistance).toDouble();
      if (resetAngles) {
        yaw = defaultYaw;
        pitch = defaultPitch;
      }
      return;
    }
    target = bounds.center;
    final radius = math.max(0.6, bounds.radius);
    // 与 web/preview.js fitCamera 一致：radius / sin(fov/2) * 1.15
    final fitted = radius / math.sin(halfFovRadians) * 1.15;
    distance = fitted.clamp(minDistance, maxDistance).toDouble();
    if (resetAngles) {
      yaw = defaultYaw;
      pitch = defaultPitch;
    }
  }

  /// 世界坐标 → 屏幕坐标（测试与页面标注用；渲染走 CameraFrame 内联计算）。
  Offset? project(Vec3 point, Size viewport) =>
      frameFor(viewport).project(point);

  /// 角度归一化到 [-pi, pi]，避免长时间旋转后数值过大。
  static double _wrapAngle(double angle) {
    var value = angle;
    while (value > math.pi) {
      value -= math.pi * 2;
    }
    while (value < -math.pi) {
      value += math.pi * 2;
    }
    return value;
  }
}

/// 3D 渲染控制器：场景、可见步骤、ghost 开关、相机操作与落位动画状态。
class Lego3DController extends ChangeNotifier {
  Lego3DController({Lego3DCamera? camera}) : camera = camera ?? Lego3DCamera();

  /// 落位动画初始抬高量（单位：stud，与 Web viewer 的 2.5 一致）。
  static const double dropHeight = 2.5;

  /// 落位动画时长（Web viewer 为 0.25s）。
  static const Duration dropDuration = Duration(milliseconds: 250);

  /// 轨道相机。
  final Lego3DCamera camera;

  Lego3DScene? _scene;
  int? _visibleStep;
  bool _showGhost = true;
  bool _animationsEnabled = true;
  bool _userAdjusted = false;
  bool _disposed = false;
  Size _viewport = const Size(400, 400);

  Float32List? _dropOffsets;
  final List<int> _dropMeshIndices = <int>[];

  /// 当前场景（null 表示还没有数据）。
  Lego3DScene? get scene => _scene;

  /// 可见步骤（null 表示全部可见；拼装模拟里 0 表示只剩底板与 ghost）。
  int? get visibleStep => _visibleStep;

  /// 是否显示目标轮廓 ghost。
  bool get showGhost => _showGhost;

  /// 是否允许播放落位动画（系统「减少动态效果」时由视图置 false）。
  bool get animationsEnabled => _animationsEnabled;

  /// 设置是否允许播放落位动画；关闭时立即结束进行中的动画（内容不变）。
  set animationsEnabled(bool value) {
    if (_animationsEnabled == value) return;
    _animationsEnabled = value;
    if (!value) endDropAnimation();
  }

  /// 用户是否手动调整过视角（换场景时决定是否保留视角）。
  bool get isUserAdjusted => _userAdjusted;

  /// 视图最近一次布局的尺寸（双指平移的像素→世界换算依据）。
  Size get viewport => _viewport;

  /// 场景步骤总数（无场景为 0）。
  int get stepCount => _scene?.stepCount ?? 0;

  /// 是否有进行中的落位动画。
  bool get hasDropAnimation => _dropOffsets != null;

  /// 逐零件下落偏移（下标与 `scene.meshes` 一致；无动画时为 null，渲染层零分配读取）。
  Float32List? get dropOffsets => _dropOffsets;

  /// 当前步骤下可见的实体零件（用于页面统计与测试）。
  List<LegoMesh> get visibleMeshes {
    final scene = _scene;
    if (scene == null) return const <LegoMesh>[];
    final step = _visibleStep;
    if (step == null) return scene.meshes;
    return <LegoMesh>[
      for (final mesh in scene.meshes)
        if (mesh.dockStep <= step) mesh,
    ];
  }

  /// 当前步骤下可见的实体零件数量。
  int get visibleMeshCount {
    final scene = _scene;
    if (scene == null) return 0;
    final step = _visibleStep;
    if (step == null) return scene.meshes.length;
    var count = 0;
    for (final mesh in scene.meshes) {
      if (mesh.dockStep <= step) count++;
    }
    return count;
  }

  /// 记录视图尺寸（布局期调用；不触发通知，避免布局期重绘循环）。
  void setViewport(Size size) {
    if (size == _viewport) return;
    _viewport = size;
  }

  /// 挂载场景。
  /// - `keepCamera` 为 true 且用户已手动调整过视角时保留当前视角，否则按包围盒取景；
  /// - 设计稿换稿时页面应传 `keepCamera: true`，这样没动过视角会重新取景、动过则保持。
  void attachScene(Lego3DScene? scene, {bool keepCamera = false}) {
    final isFirst = _scene == null;
    _scene = scene;
    _visibleStep = _clampStep(_visibleStep);
    _cancelDrop();
    if (scene == null) {
      _visibleStep = null;
      camera.fitTo(Bounds.empty, resetAngles: true);
    } else if (isFirst || !keepCamera || !_userAdjusted) {
      camera.fitTo(scene.bounds, resetAngles: isFirst || !_userAdjusted);
    } else {
      // 保留用户视角，仅更新缩放边界
      camera.applyBoundsLimits(scene.bounds);
    }
    _notify();
  }

  /// 设置可见步骤（null = 全部可见）。
  /// 步骤增加时对新出现的零件启动 250ms 落位动画（系统减少动态效果时立即到位）。
  void setVisibleStep(int? step) {
    final next = _clampStep(step);
    if (next == _visibleStep) return;
    final previous = _visibleStep;
    _visibleStep = next;
    if (previous != null && next != null && next > previous) {
      _beginDrop(previous, next);
    } else {
      _cancelDrop();
    }
    _notify();
  }

  /// 开关目标轮廓 ghost。
  void setShowGhost(bool show) {
    if (_showGhost == show) return;
    _showGhost = show;
    _notify();
  }

  /// 单指拖动旋转。
  void rotateBy(Offset delta) {
    if (delta.dx == 0 && delta.dy == 0) return;
    camera.rotateBy(delta);
    _userAdjusted = true;
    _notify();
  }

  /// 双指缩放（scale > 1 拉近）。
  void zoomBy(double scale) {
    if (!scale.isFinite || scale <= 0) return;
    final before = camera.distance;
    camera.zoomBy(scale);
    if ((camera.distance - before).abs() < 1e-12) return; // 已到缩放边界，无需重绘
    _userAdjusted = true;
    _notify();
  }

  /// 双指平移。
  void panBy(Offset delta) {
    if (delta.dx == 0 && delta.dy == 0) return;
    camera.panBy(delta, viewport: _viewport);
    _userAdjusted = true;
    _notify();
  }

  /// 重置视角：按当前场景包围盒重新取景并恢复默认朝向。
  void resetView() {
    _cancelDrop();
    camera.fitTo(_scene?.bounds ?? Bounds.empty, resetAngles: true);
    _userAdjusted = false;
    _notify();
  }

  /// 落位动画推进（0..1）；到 1 时自动结束。
  void updateDropAnimation(double progress) {
    final offsets = _dropOffsets;
    if (offsets == null) return;
    final clamped = progress.isFinite
        ? progress.clamp(0.0, 1.0).toDouble()
        : 1.0;
    if (clamped >= 1.0) {
      endDropAnimation();
      return;
    }
    final eased = 1 - math.pow(1 - clamped, 3).toDouble();
    final lift = dropHeight * (1 - eased);
    for (final index in _dropMeshIndices) {
      if (index >= 0 && index < offsets.length) offsets[index] = lift;
    }
    _notify();
  }

  /// 立即结束落位动画（内容不变，零件直接到位）。
  void endDropAnimation() {
    if (_dropOffsets == null) return;
    _dropOffsets = null;
    _dropMeshIndices.clear();
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _dropOffsets = null;
    _dropMeshIndices.clear();
    super.dispose();
  }

  /// 安全通知：dispose 之后不再通知，避免页面晚到的回调报错。
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  /// 取消未完成的落位动画（不单独通知，由调用方统一通知）。
  void _cancelDrop() {
    _dropOffsets = null;
    _dropMeshIndices.clear();
  }

  /// 对 (previous, next] 之间新出现的零件启动落位动画。
  void _beginDrop(int previous, int next) {
    final scene = _scene;
    if (scene == null || !_animationsEnabled) return;
    _dropMeshIndices.clear();
    for (var i = 0; i < scene.meshes.length; i++) {
      final dockStep = scene.meshes[i].dockStep;
      if (dockStep > previous && dockStep <= next) _dropMeshIndices.add(i);
    }
    if (_dropMeshIndices.isEmpty) return;
    var offsets = _dropOffsets;
    if (offsets == null || offsets.length != scene.meshes.length) {
      offsets = Float32List(scene.meshes.length);
      _dropOffsets = offsets;
    } else {
      offsets.fillRange(0, offsets.length, 0);
    }
    for (final index in _dropMeshIndices) {
      offsets[index] = dropHeight;
    }
  }

  /// 步骤号 clamp：不小于 0；场景有步骤数时不超过 stepCount。
  int? _clampStep(int? step) {
    if (step == null) return null;
    var value = step < 0 ? 0 : step;
    final scene = _scene;
    if (scene != null && scene.stepCount > 0 && value > scene.stepCount) {
      value = scene.stepCount;
    }
    return value;
  }
}
