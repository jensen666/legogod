// 运行日志底部抽屉：创作页与任务详情共用；支持导出客户端生成的运行日志 Markdown。
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../core/log_export.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../services/file_actions.dart';
import 'common.dart';
import 'log_view.dart';

/// 打开运行日志抽屉。
Future<void> showRunLogSheet(BuildContext context, {required JobDetail job}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.bgElevated,
    builder: (context) => _RunLogSheet(job: job),
  );
}

class _RunLogSheet extends StatelessWidget {
  const _RunLogSheet({required this.job});

  final JobDetail job;

  Future<void> _export(BuildContext context) async {
    final markdown = buildRunLogMarkdown(job);
    final result = await FileActions.shareArtifact(
      fileName: runLogFileName(job),
      bytes: utf8.encode(markdown),
      text: 'LEGOGOD 运行日志 · ${job.displayName}',
    );
    if (!context.mounted) return;
    showNotice(context, result.message);
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.of(context).size.height;
    return SafeArea(
      child: SizedBox(
        height: height * 0.85,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 6),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('运行日志',
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                        const SizedBox(height: 2),
                        Text(
                          '共 ${job.logs.length} 条（接口当前保留的完整集合）',
                          style: const TextStyle(
                              fontSize: 11, color: AppColors.textMuted),
                        ),
                      ],
                    ),
                  ),
                  TextButton.icon(
                    onPressed: job.logs.isEmpty ? null : () => _export(context),
                    icon: const Icon(Icons.ios_share, size: 16),
                    label: const Text('导出 .md', style: TextStyle(fontSize: 12)),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: LogListView(
                logs: job.logs,
                running: job.isRunning,
                liveText: job.live,
                emptyText: '还没有运行日志。',
              ),
            ),
          ],
        ),
      ),
    );
  }
}
