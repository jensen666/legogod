// 生成记录页共用展示文案：把真实来源字段、耗时字段翻译成中文说明。
// 只做「真实字段 → 文案」的映射，不推导结论、不把「无记录」冒充成任何显式结论。
import '../../core/format.dart';
import '../../models/job.dart';

/// 交付结果来源文案：显式记录 / 兼容推导 / 无记录 / 服务端未提供。
String recordOutcomeSourceText(String? source) {
  switch (source) {
    case OutcomeSource.result:
      return '结果显式记录';
    case OutcomeSource.derived:
      return '兼容推导（非显式结论）';
    case OutcomeSource.none:
      return '无记录';
    case null:
      return '服务端未提供来源字段';
    default:
      return '未知来源（$source）';
  }
}

/// 模式来源文案：原始来源代码 + 中文说明（技术信息区使用，显式展示不隐藏）。
String recordModeSourceCodeText(String? source) {
  if (source == null || source.isEmpty) return '服务端未提供模式来源字段';
  return '$source（${modeSourceHint(source)}）';
}

/// 总耗时文案：有真实耗时显示耗时；进行中显示已运行时长；否则如实说明未记录。
String recordElapsedText(JobDetail job) {
  final seconds = job.result?.elapsedSeconds;
  if (seconds != null) return fmtClock(seconds);
  if (job.isRunning) return '进行中（已运行 ${fmtElapsed(job.startedAt)}）';
  return '未记录';
}
