// 纯 Dart 场景层：把目标模型 / 实时设计稿 / 零件库 / 拼装模拟转换成可渲染的 Lego3DScene。
// - 不 import Flutter，可在纯 Dart 测试、后台 isolate 中直接构建；
// - 所有几何在构建期展开成三角面片（见 lego_geometry.dart），渲染期只读，不再分配对象；
// - 越界 / 未知零件 / 空数据一律降级：跳过该件并写入 warnings，绝不抛异常。
// 几何展开与步骤校验的实现放在 part 文件 lego_scene_geometry.dart，便于单文件保持在 500 行以内。
import 'dart:math' as math;

import '../models/artifacts.dart';
import '../models/design.dart';
import '../models/part.dart';
import 'lego_geometry.dart';

export 'lego_geometry.dart';

part 'lego_scene_geometry.dart';

/// 场景类型（页面可据此选择文案与交互）。
enum LegoSceneKind { design, model, assembly, partsRow, empty }

/// 网格类型。
enum LegoMeshKind { brick, slope, voxel, partSample, ghost, baseplate }

/// 场景内一个可独立视深排序 / 落位动画的零件网格。
class LegoMesh {
  LegoMesh({
    required this.index,
    required this.dockStep,
    required this.color,
    required this.partId,
    required this.kind,
    required this.center,
    required this.geometry,
    this.label,
    this.step,
    this.layer,
    this.rotated = false,
  });

  /// 场景内序号（0 起，与 `Lego3DScene.meshes` 下标一致；落位动画按它定位）。
  final int index;

  /// 落位步：1 起。普通零件等于步骤号，子组件成员等于子组件扣合完成步；0 表示不参与步骤过滤。
  final int dockStep;

  /// 零件基础色（ARGB，与方案里该零件的展示色一致）。
  final int color;

  /// 零件 ID（如 B2x4_LGRAY）；设计稿体素为 `voxel`，底板为 `baseplate`。
  final String partId;

  /// 网格类型。
  final LegoMeshKind kind;

  /// 包围盒中心（世界坐标，逐零件视深排序依据）。
  final Vec3 center;

  /// 三角面片几何。
  final MeshGeometry geometry;

  /// 可读名称（零件中文名 / 体素颜色名），供无障碍与页面文案使用。
  final String? label;

  /// 原始步骤号（拼装/模型场景）。
  final int? step;

  /// 所在层（拼装/模型/设计稿场景）。
  final int? layer;

  /// 是否水平旋转 90° 摆放。
  final bool rotated;

  /// 三角面数量。
  int get faceCount => geometry.faceCount;

  /// 三角面数量的别名（页面/测试可用 `faces` 读取）。
  int get faces => geometry.faceCount;

  /// 顶点数量。
  int get vertexCount => geometry.vertexCount;

  /// 几何包围盒。
  Bounds get bounds => geometry.bounds;

  /// 是否斜坡件。
  bool get isSlope => kind == LegoMeshKind.slope;

  @override
  String toString() =>
      'LegoMesh(index: $index, part: $partId, dockStep: $dockStep)';
}

/// 可渲染的 3D 场景：实体零件 + 半透明目标轮廓 + 绿色底板 + 构建告警。
class Lego3DScene {
  Lego3DScene({
    required this.kind,
    required this.description,
    required this.bounds,
    required int stepCount,
    this.meshes = const <LegoMesh>[],
    this.ghostMeshes = const <LegoMesh>[],
    this.baseplate,
    this.warnings = const <String>[],
  }) : _stepCount = stepCount;

  /// 场景类型。
  final LegoSceneKind kind;

  /// 无障碍/页面文案（一句话描述场景与数量）。
  final String description;

  /// 全部实体零件（按可见步骤过滤前的顺序）。
  final List<LegoMesh> meshes;

  /// 目标轮廓 ghost（半透明体素，绘制在实体之前）。
  final List<LegoMesh> ghostMeshes;

  /// 绿色底板（始终绘制，不属于步骤进度）。
  final LegoMesh? baseplate;

  /// 场景整体包围盒（含 ghost 与底板，首帧取景依据）。
  final Bounds bounds;

  /// 数据告警（未知零件、越界步骤、空数据等），页面可如实展示。
  final List<String> warnings;

  final int _stepCount;

  /// 拼装步骤总数（设计稿/零件库场景为 0）。
  int get stepCount => _stepCount;

  /// 是否没有任何实体零件。
  bool get isEmpty => meshes.isEmpty;

  /// 实体零件数量。
  int get meshCount => meshes.length;

  /// 目标轮廓数量。
  int get ghostCount => ghostMeshes.length;

  /// 指定步骤下可见的零件数量（`visibleStep` 为 null 时全部可见）。
  int visibleMeshCountAt(int? visibleStep) {
    if (visibleStep == null) return meshes.length;
    var count = 0;
    for (final mesh in meshes) {
      if (mesh.dockStep <= visibleStep) count++;
    }
    return count;
  }

  /// 空场景（数据未就绪时可直接展示，不崩溃）。
  static Lego3DScene empty({String description = '3D 场景（暂无数据）'}) => Lego3DScene(
    kind: LegoSceneKind.empty,
    description: description,
    bounds: Bounds.empty,
    stepCount: 0,
  );
}

/// 场景构建器：四个使用场景的统一入口（纯 Dart，无 Flutter 依赖）。
class LegoSceneBuilder {
  LegoSceneBuilder._();

  /// 零件库一行最多展示的样品数量（与 web/viewer.js 一致）。
  static const int maxPartSamples = 14;

  /// 实时设计稿场景：彩色体素，颜色来自 DesignDraft 的 palette / chars。
  static Lego3DScene design({required DesignDraft draft}) {
    final meshes = <LegoMesh>[];
    final warnings = <String>[];
    for (final voxel in draft.voxels) {
      final color = _parseHex(draft.hexOf(voxel.colorName));
      final geometryDraft = MeshDraft(baseColor: color);
      // 与 web/preview.js 一致：箱体边长 0.92，体素之间留缝，便于分辨单个体素
      final x0 = voxel.x + 0.04;
      final x1 = voxel.x + 0.96;
      final y0 = voxel.y * legoLayerHeight + legoLayerHeight * 0.04;
      final y1 = (voxel.y + 1) * legoLayerHeight - legoLayerHeight * 0.04;
      final z0 = voxel.z + 0.04;
      final z1 = voxel.z + 0.96;
      geometryDraft.addBox(x0, y0, z0, x1, y1, z1);
      final geometry = geometryDraft.build();
      meshes.add(
        LegoMesh(
          index: meshes.length,
          dockStep: 0,
          color: color,
          partId: 'voxel',
          kind: LegoMeshKind.voxel,
          center: geometry.bounds.center,
          geometry: geometry,
          label: voxel.colorName,
          layer: voxel.y,
        ),
      );
    }
    if (meshes.isEmpty) warnings.add('设计稿还没有体素');
    final name = draft.name;
    final prefix = name == null || name.isEmpty ? '设计稿' : '设计稿「$name」';
    return Lego3DScene(
      kind: LegoSceneKind.design,
      description: '$prefix：${meshes.length} 个体素，${draft.layers.length} 层',
      bounds: _boundsOf(meshes: meshes),
      meshes: meshes,
      warnings: warnings,
      stepCount: 0,
    );
  }

  /// 目标模型场景：逐块渲染 solution.steps 的真实零件与颜色，外观与最终方案一致。
  static Lego3DScene model({
    required ModelData model,
    required SolutionData solution,
    required PartsCatalog parts,
  }) {
    final warnings = <String>[];
    final resolved = _resolveSteps(
      solution: solution,
      parts: parts,
      model: model,
      warnings: warnings,
    );
    final occupied = _occupiedCells(resolved);
    final meshes = <LegoMesh>[];
    for (final item in resolved) {
      meshes.add(
        _createPartMesh(
          index: meshes.length,
          part: item.part,
          step: item.step,
          dockStep: item.step.step,
          occupied: occupied,
        ),
      );
    }
    final extent = _gridExtent(model, resolved);
    final baseplate = _baseplateMesh(gridW: extent.w, gridD: extent.d);
    return Lego3DScene(
      kind: LegoSceneKind.model,
      description: _modelDescription(model, meshes.length),
      bounds: _boundsOf(meshes: meshes, baseplate: baseplate),
      meshes: meshes,
      baseplate: baseplate,
      warnings: warnings,
      stepCount: solution.stepCount,
    );
  }

  /// 拼装模拟场景：逐块零件 + 子组件成组落位 + 目标轮廓 ghost。
  static Lego3DScene assembly({
    required ModelData model,
    required SolutionData solution,
    required PartsCatalog parts,
  }) {
    final warnings = <String>[];
    final resolved = _resolveSteps(
      solution: solution,
      parts: parts,
      model: model,
      warnings: warnings,
    );
    final occupied = _occupiedCells(resolved);
    // 子组件成组落位：成员步骤的可见性统一到子组件扣合完成步（dockStep），
    // 与 web/viewer.js 的 brickVisibleAtStep 语义完全一致。
    final dockByStep = _dockStepByStep(solution);
    final meshes = <LegoMesh>[];
    for (final item in resolved) {
      meshes.add(
        _createPartMesh(
          index: meshes.length,
          part: item.part,
          step: item.step,
          dockStep: dockByStep[item.step.step] ?? item.step.step,
          occupied: occupied,
        ),
      );
    }
    final ghosts = _ghostMeshes(model);
    final extent = _gridExtent(model, resolved);
    final baseplate = _baseplateMesh(gridW: extent.w, gridD: extent.d);
    return Lego3DScene(
      kind: LegoSceneKind.assembly,
      description: '拼装模拟：共 ${solution.stepCount} 步，${meshes.length} 块零件',
      bounds: _boundsOf(meshes: meshes, ghosts: ghosts, baseplate: baseplate),
      meshes: meshes,
      ghostMeshes: ghosts,
      baseplate: baseplate,
      warnings: warnings,
      stepCount: solution.stepCount,
    );
  }

  /// 零件库场景：本方案实际用到的零件按用量降序，最多 14 个样品在原点排一行。
  static Lego3DScene partsRow({
    required List<Part> parts,
    required SolutionData solution,
  }) {
    final warnings = <String>[];
    final byId = <String, Part>{for (final part in parts) part.id: part};
    final catalogOrder = <String, int>{
      for (var i = 0; i < parts.length; i++) parts[i].id: i,
    };
    final usedIds = <String>[
      for (final id in solution.usage.keys)
        if (byId.containsKey(id)) id,
    ];
    // 按方案用量降序；用量相同按目录顺序，保证结果稳定可测
    usedIds.sort((a, b) {
      final byUsage = (solution.usage[b] ?? 0).compareTo(
        solution.usage[a] ?? 0,
      );
      if (byUsage != 0) return byUsage;
      return (catalogOrder[a] ?? 0).compareTo(catalogOrder[b] ?? 0);
    });
    final showIds = usedIds.take(maxPartSamples).toList();
    if (showIds.isEmpty) warnings.add('方案没有可展示的零件样品');
    final meshes = <LegoMesh>[];
    var cursor = 0.0;
    for (final id in showIds) {
      final part = byId[id]!;
      final geometryDraft = MeshDraft(baseColor: _parseHex(part.hex));
      // 零件库样品始终展示凸点（web/viewer.js：makeBrick / makeSlopeBrick(includeStuds=true)）
      _addPartGeometry(
        geometryDraft,
        part: part,
        width: part.w,
        depth: part.d,
        rotated: false,
        originX: cursor,
        originZ: 0,
        layer: 0,
        occupied: const <int>{},
      );
      final geometry = geometryDraft.build();
      meshes.add(
        LegoMesh(
          index: meshes.length,
          dockStep: 0,
          color: _parseHex(part.hex),
          partId: part.id,
          kind: LegoMeshKind.partSample,
          center: geometry.bounds.center,
          geometry: geometry,
          label: part.name,
        ),
      );
      cursor += part.w + _partRowGap;
    }
    return Lego3DScene(
      kind: LegoSceneKind.partsRow,
      description: '零件库：${meshes.length} 种零件样品',
      bounds: _boundsOf(meshes: meshes),
      meshes: meshes,
      warnings: warnings,
      stepCount: 0,
    );
  }

  /// 零件库样品行间距（web/viewer.js：cx += p.w + 1.7）。
  static const double _partRowGap = 1.7;
}
