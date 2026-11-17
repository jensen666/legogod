// 生成记录「设计版本、修订与求解轨迹」区块：
// 复用旧复盘里程碑规则（阶段 / 评审 / 版本 / 修订 / 规划 / 错误 / 关键求解事件），
// 有真实阶段与设计稿版本时如实展示；空时明确说明没有可复盘的里程碑。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/logs.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 设计版本、修订与求解轨迹区块。
class RecordMilestonesSection extends StatelessWidget {
  const RecordMilestonesSection({super.key, required this.job});

  /// 目标任务详情。
  final JobDetail job;

  @override
  Widget build(BuildContext context) {
    final milestones = milestoneLogs(job.logs);
    final seen = job.stage.allSeen;
    final designRevision = job.design?.revision;
    final reviseCount = job.stage.revise;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (seen.isNotEmpty || designRevision != null || reviseCount > 0) ...[
          FactChips(
            facts: [
              if (seen.isNotEmpty) FactChipData('阶段', '${seen.length} 个'),
              if (reviseCount > 0) FactChipData('修订', '$reviseCount 次'),
              if (designRevision != null) FactChipData('设计稿版本', 'r$designRevision'),
            ],
          ),
          if (seen.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                '已出现阶段：${[for (final id in seen) phaseLabel(id)].join(' → ')}',
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.textMuted,
                  height: 1.45,
                ),
              ),
            ),
          const SizedBox(height: 10),
        ],
        if (milestones.isEmpty)
          const Text(
            '该任务没有可复盘的里程碑。',
            style: TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.5),
          )
        else
          for (final entry in milestones) _MilestoneRow(entry: entry),
      ],
    );
  }
}

/// 单条里程碑（沿用旧复盘的图标与文案规则）。
class _MilestoneRow extends StatelessWidget {
  const _MilestoneRow({required this.entry});

  final LogEntry entry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_icon, style: const TextStyle(fontSize: 12)),
          const SizedBox(width: 6),
          if (entry.step != null)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: Text(
                'S${entry.step}',
                style: const TextStyle(
                  fontSize: 10.5,
                  color: AppColors.textDim,
                  fontFamily: 'monospace',
                ),
              ),
            ),
          Expanded(
            child: Text(
              _text,
              style: const TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.45),
            ),
          ),
        ],
      ),
    );
  }

  /// 里程碑图标：与旧复盘一致（阶段 / 评审 / 错误 / 成功 / 其他）。
  String get _icon {
    if (entry.kind == 'phase') return '◆';
    if (entry.kind == 'review') return '👁️';
    if (entry.kind == 'error' || entry.text.contains('失败')) return '❌';
    if (entry.text.contains('成功') || entry.text.contains('已保存')) return '✅';
    return '🛠';
  }

  /// 里程碑文案：阶段事件显示中文阶段名，其余取首行并限制长度。
  String get _text {
    if (entry.kind == 'phase') {
      final label = phaseLabel(entry.phase);
      return label.isEmpty ? entry.text : '阶段 · $label';
    }
    final firstLine = entry.text.split('\n').first;
    return firstLine.length > 150 ? '${firstLine.substring(0, 150)}…' : firstLine;
  }
}
