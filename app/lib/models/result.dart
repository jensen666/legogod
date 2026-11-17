// 生成结果 DTO：任务 result 字段（快照统计 + 评审 + 两次尝试 + 运行记录）。
// 保持 raw 原始 Map 便于读取契约中新增字段；UI 只通过类型化 getter 展示真实值。
import 'json.dart';

/// 配色分布项（历史摘要 colors）。
class ColorShare {
  const ColorShare({
    required this.name,
    required this.count,
    required this.hex,
    required this.share,
  });

  final String name;
  final int count;
  final String? hex;

  /// 占比 0..1。
  final double? share;

  /// 从 result.colors（颜色名→块数）构造配色分布（无 hex 时由调用方补齐）。
  static List<ColorShare> fromCounts(Map<String, int> counts) {
    final total = counts.values.fold<int>(0, (sum, value) => sum + value);
    if (total <= 0) return const <ColorShare>[];
    final entries = counts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return [
      for (final entry in entries)
        ColorShare(
          name: entry.key,
          count: entry.value,
          hex: null,
          share: entry.value / total,
        ),
    ];
  }

  static List<ColorShare> listFromJson(Object? raw) {
    if (raw is! List) {
      return const <ColorShare>[];
    }
    final out = <ColorShare>[];
    for (final item in raw) {
      final map = asMap(item);
      final name = asString(map['name']);
      if (name.isEmpty) continue;
      out.add(ColorShare(
        name: name,
        count: asInt(map['count']),
        hex: asStringOrNull(map['hex']),
        share: asDoubleOrNull(map['share']),
      ));
    }
    return out;
  }
}

/// 视觉评审结果。
class ReviewData {
  const ReviewData({
    required this.scores,
    required this.worstParts,
    required this.missingFeatures,
    required this.suggestions,
    required this.keep,
  });

  final Map<String, num> scores;
  final List<String> worstParts;
  final List<String> missingFeatures;
  final List<String> suggestions;
  final List<String> keep;

  /// 整体分（0-10）；没有有效评分返回 null，绝不把「未评审」当 0 分。
  num? get overall => scores['overall'];

  bool get hasScores => scores.isNotEmpty && scores['overall'] != null;

  factory ReviewData.fromJson(Object? raw) {
    final map = asMap(raw);
    if (map.isEmpty) {
      return const ReviewData(
          scores: <String, num>{},
          worstParts: <String>[],
          missingFeatures: <String>[],
          suggestions: <String>[],
          keep: <String>[]);
    }
    final scores = <String, num>{};
    for (final entry in asMap(map['scores']).entries) {
      final value = entry.value;
      if (value is num) scores[entry.key] = value;
    }
    List<String> strings(Object? value) =>
        [for (final item in asList(value)) asString(item)].where((e) => e.isNotEmpty).toList();
    return ReviewData(
      scores: scores,
      worstParts: strings(map['worst_parts']),
      missingFeatures: strings(map['missing_features']),
      suggestions: strings(map['suggestions']),
      keep: strings(map['keep']),
    );
  }
}

/// 一次生成尝试（高保真失败后的快速保底会形成第二条）。
class AttemptData {
  const AttemptData({
    required this.mode,
    required this.ok,
    required this.runId,
    required this.elapsedSeconds,
    required this.error,
    required this.failureKind,
    required this.failureStage,
  });

  final String mode;
  final bool ok;
  final String? runId;
  final double? elapsedSeconds;
  final String? error;
  final String? failureKind;
  final String? failureStage;

  /// 尝试名称：高保真尝试 / 快速保底 / 快速尝试。
  String get title {
    if (mode == 'fast') return ok ? '快速尝试' : '快速保底';
    return '高保真尝试';
  }

  factory AttemptData.fromJson(Object? raw) {
    final map = asMap(raw);
    final failure = asMap(map['failure']);
    return AttemptData(
      mode: asString(map['mode'], 'fidelity'),
      ok: asBool(map['ok']),
      runId: asStringOrNull(map['run_id']),
      elapsedSeconds: asDoubleOrNull(map['elapsed_s']),
      error: asStringOrNull(map['error']),
      failureKind: asStringOrNull(failure['kind']),
      failureStage: asStringOrNull(failure['stage']),
    );
  }
}

/// 任务结果为对象时的类型化视图。
class ResultData {
  ResultData(this.raw);

  /// 服务端原始 result 对象（只读）。
  final Map<String, dynamic> raw;

  bool get ok => asBool(raw['ok']);

  String get outcome => asString(raw['outcome']);

  String? get error => asStringOrNull(raw['error']);

  String? get name => asStringOrNull(raw['name']);

  String? get slug => asStringOrNull(raw['slug']);

  /// 结果记录的模式（旧记录才需要从 result 读取）。
  String? get mode => asStringOrNull(raw['mode']);

  int? get pieces => asIntOrNull(raw['pieces']);

  int? get voxels => asIntOrNull(raw['voxels']);

  /// 层数：result.layers 是数字（discriminated：与 result 里的 model layers 数组不同）。
  int? get layerCount => raw['layers'] is num ? asIntOrNull(raw['layers']) : null;

  int? get attempts => asIntOrNull(raw['attempts']);

  double? get elapsedSeconds => asDoubleOrNull(raw['elapsed_s']);

  String? get runId => asStringOrNull(raw['run_id']);

  String? get modelPath => asStringOrNull(raw['model_path']);

  String? get solutionPath => asStringOrNull(raw['solution_path']);

  String? get mdPath => asStringOrNull(raw['md_path']);

  String? get vizFile => asStringOrNull(raw['viz_file']);

  int? get gridW => asIntOrNull(asMap(raw['grid'])['w']);

  int? get gridD => asIntOrNull(asMap(raw['grid'])['d']);

  /// 配色统计 {颜色名: 块数}。
  Map<String, int> get colors {
    final out = <String, int>{};
    for (final entry in asMap(raw['colors']).entries) {
      final value = asIntOrNull(entry.value);
      if (value != null && value > 0) out[entry.key] = value;
    }
    return out;
  }

  ReviewData get review => ReviewData.fromJson(raw['review']);

  String? get reviewFlag => asStringOrNull(raw['review_flag']);

  bool get reviewFailed => asBool(raw['review_failed']) || reviewFlag == 'review_failed';

  bool get reviewUnavailable =>
      asBool(raw['review_unavailable']) || reviewFlag == 'review_unavailable';

  bool get reviewStale => asBool(raw['reviewStale']) || reviewFlag == 'review_stale';

  /// 降级原因（高保真未完全通过时的真实原因）。
  String? get degradedReason => asStringOrNull(raw['degraded_reason']);

  /// 高保真首次失败原因（快速保底时展示）。
  String? get fidelityAttemptError => asStringOrNull(raw['fidelity_attempt_error']);

  bool get revisionIncomplete => asBool(raw['revisionIncomplete']);

  String? get revisionIncompleteReason => asStringOrNull(raw['revisionIncompleteReason']);

  /// 两次尝试明细（少于 2 条说明没有第二次尝试）。
  List<AttemptData> get attemptsDetail =>
      [for (final item in asList(raw['attempts_detail'])) AttemptData.fromJson(item)];

  /// 失败明细列表。
  List<Map<String, dynamic>> get failures =>
      [for (final item in asList(raw['failures'])) asMap(item)];

  /// 结果里附带的运行记录（旧记录模式回退、输入快照来源）。
  Map<String, dynamic> get runRecord => asMap(raw['run_record']);

  /// 结果自带的评审图路径（历史任务没有 views 通道时的补充来源）。
  String? get reviewSheet => asStringOrNull(raw['review_sheet']);

  /// 统计以真实产物文件为准时的核对提示：快照与文件不一致需要展示。
  bool inconsistentWith({required int filePieces, required int fileVoxels}) {
    final snapshotPieces = pieces;
    final snapshotVoxels = voxels;
    return (snapshotPieces != null && snapshotPieces != filePieces) ||
        (snapshotVoxels != null && snapshotVoxels != fileVoxels);
  }

  /// 任务是否成功交付可拼产物（以 result.ok 为准）。
  bool get delivered => ok;
}
