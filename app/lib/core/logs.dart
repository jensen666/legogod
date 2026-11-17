// 运行日志展示逻辑（与 Web web/logview.js 同一语义）：
// - 求解器连续明细合并为可折叠分组；
// - 已配对 thought 摘要并入思考块，不再单独占行；空 thought 丢弃；
// - 里程碑按关键事件与求解关键字过滤。
// 折叠/合并不影响导出：导出使用完整日志集合（见 log_export.dart）。
import '../models/job.dart';
import 'thinking.dart';

/// 日志展示块。
class LogBlock {
  const LogBlock.phase(this.entry)
      : type = 'phase',
        items = const <LogEntry>[],
        thought = '';

  const LogBlock.line(this.entry, {this.thought = ''})
      : type = 'line',
        items = const <LogEntry>[];

  const LogBlock.solver(this.items)
      : type = 'solver',
        entry = null,
        thought = '';

  final String type;
  final LogEntry? entry;
  final List<LogEntry> items;

  /// 合并到思考块标题的中文摘要。
  final String thought;
}

/// 把原始日志整理成展示块。
List<LogBlock> presentLogs(List<LogEntry> logs) {
  final out = <LogBlock>[];
  List<LogEntry>? bucket;
  final pairs = pairThoughtEntries(logs);
  final byEntry = <LogEntry, String>{};
  final absorbed = <LogEntry>{};
  for (final pair in pairs) {
    byEntry[pair.entry] = pair.thought;
    final thoughtEntry = pair.thoughtEntry;
    if (thoughtEntry != null) absorbed.add(thoughtEntry);
  }
  void flush() {
    final current = bucket;
    if (current != null && current.isNotEmpty) {
      out.add(LogBlock.solver(List<LogEntry>.unmodifiable(current)));
    }
    bucket = null;
  }

  for (final entry in logs) {
    if (absorbed.contains(entry)) continue;
    if (entry.kind == 'thought' && entry.text.trim().isEmpty) continue;
    if (entry.isSolver) {
      (bucket ??= <LogEntry>[]).add(entry);
      continue;
    }
    flush();
    if (entry.isPhase) {
      out.add(LogBlock.phase(entry));
    } else {
      out.add(LogBlock.line(entry, thought: byEntry[entry] ?? ''));
    }
  }
  flush();
  return out;
}

/// 里程碑事件（阶段 / 评审 / 结果 / 错误 / 版本 / 修订 / 规划 / 关键求解事件）。
List<LogEntry> milestoneLogs(List<LogEntry> logs) {
  final keySolve = RegExp(r'求解成功|求解结束：失败|校验未通过|设计已保存|求解失败');
  final out = <LogEntry>[];
  for (final entry in logs) {
    if (entry.isThinking) continue;
    if (entry.isMilestone || keySolve.hasMatch(entry.text)) {
      out.add(entry);
    }
  }
  return out;
}
