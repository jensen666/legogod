// 拼装指导「模拟」视图：
// 播放控制（重置 / 上一步 / 播放暂停 / 下一步 / 进度滑块 / 目标轮廓开关 / 减少动态效果提示）、
// 当前步骤真实零件信息、最终步逐体素一致性结论、预拼子模块提示与可拼性检查摘要。
// 所有内容来自真实方案文件；未知零件 ID 明确报错，不静默省略。
import 'package:flutter/material.dart';

import '../../core/studio_helpers.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../ui/widgets/common.dart';
import 'work_shared.dart';

/// 拼装指导「模拟」视图。
class AssemblyGuideSimView extends StatelessWidget {
  const AssemblyGuideSimView({
    super.key,
    required this.artifacts,
    required this.plan,
    required this.step,
    required this.total,
    required this.playing,
    required this.showGhost,
    required this.reducedMotion,
    required this.consistencyError,
    required this.onReset,
    required this.onPrev,
    required this.onNext,
    required this.onTogglePlay,
    required this.onSeek,
    required this.onToggleGhost,
  });

  /// 真实产物（模型 + 方案 + 零件目录）。
  final StudioArtifacts artifacts;

  /// 预拼子组件计划（子组件成员按扣合完成步成组落位）。
  final SubAssemblyPlan plan;

  /// 当前步数（0 = 绿色底板空载，total = 完成）。
  final int step;

  /// 方案步骤总数。
  final int total;

  /// 是否正在自动播放。
  final bool playing;

  /// 是否显示目标模型半透明轮廓。
  final bool showGhost;

  /// 系统是否开启「减少动态效果」。
  final bool reducedMotion;

  /// 最终步与目标模型逐体素一致性检查结果（null 表示一致）。
  final String? consistencyError;

  final VoidCallback onReset;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onTogglePlay;
  final ValueChanged<int> onSeek;
  final ValueChanged<bool> onToggleGhost;

  @override
  Widget build(BuildContext context) {
    final solution = artifacts.solution;
    return ListView(
      // 模拟视图控件数量有限：增大缓存区，保证横屏/小屏下卡片也已完成构建。
      cacheExtent: 1600,
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
      children: [
        if (total == 0) ...[
          const InfoBanner(
            icon: '🧩',
            tone: 'warn',
            text: '该作品没有可拼装步骤：方案文件中没有步骤记录，播放控制已禁用。',
          ),
        ] else ...[
          _controlRow(),
          Slider(
            key: const Key('guide-slider'),
            min: 0,
            max: total.toDouble(),
            divisions: total,
            value: step.toDouble(),
            label: '$step / $total',
            semanticFormatterCallback: (value) =>
                '拼装进度第 ${value.round()} 步，共 $total 步',
            onChanged: (value) => onSeek(value.round()),
          ),
        ],
        _ghostRow(),
        const SizedBox(height: 4),
        _stepCard(),
        if (solution.subassemblies.isNotEmpty) ...[
          const SizedBox(height: 8),
          InfoBanner(
            icon: '🧩',
            tone: 'fb',
            title: '预拼子模块',
            text: _preassemblyText(solution),
          ),
        ],
        const SizedBox(height: 8),
        WorkValidationSummary(
          key: const Key('guide-validation'),
          solution: solution,
        ),
      ],
    );
  }

  /// 播放控制行：重置 / 上一步 / 播放暂停 / 下一步 / 当前步数。
  Widget _controlRow() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        IconButton(
          key: const Key('guide-reset'),
          tooltip: '重置到第 0 步',
          onPressed: total > 0 ? onReset : null,
          icon: const Icon(Icons.restart_alt),
        ),
        IconButton(
          key: const Key('guide-prev'),
          tooltip: '上一步',
          onPressed: total > 0 && step > 0 ? onPrev : null,
          icon: const Icon(Icons.remove),
        ),
        IconButton.filled(
          key: const Key('guide-play'),
          tooltip: playing ? '暂停' : '播放',
          onPressed: total > 0 ? onTogglePlay : null,
          icon: Icon(playing ? Icons.pause : Icons.play_arrow),
        ),
        IconButton(
          key: const Key('guide-next'),
          tooltip: '下一步',
          onPressed: total > 0 && step < total ? onNext : null,
          icon: const Icon(Icons.add),
        ),
        const SizedBox(width: 8),
        Text(
          '$step / $total',
          style: const TextStyle(
            fontSize: 13,
            fontFamily: 'monospace',
            color: AppColors.textMuted,
          ),
        ),
      ],
    );
  }

  /// 目标轮廓开关 + 减少动态效果提示。
  Widget _ghostRow() {
    return Row(
      children: [
        Expanded(
          child: SwitchListTile(
            key: const Key('guide-ghost-toggle'),
            contentPadding: EdgeInsets.zero,
            dense: true,
            value: showGhost,
            onChanged: total > 0 ? onToggleGhost : null,
            title: const Text('目标轮廓', style: TextStyle(fontSize: 13)),
            subtitle: const Text(
              '显示目标模型半透明轮廓',
              style: TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          reducedMotion ? '减少动态效果：已关闭落位动画' : '落位动画 250ms',
          style: const TextStyle(fontSize: 10.5, color: AppColors.textDim),
        ),
      ],
    );
  }

  /// 当前步骤卡片：第 N 步、层、区域、真实零件与颜色、坐标、旋转、子模块说明。
  Widget _stepCard() {
    if (total == 0) {
      return AppCard(
        key: const Key('guide-step-card'),
        child: const Text(
          '该作品没有可拼装步骤。',
          style: TextStyle(fontSize: 12, color: AppColors.textMuted),
        ),
      );
    }
    if (step == 0) {
      return AppCard(
        key: const Key('guide-step-card'),
        child: const Text(
          '绿色底板上还没有零件 —— 点击「播放」或拖动滑块，看拼装方案逐块成型。',
          style: TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.5),
        ),
      );
    }
    final brick = _brickAt(step);
    if (brick == null) {
      return AppCard(
        key: const Key('guide-step-card'),
        child: Text(
          '步骤数据缺失：方案文件里没有第 $step 步的记录。',
          style: const TextStyle(fontSize: 12, color: AppColors.danger),
        ),
      );
    }
    final info = stepInfoOf(
      step: brick,
      model: artifacts.model,
      solution: artifacts.solution,
      plan: plan,
    );
    final part = artifacts.parts.partOf(info.partId);
    return AppCard(
      key: const Key('guide-step-card'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '第 ${info.step} 步',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  info.isFinal ? '最终步' : '进度 $step / $total',
                  textAlign: TextAlign.right,
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.textMuted,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (part != null) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: ColorDot(part.hex, size: 14),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${part.colorName} · ${part.name}',
                    style: const TextStyle(fontSize: 12.5, height: 1.4),
                  ),
                ),
              ] else
                Expanded(
                  child: Text(
                    '未知零件 ${info.partId}（零件目录未同步）',
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: AppColors.danger,
                      height: 1.4,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              WorkPill('y=${info.layer} 层'),
              WorkPill(info.zone),
              WorkPill(info.rangeText),
              if (info.rotate) WorkPill('旋转 90°'),
              if (info.subLabel.isNotEmpty)
                WorkPill(info.subLabel, tone: AppColors.fallback),
            ],
          ),
          if (part == null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                '未知零件 ${info.partId}：零件目录没有该 ID，'
                '无法展示名称与颜色（不静默省略）。',
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.danger,
                  height: 1.45,
                ),
              ),
            ),
          if (info.isFinal) ...[
            const SizedBox(height: 8),
            _finalConclusion(),
          ],
        ],
      ),
    );
  }

  /// 最终步结论：完成 N/N + 逐体素一致性（一致 / 未通过）。
  Widget _finalConclusion() {
    final consistent = consistencyError == null;
    final color = consistent ? AppColors.ok : AppColors.warn;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '完成 $total / $total',
                style: TextStyle(fontSize: 12, color: color),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  consistent ? '与目标模型逐体素一致 ✅' : '未通过逐体素核对 ⚠️',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
              ),
            ],
          ),
          if (!consistent)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '逐体素核对不一致：$consistencyError',
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.warn,
                  height: 1.45,
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 预拼子模块说明（仅实际存在时显示）。
  String _preassemblyText(SolutionData solution) {
    final planItems = solution.subassemblies;
    final lines = <String>[
      '以下子模块先在桌面预拼成刚性整体，再在指定步骤整组扣入主结构；'
          '播放模拟时按扣合完成步成组落位，不会出现中间悬空的孤立单砖。',
    ];
    for (var i = 0; i < planItems.length; i++) {
      final item = planItems[i];
      lines.add(
        '子模块 sub${i + 1}：共 ${item.steps.length} 块'
        '（步骤 ${item.steps.join('、')}），第 ${item.dockStep} 步整组扣入主结构。',
      );
    }
    return lines.join('\n');
  }

  /// 按步骤号取真实步骤；步骤号与下标不匹配时按方案步骤顺序回退。
  BrickStep? _brickAt(int stepNumber) {
    final steps = artifacts.solution.steps;
    for (final brick in steps) {
      if (brick.step == stepNumber) return brick;
    }
    if (stepNumber >= 1 && stepNumber <= steps.length) {
      return steps[stepNumber - 1];
    }
    return null;
  }
}
