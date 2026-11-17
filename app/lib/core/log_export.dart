// 运行日志 Markdown 导出：
// 由 /api/job/<id> 返回的全部已保留日志在客户端生成，不虚构服务端文件路径；
// 展示层的折叠/合并不得删除导出内容。日志 Markdown 不属于 /files/<name> 产物。
import '../models/job.dart';
import 'format.dart';

/// 生成真实运行日志 Markdown。
String buildRunLogMarkdown(JobDetail job) {
  final result = job.result;
  final out = <String>[
    '# LEGOGOD 运行日志 · ${result?.name ?? job.displayName}',
    '',
    '- 任务 ID：${job.id}',
    '- 状态：${JobStatus.label(job.status)}',
    '- 模式：${modeDisplay(job.mode, job.modeSource)}',
    if (result != null && result.outcome.isNotEmpty)
      '- 交付结果：${JobOutcome.label(result.outcome)}',
    '- 结论：${(result?.ok ?? false) ? '拼装成功' : '未完成'}'
        '；体素 ${result?.voxels ?? '-'}；零件 ${result?.pieces ?? '-'}；'
        '求解尝试 ${result?.attempts ?? '-'} 次',
    if (result?.runId != null) '- run_id：${result!.runId}',
    if (result?.error != null) '- 错误：${result!.error}',
    '',
    '## 时间线',
    '',
  ];
  for (final entry in job.logs) {
    final time = fmtLogTime(entry.ts);
    out.add('### [$time] S${entry.step ?? '-'} · ${entry.kind}');
    out.add('```');
    out.add(entry.text);
    out.add('```');
  }
  return out.join('\n');
}

/// 日志导出文件名：可识别作品。
String runLogFileName(JobDetail job) {
  final result = job.result;
  final slug = result?.slug;
  final name = result?.name ?? job.id;
  final base = (slug != null && slug.isNotEmpty) ? slug : name;
  return '运行日志_${_safeFileName(base)}.md';
}

/// 把任意展示名转成安全文件名。
String _safeFileName(String raw) {
  final text = raw.replaceAll(RegExp(r'[\\/:*?"<>|\s]+'), '_').trim();
  final trimmed = text.length > 60 ? text.substring(0, 60) : text;
  return trimmed.isEmpty ? 'job' : trimmed;
}
