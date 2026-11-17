// 诊断与高级页：集中展示连接诊断摘要、原始网络错误与本地调试日志，
// 并提供复制诊断日志、重新拉取真实数据与调试日志折叠查看；所有内容不含令牌与需求原文。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app_scope.dart';
import '../../core/theme.dart';
import '../../ui/widgets/common.dart';

/// 诊断与高级页。
class DiagnosticsPage extends StatelessWidget {
  const DiagnosticsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final rawError = app.lastNetworkError;
    return Scaffold(
      appBar: AppBar(title: const Text('诊断与高级')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          const SectionTitle('诊断摘要'),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SelectableText(
                  app.diagnostics,
                  style: const TextStyle(
                    fontSize: 12,
                    height: 1.6,
                    color: AppColors.textMuted,
                    fontFamily: 'monospace',
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () async {
                          final state = AppScope.read(context);
                          await Clipboard.setData(
                            ClipboardData(text: state.exportDebugLog()),
                          );
                          if (context.mounted) {
                            showNotice(context, '已复制诊断日志（不含令牌与需求内容）');
                          }
                        },
                        icon: const Icon(Icons.copy, size: 16),
                        label: const Text('复制诊断日志'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () async {
                          final state = AppScope.read(context);
                          await state.refreshParts();
                          await state.refreshRunning(silent: false);
                          if (context.mounted) showNotice(context, '已重新拉取任务与零件');
                        },
                        icon: const Icon(Icons.refresh, size: 16),
                        label: const Text('重新拉取数据'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          if (rawError != null && rawError.isNotEmpty) ...[
            const SectionTitle('原始网络错误'),
            AppCard(
              child: SelectableText(
                rawError,
                style: const TextStyle(
                  fontSize: 11.5,
                  height: 1.6,
                  color: AppColors.danger,
                  fontFamily: 'monospace',
                ),
              ),
            ),
          ],
          const SizedBox(height: 16),
          ExpandableSection(
            title: '调试日志',
            subtitle: '默认收起；展开查看最近 ${app.debugLog.length} 条本地记录（不含令牌与需求原文）',
            child: _DebugLogView(text: app.exportDebugLog()),
          ),
        ],
      ),
    );
  }
}

/// 调试日志正文：等宽小字，长文在限高区域内滚动。
class _DebugLogView extends StatelessWidget {
  const _DebugLogView({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final content = text.trim().isEmpty ? '暂无调试日志。' : text;
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 280),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Scrollbar(
        child: SingleChildScrollView(
          child: SelectableText(
            content,
            style: const TextStyle(
              fontSize: 10.5,
              height: 1.5,
              color: AppColors.textMuted,
              fontFamily: 'monospace',
            ),
          ),
        ),
      ),
    );
  }
}
