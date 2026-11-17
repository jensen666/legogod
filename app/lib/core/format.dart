// 统一格式化与文案：状态、模式、交付结果、阶段、耗时、时间、失败原因。
// 所有展示语义以服务端真实字段为准；兼容推导/无记录必须与显式记录区分。
import '../models/job.dart';
import '../models/result.dart';

/// 秒数 → 「N分SS秒」。
String fmtClock(num seconds) {
  final total = seconds.isFinite ? seconds.round() : 0;
  final safe = total < 0 ? 0 : total;
  return '${safe ~/ 60}分${(safe % 60).toString().padLeft(2, '0')}秒';
}

/// 已运行时长（开始时间戳秒 → 现在）。
String fmtElapsed(num? startedAt, {DateTime? now}) {
  if (startedAt == null || startedAt <= 0) return '—';
  final current = (now ?? DateTime.now()).millisecondsSinceEpoch / 1000;
  return fmtClock(current - startedAt);
}

/// 日期时间：11-15 12:31（本地时区）。
String fmtDateTime(num? ts) {
  if (ts == null || ts <= 0) return '-';
  final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(dt.month)}-${two(dt.day)} ${two(dt.hour)}:${two(dt.minute)}';
}

/// 日志时间：12:31:05。
String fmtLogTime(num? ts) {
  if (ts == null || ts <= 0) return '-';
  final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(dt.hour)}:${two(dt.minute)}:${two(dt.second)}';
}

/// 需求/名称摘要：折叠空白并截断。
String shortDesc(Object? text, [int max = 40]) {
  final value = (text ?? '').toString().replaceAll(RegExp(r'\s+'), ' ').trim();
  if (value.length <= max) return value;
  return '${value.substring(0, max)}…';
}

// ---------- 模式 ----------
/// 模式中文名：快速/高保真/未记录（不擅自把未知归为某一档）。
String modeLabel(String? mode) {
  switch (mode) {
    case 'fast':
      return '快速';
    case 'fidelity':
      return '高保真';
    default:
      return '未记录';
  }
}

/// 模式徽章：只有真实有效模式才显示（避免把旧任务错标）。
String? modeBadgeText(String? mode) =>
    (mode == 'fast' || mode == 'fidelity') ? modeLabel(mode) : null;

/// 模式来源说明：区分真实记录与兼容回退。
String modeSourceHint(String? source) {
  switch (source) {
    case ModeSource.job:
      return '任务字段记录';
    case ModeSource.result:
      return '结果记录（兼容补取）';
    case ModeSource.runRecord:
      return '运行记录（兼容补取）';
    case ModeSource.defaultValue:
      return '未记录（重试按高保真处理）';
    default:
      return '服务端未提供模式来源';
  }
}

/// 展示用模式文案：
/// - 模式来源为 default（完全无记录）时显示「未记录（重试按高保真处理）」，不冒充原始记录；
/// - 否则显示真实模式。
String modeDisplay(String? mode, String? modeSource) {
  if (modeSource == ModeSource.defaultValue) return '未记录（重试按高保真处理）';
  return modeLabel(mode);
}

/// 重试按钮文案：快速任务没有视觉评审意见可继承。
String retryLabel(String? mode) {
  if (mode == 'fast') return '按快速模式重试';
  return '携带评审意见重试';
}

// ---------- 交付结果 ----------
/// 交付结果展示元数据。
class OutcomeMeta {
  const OutcomeMeta({
    required this.text,
    required this.icon,
    required this.tone,
    required this.neutral,
    this.note,
  });

  /// 中文文案。
  final String text;

  /// 图标（不依赖颜色区分状态）。
  final String icon;

  /// 语义色调：ok/warn/fb/bad/info/run/neutral。
  final String tone;

  /// 是否为兼容推导的中性文案（observation：不等于显式交付结论）。
  final bool neutral;

  /// 附加说明（推导来源 / 无记录）。
  final String? note;
}

/// 依据 outcome + outcomeSource 生成展示元数据。
/// 兼容推导（derived）使用中性文案并可附真实评审异常；无记录（none）明确说明无记录。
OutcomeMeta outcomeMeta(
  String? outcome, {
  String? outcomeSource,
  String? mode,
}) {
  final source = outcomeSource;
  if (source == OutcomeSource.none || (outcome == null || outcome.isEmpty)) {
    return const OutcomeMeta(
      text: '无交付记录',
      icon: '•',
      tone: 'neutral',
      neutral: true,
      note: '该任务没有可展示的交付结果记录',
    );
  }
  final derived = source == OutcomeSource.derived;
  const mapping = <String, List<String>>{
    JobOutcome.fidelitySuccess: ['高保真成功', '✅', 'ok'],
    JobOutcome.fidelityDegraded: ['降级交付', '⚠️', 'warn'],
    JobOutcome.fastFallback: ['快速保底', '🛟️', 'fb'],
    JobOutcome.fastSuccess: ['快速成功', '✅', 'ok'],
    JobOutcome.failed: ['生成失败', '❌', 'bad'],
    JobOutcome.cancelled: ['已取消', '⏹️', 'info'],
  };
  final meta = mapping[outcome];
  if (meta == null) {
    return const OutcomeMeta(
      text: '未知交付结果',
      icon: '❓',
      tone: 'neutral',
      neutral: true,
      note: '服务端返回了未知枚举',
    );
  }
  if (derived) {
    // 兼容推导：中性文案 + 真实评审异常说明，不冒充当次显式交付结论。
    final label = switch (outcome) {
      JobOutcome.fidelityDegraded => '生成成功（评审异常）',
      JobOutcome.fastFallback => '生成成功（快速保底）',
      JobOutcome.fidelitySuccess || JobOutcome.fastSuccess => '生成成功',
      JobOutcome.failed => '生成失败',
      JobOutcome.cancelled => '已取消',
      _ => '生成成功',
    };
    return OutcomeMeta(
      text: label,
      icon: meta[1],
      tone: outcome == JobOutcome.failed ? 'bad' : 'neutral',
      neutral: true,
      note: '兼容推导：历史记录未显式记录交付结论',
    );
  }
  return OutcomeMeta(
    text: meta[0],
    icon: meta[1],
    tone: meta[2],
    neutral: false,
  );
}

/// 统一状态标签：优先 outcome，其次执行状态；旧记录用中性「生成成功」。
OutcomeMeta statusMeta(JobDetail job) {
  final outcome = job.outcome;
  final source = job.outcomeSource;
  if (outcome != null && outcome.isNotEmpty) {
    return outcomeMeta(outcome, outcomeSource: source, mode: job.mode);
  }
  switch (job.status) {
    case JobStatus.running:
      return const OutcomeMeta(
        text: '进行中',
        icon: '⏳',
        tone: 'run',
        neutral: false,
      );
    case JobStatus.cancelled:
      return const OutcomeMeta(
        text: '已取消',
        icon: '⏹️',
        tone: 'info',
        neutral: false,
      );
    case JobStatus.interrupted:
      return const OutcomeMeta(
        text: '已中断',
        icon: '⏸️',
        tone: 'warn',
        neutral: false,
      );
    case JobStatus.error:
      return const OutcomeMeta(
        text: '生成失败',
        icon: '❌',
        tone: 'bad',
        neutral: false,
      );
    case JobStatus.done:
      return const OutcomeMeta(
        text: '生成成功',
        icon: '✅',
        tone: 'ok',
        neutral: true,
      );
    default:
      return OutcomeMeta(
        text: JobStatus.label(job.status),
        icon: '•',
        tone: 'neutral',
        neutral: true,
      );
  }
}

/// 摘要任务的统一状态标签。
OutcomeMeta summaryStatusMeta(JobSummary job) {
  final outcome = job.outcome;
  if (outcome != null && outcome.isNotEmpty) {
    return outcomeMeta(
      outcome,
      outcomeSource: job.outcomeSource,
      mode: job.mode,
    );
  }
  switch (job.status) {
    case JobStatus.running:
      return const OutcomeMeta(
        text: '进行中',
        icon: '⏳',
        tone: 'run',
        neutral: false,
      );
    case JobStatus.cancelled:
      return const OutcomeMeta(
        text: '已取消',
        icon: '⏹️',
        tone: 'info',
        neutral: false,
      );
    case JobStatus.interrupted:
      return const OutcomeMeta(
        text: '已中断',
        icon: '⏸️',
        tone: 'warn',
        neutral: false,
      );
    case JobStatus.error:
      return const OutcomeMeta(
        text: '生成失败',
        icon: '❌',
        tone: 'bad',
        neutral: false,
      );
    case JobStatus.done:
      return const OutcomeMeta(
        text: '生成成功',
        icon: '✅',
        tone: 'ok',
        neutral: true,
      );
    default:
      return OutcomeMeta(
        text: JobStatus.label(job.status),
        icon: '•',
        tone: 'neutral',
        neutral: true,
      );
  }
}

// ---------- 阶段 ----------
/// 真实阶段元数据（阶段名只来自服务端上报，不从日志正文猜测）。
class PhaseMeta {
  const PhaseMeta(this.id, this.icon, this.label, this.blurb);

  final String id;
  final String icon;
  final String label;
  final String blurb;
}

const Map<String, PhaseMeta> phases = {
  'plan': PhaseMeta('plan', '📋', '规划', '正在确认规模、部位和造型计划'),
  'draw': PhaseMeta('draw', '🎨', '造型', '正在把计划编译成彩色体素设计稿'),
  'label': PhaseMeta('label', '🏷️', '标注', '正在补齐部位标注'),
  'review': PhaseMeta('review', '👁️', '评审', '正在对照多视角渲染做视觉评审'),
  'revise': PhaseMeta('revise', '🔧', '修订', '正在按评审或结构问题修订设计稿'),
  'solve': PhaseMeta('solve', '🧱', '求解', '正在把设计稿铺成可拼的零件'),
  'final': PhaseMeta('final', '📦', '收尾', '正在做最后一次求解并写出产物'),
  'artifacts': PhaseMeta('artifacts', '📦', '产物', '正在写出步骤文档和独立 3D 页'),
};

/// 阶段中文名。
String phaseLabel(String? id) =>
    (id == null || id.isEmpty) ? '' : (phases[id]?.label ?? id);

/// 当前阶段叙述。
String phaseBlurb(String? current) => (current == null || current.isEmpty)
    ? ''
    : (phases[current]?.blurb ?? '正在进行当前阶段');

/// 当前阶段图标。
String phaseIcon(String? current) =>
    (current == null) ? '◆' : (phases[current]?.icon ?? '◆');

// ---------- 失败原因 ----------
/// 失败/取消/中断原因信息。
class FailureInfo {
  const FailureInfo({
    required this.reason,
    required this.stage,
    required this.stageLabel,
  });

  final String reason;
  final String stage;
  final String stageLabel;
}

/// 提炼任务的断点阶段与真实原因（不伪造）。
FailureInfo failureInfo(JobDetail job) {
  final result = job.result;
  final failure = result?.failures.isNotEmpty == true
      ? result!.failures.first
      : const <String, dynamic>{};
  final stage = (failure['stage'] as String?) ?? (job.stage.current ?? '');
  var reason = result?.error ?? '';
  if (reason.isEmpty && job.status == JobStatus.cancelled) reason = '已由用户取消';
  if (reason.isEmpty && job.status == JobStatus.interrupted) {
    reason = '任务已中断（服务重启前未完成）';
  }
  if (reason.isEmpty) reason = '任务未完成';
  return FailureInfo(
    reason: reason,
    stage: stage,
    stageLabel: phaseLabel(stage),
  );
}

// ---------- 评审 ----------
/// 评分分项中文名。
const Map<String, String> reviewScoreLabels = {
  'proportion': '比例',
  'features': '特征',
  'color': '颜色',
  'detail': '细节',
};

/// 快速任务「未进行视觉评审」的固定说明（不显示 0 分）。
const String fastNoReviewText = '快速生成，未进行视觉评审与视觉修订，因此没有视觉评分；结构与统一校验标准与高保真一致。';

/// 尝试行文案。
String attemptSummary(AttemptData attempt) {
  final bits = <String>[attempt.ok ? '成功' : '失败'];
  if (attempt.runId != null && attempt.runId!.isNotEmpty) {
    bits.add('run_id ${attempt.runId}');
  }
  if (attempt.elapsedSeconds != null) bits.add('耗时 ${attempt.elapsedSeconds}s');
  if (!attempt.ok) {
    final kind = attempt.failureKind;
    bits.add(
      kind != null && kind.isNotEmpty
          ? '失败类别 $kind${attempt.failureStage != null ? '（阶段 ${attempt.failureStage}）' : ''}'
          : '失败类别未记录',
    );
    bits.add(
      attempt.error == null || attempt.error!.isEmpty ? '未知原因' : attempt.error!,
    );
  }
  return bits.join(' · ');
}

/// 配色种类数。
int colorCountOf(Map<String, int> colors) => colors.length;

// ============================================================
// 手机 APP 信息架构简化重构：面向普通用户的展示文案。
// 只调整展示文案与分级，不修改 API 枚举、筛选值和任何业务语义。
// ============================================================

/// 快速模式的一句说明：必须表达「不评审但检查标准不降低」。
const String fastModeLine = '不进行视觉评审与视觉修订，结构与可拼性检查标准不降低。';

/// 高保真模式的一句说明：必须表达「更慢 + 硬失败自动快速保底一次」。
const String fidelityModeLine = '增加视觉评审与有界修订，通常更慢；硬失败按真实规则自动快速保底一次。';

/// 按模式返回一句简短说明；未知/无记录模式返回空串（不冒充任何一档）。
String modeLine(String? mode) {
  switch (mode) {
    case 'fast':
      return fastModeLine;
    case 'fidelity':
      return fidelityModeLine;
    default:
      return '';
  }
}

/// 两档模式完整对比（「模式说明」弹层与「我的 → 生成规则」共用）。
const String modeComparisonText =
    '快速：跳过视觉评审与视觉修订，优先产出可拼初稿，速度更快。'
    '结构预检、部位绑定、精确求解与统一校验与高保真完全相同，不因简化而降低。\n\n'
    '高保真：在快速基础上追加多视角视觉评审与有界外观修订，通常耗时更长；'
    '若最终硬失败，按真实规则自动快速保底一次（计为同一任务的第二次尝试，'
    '结果如实标注为「快速保底」，不冒充高保真成功）。\n\n'
    '两档都完整保留原始需求；任务运行期间可继续发起新任务并独立取消，互不影响；'
    '手动重试沿用原任务模式。';

/// 生成规则全文（默认收起，不在创作页首屏展开）。
const String generationRulesText =
    '两档生成模式：快速跳过视觉评审和视觉修订，优先生成可拼初稿；'
    '高保真追加多视角视觉评审与有界外观修订，通常耗时更长，硬失败时自动快速保底一次'
    '（计为同一任务的第二次尝试）。两档都完整保留原始需求，部位绑定、设计预检、结构修订、'
    '精确求解与统一校验执行同一标准。任务运行期间可继续发起新任务并独立取消，互不影响；'
    '手动重试沿用原任务模式。Agent 可用零件与库存以「零件目录」为准。';

/// 任务页标题：进行中 →「生成进度」；可交付完成 →「作品」；其余 →「生成记录」。
String taskPageTitle(JobDetail job) {
  if (job.isRunning) return '生成进度';
  if (job.isDoneSuccess) return '作品';
  return '生成记录';
}

/// 作品详情页需要显示的简短警告：降级、保底、评审异常、修订未完成。
/// 颜色回退、产物不一致等依赖真实产物文件的警告由作品详情页在产物加载后追加。
class WorkWarning {
  const WorkWarning({
    required this.title,
    required this.detail,
    this.tone = 'warn',
  });

  /// 简短标题（首屏摘要）。
  final String title;

  /// 完整原因（展开可见）。
  final String detail;

  /// 语义色调：warn / bad / info。
  final String tone;
}

/// 从任务结果字段提炼作品级警告；没有真实依据时不返回任何项（不伪造）。
List<WorkWarning> workWarnings(JobDetail job) {
  final result = job.result;
  if (result == null) return const <WorkWarning>[];
  final out = <WorkWarning>[];
  final outcome = job.outcome ?? result.outcome;
  final derived = job.outcomeSource == OutcomeSource.derived;
  if (outcome == JobOutcome.fidelityDegraded) {
    out.add(
      WorkWarning(
        title: '作品已生成，视觉评审未完全通过',
        detail:
            '降级原因：${result.degradedReason ?? '视觉评分不足或评审不可用'}。'
            '按规则不重跑快速保底，产物仍可正常拼装。'
            '${derived ? '\n该历史记录未显式记录交付结论，此处按状态与评审标记兼容推导。' : ''}',
      ),
    );
  }
  if (outcome == JobOutcome.fastFallback) {
    out.add(
      WorkWarning(
        title: '高保真未完成，已提供快速方案',
        detail:
            '高保真失败原因：${result.fidelityAttemptError ?? '未记录'}。'
            '快速保底产物不计为高保真成功，可在生成记录查看两次尝试。',
        tone: 'info',
      ),
    );
  }
  if (result.reviewFailed && outcome != JobOutcome.fidelityDegraded) {
    out.add(
      WorkWarning(
        title: '视觉评审未通过',
        detail:
            '本次没有可展示的有效视觉评分'
            '${result.degradedReason == null ? '' : '（${result.degradedReason}）'}。',
      ),
    );
  }
  if (result.revisionIncomplete) {
    out.add(
      WorkWarning(
        title: '视觉修订未完成',
        detail: result.revisionIncompleteReason ?? '视觉修订未完成，产物按已完成版本交付。',
      ),
    );
  }
  return out;
}

/// 执行状态/交付结果的中性摘要文案（作品列表卡片用）。
String jobStatusSummary(JobDetail job) {
  final meta = statusMeta(job);
  return meta.text;
}
