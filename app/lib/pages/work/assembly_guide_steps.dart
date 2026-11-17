// 拼装指导「分层步骤」视图：
// 按模型层 y 升序分组，底层默认展开；每层列出真实步骤（步骤号 / 颜色点 / 颜色名+零件名 /
// 坐标范围 / 旋转 / 预拼子模块说明）。点击任一步回传步骤号，由页面切回「模拟」视图并同步 3D；
// 未知零件 ID 明确标红报错，不静默省略。
import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/part.dart';
import '../../ui/widgets/common.dart';

/// 拼装指导「分层步骤」视图。
class AssemblyGuideStepsView extends StatelessWidget {
  const AssemblyGuideStepsView({
    super.key,
    required this.model,
    required this.solution,
    required this.parts,
    required this.currentStep,
    required this.onSelectStep,
  });

  /// 真实设计模型（提供层与模块名）。
  final ModelData model;

  /// 真实装配方案（提供全部步骤与预拼子组件）。
  final SolutionData solution;

  /// 真实零件目录（展示颜色与名称）。
  final PartsCatalog parts;

  /// 当前步数（与 3D 共用同一状态源）。
  final int currentStep;

  /// 选择某一步的回调（页面负责把 _step 设为该步并切回「模拟」）。
  final ValueChanged<int> onSelectStep;

  @override
  Widget build(BuildContext context) {
    final layers = [...model.layers]..sort((a, b) => a.y.compareTo(b.y));
    return ListView(
      // 层与步骤数量有限：增大缓存区，保证切换到该视图时全部分层入口已构建。
      cacheExtent: 2400,
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
      children: [
        const Text(
          '按层查看全部拼装步骤；点击任一步，3D 会跳到该步并切回「模拟」视图。',
          style: TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.45),
        ),
        const SizedBox(height: 8),
        if (layers.isEmpty)
          const InfoBanner(
            icon: '🧩',
            tone: 'warn',
            text: '模型文件没有分层记录，无法按层展示步骤。',
          )
        else
          for (var index = 0; index < layers.length; index++)
            _layerTile(context, layers[index], initiallyExpanded: index == 0),
      ],
    );
  }

  /// 单层区块：该层全部步骤，底层默认展开。
  Widget _layerTile(
    BuildContext context,
    ModelLayer layer, {
    required bool initiallyExpanded,
  }) {
    final steps = solution.steps.where((step) => step.layer == layer.y).toList()
      ..sort((a, b) => a.step.compareTo(b.step));
    final module = layer.module.isEmpty ? '模型' : layer.module.join('·');
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderSoft),
        ),
        clipBehavior: Clip.antiAlias,
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            initiallyExpanded: initiallyExpanded,
            title: Text(
              'y=${layer.y} · $module · ${steps.length} 块',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
            childrenPadding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
            children: [
              if (steps.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 6),
                  child: Text(
                    '该层没有拼装步骤记录。',
                    style: TextStyle(fontSize: 12, color: AppColors.textMuted),
                  ),
                )
              else
                for (final step in steps) _stepRow(step),
            ],
          ),
        ),
      ),
    );
  }

  /// 单条步骤：满足 48dp 触控，点击即选中该步。
  Widget _stepRow(BrickStep step) {
    final part = parts.partOf(step.piece);
    final selected = step.step == currentStep;
    final subText = _subassemblyText(step);
    return Material(
      color: selected ? AppColors.yellowSoft : Colors.transparent,
      child: InkWell(
        key: Key('guide-step-${step.step}'),
        onTap: () => onSelectStep(step.step),
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 30,
                child: Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: Text(
                    '${step.step}',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.textDim,
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
              ),
              if (part != null) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: ColorDot(part.hex, size: 14),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${part.colorName} ${part.name}',
                        style: const TextStyle(fontSize: 12.5, height: 1.4),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${step.rangeText}${step.rotate ? ' · 旋转 90°' : ''}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.textMuted,
                          height: 1.4,
                        ),
                      ),
                      if (subText != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(
                            subText,
                            style: const TextStyle(
                              fontSize: 11,
                              color: AppColors.fallback,
                              height: 1.4,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ] else
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '未知零件 ${step.piece}（零件目录未同步，不能静默省略）',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.danger,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${step.rangeText}${step.rotate ? ' · 旋转 90°' : ''}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.textMuted,
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
              if (selected)
                const Padding(
                  padding: EdgeInsets.only(left: 6, top: 2),
                  child: Text(
                    '当前',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: AppColors.yellowDeep,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  /// 预拼子模块说明：成员步骤标注所属子模块，扣合完成步说明整组扣入。
  String? _subassemblyText(BrickStep step) {
    for (var i = 0; i < solution.subassemblies.length; i++) {
      final sub = solution.subassemblies[i];
      if (!sub.steps.contains(step.step)) continue;
      if (step.step == sub.dockStep) {
        return '预拼子模块 sub${i + 1} 跨接锁扣砖 —— 将预拼好的整体扣入主结构';
      }
      return '预拼子模块 sub${i + 1} 预拼件 —— 先在桌面预拼，'
          '待第 ${sub.dockStep} 步整组扣入';
    }
    return null;
  }
}
