// 作品详情「作品信息」弹层：
// 集中展示体素、占地、层数、零件数、求解尝试、模型版本与方案策略、统计一致性说明；
// 技术 ID（job_id / run_id / retryOf / modeSource / outcomeSource）只在生成记录展示。
// 所有数值来自真实产物文件或任务结果快照，缺失显示「未记录」，绝不伪造。
import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';
import 'work_shared.dart';

/// 打开「作品信息」弹层。
Future<void> showWorkInfoSheet(
  BuildContext context, {
  required JobDetail job,
  StudioArtifacts? artifacts,
  String? consistencyError,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.bgElevated,
    builder: (_) => _WorkInfoSheet(
      job: job,
      artifacts: artifacts,
      consistencyError: consistencyError,
    ),
  );
}

/// 打开「原始需求」弹层（完整原文，可选中复制）。
Future<void> showRequirementSheet(BuildContext context, {required String desc}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.bgElevated,
    builder: (_) => SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.7,
        ),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '原始需求',
                    style:
                        TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  tooltip: '关闭',
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const SizedBox(height: 4),
            if (desc.trim().isEmpty)
              const Text(
                '该任务没有记录原始需求。',
                style: TextStyle(fontSize: 13, color: AppColors.textMuted),
              )
            else
              SelectableText(
                desc,
                style: const TextStyle(fontSize: 13, height: 1.6),
              ),
          ],
        ),
      ),
    ),
  );
}

/// 「作品信息」面板。
class _WorkInfoSheet extends StatelessWidget {
  const _WorkInfoSheet({
    required this.job,
    required this.artifacts,
    required this.consistencyError,
  });

  final JobDetail job;
  final StudioArtifacts? artifacts;
  final String? consistencyError;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.85,
        ),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '作品信息',
                    style:
                        TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  tooltip: '关闭',
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            Text(
              job.displayName,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
            ),
            const SectionTitle('规格', padding: EdgeInsets.only(top: 12, bottom: 6)),
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: _specRows(),
              ),
            ),
            if (artifacts != null) ...[
              const SectionTitle(
                '统计一致性',
                padding: EdgeInsets.only(top: 14, bottom: 6),
              ),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: _consistencyRows(),
                ),
              ),
              const SectionTitle(
                '可拼性检查',
                padding: EdgeInsets.only(top: 14, bottom: 6),
              ),
              WorkValidationSummary(solution: artifacts!.solution),
            ] else ...[
              const SectionTitle(
                '统计一致性',
                padding: EdgeInsets.only(top: 14, bottom: 6),
              ),
              const InfoBanner(
                icon: '⚠️',
                tone: 'warn',
                text: '3D 产物未加载，当前数值来自任务结果快照，暂无法与产物文件核对；'
                    '在作品详情重试加载 3D 成品后可查看完整一致性说明。',
              ),
            ],
            const SizedBox(height: 12),
            const Text(
              '统计以服务端真实产物文件（设计 JSON / 方案 JSON）为准。'
              '任务编号、运行标识、重试关系与技术来源字段只在「生成记录」展示。',
              style: TextStyle(
                fontSize: 11,
                color: AppColors.textDim,
                height: 1.5,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 规格行：优先真实产物文件，其次任务结果快照。
  List<Widget> _specRows() {
    final result = job.result;
    final model = artifacts?.model;
    final solution = artifacts?.solution;

    String voxelsText;
    if (model != null) {
      voxelsText = '${model.totalVoxels}';
    } else if (result?.voxels != null) {
      voxelsText = '${result!.voxels}';
    } else {
      voxelsText = '未记录';
    }

    String gridText;
    final snapshotGridW = result?.gridW;
    final snapshotGridD = result?.gridD;
    if (model != null && model.gridW > 0 && model.gridD > 0) {
      gridText = '${model.gridW}×${model.gridD}';
    } else if (snapshotGridW != null && snapshotGridD != null) {
      gridText = '$snapshotGridW×$snapshotGridD';
    } else {
      gridText = '未记录';
    }

    String layersText;
    if (model != null) {
      layersText = '${model.layerCount}';
    } else if (result?.layerCount != null) {
      layersText = '${result!.layerCount}';
    } else {
      layersText = '未记录';
    }

    String piecesText;
    if (solution != null) {
      piecesText = '${solution.stepCount}';
    } else if (result?.pieces != null) {
      piecesText = '${result!.pieces}';
    } else {
      piecesText = '未记录';
    }

    String attemptsText;
    if (solution != null) {
      attemptsText = '${solution.attempts}';
    } else if (result?.attempts != null) {
      attemptsText = '${result!.attempts}';
    } else {
      attemptsText = '未记录';
    }

    return [
      KeyValueRow(label: '体素', value: voxelsText),
      KeyValueRow(label: '占地', value: gridText),
      KeyValueRow(label: '层数', value: layersText),
      KeyValueRow(label: '零件数', value: piecesText),
      KeyValueRow(label: '求解尝试', value: attemptsText),
      KeyValueRow(label: '模型', value: _modelVersionText()),
      KeyValueRow(label: '方案策略', value: solution?.strategy ?? '未记录'),
      KeyValueRow(
        label: '方案尝试',
        value: solution == null ? '未记录' : '${solution.attempts} 次',
      ),
    ];
  }

  /// 模型版本文案：slug / revision / run（真实产物字段，未记录则明确说明）。
  String _modelVersionText() {
    final model = artifacts?.model;
    final result = job.result;
    final bits = <String>[];
    final slug = model?.slug ?? result?.slug;
    if (slug != null && slug.isNotEmpty) bits.add(slug);
    if (model?.revision != null) bits.add('r${model!.revision}');
    if (model?.runId != null && model!.runId!.isNotEmpty) {
      bits.add('run ${model.runId}');
    }
    return bits.isEmpty ? '未记录' : bits.join(' · ');
  }

  /// 统计一致性说明：快照统计 vs 真实产物文件，逐项如实标注。
  List<Widget> _consistencyRows() {
    final result = job.result;
    final model = artifacts!.model;
    final solution = artifacts!.solution;
    final rows = <Widget>[];

    if (result == null) {
      rows.add(
        const KeyValueRow(
          label: '快照统计',
          value: '任务结果快照缺失，无法与产物文件对比；页面以产物文件为准。',
        ),
      );
    } else {
      final snapshotPieces = result.pieces;
      final snapshotVoxels = result.voxels;
      final piecesMismatch =
          snapshotPieces != null && snapshotPieces != solution.stepCount;
      final voxelsMismatch =
          snapshotVoxels != null && snapshotVoxels != model.totalVoxels;
      if (piecesMismatch || voxelsMismatch) {
        rows.add(
          KeyValueRow(
            label: '快照统计',
            value: '与产物文件不一致：'
                '快照零件 ${snapshotPieces ?? '未记录'} / 产物 ${solution.stepCount}，'
                '快照体素 ${snapshotVoxels ?? '未记录'} / 产物 ${model.totalVoxels}。'
                '页面按真实产物文件展示。',
          ),
        );
      } else if (snapshotPieces == null && snapshotVoxels == null) {
        rows.add(
          const KeyValueRow(
            label: '快照统计',
            value: '快照没有记录零件数与体素数，无法对比；页面以产物文件为准。',
          ),
        );
      } else {
        rows.add(
          const KeyValueRow(label: '快照统计', value: '零件数与体素数与产物文件一致。'),
        );
      }
    }

    rows.add(
      KeyValueRow(
        label: '用量合计',
        value: solution.usageMatchesSteps
            ? '${solution.usageTotal} 块，与步骤数 ${solution.stepCount} 块一致。'
            : '${solution.usageTotal} 块与步骤数 ${solution.stepCount} 块不一致，'
                '页面按真实方案文件如实展示。',
      ),
    );

    rows.add(
      KeyValueRow(
        label: '逐体素核对',
        value: consistencyError == null
            ? '最终模型与方案步骤逐体素一致。'
            : '不一致：$consistencyError。',
      ),
    );
    return rows;
  }
}
