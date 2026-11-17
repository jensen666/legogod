// 作品相关页面共享组件与真实数据组装（作品详情 / 拼装指导 / 零件清单共用）：
// - 3D 舞台容器统一视觉规格，避免各页重复实现；
// - 可拼性检查摘要默认一句真实结论，异常标红且分项明细可展开；
// - 交付/产物警告以「简短标题 + 展开原因」呈现，完整原因不丢失；
// - 首屏核心规格与警告只从真实产物文件 / 任务结果字段组装，缺失显示占位，绝不伪造。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 3D 舞台容器：固定高度 + 圆角边框 + 裁剪，供作品详情与拼装指导复用。
class WorkStageBox extends StatelessWidget {
  const WorkStageBox({super.key, required this.height, required this.child});

  /// 舞台高度（作品详情 ≥300，拼装指导 260~300）。
  final double height;

  /// 舞台内容（Lego3DView / 加载态 / 错误态）。
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppColors.stage,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderSoft),
      ),
      clipBehavior: Clip.antiAlias,
      child: child,
    );
  }
}

/// 可拼性检查分项的真实中文名（详细校验名保持服务端真实 key，仅做展示翻译）。
String validationCheckLabel(String key) {
  const labels = {
    'coverage': '覆盖',
    'inventory': '库存',
    'stud_connection': '凸点连接',
    'part_graph': '零件级连通',
    'suspension': '悬吊物理',
    'assembly_order': '装配顺序',
    'stability': '稳定性',
  };
  return labels[key] ?? key;
}

/// 可拼性检查摘要：默认显示一句真实结论，异常标红，分项明细可展开。
class WorkValidationSummary extends StatefulWidget {
  const WorkValidationSummary({super.key, required this.solution});

  /// 真实方案文件（含统一校验结论与分项）。
  final SolutionData solution;

  @override
  State<WorkValidationSummary> createState() => _WorkValidationSummaryState();
}

class _WorkValidationSummaryState extends State<WorkValidationSummary> {
  /// 明细展开状态：异常时默认展开，保证问题直接可见。
  late bool _open = !widget.solution.validationOk;

  @override
  void didUpdateWidget(covariant WorkValidationSummary oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 产物文件变化（重新加载）时按新结论重建默认展开状态。
    if (!identical(oldWidget.solution, widget.solution)) {
      _open = !widget.solution.validationOk;
    }
  }

  @override
  Widget build(BuildContext context) {
    final solution = widget.solution;
    final ok = solution.validationOk;
    final summary = solution.validationSummary ?? (ok ? '通过' : '未通过');
    final color = ok ? AppColors.ok : AppColors.danger;
    final checks = solution.validationChecks;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                ok ? Icons.check_circle : Icons.error,
                size: 16,
                color: color,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '可拼性检查：$summary',
                  style: TextStyle(fontSize: 12.5, color: color, height: 1.45),
                ),
              ),
            ],
          ),
          if (!ok && solution.residualErrors.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '残余问题：${solution.residualErrors.join('；')}',
              style: const TextStyle(
                fontSize: 11.5,
                color: AppColors.textMuted,
                height: 1.45,
              ),
            ),
          ],
          if (checks.isNotEmpty) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => setState(() => _open = !_open),
                style: TextButton.styleFrom(
                  minimumSize: const Size(48, 40),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                ),
                child: Text(
                  _open ? '收起校验明细' : '展开校验明细',
                  style: const TextStyle(fontSize: 12),
                ),
              ),
            ),
            if (_open)
              for (final entry in checks) _checkRow(entry),
          ],
        ],
      ),
    );
  }

  /// 单条校验分项：图标 + 真实分项名 + 服务端明细。
  Widget _checkRow(MapEntry<String, Map<String, dynamic>> entry) {
    final ok = entry.value['ok'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            ok ? Icons.check_circle : Icons.error,
            size: 13,
            color: ok ? AppColors.ok : AppColors.danger,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              '${validationCheckLabel(entry.key)}：${entry.value['detail'] ?? ''}',
              style: const TextStyle(
                fontSize: 11.5,
                color: AppColors.textMuted,
                height: 1.45,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 交付/产物警告项：简短标题一行 + 「展开原因」查看完整说明。
class WorkReasonTile extends StatefulWidget {
  const WorkReasonTile({super.key, required this.warning});

  /// 真实警告内容（标题 + 完整原因 + 色调）。
  final WorkWarning warning;

  @override
  State<WorkReasonTile> createState() => _WorkReasonTileState();
}

class _WorkReasonTileState extends State<WorkReasonTile> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final tone = AppColors.tone(widget.warning.tone);
    final icon = switch (widget.warning.tone) {
      'bad' => '❌',
      'info' => 'ℹ️',
      _ => '⚠️',
    };
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: tone.withValues(alpha: 0.35)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            button: true,
            expanded: _open,
            label: '${widget.warning.title}，${_open ? '收起原因' : '展开原因'}',
            child: InkWell(
              onTap: () => setState(() => _open = !_open),
              child: Container(
                constraints: const BoxConstraints(minHeight: 48),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                child: Row(
                  children: [
                    Text(icon, style: const TextStyle(fontSize: 15)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        widget.warning.title,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.text,
                        ),
                      ),
                    ),
                    Text(
                      _open ? '收起原因' : '展开原因',
                      style: TextStyle(fontSize: 11.5, color: tone),
                    ),
                    Icon(
                      _open ? Icons.expand_less : Icons.expand_more,
                      size: 18,
                      color: AppColors.textMuted,
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_open)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Text(
                widget.warning.detail,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textMuted,
                  height: 1.55,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 拼装信息胶囊（步/层/区域/零件/坐标等）。
class WorkPill extends StatelessWidget {
  const WorkPill(this.text, {super.key, this.tone});

  final String text;

  /// 语义色调；为空时用中性色。
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final color = tone ?? AppColors.textMuted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(text, style: TextStyle(fontSize: 11, color: color)),
    );
  }
}

/// 作品详情首屏核心规格：最多 3 项「零件数 / 层数 / 配色数」。
/// 数据优先级：真实产物文件 → 任务结果快照 → 显示「-」（不伪造）。
List<FactChipData> buildWorkSpecs(JobDetail job, StudioArtifacts? artifacts) {
  final result = job.result;
  final solution = artifacts?.solution;
  final model = artifacts?.model;

  final int? pieces = solution != null ? solution.stepCount : result?.pieces;
  final int? layers = model != null ? model.layerCount : result?.layerCount;

  int? colors;
  final fileColors = solution?.colors;
  if (fileColors != null && fileColors.isNotEmpty) {
    colors = fileColors.length;
  } else {
    final snapshotColors = result?.colors;
    if (snapshotColors != null && snapshotColors.isNotEmpty) {
      colors = snapshotColors.length;
    }
  }

  return [
    FactChipData('零件数', pieces == null ? '-' : '$pieces 块'),
    FactChipData('层数', layers == null ? '-' : '$layers 层'),
    FactChipData('配色数', colors == null ? '-' : '$colors 种'),
  ];
}

/// 作品级警告：任务交付警告 + 真实产物文件警告。
/// 没有真实依据时不返回任何项，不清空、不伪造。
List<WorkWarning> buildWorkWarnings({
  required JobDetail job,
  required StudioArtifacts? artifacts,
  String? consistencyError,
}) {
  final warnings = <WorkWarning>[...workWarnings(job)];
  final solution = artifacts?.solution;
  if (solution != null) {
    if (solution.colorFallbacks.isNotEmpty) {
      warnings.add(
        WorkWarning(
          title: '颜色回退',
          detail: '${solution.colorFallbacks.map((item) => item.text).join('\n')}\n'
              '设计色库存不足时按真实回退记录交付，3D 成品按实际使用的零件颜色展示。',
        ),
      );
    }
    if (!solution.validationOk) {
      final detail = solution.validationSummary ??
          (solution.residualErrors.isNotEmpty
              ? solution.residualErrors.join('；')
              : '方案文件的统一校验结论为未通过。');
      warnings.add(
        WorkWarning(title: '可拼性检查未通过', detail: detail, tone: 'bad'),
      );
    }
  }
  if (consistencyError != null) {
    warnings.add(
      WorkWarning(
        title: '产物逐体素核对不一致',
        detail: '$consistencyError。界面按真实产物文件展示，'
            '不显示「逐体素一致」结论。',
      ),
    );
  }
  return warnings;
}
