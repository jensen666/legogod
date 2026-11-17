// 生成记录页：原「复盘」Tab 的集中化重写。
// 首屏只展开交付结果横幅、失败/取消/中断的真实原因与断点阶段、重试入口和作品入口；
// 运行与需求信息、两次尝试、视觉评审与评审图、设计版本与求解轨迹、颜色回退与产物统计、
// 全部思考回合、完整运行日志、技术信息与文件入口按分组默认收起，原有复盘数据完整保留、不伪造。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../core/thinking.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';
import '../../ui/widgets/log_view.dart';
import '../../ui/widgets/outcome_banner.dart';
import '../../ui/widgets/retry_action.dart';
import '../../ui/widgets/thinking_panel.dart';
import 'record_artifacts_section.dart';
import 'record_milestones_section.dart';
import 'record_review_section.dart';
import 'record_run_section.dart';
import 'record_tech_section.dart';

/// 生成记录页（按任务 ID 打开，集中展示该任务全部复盘信息）。
class GenerationRecordPage extends StatefulWidget {
  const GenerationRecordPage({super.key, required this.jobId});

  /// 目标任务 ID。
  final String jobId;

  @override
  State<GenerationRecordPage> createState() => _GenerationRecordPageState();
}

class _GenerationRecordPageState extends State<GenerationRecordPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _loadJob();
    });
  }

  /// 进入页面即选中并加载该任务详情；错误保存在快照上，由页面错误态展示并允许重试。
  Future<void> _loadJob() async {
    final app = AppScope.read(context);
    await app.selectJob(widget.jobId);
    try {
      await app.ensureJobLoaded(widget.jobId);
    } catch (_) {
      // 详情加载错误由快照的 error 字段承载，页面会显示错误与重试入口。
    }
  }

  /// 手动刷新真实任务详情；失败用轻提示，不覆盖已经展示的快照。
  Future<void> _refresh() async {
    final app = AppScope.read(context);
    try {
      await app.fetchJob(widget.jobId);
    } catch (e) {
      if (mounted) showNotice(context, '刷新失败：${describeError(e)}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final snapshot = app.jobs[widget.jobId];
    return Scaffold(
      appBar: AppBar(
        title: const Text('生成记录'),
        actions: [
          IconButton(
            tooltip: '刷新生成记录',
            onPressed: _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: snapshot == null
          ? const LoadingBlock(text: '正在加载生成记录……')
          : ListenableBuilder(
              listenable: snapshot,
              builder: (context, _) {
                final detail = snapshot.detail;
                if (detail == null) {
                  final error = snapshot.error;
                  if (error != null) {
                    return ErrorView(
                      title: '生成记录加载失败',
                      message: error,
                      onRetry: _refresh,
                    );
                  }
                  return const LoadingBlock(text: '正在加载生成记录……');
                }
                return _buildRecord(context, detail);
              },
            ),
    );
  }

  /// 已加载任务的主体：首屏摘要 + 8 个默认收起的可展开分组。
  Widget _buildRecord(BuildContext context, JobDetail job) {
    final result = job.result;
    final turns = pickThinkingTurns(job.logs);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
      children: [
        // 唯一默认展开的结果横幅。
        KeyedSubtree(
          key: const Key('record-banner'),
          child: outcomeBannerWidget(job),
        ),
        if (_hasTerminalIssue(job))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: _failureSummary(job),
          ),
        _firstScreenActions(context, job),
        const SizedBox(height: 8),
        ExpandableSection(
          key: const Key('record-section-run'),
          title: '运行与需求信息',
          subtitle: '需求原文、任务 ID、模式与来源、时间、交付结果与重试关系',
          child: RecordRunInfoSection(job: job),
        ),
        if (result != null && result.attemptsDetail.length > 1)
          ExpandableSection(
            key: const Key('record-section-attempts'),
            title: '两次尝试及最终交付来源',
            subtitle: '共 ${result.attemptsDetail.length} 次尝试，分别保留真实结果与失败原因',
            child: RecordAttemptsSection(result: result),
          ),
        ExpandableSection(
          key: const Key('record-section-review'),
          title: '视觉评审与评审图',
          subtitle: recordReviewSubtitle(job),
          child: RecordReviewSection(job: job),
        ),
        ExpandableSection(
          key: const Key('record-section-versions'),
          title: '设计版本、修订与求解轨迹',
          subtitle: '阶段出现顺序、修订次数与里程碑事件',
          child: RecordMilestonesSection(job: job),
        ),
        ExpandableSection(
          key: const Key('record-section-artifacts'),
          title: '颜色回退与产物统计',
          subtitle: '以真实模型/方案文件为准的统计、配色与颜色回退',
          child: RecordArtifactsSection(job: job),
        ),
        ExpandableSection(
          key: const Key('record-section-thinking'),
          title: '全部思考回合',
          subtitle: '共 ${turns.length} 轮（全部保留，不只最后一轮）',
          child: ThinkingTurnsList(turns: turns),
        ),
        ExpandableSection(
          key: const Key('record-section-logs'),
          title: '完整运行日志',
          subtitle: '共 ${job.logs.length} 条日志，含运行日志 Markdown 导出入口',
          child: _logsSection(context, job),
        ),
        ExpandableSection(
          key: const Key('record-section-tech'),
          title: '技术信息与文件入口',
          subtitle: 'job_id、run_id、来源字段、版本信息与统一导出入口',
          child: RecordTechSection(job: job),
        ),
      ],
    );
  }

  /// 是否属于失败 / 取消 / 中断终态（需要首屏展示真实原因与断点阶段）。
  bool _hasTerminalIssue(JobDetail job) =>
      job.isFailed || job.isCancelled || job.isInterrupted;

  /// 失败 / 取消 / 中断的真实原因与断点阶段（不冒充成功）。
  Widget _failureSummary(JobDetail job) {
    final info = failureInfo(job);
    final where = info.stageLabel.isEmpty
        ? '没有记录到断点阶段'
        : '断在「${info.stageLabel}」阶段';
    if (job.isCancelled) {
      return InfoBanner(
        key: const Key('record-failure'),
        icon: '⏹️',
        tone: 'info',
        title: '已取消',
        text: '${info.reason}\n$where\n已取消：不再启动新的模型调用或保底。',
      );
    }
    if (job.isInterrupted) {
      return InfoBanner(
        key: const Key('record-failure'),
        icon: '⏸️',
        tone: 'warn',
        title: '生成已中断',
        text: '${info.reason}\n$where\n服务重启前未完成；可以回看日志，或按原模式重试。',
      );
    }
    return InfoBanner(
      key: const Key('record-failure'),
      icon: '❌',
      tone: 'bad',
      title: '生成未完成',
      text: '${info.reason}\n$where',
    );
  }

  /// 首屏操作区：成功交付记录提供「查看作品」，可重试记录提供醒目的「按原模式重试」。
  Widget _firstScreenActions(BuildContext context, JobDetail job) {
    final canViewWork = job.isDoneSuccess &&
        job.result?.modelPath != null &&
        job.result?.solutionPath != null;
    final canRetry = _canRetry(job);
    if (!canViewWork && !canRetry) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          if (canViewWork)
            FilledButton.icon(
              key: const Key('record-view-work'),
              onPressed: () => openWorkDetailPage(context, job.id),
              icon: const Icon(Icons.view_in_ar_outlined, size: 18),
              label: const Text('查看作品'),
            ),
          if (canRetry)
            RetryJobButton(
              key: const Key('record-retry'),
              jobId: job.id,
              mode: job.mode,
              label: '按原模式重试',
              tonal: !canViewWork,
              onCreated: (newId) async {
                if (!mounted) return;
                await openGenerationProgressPage(context, newId, replace: true);
              },
            ),
        ],
      ),
    );
  }

  /// 是否可重试：非运行中，且能拿到真实需求原文（任务字段或运行记录输入快照）。
  bool _canRetry(JobDetail job) {
    if (job.isRunning) return false;
    final desc = job.desc.isNotEmpty
        ? job.desc
        : (job.result?.runRecord['desc'] ?? '').toString();
    return desc.isNotEmpty;
  }

  /// 完整运行日志：固定高度滚动区；导出统一走本页唯一的「分享与导出」入口。
  Widget _logsSection(BuildContext context, JobDetail job) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          decoration: BoxDecoration(
            color: AppColors.bgElevated,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.borderSoft),
          ),
          clipBehavior: Clip.antiAlias,
          child: SizedBox(
            height: 360,
            child: LogListView(
              logs: job.logs,
              running: job.isRunning,
              liveText: job.live,
              emptyText: '本次运行没有保留日志。',
            ),
          ),
        ),
        const SizedBox(height: 10),
        const Text(
          '导出内容由 /api/job 返回的全部已保留日志生成，请使用本页「技术信息与文件入口」中的「分享与导出」。',
          style: TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.45),
        ),
      ],
    );
  }
}
