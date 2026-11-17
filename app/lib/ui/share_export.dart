// 分享与导出统一面板：
// 五类真实产物集中在一个二级面板，按常用程度分组，不再在各页面平铺操作条。
// - 常用：拼装步骤（默认结构化内容，可切换原始文件）、独立 3D 页（系统浏览器）；
// - 高级文件：设计 JSON、方案 JSON、运行日志 Markdown。
// 所有内容来自该任务真实结果 /files/* 或由 /api/job 完整日志生成，绝不生成空文件或伪造路径。
import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_scope.dart';
import '../core/log_export.dart';
import '../core/theme.dart';
import '../models/job.dart';
import '../services/file_actions.dart';
import 'structured_steps_page.dart';
import 'widgets/common.dart';

/// 打开统一的「分享与导出」面板。
Future<void> showShareExportSheet(BuildContext context, JobDetail job) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.bgElevated,
    builder: (_) => _ShareExportSheet(job: job),
  );
}

/// 面板中的一行导出项。
class _ExportItem {
  const _ExportItem({
    required this.label,
    required this.hint,
    required this.icon,
    required this.available,
    required this.unavailableReason,
    required this.onTap,
  });

  final String label;
  final String hint;
  final IconData icon;
  final bool available;
  final String unavailableReason;
  final Future<void> Function(BuildContext context) onTap;
}

class _ShareExportSheet extends StatelessWidget {
  const _ShareExportSheet({required this.job});

  final JobDetail job;

  bool get _stepsAvailable =>
      job.result?.mdPath != null ||
      (job.result?.modelPath != null && job.result?.solutionPath != null);

  bool get _vizAvailable => job.result?.vizFile != null;

  bool get _modelAvailable => job.result?.modelPath != null;

  bool get _solutionAvailable => job.result?.solutionPath != null;

  bool get _logAvailable => job.logs.isNotEmpty;

  List<_ExportItem> _items(BuildContext context) => [
    _ExportItem(
      label: '拼装步骤',
      hint: '结构化步骤内容；可在页面内切换原始 Markdown',
      icon: Icons.format_list_numbered,
      available: _stepsAvailable,
      unavailableReason: '该任务没有拼装步骤产物',
      onTap: (context) async {
        Navigator.of(context).pop();
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => StructuredStepsPage(job: job),
          ),
        );
      },
    ),
    _ExportItem(
      label: '独立 3D 页',
      hint: '用系统浏览器打开服务端 3D 页面',
      icon: Icons.open_in_browser,
      available: _vizAvailable,
      unavailableReason: '该任务没有独立 3D 页产物',
      onTap: _openViz,
    ),
    _ExportItem(
      label: '设计 JSON',
      hint: '服务端设计模型文件',
      icon: Icons.data_object,
      available: _modelAvailable,
      unavailableReason: '该任务没有设计 JSON 产物',
      onTap: (context) => _openPreview(context, kind: _PreviewKind.modelJson),
    ),
    _ExportItem(
      label: '方案 JSON',
      hint: '服务端装配方案文件',
      icon: Icons.account_tree_outlined,
      available: _solutionAvailable,
      unavailableReason: '该任务没有方案 JSON 产物',
      onTap: (context) =>
          _openPreview(context, kind: _PreviewKind.solutionJson),
    ),
    _ExportItem(
      label: '运行日志 Markdown',
      hint: '由 /api/job 返回的全部已保留日志生成',
      icon: Icons.subject,
      available: _logAvailable,
      unavailableReason: '该任务没有保留运行日志',
      onTap: (context) => _openPreview(context, kind: _PreviewKind.runLog),
    ),
  ];

  Future<void> _openViz(BuildContext context) async {
    final app = AppScope.read(context);
    final name = job.result?.vizFile;
    if (name == null) return;
    final url = app.api.absoluteUrl('/viz/${Uri.encodeComponent(name)}');
    final confirmed = await showConfirmDialog(
      context,
      title: '将在系统浏览器打开',
      message: '将用系统浏览器打开独立 3D 页：\n$url\n\n看完后按系统返回键回到 LEGOGOD。',
      confirmText: '打开',
    );
    if (!confirmed || !context.mounted) return;
    final result = await FileActions.openExternal(url);
    if (context.mounted) showNotice(context, result.message);
  }

  Future<void> _openPreview(
    BuildContext context, {
    required _PreviewKind kind,
  }) async {
    Navigator.of(context).pop();
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _ArtifactPreviewPage(job: job, kind: kind),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final items = _items(context);
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.82,
        ),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '分享与导出',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
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
            const SectionTitle(
              '常用',
              padding: EdgeInsets.only(top: 12, bottom: 6),
            ),
            for (final item in items.take(2)) _buildRow(context, item),
            const SectionTitle(
              '高级文件',
              padding: EdgeInsets.only(top: 12, bottom: 6),
            ),
            for (final item in items.skip(2)) _buildRow(context, item),
            const SizedBox(height: 8),
            const Text(
              '文件内容全部来自该任务真实产物或真实 API 日志；没有产物的项会明确标注，不会生成空文件。',
              style: TextStyle(
                fontSize: 11,
                color: AppColors.textDim,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRow(BuildContext context, _ExportItem item) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: item.available ? () => item.onTap(context) : null,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Icon(
                  item.icon,
                  size: 20,
                  color: item.available
                      ? AppColors.yellowDeep
                      : AppColors.textDim,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.label,
                        style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w600,
                          color: item.available
                              ? AppColors.text
                              : AppColors.textDim,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        item.available ? item.hint : item.unavailableReason,
                        style: TextStyle(
                          fontSize: 11,
                          color: item.available
                              ? AppColors.textMuted
                              : AppColors.textDim,
                        ),
                      ),
                    ],
                  ),
                ),
                if (item.available)
                  const Icon(
                    Icons.chevron_right,
                    size: 18,
                    color: AppColors.textDim,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 可预览的产物类型。
enum _PreviewKind { modelJson, solutionJson, runLog }

/// 单文件预览页：真实字节 + 保存 / 系统分享 + 失败重试。
class _ArtifactPreviewPage extends StatefulWidget {
  const _ArtifactPreviewPage({required this.job, required this.kind});

  final JobDetail job;
  final _PreviewKind kind;

  @override
  State<_ArtifactPreviewPage> createState() => _ArtifactPreviewPageState();
}

class _ArtifactPreviewPageState extends State<_ArtifactPreviewPage> {
  String? _fileName;
  String? _hint;
  String? _mime;
  List<int>? _bytes;
  String? _error;
  bool _loading = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = widget.job.result;
      switch (widget.kind) {
        case _PreviewKind.modelJson:
          final name = result?.modelPath;
          if (name == null) throw StateError('该任务没有设计 JSON 产物');
          final app = AppScope.read(context);
          final bytes = await app.api.artifactBytes('files', name);
          if (!mounted) return;
          setState(() {
            _fileName = name;
            _hint = '服务端设计模型 JSON';
            _mime = 'application/json';
            _bytes = bytes;
            _loading = false;
          });
        case _PreviewKind.solutionJson:
          final name = result?.solutionPath;
          if (name == null) throw StateError('该任务没有方案 JSON 产物');
          final app = AppScope.read(context);
          final bytes = await app.api.artifactBytes('files', name);
          if (!mounted) return;
          setState(() {
            _fileName = name;
            _hint = '服务端装配方案 JSON';
            _mime = 'application/json';
            _bytes = bytes;
            _loading = false;
          });
        case _PreviewKind.runLog:
          final markdown = buildRunLogMarkdown(widget.job);
          if (!mounted) return;
          setState(() {
            _fileName = runLogFileName(widget.job);
            _hint = '由 /api/job 返回的全部已保留日志在客户端生成';
            _mime = 'text/markdown';
            _bytes = utf8.encode(markdown);
            _loading = false;
          });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = describeError(e);
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    final bytes = _bytes;
    final name = _fileName;
    if (bytes == null || name == null || _busy) return;
    setState(() => _busy = true);
    final result = await FileActions.saveArtifact(
      fileName: name,
      bytes: bytes,
      mime: _mime,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    showNotice(context, result.message);
  }

  Future<void> _share() async {
    final bytes = _bytes;
    final name = _fileName;
    if (bytes == null || name == null || _busy) return;
    setState(() => _busy = true);
    final result = await FileActions.shareArtifact(
      fileName: name,
      bytes: bytes,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    showNotice(context, result.message);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_fileName ?? '文件预览')),
      body: _buildBody(),
      bottomNavigationBar: BottomPrimaryBar(
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _busy || _bytes == null ? null : _save,
                icon: const Icon(Icons.download, size: 18),
                label: const Text('保存到文件'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: FilledButton.icon(
                onPressed: _busy || _bytes == null ? null : _share,
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
    if (_loading) return const LoadingBlock(text: '正在读取文件……');
    if (_error != null) {
      return ErrorView(title: '文件读取失败', message: _error!, onRetry: _load);
    }
    final bytes = _bytes ?? const <int>[];
    String text;
    try {
      text = utf8.decode(bytes);
    } catch (_) {
      text = '（文件不是 UTF-8 文本，无法在 APP 内预览；可使用保存或分享）';
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
            Text(
              _hint ?? '',
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: SingleChildScrollView(
                child: SelectableText(
                  text,
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
}
