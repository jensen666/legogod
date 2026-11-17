// 任务摘要与历史分页 DTO（JobSummary/HistoryPageData）。
import 'job_core.dart';
import 'job_detail.dart';
import 'json.dart';
import 'result.dart';

/// 历史列表 / 任务切换器共用的任务摘要。
class JobSummary {
  const JobSummary({
    required this.id,
    required this.status,
    required this.name,
    required this.slug,
    required this.pieces,
    required this.desc,
    required this.error,
    required this.mode,
    required this.modeSource,
    required this.retryOf,
    required this.outcome,
    required this.outcomeSource,
    required this.startedAt,
    required this.gridW,
    required this.gridD,
    required this.layerCount,
    required this.colors,
  });

  final String id;
  final String status;
  final String? name;
  final String? slug;
  final int? pieces;
  final String desc;
  final String? error;

  /// 服务端解析后的有效模式（fast/fidelity）；可能来自兼容回退。
  final String mode;

  /// 模式来源；null 表示服务端未提供（老版本服务）。
  final String? modeSource;

  /// 重试自哪个任务。
  final String? retryOf;

  /// 兼容交付结果；可能为 null（进行中 / 中断）。
  final String? outcome;

  /// 交付结果来源；null 表示服务端未提供。
  final String? outcomeSource;

  /// 发起时间（秒）。
  final double? startedAt;

  final int? gridW;
  final int? gridD;
  final int? layerCount;

  /// 配色分布。
  final List<ColorShare> colors;

  /// 展示名称：优先结果名 → 需求 → 任务 ID。
  String get displayName => (name != null && name!.isNotEmpty) ? name! : (desc.isNotEmpty ? desc : id);

  /// 是否进行中。
  bool get isRunning => status == JobStatus.running;

  /// 是否完成且成功（用于「查看作品」入口）。
  bool get isDelivered => status == JobStatus.done;

  /// 规格摘要：占地 · 零件 · 层数，缺数据不占位。
  String get specText {
    final bits = <String>[];
    if (gridW != null && gridD != null) bits.add('$gridW×$gridD');
    if (pieces != null) bits.add('$pieces 块');
    if (layerCount != null) bits.add('$layerCount 层');
    return bits.join(' · ');
  }

  factory JobSummary.fromJson(Object? raw) {
    final map = asMap(raw);
    final grid = asMap(map['grid']);
    return JobSummary(
      id: asString(map['id']),
      status: asString(map['status'], JobStatus.error),
      name: asStringOrNull(map['name']),
      slug: asStringOrNull(map['slug']),
      pieces: asIntOrNull(map['pieces']),
      desc: asString(map['desc']),
      error: asStringOrNull(map['error']),
      mode: asString(map['mode'], 'fidelity'),
      modeSource: ModeSource.normalize(asStringOrNull(map['modeSource'])),
      retryOf: asStringOrNull(map['retryOf']),
      outcome: asStringOrNull(map['outcome']),
      outcomeSource: OutcomeSource.normalize(asStringOrNull(map['outcomeSource'])),
      startedAt: asTimestamp(map['startedAt']),
      gridW: asIntOrNull(grid['w']),
      gridD: asIntOrNull(grid['d']),
      layerCount: asIntOrNull(map['layers']),
      colors: ColorShare.listFromJson(map['colors']),
    );
  }

  /// 本地缓存/历史兼容：从完整详情构造摘要。
  factory JobSummary.fromDetail(JobDetail detail) {
    final result = detail.result;
    return JobSummary(
      id: detail.id,
      status: detail.status,
      name: result?.name,
      slug: result?.slug,
      pieces: result?.pieces,
      desc: detail.desc,
      error: result?.error,
      mode: detail.mode,
      modeSource: detail.modeSource,
      retryOf: detail.retryOf,
      outcome: detail.outcome,
      outcomeSource: detail.outcomeSource,
      startedAt: detail.startedAt,
      gridW: result?.gridW,
      gridD: result?.gridD,
      layerCount: result?.layerCount,
      colors: ColorShare.fromCounts(result?.colors ?? const <String, int>{}),
    );
  }

  /// 序列化（本地缓存用）。
  Map<String, dynamic> toJson() => {
        'id': id,
        'status': status,
        'name': name,
        'slug': slug,
        'pieces': pieces,
        'desc': desc,
        'error': error,
        'mode': mode,
        'modeSource': modeSource,
        'retryOf': retryOf,
        'outcome': outcome,
        'outcomeSource': outcomeSource,
        'startedAt': startedAt,
        'grid': {'w': gridW, 'd': gridD},
        'layers': layerCount,
        'colors': [
          for (final color in colors)
            {'name': color.name, 'count': color.count, 'hex': color.hex, 'share': color.share}
        ],
      };
}

/// 历史分页响应（/api/jobs?page=...）。
class HistoryPageData {
  const HistoryPageData({
    required this.jobs,
    required this.total,
    required this.page,
    required this.pageSize,
    required this.pages,
    required this.running,
  });

  final List<JobSummary> jobs;
  final int total;
  final int page;
  final int pageSize;
  final int pages;

  /// 全量进行中任务（不受分页与筛选影响，用于底部角标与进行中专区）。
  final List<JobSummary> running;

  factory HistoryPageData.fromJson(Object? raw) {
    final map = asMap(raw);
    return HistoryPageData(
      jobs: [for (final item in asList(map['jobs'])) JobSummary.fromJson(item)],
      total: asInt(map['total']),
      page: asInt(map['page'], 1),
      pageSize: asInt(map['pageSize'], 20),
      pages: asInt(map['pages'], 1),
      running: [for (final item in asList(map['running'])) JobSummary.fromJson(item)],
    );
  }

  /// 序列化（本地缓存用）。
  Map<String, dynamic> toJson() => {
        'jobs': [for (final job in jobs) job.toJson()],
        'total': total,
        'page': page,
        'pageSize': pageSize,
        'pages': pages,
        'running': [for (final job in running) job.toJson()],
      };
}

