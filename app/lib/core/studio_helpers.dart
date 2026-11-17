// 3D 工作室展示辅助：区域名、预拼子组件可见性、拼装步信息（与 Web viewer.js 语义一致）。
import '../models/artifacts.dart';

/// 子组件信息（步骤号与成组落位关系）。
class SubAssemblyPlan {
  SubAssemblyPlan._({
    required this.subOfStep,
    required this.dockOfBrick,
    required this.bricksOfDock,
    required this.subCount,
  });

  /// 步骤号（1 起）→ 子组件编号（1 起）。
  final Map<int, int> subOfStep;

  /// 方案步骤索引（0 起）→ 成组落位步（1 起）。
  final Map<int, int> dockOfBrick;

  /// 成组落位步（1 起）→ 该组方案步骤索引。
  final Map<int, List<int>> bricksOfDock;

  /// 子组件数量。
  final int subCount;

  /// 某方案步骤索引（0 起）在给定步数下是否可见。
  bool brickVisibleAtStep(int brickIndex, int step) {
    final dock = dockOfBrick[brickIndex];
    if (dock != null) return step >= dock;
    return brickIndex < step;
  }

  static SubAssemblyPlan fromSolution(SolutionData solution) {
    final subOfStep = <int, int>{};
    final dockOfBrick = <int, int>{};
    final bricksOfDock = <int, List<int>>{};
    final subs = solution.subassemblies;
    for (var i = 0; i < subs.length; i++) {
      final sub = subs[i];
      final steps = List<int>.from(sub.steps)..sort();
      if (steps.isEmpty) continue;
      final dock = steps.last;
      final brickIndices = [
        for (final number in steps)
          if (number - 1 >= 0 && number - 1 < solution.steps.length) number - 1,
      ];
      for (final number in steps) {
        subOfStep[number] = i + 1;
      }
      for (final brickIndex in brickIndices) {
        dockOfBrick[brickIndex] = dock;
      }
      bricksOfDock[dock] = [...?bricksOfDock[dock], ...brickIndices];
    }
    return SubAssemblyPlan._(
      subOfStep: subOfStep,
      dockOfBrick: dockOfBrick,
      bricksOfDock: bricksOfDock,
      subCount: subs.length,
    );
  }

  /// 当前步（1 起）的整组落位方案步骤索引（无则空）。
  List<int> bricksDockingAt(int step) => bricksOfDock[step] ?? const <int>[];
}

/// 墙面区域名（与 Web viewer 的 zoneName 一致：模块名含「墙」时按位置细分为前/后/左/右墙）。
String zoneName(BrickStep step, ModelData model) {
  ModelLayer? layer;
  for (final item in model.layers) {
    if (item.y == step.layer) {
      layer = item;
      break;
    }
  }
  final modules = layer?.module ?? const <String>[];
  if (modules.any((name) => name.contains('墙'))) {
    if (step.z == 0) return '前墙';
    if (step.z + step.d == model.gridD) return '后墙';
    if (step.x == 0) return '左墙';
    if (step.x + step.w == model.gridW) return '右墙';
    return '墙体';
  }
  return modules.isEmpty ? '模型' : modules.join('·');
}

/// 拼装信息（当前步）。
class StepInfo {
  const StepInfo({
    required this.step,
    required this.layer,
    required this.zone,
    required this.partId,
    required this.rangeText,
    required this.rotate,
    required this.subLabel,
    required this.isFinal,
  });

  final int step;
  final int layer;
  final String zone;
  final String partId;
  final String rangeText;
  final bool rotate;

  /// 子组件标签（如「预拼子模块 sub1（整组落位）」）；无则空串。
  final String subLabel;

  /// 是否为最终步（展示「与目标模型逐体素一致」）。
  final bool isFinal;
}

/// 构造当前步信息。
StepInfo stepInfoOf({
  required BrickStep step,
  required ModelData model,
  required SolutionData solution,
  required SubAssemblyPlan plan,
}) {
  final subNumber = plan.subOfStep[step.step];
  final total = solution.steps.length;
  return StepInfo(
    step: step.step,
    layer: step.layer,
    zone: zoneName(step, model),
    partId: step.piece,
    rangeText: step.rangeText,
    rotate: step.rotate,
    subLabel: subNumber == null ? '' : '预拼子模块 sub$subNumber（整组落位）',
    isFinal: step.step == total,
  );
}
