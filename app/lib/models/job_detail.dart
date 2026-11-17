// 任务详情与实时通道 DTO（StageInfo/ProgressInfo/ThinkingLive/LogEntry/JobDetail）。
import 'design.dart';
import 'job_core.dart';
import 'json.dart';
import 'result.dart';

/// 阶段馈送（只来自服务端真实上报）。
class StageInfo {
  const StageInfo({required this.current, required this.seen, required this.revise});

  final String? current;
  final List<String> seen;
  final int revise;

  static const StageInfo empty = StageInfo(current: null, seen: <String>[], revise: 0);

  /// 服务端出现的阶段列表（当前阶段若不在 seen 中会补入）。
  List<String> get allSeen {
    final list = <String>[...seen];
    final cur = current;
    if (cur != null && cur.isNotEmpty && !list.contains(cur)) list.add(cur);
    return list;
  }

  factory StageInfo.fromJson(Object? raw) {
    final map = asMap(raw);
    return StageInfo(
      current: asStringOrNull(map['current']),
      seen: [for (final item in asList(map['seen'])) asString(item)],
      revise: asInt(map['revise']),
    );
  }

  Map<String, dynamic> toJson() => {
        'current': current,
        'seen': seen,
        'revise': revise,
      };
}

/// 求解进度（服务端显式上报的层号/总层数/轮次；无数据不拼接虚假进度）。
class ProgressInfo {
  const ProgressInfo({
    required this.layer,
    required this.total,
    required this.round,
    this.y,
    this.rounds,
  });

  final int layer;
  final int total;
  final int round;
  final int? y;
  final int? rounds;

  /// 展示文案；三个必要字段缺失时为空字符串（不显示伪进度）。
  String get text {
    if (layer < 1 || total < 1 || round < 1) return '';
    final yText = y != null ? '（y=$y）' : '';
    return '正在铺第 $layer 层$yText，共 $total 层，第 $round 轮';
  }

  factory ProgressInfo.fromJson(Object? raw) {
    final map = asMap(raw);
    return ProgressInfo(
      layer: asInt(map['layer']),
      total: asInt(map['total']),
      round: asInt(map['round']),
      y: asIntOrNull(map['y']),
      rounds: asIntOrNull(map['rounds']),
    );
  }

  Map<String, dynamic> toJson() => {
        'layer': layer,
        'total': total,
        'round': round,
        'y': y,
        'rounds': rounds,
      };
}

/// 实时思考通道（未完成时覆盖，完成后由日志条目接管）。
class ThinkingLive {
  const ThinkingLive({
    required this.phase,
    required this.text,
    required this.elapsed,
    required this.done,
    required this.partial,
    required this.chars,
  });

  final String? phase;
  final String text;
  final double? elapsed;
  final bool done;
  final bool partial;
  final int chars;

  bool get isUsable => text.isNotEmpty;

  factory ThinkingLive.fromJson(Object? raw) {
    final map = asMap(raw);
    return ThinkingLive(
      phase: asStringOrNull(map['phase']),
      text: asString(map['text']),
      elapsed: asDoubleOrNull(map['elapsed']),
      done: asBool(map['done']),
      partial: asBool(map['partial']),
      chars: asInt(map['chars']),
    );
  }

  Map<String, dynamic> toJson() => {
        'phase': phase,
        'text': text,
        'elapsed': elapsed,
        'done': done,
        'partial': partial,
        'chars': chars,
      };
}

/// 一条运行日志。
class LogEntry {
  const LogEntry({
    required this.kind,
    required this.text,
    required this.ts,
    this.step,
    this.phase,
    this.chars,
    this.elapsed,
    this.partial = false,
    this.truncated = false,
    this.done = false,
  });

  final String kind;
  final String text;
  final double? ts;
  final int? step;
  final String? phase;
  final int? chars;
  final double? elapsed;
  final bool partial;
  final bool truncated;
  final bool done;

  /// 是否思考条目。
  bool get isThinking => kind == 'thinking';

  /// 是否阶段事件。
  bool get isPhase => kind == 'phase';

  /// 是否求解器明细。
  bool get isSolver => kind == 'solver';

  /// 是否关键里程碑事件（阶段/评审/结果/错误/版本/修订/规划）。
  bool get isMilestone => const {
        'phase',
        'review',
        'result',
        'error',
        'version',
        'revise',
        'plan',
      }.contains(kind);

  factory LogEntry.fromJson(Object? raw) {
    final map = asMap(raw);
    return LogEntry(
      kind: asString(map['kind'], 'info'),
      text: asString(map['text']),
      ts: asDoubleOrNull(map['ts']),
      step: asIntOrNull(map['step']),
      phase: asStringOrNull(map['phase']),
      chars: asIntOrNull(map['chars']),
      elapsed: asDoubleOrNull(map['elapsed']),
      partial: asBool(map['partial']),
      truncated: asBool(map['truncated']),
      done: asBool(map['done']),
    );
  }

  Map<String, dynamic> toJson() => {
        'kind': kind,
        'text': text,
        'ts': ts,
        'step': step,
        'phase': phase,
        'chars': chars,
        'elapsed': elapsed,
        'partial': partial,
        'truncated': truncated,
        'done': done,
      };
}

/// 单任务详情（/api/job/{id}）。
class JobDetail {
  const JobDetail({
    required this.id,
    required this.status,
    required this.live,
    required this.logs,
    required this.result,
    required this.desc,
    required this.startedAt,
    required this.mode,
    required this.modeSource,
    required this.retryOf,
    required this.outcome,
    required this.outcomeSource,
    required this.design,
    required this.progress,
    required this.stage,
    required this.views,
    required this.thinking,
  });

  final String id;
  final String status;

  /// 进行中实时状态文本（服务端 live 通道）。
  final String? live;
  final List<LogEntry> logs;
  final ResultData? result;
  final String desc;
  final double? startedAt;
  final String mode;
  final String? modeSource;
  final String? retryOf;
  final String? outcome;
  final String? outcomeSource;
  final DesignDraft? design;
  final ProgressInfo? progress;
  final StageInfo stage;

  /// 评审图相对路径：front/side/top/iso/sheet。
  final Map<String, String> views;
  final ThinkingLive? thinking;

  bool get isRunning => status == JobStatus.running;

  bool get isDoneSuccess => status == JobStatus.done && (result?.ok ?? false);

  bool get isCancelled => status == JobStatus.cancelled;

  bool get isInterrupted => status == JobStatus.interrupted;

  bool get isFailed => status == JobStatus.error;

  /// 展示名称：结果名 → 需求摘要 → 任务 ID。
  String get displayName {
    final name = result?.name;
    if (name != null && name.isNotEmpty) return name;
    return desc.isNotEmpty ? desc : id;
  }

  /// 可展示的日志条数。
  int get logCount => logs.length;

  /// 视图相对路径 → 绝对 URL（由 API 客户端解析）。
  String? viewUrl(String key) => views[key];

  factory JobDetail.fromJson(Object? raw) {
    final map = asMap(raw);
    final views = <String, String>{};
    final rawViews = asMapOrNull(map['views']);
    if (rawViews != null) {
      for (final entry in rawViews.entries) {
        final value = asStringOrNull(entry.value);
        if (value != null && value.isNotEmpty) views[entry.key] = value;
      }
    }
    return JobDetail(
      id: asString(map['id']),
      status: asString(map['status'], JobStatus.error),
      live: asStringOrNull(map['live']),
      logs: [for (final item in asList(map['logs'])) LogEntry.fromJson(item)],
      result: map['result'] == null ? null : ResultData(asMap(map['result'])),
      desc: asString(map['desc']),
      startedAt: asTimestamp(map['startedAt']),
      mode: asString(map['mode'], 'fidelity'),
      modeSource: ModeSource.normalize(asStringOrNull(map['modeSource'])),
      retryOf: asStringOrNull(map['retryOf']),
      outcome: asStringOrNull(map['outcome']) ??
          asStringOrNull(asMap(map['result'])['outcome']),
      outcomeSource: OutcomeSource.normalize(asStringOrNull(map['outcomeSource'])),
      design: map['design'] == null ? null : DesignDraft.fromJson(map['design']),
      progress: map['progress'] == null ? null : ProgressInfo.fromJson(map['progress']),
      stage: StageInfo.fromJson(map['stage']),
      views: views,
      thinking: map['thinking'] == null ? null : ThinkingLive.fromJson(map['thinking']),
    );
  }

  /// 序列化（本地缓存用；字段与 API 详情 DTO 对齐，反序列化走同一 fromJson）。
  Map<String, dynamic> toJson() => {
        'id': id,
        'status': status,
        'live': live,
        'logs': [for (final entry in logs) entry.toJson()],
        'result': result?.raw,
        'desc': desc,
        'startedAt': startedAt,
        'mode': mode,
        'modeSource': modeSource,
        'retryOf': retryOf,
        'outcome': outcome,
        'outcomeSource': outcomeSource,
        'design': design?.toJson(),
        'progress': progress?.toJson(),
        'stage': stage.toJson(),
        'views': views,
        'thinking': thinking?.toJson(),
      };
}

