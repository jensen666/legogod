// 生成记录「技术信息与文件入口」区块：
// 集中展示 job_id、run_id、retryOf、模式来源、交付结果来源、体素、求解尝试、
// 模型/方案版本信息（slug/revision/modelHash/schemaVersion）与真实产物文件路径，
// 并提供本页唯一的「分享与导出」统一入口（不在此平铺五类产物按钮）。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../models/result.dart';
import '../../ui/share_export.dart';
import '../../ui/widgets/common.dart';
import 'record_texts.dart';

/// 技术信息与文件入口区块。
class RecordTechSection extends StatefulWidget {
  const RecordTechSection({super.key, required this.job});

  /// 目标任务详情。
  final JobDetail job;

  @override
  State<RecordTechSection> createState() => _RecordTechSectionState();
}

class _RecordTechSectionState extends State<RecordTechSection> {
  StudioArtifacts? _artifacts;
  String? _artifactError;
  bool _artifactLoading = false;
  bool _artifactRequested = false;

  @override
  void initState() {
    super.initState();
    // 有真实产物路径时先进入加载态，避免首帧误显示「未读取到方案文件版本信息」。
    final result = widget.job.result;
    _artifactLoading = result != null &&
        result.modelPath != null &&
        result.solutionPath != null;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _loadVersionInfo();
    });
  }

  /// 版本信息（modelHash/schemaVersion 等）只存在于真实产物文件，展开时按需读取；
  /// 没有产物路径的任务不发起请求，读取失败如实显示并可重试。
  Future<void> _loadVersionInfo() async {
    final result = widget.job.result;
    if (result == null || result.modelPath == null || result.solutionPath == null) {
      return;
    }
    if (_artifactRequested && _artifacts != null) return;
    _artifactRequested = true;
    setState(() {
      _artifactLoading = true;
      _artifactError = null;
    });
    try {
      final artifacts = await AppScope.read(context).loadStudioArtifacts(widget.job.id);
      if (!mounted) return;
      setState(() {
        _artifacts = artifacts;
        _artifactLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _artifactError = describeError(e);
        _artifactLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final result = widget.job.result;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        KeyValueRow(label: 'job_id', value: widget.job.id),
        KeyValueRow(label: 'run_id', value: result?.runId ?? '未记录'),
        KeyValueRow(label: 'retryOf', value: widget.job.retryOf ?? '无（非重试任务）'),
        KeyValueRow(
          label: 'modeSource',
          value: recordModeSourceCodeText(widget.job.modeSource),
        ),
        KeyValueRow(
          label: 'outcomeSource',
          value: recordOutcomeSourceText(widget.job.outcomeSource),
        ),
        KeyValueRow(
          label: '体素',
          value: result?.voxels == null ? '未记录' : '${result!.voxels}',
        ),
        KeyValueRow(
          label: '求解尝试',
          value: result?.attempts == null ? '未记录' : '${result!.attempts} 次',
        ),
        KeyValueRow(label: '模型版本', value: _modelVersionText(result)),
        _solutionVersionRow(),
        const SizedBox(height: 12),
        const Text(
          '真实产物文件路径',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 6),
        ..._pathRows(result),
        const SizedBox(height: 14),
        FilledButton.tonalIcon(
          key: const Key('record-open-export'),
          onPressed: () => showShareExportSheet(context, widget.job),
          icon: const Icon(Icons.ios_share, size: 18),
          label: const Text('分享与导出'),
        ),
        const SizedBox(height: 8),
        const Text(
          '五类真实产物（拼装步骤、独立 3D 页、设计 JSON、方案 JSON、运行日志 Markdown）'
          '统一在「分享与导出」面板中选择；没有产物的项会明确标注，不会生成空文件。',
          style: TextStyle(fontSize: 11, color: AppColors.textDim, height: 1.45),
        ),
      ],
    );
  }

  /// 模型版本：来自 result 的真实 slug / revision / model_hash 字段（有则展示）。
  String _modelVersionText(ResultData? result) {
    if (result == null) return '未记录';
    final bits = <String>[];
    final slug = result.slug;
    if (slug != null && slug.isNotEmpty) bits.add('slug $slug');
    final revision = result.raw['revision'];
    if (revision is num) bits.add('revision $revision');
    final hash = result.raw['model_hash'];
    if (hash is String && hash.isNotEmpty) bits.add('modelHash $hash');
    return bits.isEmpty ? '未记录' : bits.join(' · ');
  }

  /// 方案版本行：方案文件里的 revision / modelHash / schemaVersion，按需读取真实文件。
  Widget _solutionVersionRow() {
    final result = widget.job.result;
    if (result == null || result.modelPath == null || result.solutionPath == null) {
      return const KeyValueRow(label: '方案版本', value: '该任务没有可读取的模型/方案产物文件');
    }
    if (_artifactLoading) {
      return const Padding(
        padding: EdgeInsets.only(top: 4, bottom: 4),
        child: Text(
          '正在读取方案文件版本信息……',
          style: TextStyle(fontSize: 12, color: AppColors.textMuted),
        ),
      );
    }
    final error = _artifactError;
    if (error != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '方案文件版本信息读取失败：$error',
            style: const TextStyle(fontSize: 11.5, color: AppColors.danger, height: 1.45),
          ),
          TextButton(
            style: TextButton.styleFrom(minimumSize: const Size(48, 40)),
            onPressed: _loadVersionInfo,
            child: const Text('重试', style: TextStyle(fontSize: 12)),
          ),
        ],
      );
    }
    final solution = _artifacts?.solution;
    if (solution == null) {
      return const KeyValueRow(label: '方案版本', value: '未读取到方案文件版本信息');
    }
    // 方案文件里的 revision 字段是字符串版本号（如 r001），类型化模型只接整数版本号；
    // 整数版本号已在上一行「模型版本」展示，这里展示方案文件自身的哈希与结构版本。
    final bits = <String>[];
    if (solution.revision != null) bits.add('revision ${solution.revision}');
    final modelHash = solution.modelHash;
    if (modelHash != null && modelHash.isNotEmpty) bits.add('modelHash $modelHash');
    if (solution.schemaVersion != null) bits.add('schemaVersion ${solution.schemaVersion}');
    return KeyValueRow(
      label: '方案版本',
      value: bits.isEmpty ? '方案文件没有可展示的版本字段' : bits.join(' · '),
    );
  }

  /// 真实产物路径行：只展示服务端真实返回的路径，没有则如实说明。
  List<Widget> _pathRows(ResultData? result) {
    final rows = <Widget>[];
    void add(String label, String? value) {
      if (value != null && value.isNotEmpty) {
        rows.add(KeyValueRow(label: label, value: value));
      }
    }

    add('model_path', result?.modelPath);
    add('solution_path', result?.solutionPath);
    add('md_path', result?.mdPath);
    add('viz_file', result?.vizFile);
    if (rows.isEmpty) {
      rows.add(const Text(
        '该任务没有记录产物文件路径。',
        style: TextStyle(fontSize: 12, color: AppColors.textMuted),
      ));
    }
    return rows;
  }
}
