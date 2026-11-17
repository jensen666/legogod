// 生成记录「颜色回退与产物统计」区块：
// 统计一律以该任务真实 model_*.json / solution_*.json 文件为准，快照只做兜底与核对；
// 加载失败只影响本区块并可局部重试；失败任务没有可读取产物时按真实快照兜底并注明来源。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 颜色回退与产物统计区块。
class RecordArtifactsSection extends StatefulWidget {
  const RecordArtifactsSection({super.key, required this.job});

  /// 目标任务详情。
  final JobDetail job;

  @override
  State<RecordArtifactsSection> createState() => _RecordArtifactsSectionState();
}

class _RecordArtifactsSectionState extends State<RecordArtifactsSection> {
  StudioArtifacts? _artifacts;
  String? _error;
  bool _loading = false;
  bool _requested = false;

  @override
  void initState() {
    super.initState();
    // 有真实产物路径时先进入加载态，避免首帧误显示「没有可读取的产物文件」。
    final result = widget.job.result;
    _loading = result != null &&
        result.modelPath != null &&
        result.solutionPath != null;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  /// 加载真实产物文件（模型 + 方案 + 零件目录）；没有产物路径的任务不发起请求。
  Future<void> _load() async {
    final result = widget.job.result;
    if (result == null || result.modelPath == null || result.solutionPath == null) {
      return;
    }
    if (_requested && _artifacts != null) return;
    _requested = true;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final artifacts = await AppScope.read(context).loadStudioArtifacts(widget.job.id);
      if (!mounted) return;
      setState(() {
        _artifacts = artifacts;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = describeError(e);
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SizedBox(height: 64, child: LoadingBlock(text: '正在读取真实产物文件……'));
    }
    if (_error != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '产物统计加载失败：$_error',
            style: const TextStyle(fontSize: 12, color: AppColors.danger, height: 1.45),
          ),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _load, child: const Text('重试')),
        ],
      );
    }
    final artifacts = _artifacts;
    if (artifacts == null) return _snapshotFallback();
    return _artifactStats(artifacts);
  }

  /// 没有可读取产物文件时的快照兜底：明确注明来源，不伪装成文件统计。
  Widget _snapshotFallback() {
    final result = widget.job.result;
    if (result == null) {
      return const Text(
        '该任务没有产物统计。',
        style: TextStyle(fontSize: 12, color: AppColors.textMuted),
      );
    }
    final facts = <FactChipData>[
      if (result.pieces != null) FactChipData('零件', '${result.pieces} 块'),
      if (result.voxels != null) FactChipData('体素', '${result.voxels}'),
      if (result.layerCount != null) FactChipData('层数', '${result.layerCount}'),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '该任务没有可读取的产物文件，以下为结果快照统计：',
          style: TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.5),
        ),
        const SizedBox(height: 8),
        if (facts.isEmpty)
          const Text(
            '结果快照里也没有可展示的统计。',
            style: TextStyle(fontSize: 11.5, color: AppColors.textMuted),
          )
        else
          FactChips(facts: facts),
      ],
    );
  }

  /// 真实产物文件统计：体素/层数/占地/零件/求解尝试/配色 + 颜色回退 + 文件与统计不一致提示。
  Widget _artifactStats(StudioArtifacts artifacts) {
    final result = widget.job.result;
    final model = artifacts.model;
    final solution = artifacts.solution;
    final colorNames = solution.colors.keys.toList();
    final mismatch = result?.inconsistentWith(
          filePieces: solution.stepCount,
          fileVoxels: model.totalVoxels,
        ) ??
        false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FactChips(
          facts: [
            FactChipData('体素', '${model.totalVoxels}'),
            FactChipData('层数', '${model.layerCount}'),
            FactChipData('占地', '${model.gridW}×${model.gridD}'),
            FactChipData('零件', '${solution.stepCount} 块'),
            FactChipData('求解尝试', '${solution.attempts} 次'),
            if (colorNames.isNotEmpty) FactChipData('配色', '${colorNames.length} 种'),
          ],
        ),
        if (colorNames.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(
            '配色：${colorNames.join('、')}',
            style: const TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.45),
          ),
        ],
        if (solution.colorFallbacks.isNotEmpty) ...[
          const SizedBox(height: 10),
          const Text(
            '颜色回退（设计色库存不足）',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          for (final fallback in solution.colorFallbacks)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Text(
                '· ${fallback.text}',
                style: const TextStyle(fontSize: 11.5, color: AppColors.warn, height: 1.45),
              ),
            ),
        ],
        if (mismatch) ...[
          const SizedBox(height: 8),
          const Text(
            '注意：该任务的产物文件已在之后重新生成，统计以最新文件为准；运行记录是任务当时的日志。',
            style: TextStyle(fontSize: 11.5, color: AppColors.warn, height: 1.45),
          ),
        ],
      ],
    );
  }
}
