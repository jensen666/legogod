// lego_scene.dart 的 part 文件：步骤校验、几何展开、ghost / 底板等构建细节。
// 与 lego_scene.dart 同属一个库，共享 import 与私有成员；拆开只为单文件保持在 500 行以内。
part of 'lego_scene.dart';

/// 目标轮廓半透明度（Web 用 0.05 + 线框；软渲染需要稍高才看得清轮廓）。
const double _ghostAlpha = 0.12;

/// 一条已校验通过的拼装步骤。
class _ResolvedStep {
  const _ResolvedStep({required this.step, required this.part});

  final BrickStep step;
  final Part part;
}

/// 校验并解析方案步骤：未知零件 / 非法尺寸 / 越界坐标一律跳过并记入 warnings。
List<_ResolvedStep> _resolveSteps({
  required SolutionData solution,
  required PartsCatalog parts,
  required ModelData model,
  required List<String> warnings,
}) {
  final resolved = <_ResolvedStep>[];
  for (final step in solution.steps) {
    final part = parts.partOf(step.piece);
    if (part == null) {
      warnings.add('第 ${step.step} 步的零件「${step.piece}」不在零件目录中，已跳过');
      continue;
    }
    if (step.w <= 0 || step.d <= 0) {
      warnings.add('第 ${step.step} 步尺寸非法（w=${step.w}，d=${step.d}），已跳过');
      continue;
    }
    if (step.layer < 0) {
      warnings.add('第 ${step.step} 步层号非法（layer=${step.layer}），已跳过');
      continue;
    }
    final outX =
        step.x < 0 || (model.gridW > 0 && step.x + step.w > model.gridW);
    final outZ =
        step.z < 0 || (model.gridD > 0 && step.z + step.d > model.gridD);
    if (outX || outZ) {
      warnings.add(
        '第 ${step.step} 步越界（x=${step.x}，z=${step.z}，覆盖 ${step.w}×${step.d}），已跳过',
      );
      continue;
    }
    resolved.add(_ResolvedStep(step: step, part: part));
  }
  return resolved;
}

/// 占用格子集合：用于「凸点只在未被上层覆盖的顶面显示」。
Set<int> _occupiedCells(List<_ResolvedStep> steps) {
  final occupied = <int>{};
  for (final item in steps) {
    final step = item.step;
    for (var a = 0; a < step.w; a++) {
      for (var b = 0; b < step.d; b++) {
        occupied.add(_cellKey(step.x + a, step.layer, step.z + b));
      }
    }
  }
  return occupied;
}

/// 子组件成组落位映射：成员步骤号 → 子组件扣合完成步（dockStep）。
Map<int, int> _dockStepByStep(SolutionData solution) {
  final dockByStep = <int, int>{};
  for (final sub in solution.subassemblies) {
    final memberSteps = <int>[...sub.steps]..sort();
    if (memberSteps.isEmpty) continue;
    final dockStep = memberSteps.last;
    for (final stepNo in memberSteps) {
      dockByStep[stepNo] = dockStep;
    }
  }
  return dockByStep;
}

/// 把一块零件写进几何草稿：普通砖 = 长方体 + 凸点；斜坡 = 逐格楔形 + 满格单元。
void _addPartGeometry(
  MeshDraft draft, {
  required Part part,
  required int width,
  required int depth,
  required bool rotated,
  required double originX,
  required double originZ,
  required int layer,
  required Set<int> occupied,
}) {
  final baseY = layer * legoLayerHeight;
  final topY = baseY + legoLayerHeight;
  final cellOriginX = originX.round();
  final cellOriginZ = originZ.round();
  if (part.isSlope) {
    final slopeChar = part.slope!;
    final inverse = VoxelChar.inverseSlopes.contains(slopeChar);
    final fullCells = _slopeMaskCells(part, width, depth, rotated);
    for (var a = 0; a < width; a++) {
      for (var b = 0; b < depth; b++) {
        final cellX = originX + a;
        final cellZ = originZ + b;
        if (fullCells != null && fullCells.contains('$a,$b')) {
          // 多格斜坡的满格单元按完整方块绘制（web/viewer.js isFullCell）
          draft.addBox(cellX, baseY, cellZ, cellX + 1, topY, cellZ + 1);
        } else if (inverse) {
          draft.addInverseSlopeCell(cellX, baseY, cellZ, slopeChar);
        } else {
          draft.addSlopeCell(cellX, baseY, cellZ, slopeChar);
        }
      }
    }
    _addStuds(
      draft,
      part: part,
      width: width,
      depth: depth,
      rotated: rotated,
      originX: originX,
      originZ: originZ,
      cellOriginX: cellOriginX,
      cellOriginZ: cellOriginZ,
      layer: layer,
      topY: topY,
      occupied: occupied,
    );
    return;
  }
  draft.addBox(originX, baseY, originZ, originX + width, topY, originZ + depth);
  _addStuds(
    draft,
    part: part,
    width: width,
    depth: depth,
    rotated: rotated,
    originX: originX,
    originZ: originZ,
    cellOriginX: cellOriginX,
    cellOriginZ: cellOriginZ,
    layer: layer,
    topY: topY,
    occupied: occupied,
  );
}

/// 追加凸点：位置语义与 web/viewer.js partStudOffsets 一致，且跳过被上层覆盖的顶面。
void _addStuds(
  MeshDraft draft, {
  required Part part,
  required int width,
  required int depth,
  required bool rotated,
  required double originX,
  required double originZ,
  required int cellOriginX,
  required int cellOriginZ,
  required int layer,
  required double topY,
  required Set<int> occupied,
}) {
  for (final cell in _studOffsets(part, width, depth, rotated)) {
    final a = cell[0];
    final b = cell[1];
    if (occupied.contains(
      _cellKey(cellOriginX + a, layer + 1, cellOriginZ + b),
    )) {
      continue;
    }
    draft.addStud(originX + a + 0.5, topY, originZ + b + 0.5);
  }
}

/// 凸点偏移：hasStuds=false 无凸点；studMask 存在时按掩码（旋转时交换 i/j）；否则满格。
List<List<int>> _studOffsets(Part part, int width, int depth, bool rotated) {
  if (!part.hasStuds) return const <List<int>>[];
  final mask = part.studMask;
  if (mask != null && mask.isNotEmpty) {
    final out = <List<int>>[];
    for (final cell in mask) {
      if (cell.length < 2) continue;
      final i = rotated ? cell[1] : cell[0];
      final j = rotated ? cell[0] : cell[1];
      if (i >= 0 && j >= 0 && i < width && j < depth) out.add(<int>[i, j]);
    }
    return out;
  }
  final all = <List<int>>[];
  for (var i = 0; i < width; i++) {
    for (var j = 0; j < depth; j++) {
      all.add(<int>[i, j]);
    }
  }
  return all;
}

/// 多格斜坡的满格单元集合（web/viewer.js：rootMask 优先，其次 studMask）。
Set<String>? _slopeMaskCells(Part part, int width, int depth, bool rotated) {
  final mask = part.rootMask ?? part.studMask;
  if (mask == null || mask.isEmpty || width * depth <= 1) return null;
  final out = <String>{};
  for (final cell in mask) {
    if (cell.length < 2) continue;
    final i = rotated ? cell[1] : cell[0];
    final j = rotated ? cell[0] : cell[1];
    out.add('$i,$j');
  }
  return out.isEmpty ? null : out;
}

/// 单块零件的完整网格（模型 / 拼装场景共用）。
LegoMesh _createPartMesh({
  required int index,
  required Part part,
  required BrickStep step,
  required int dockStep,
  required Set<int> occupied,
}) {
  final color = _parseHex(part.hex);
  final geometryDraft = MeshDraft(baseColor: color);
  _addPartGeometry(
    geometryDraft,
    part: part,
    width: step.w,
    depth: step.d,
    rotated: step.rotate,
    originX: step.x.toDouble(),
    originZ: step.z.toDouble(),
    layer: step.layer,
    occupied: occupied,
  );
  final geometry = geometryDraft.build();
  return LegoMesh(
    index: index,
    dockStep: dockStep,
    color: color,
    partId: part.id,
    kind: part.isSlope ? LegoMeshKind.slope : LegoMeshKind.brick,
    center: geometry.bounds.center,
    geometry: geometry,
    label: part.name,
    step: step.step,
    layer: step.layer,
    rotated: step.rotate,
  );
}

/// 目标轮廓 ghost：目标模型每个体素一个半透明方块（画在实体之前）。
List<LegoMesh> _ghostMeshes(ModelData model) {
  final ghosts = <LegoMesh>[];
  for (final voxel in model.allVoxels) {
    final geometryDraft = MeshDraft(
      baseColor: legoGhostColor,
      alpha: _ghostAlpha,
    );
    final y0 = voxel.y * legoLayerHeight;
    // 与 web/viewer.js ghost 一致：BoxGeometry(1, H, 1) 占满整格
    geometryDraft.addBox(
      voxel.x.toDouble(),
      y0,
      voxel.z.toDouble(),
      voxel.x + 1.0,
      y0 + legoLayerHeight,
      voxel.z + 1.0,
    );
    final geometry = geometryDraft.build();
    ghosts.add(
      LegoMesh(
        index: ghosts.length,
        dockStep: 0,
        color: legoGhostColor,
        partId: 'ghost',
        kind: LegoMeshKind.ghost,
        center: geometry.bounds.center,
        geometry: geometry,
        label: '目标轮廓',
        layer: voxel.y,
      ),
    );
  }
  return ghosts;
}

/// 绿色底板网格（尺寸 = 模型网格 + 四周各 3 格，与 web/viewer.js fitCam 一致）。
LegoMesh _baseplateMesh({required int gridW, required int gridD}) {
  final cellsX = (gridW > 0 ? gridW : 1) + 6;
  final cellsZ = (gridD > 0 ? gridD : 1) + 6;
  final geometryDraft = MeshDraft(baseColor: legoBaseplateColor);
  geometryDraft.addBaseplate(cellsX: cellsX, cellsZ: cellsZ);
  final geometry = geometryDraft.build();
  return LegoMesh(
    index: -1,
    dockStep: 0,
    color: legoBaseplateColor,
    partId: 'baseplate',
    kind: LegoMeshKind.baseplate,
    center: geometry.bounds.center,
    geometry: geometry,
    label: '绿色底板',
  );
}

/// 场景网格范围：优先用模型声明的网格，缺失时从步骤覆盖范围推导。
({int w, int d}) _gridExtent(ModelData model, List<_ResolvedStep> steps) {
  var width = model.gridW;
  var depth = model.gridD;
  for (final item in steps) {
    final step = item.step;
    if (step.x + step.w > width) width = step.x + step.w;
    if (step.z + step.d > depth) depth = step.z + step.d;
  }
  return (w: math.max(1, width), d: math.max(1, depth));
}

/// 合并若干网格的包围盒。
Bounds _boundsOf({
  required List<LegoMesh> meshes,
  List<LegoMesh> ghosts = const <LegoMesh>[],
  LegoMesh? baseplate,
}) {
  var bounds = Bounds.empty;
  for (final mesh in meshes) {
    bounds = bounds.union(mesh.bounds);
  }
  for (final mesh in ghosts) {
    bounds = bounds.union(mesh.bounds);
  }
  if (baseplate != null) bounds = bounds.union(baseplate.bounds);
  return bounds;
}

/// 目标模型文案。
String _modelDescription(ModelData model, int meshCount) {
  final name = model.name;
  final prefix = name == null || name.isEmpty ? '目标模型' : '目标模型「$name」';
  return '$prefix：$meshCount 块零件，${model.layerCount} 层';
}

/// #RRGGBB / #AARRGGBB → ARGB；非法值兜底中性灰（与 DesignDraft.hexOf 一致）。
int _parseHex(String hex) {
  final text = hex.trim();
  final value = text.startsWith('#') ? text.substring(1) : text;
  if (value.length == 6 || value.length == 8) {
    final parsed = int.tryParse(value, radix: 16);
    if (parsed != null) {
      return value.length == 6 ? (0xFF000000 | parsed) : parsed;
    }
  }
  return 0xFFA0A5A9;
}

/// 格子键（y 层 + x/z），非负坐标下无冲突。
int _cellKey(int x, int y, int z) => (x << 24) | (z << 12) | y;
