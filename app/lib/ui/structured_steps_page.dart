// 拼装步骤的结构化、可读预览：
// 默认展示按层分组的真实步骤（零件、颜色、层、区域、坐标、旋转、预拼说明），
// 只有用户主动选择「查看原始文件」时才展示服务端 Markdown 原文，避免把源码当默认预览。
// 保存/分享始终使用服务端真实产物字节，不生成空文件。
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_scope.dart';
import '../core/studio_helpers.dart';
import '../core/theme.dart';
import '../models/artifacts.dart';
import '../models/job.dart';
import '../models/part.dart';
import '../services/file_actions.dart';
import 'widgets/common.dart';

/// 结构化拼装步骤页。
class StructuredStepsPage extends StatefulWidget {
  const StructuredStepsPage({super.key, required this.job});

  final JobDetail job;

  @override
  State<StructuredStepsPage> createState() => _StructuredStepsPageState();
}

class _StructuredStepsPageState extends State<StructuredStepsPage> {
  StudioArtifacts? _artifacts;
  String? _loadError;
  bool _loading = true;
  bool _rawMode = false;
  String? _rawText;
  String? _rawError;
  bool _rawLoading = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  Future<void> _load() async {
    final app = AppScope.read(context);
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final artifacts = await app.loadStudioArtifacts(widget.job.id);
      if (!mounted) return;
      setState(() {
        _artifacts = artifacts;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = describeError(e);
        _loading = false;
      });
    }
  }

  String? get _mdPath => widget.job.result?.mdPath;

  /// 读取真实 Markdown 原文（只在用户切换原始文件时请求）。
  Future<void> _loadRaw() async {
    final name = _mdPath;
    if (name == null) return;
    if (_rawText != null || _rawLoading) return;
    setState(() => _rawLoading = true);
    try {
      final app = AppScope.read(context);
      final bytes = await app.api.artifactBytes('files', name);
      final text = utf8.decode(bytes, allowMalformed: true);
      if (!mounted) return;
      setState(() {
        _rawText = text;
        _rawError = null;
        _rawLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _rawError = describeError(e);
        _rawLoading = false;
      });
    }
  }

  void _toggleRaw() {
    setState(() => _rawMode = !_rawMode);
    if (_rawMode) unawaited(_loadRaw());
  }

  /// 读取 Markdown 真实字节（保存/分享用）。
  Future<List<int>?> _readBytes() async {
    final name = _mdPath;
    if (name == null) return null;
    final app = AppScope.read(context);
    return app.api.artifactBytes('files', name);
  }

  Future<void> _save() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final bytes = await _readBytes();
      if (!mounted) return;
      if (bytes == null) {
        showNotice(context, '该任务没有「拼装步骤.md」产物，无法保存');
        return;
      }
      final result = await FileActions.saveArtifact(
        fileName: _mdPath!,
        bytes: bytes,
        mime: 'text/markdown',
      );
      if (mounted) showNotice(context, result.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _share() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final bytes = await _readBytes();
      if (!mounted) return;
      if (bytes == null) {
        showNotice(context, '该任务没有「拼装步骤.md」产物，无法分享');
        return;
      }
      final result = await FileActions.shareArtifact(
        fileName: _mdPath!,
        bytes: bytes,
      );
      if (mounted) showNotice(context, result.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('拼装步骤'),
        actions: [
          TextButton.icon(
            onPressed: _toggleRaw,
            icon: Icon(
              _rawMode ? Icons.view_list_outlined : Icons.description_outlined,
              size: 18,
            ),
            label: Text(_rawMode ? '查看结构化内容' : '查看原始文件'),
          ),
        ],
      ),
      body: _buildBody(),
      bottomNavigationBar: BottomPrimaryBar(
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _busy || _mdPath == null ? null : _save,
                icon: const Icon(Icons.download, size: 18),
                label: const Text('保存到文件'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: FilledButton.icon(
                onPressed: _busy || _mdPath == null ? null : _share,
                icon: const Icon(Icons.share, size: 18),
                label: const Text('系统分享'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_rawMode) return _buildRaw();
    if (_loading) return const LoadingBlock(text: '正在加载拼装步骤……');
    if (_loadError != null) {
      return ErrorView(title: '拼装步骤加载失败', message: _loadError!, onRetry: _load);
    }
    final artifacts = _artifacts;
    if (artifacts == null) {
      return const EmptyState(
        icon: '🧩',
        title: '没有可展示的拼装步骤',
        message: '该任务没有可读取的 model / solution 产物文件。',
      );
    }
    return _buildStructured(artifacts);
  }

  Widget _buildRaw() {
    if (_mdPath == null) {
      return const EmptyState(
        icon: '📄',
        title: '没有原始步骤文件',
        message: '该任务没有「拼装步骤.md」产物，不能展示原始文件。',
      );
    }
    if (_rawLoading) return const LoadingBlock(text: '正在读取原始文件……');
    if (_rawError != null) {
      return ErrorView(
        title: '原始文件读取失败',
        message: _rawError!,
        onRetry: () {
          setState(() => _rawError = null);
          _loadRaw();
        },
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderSoft),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              '原始文件：服务端「拼装步骤.md」原文（默认视图为结构化步骤）',
              style: TextStyle(fontSize: 11.5, color: AppColors.textMuted),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: SingleChildScrollView(
                child: SelectableText(
                  _rawText ?? '',
                  style: const TextStyle(
                    fontSize: 11.5,
                    height: 1.45,
                    fontFamily: 'monospace',
                    color: AppColors.textMuted,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStructured(StudioArtifacts artifacts) {
    final solution = artifacts.solution;
    final model = artifacts.model;
    final parts = artifacts.parts;
    final layers = [...model.layers]..sort((a, b) => a.y.compareTo(b.y));
    final plan = SubAssemblyPlan.fromSolution(solution);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
      children: [
        AppCard(
          child: Text(
            '共 ${solution.stepCount} 块零件 · ${model.layerCount} 层 · '
            '占地 ${model.gridW}×${model.gridD} · 体素 ${model.totalVoxels}'
            '${solution.usageMatchesSteps ? '（用量合计与步骤数一致）' : '（用量合计与步骤数不一致，按真实文件展示）'}',
            style: const TextStyle(fontSize: 12.5, height: 1.5),
          ),
        ),
        const SizedBox(height: 10),
        for (final layer in layers)
          _buildLayer(layer, solution, parts, model, plan),
      ],
    );
  }

  Widget _buildLayer(
    ModelLayer layer,
    SolutionData solution,
    PartsCatalog parts,
    ModelData model,
    SubAssemblyPlan plan,
  ) {
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
            initiallyExpanded: layer.y == 0,
            title: Text(
              'y=${layer.y} · $module · ${steps.length} 块',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
            childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
            children: [
              for (final step in steps)
                _StepDumpRow(
                  step: step,
                  solution: solution,
                  parts: parts,
                  model: model,
                  plan: plan,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 单条结构化步骤。
class _StepDumpRow extends StatelessWidget {
  const _StepDumpRow({
    required this.step,
    required this.solution,
    required this.parts,
    required this.model,
    required this.plan,
  });

  final BrickStep step;
  final SolutionData solution;
  final PartsCatalog parts;
  final ModelData model;
  final SubAssemblyPlan plan;

  @override
  Widget build(BuildContext context) {
    final part = parts.partOf(step.piece);
    final info = stepInfoOf(
      step: step,
      model: model,
      solution: solution,
      plan: plan,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 28,
                child: Text(
                  '${step.step}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.textDim,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
              if (part != null) ...[
                ColorDot(part.hex, size: 14),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${part.colorName} ${part.name}',
                    style: const TextStyle(fontSize: 12.5, height: 1.4),
                  ),
                ),
              ] else
                Expanded(
                  child: Text(
                    '未知零件 ${step.piece}（零件目录未同步，不能静默省略）',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.danger,
                    ),
                  ),
                ),
              Text(
                '${step.rangeText}${step.rotate ? ' · 旋转 90°' : ''}',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textMuted,
                ),
              ),
            ],
          ),
          if (info.subLabel.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 28, top: 3),
              child: Text(
                step.step ==
                        solution
                            .subassemblies[plan.subOfStep[step.step]! - 1]
                            .dockStep
                    ? '预拼子模块 sub${plan.subOfStep[step.step]} 跨接锁扣砖 —— 将预拼好的整体扣入主结构'
                    : '预拼子模块 sub${plan.subOfStep[step.step]} 预拼件 —— 先在桌面预拼，再整组扣入',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.fallback,
                  height: 1.4,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
