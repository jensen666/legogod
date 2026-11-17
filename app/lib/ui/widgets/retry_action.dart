// 通用「按原模式重试」按钮：请求在途时禁用并显示进行中，防快速连点创建多个真实任务。
// 状态层 AppState.retryJob 另有同一任务的 Future 去重作为第二道防线。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/format.dart';
import '../../models/job.dart';
import 'common.dart';

/// 重试按钮（新建任务成功后由 [onCreated] 决定跳转行为）。
class RetryJobButton extends StatefulWidget {
  const RetryJobButton({
    super.key,
    required this.jobId,
    required this.mode,
    required this.onCreated,
    this.label,
    this.tonal = false,
  });

  final String jobId;
  final String mode;
  final Future<void> Function(String newId) onCreated;
  final String? label;

  /// true 用于强调样式（实时舞台等）。
  final bool tonal;

  @override
  State<RetryJobButton> createState() => _RetryJobButtonState();
}

class _RetryJobButtonState extends State<RetryJobButton> {
  bool _busy = false;

  Future<void> _run() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final app = AppScope.read(context);
      final newId = await app.retryJob(widget.jobId);
      if (!mounted) return;
      await widget.onCreated(newId);
    } catch (e) {
      if (mounted) showNotice(context, '重试失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = _busy ? '重试中…' : (widget.label ?? retryLabel(widget.mode));
    final icon = _busy
        ? const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        : const Icon(Icons.refresh, size: 16);
    if (widget.tonal) {
      return FilledButton.tonalIcon(
        onPressed: _busy ? null : _run,
        icon: icon,
        label: Text(text),
      );
    }
    return OutlinedButton.icon(
      onPressed: _busy ? null : _run,
      icon: icon,
      label: Text(text, style: const TextStyle(fontSize: 12)),
    );
  }
}
