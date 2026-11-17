// 思考过程展示逻辑（与 Web web/thinking.js 同一语义）：
// - 从日志里抽出全部 thinking 回合，并按「同一 phase 下、下一条 thinking 之前最近的 thought」
//   配对中文摘要；
// - 进行中优先展示实时通道；模型输出一律作为不可信纯文本展示（由 Text 组件天然转义）。
import '../models/job.dart';
import 'format.dart' as fmt;

/// 一个思考回合。
class ThinkingTurn {
  const ThinkingTurn({
    required this.phase,
    required this.phaseLabel,
    required this.text,
    required this.thought,
    required this.chars,
    required this.truncated,
    required this.partial,
    required this.elapsed,
    required this.ts,
    required this.key,
    required this.live,
  });

  final String phase;
  final String phaseLabel;
  final String text;

  /// 配对的中文摘要（只有解析成功后的 thought 才有）。
  final String thought;
  final int chars;
  final bool truncated;
  final bool partial;
  final double? elapsed;
  final double? ts;
  final String key;
  final bool live;

  bool get isTruncated => truncated;

  /// 标题行元信息：阶段 · 耗时 · 字数 · 标记。
  String get metaText {
    final bits = <String>[phaseLabel.isEmpty ? '思考' : phaseLabel];
    if (elapsed != null && elapsed! > 0) bits.add('${elapsed!.round()}s');
    bits.add('${_thousands(chars)} 字');
    if (partial) bits.add('未完成');
    if (truncated) bits.add('已截断');
    if (live) bits.add('实时');
    return bits.join(' · ');
  }

  static String _thousands(int value) {
    final text = value.abs().toString();
    final buffer = StringBuffer();
    for (var i = 0; i < text.length; i++) {
      if (i > 0 && (text.length - i) % 3 == 0) buffer.write(',');
      buffer.write(text[i]);
    }
    return value < 0 ? '-$buffer' : buffer.toString();
  }

  factory ThinkingTurn.fromLive(ThinkingLive live) {
    return ThinkingTurn(
      phase: live.phase ?? '',
      phaseLabel: fmt.phaseLabel(live.phase).isEmpty ? '思考' : fmt.phaseLabel(live.phase),
      text: live.text,
      thought: '',
      chars: live.chars > 0 ? live.chars : live.text.length,
      truncated: false,
      partial: live.partial,
      elapsed: live.elapsed,
      ts: null,
      key: 'live',
      live: true,
    );
  }

  factory ThinkingTurn.fromLog(
    LogEntry entry, {
    String thought = '',
    required String key,
  }) {
    return ThinkingTurn(
      phase: entry.phase ?? '',
      phaseLabel: fmt.phaseLabel(entry.phase).isEmpty ? '思考' : fmt.phaseLabel(entry.phase),
      text: entry.text,
      thought: thought,
      chars: entry.chars ?? entry.text.length,
      truncated: entry.truncated,
      partial: entry.partial,
      elapsed: entry.elapsed,
      ts: entry.ts,
      key: key,
      live: false,
    );
  }
}

/// 配对结果：thinking 日志条目 + 可选 thought 摘要条目。
class ThinkingPair {
  const ThinkingPair({required this.entry, required this.thoughtEntry, required this.thought});

  final LogEntry entry;
  final LogEntry? thoughtEntry;
  final String thought;
}

/// 按真实发出顺序配对：thinking 回合结束先落盘，解析成功后才有 thought。
/// 配对规则：同一 phase 下、下一条 thinking 之前最近的 thought 归前一条 thinking。
List<ThinkingPair> pairThoughtEntries(List<LogEntry> logs) {
  final out = <ThinkingPair>[];
  ThinkingPair? lastOpen;
  for (final entry in logs) {
    if (entry.isThinking) {
      final pair = ThinkingPair(entry: entry, thoughtEntry: null, thought: '');
      out.add(pair);
      lastOpen = pair;
      continue;
    }
    if (entry.kind != 'thought' || lastOpen == null || lastOpen.thoughtEntry != null) {
      continue;
    }
    if ((lastOpen.entry.phase ?? '') != (entry.phase ?? '')) continue;
    final text = entry.text.trim();
    if (text.isEmpty) continue;
    lastOpen = ThinkingPair(entry: lastOpen.entry, thoughtEntry: entry, thought: text);
    out[out.length - 1] = lastOpen;
  }
  return out;
}

/// 全部思考回合（历史顺序）。
List<ThinkingTurn> pickThinkingTurns(List<LogEntry> logs) {
  final pairs = pairThoughtEntries(logs);
  final out = <ThinkingTurn>[];
  for (var i = 0; i < pairs.length; i++) {
    final pair = pairs[i];
    if (pair.entry.text.isEmpty) continue;
    out.add(ThinkingTurn.fromLog(pair.entry, thought: pair.thought, key: 'tk$i'));
  }
  return out;
}

/// 当前应展示的思考：进行中优先实时通道，否则最后一条落盘回合。
ThinkingTurn? currentThinking(JobDetail job) {
  final live = job.thinking;
  if (live != null && live.text.isNotEmpty) return ThinkingTurn.fromLive(live);
  final turns = pickThinkingTurns(job.logs);
  return turns.isEmpty ? null : turns.last;
}
