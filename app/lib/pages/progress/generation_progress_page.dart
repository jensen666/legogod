// 生成进度页：独立页面，负责「进行中」任务的实时展示与结果收口。
// - 首屏优先：作品名、真实状态、耗时、当前真实阶段与一句阶段说明；
// - 有真实求解进度才显示层/总层数/轮次，不拼接虚假百分比或线性进度；
// - 设计稿产生后成为主视觉（可旋转/缩放/重置视角，换稿不重置视角），未产生时紧凑空态；
// - 全部阶段、修订次数、评审图、思考与日志统一在「生成详情」入口（生成记录页）；
// - 思考默认收起，只显示阶段/字数摘要，用户展开状态不被轮询覆盖；
// - 取消是次要危险操作；完成显示真实结果摘要与「查看作品」主按钮，不强制自动跳走。
import 'dart:async';

import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../core/thinking.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';
import '../../ui/widgets/outcome_banner.dart';
import 'progress_design_section.dart';

/// 生成进度页。
class GenerationProgressPage extends StatefulWidget {
  const GenerationProgressPage({super.key, required this.jobId});

  /// 任务 ID（真实 /api/job 快照）。
  final String jobId;

  @override
  State<GenerationProgressPage> createState() => _GenerationProgressPageState();
}

class _GenerationProgressPageState extends State<GenerationProgressPage> {
  /// 是否已发起本轮详情加载（避免重复请求）。
  bool _requested = false;

  /// 每秒刷新一次进行中耗时展示。
  Timer? _ticker;

  /// 取消请求在途。
  bool _cancelBusy = false;

  /// 重试请求在途（防止连点创建多个真实任务）。
  bool _retryBusy = false;

  /// 思考面板是否由用户展开（轮询刷新不会重置该选择）。
  bool _thinkingExpanded = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      final detail = AppScope.read(context).jobs[widget.jobId]?.detail;
      if (detail == null || !detail.isRunning) return;
      setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  /// 进入页面：设为当前任务并拉取真实快照（失败由页面主体展示，不吞掉错误）。
  Future<void> _load() async {
    if (_requested) return;
    _requested = true;
    final app = AppScope.read(context);
    await app.selectJob(widget.jobId);
    try {
      await app.ensureJobLoaded(widget.jobId);
    } catch (_) {
      // 错误已写入快照，页面提供重试入口。
    }
  }

  /// 手动刷新真实快照。
  Future<void> _refresh() async {
    final app = AppScope.read(context);
    try {
      await app.fetchJob(widget.jobId);
    } catch (e) {
      if (mounted) showNotice(context, '刷新失败：${describeError(e)}');
    }
  }

  /// 取消任务前的确认（与原有取消语义一致，不改变任何服务端行为）。
  Future<void> _cancel(JobDetail job) async {
    if (_cancelBusy) return;
    final app = AppScope.read(context);
    final confirmed = await showConfirmDialog(
      context,
      title: '取消任务',
      message:
          '确定取消「${shortDesc(job.displayName, 24)}」？取消后服务端会在下一个取消点停止，'
          '不会再启动快速保底或新的模型调用；其他任务不受影响。',
      confirmText: '确认取消',
      danger: true,
    );
    if (!confirmed || !mounted) return;
    setState(() => _cancelBusy = true);
    try {
      await app.cancelJob(job.id);
      if (mounted) showNotice(context, '已提交取消请求');
    } catch (e) {
      if (mounted) showNotice(context, '取消失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _cancelBusy = false);
    }
  }

  /// 按原模式重试并进入新任务的生成进度页。
  Future<void> _retry(JobDetail job) async {
    if (_retryBusy) return;
    setState(() => _retryBusy = true);
    try {
      final newId = await AppScope.read(context).retryJob(job.id);
      if (!mounted) return;
      showNotice(context, '已按原模式创建重试任务：$newId');
      await openGenerationProgressPage(context, newId, replace: true);
    } catch (e) {
      if (mounted) showNotice(context, '重试失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _retryBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final snapshot = app.jobs[widget.jobId];
    return Scaffold(
      appBar: AppBar(
        title: const Text('生成进度'),
        actions: [
          TextButton(
            key: const Key('progress-detail-button'),
            onPressed: () => openGenerationRecordPage(context, widget.jobId),
            child: const Text('生成详情'),
          ),
          IconButton(
            tooltip: '刷新任务',
            onPressed: _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: snapshot == null
          ? const LoadingBlock(text: '正在加载任务……')
          : ListenableBuilder(
              listenable: snapshot,
              builder: (context, _) {
                final detail = snapshot.detail;
                if (detail == null) {
                  if (snapshot.error != null) {
                    return ErrorView(
                      title: '任务加载失败',
                      message: snapshot.error!,
                      onRetry: _refresh,
                    );
                  }
                  return const LoadingBlock(text: '正在加载任务……');
                }
                return ListView(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
                  children: _buildBody(detail, snapshot.error),
                );
              },
            ),
    );
  }

  /// 页面主体：按真实状态分支（进行中 / 完成 / 失败取消中断）。
  List<Widget> _buildBody(JobDetail job, String? snapshotError) {
    return [
      _buildHeader(job),
      if (snapshotError != null) ...[
        const SizedBox(height: 8),
        InfoBanner(
          icon: '⚠️',
          tone: 'warn',
          text: '任务快照更新失败，当前显示最近一次数据：$snapshotError',
        ),
      ],
      if (job.isRunning) ..._buildRunning(job),
      if (job.isDoneSuccess) ..._buildDone(job),
      if (!job.isRunning && !job.isDoneSuccess) ..._buildTerminal(job),
    ];
  }

  /// 页头：作品名 + 真实状态 + 模式 + 耗时（技术 ID 不在此展示）。
  Widget _buildHeader(JobDetail job) {
    final elapsedSeconds = job.result?.elapsedSeconds;
    final elapsed = job.isRunning
        ? '耗时 ${fmtElapsed(job.startedAt)}'
        : (elapsedSeconds != null ? '耗时 ${fmtClock(elapsedSeconds)}' : '');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                shortDesc(job.displayName, 40),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 8),
            StatusTag(meta: statusMeta(job), compact: true),
          ],
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ModeChip(mode: job.mode, modeSource: job.modeSource, compact: true),
            if (elapsed.isNotEmpty)
              Text(
                elapsed,
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.textMuted,
                ),
              ),
          ],
        ),
      ],
    );
  }

  // ---------- 进行中 ----------
  List<Widget> _buildRunning(JobDetail job) {
    final stage = job.stage;
    final current = stage.current;
    final blurb = phaseBlurb(current);
    final progressText = job.progress?.text ?? '';
    final live = job.live ?? '';
    final thinking = currentThinking(job);
    final revise = stage.revise;
    return [
      const SizedBox(height: 12),
      // 当前阶段：只显示当前阶段，不做固定线性步骤条。
      Container(
        key: const Key('progress-stage'),
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.yellowSoft,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: AppColors.yellowDeep.withValues(alpha: 0.28),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(phaseIcon(current), style: const TextStyle(fontSize: 15)),
                const SizedBox(width: 6),
                Text(
                  current == null || current.isEmpty
                      ? '等待阶段上报'
                      : phaseLabel(current),
                  style: const TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.yellowDeep,
                  ),
                ),
                if (revise > 0) ...[
                  const SizedBox(width: 8),
                  Text(
                    '修订 $revise 次',
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: AppColors.fallback,
                    ),
                  ),
                ],
              ],
            ),
            if (blurb.isNotEmpty) ...[
              const SizedBox(height: 5),
              Text(
                blurb,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textMuted,
                ),
              ),
            ],
            if (progressText.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                '🧱 $progressText',
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textMuted,
                ),
              ),
            ],
            if (live.isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2),
                    child: SizedBox(
                      width: 12,
                      height: 12,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      live,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.run,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
      const SizedBox(height: 12),
      // 设计稿主视觉：真实设计稿优先，未产生时紧凑空态。
      ProgressDesignSection(
        key: const Key('progress-design'),
        design: job.design,
      ),
      if (thinking != null) ...[
        const SizedBox(height: 10),
        _buildThinking(thinking),
      ],
      const SizedBox(height: 16),
      // 取消是次要危险操作：确认后提交，不与其他主操作争夺注意力。
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton.icon(
          key: const Key('progress-cancel'),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.danger,
            side: BorderSide(color: AppColors.danger.withValues(alpha: 0.45)),
            minimumSize: const Size(48, 44),
          ),
          onPressed: _cancelBusy ? null : () => _cancel(job),
          icon: const Icon(Icons.cancel_outlined, size: 16),
          label: Text(
            _cancelBusy ? '提交中…' : '取消任务',
            style: const TextStyle(fontSize: 12),
          ),
        ),
      ),
    ];
  }

  /// 思考面板：默认收起只显示阶段/字数摘要；用户展开状态不被轮询覆盖。
  Widget _buildThinking(ThinkingTurn turn) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: turn.live
              ? AppColors.yellow.withValues(alpha: 0.45)
              : AppColors.borderSoft,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            expanded: _thinkingExpanded,
            button: true,
            label: '思考过程',
            child: InkWell(
              key: const Key('thinking-summary'),
              onTap: () =>
                  setState(() => _thinkingExpanded = !_thinkingExpanded),
              child: Container(
                constraints: const BoxConstraints(minHeight: 48),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                child: Row(
                  children: [
                    const Text('💭', style: TextStyle(fontSize: 14)),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        turn.metaText,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: turn.live
                              ? AppColors.yellowDeep
                              : AppColors.textMuted,
                        ),
                      ),
                    ),
                    Icon(
                      _thinkingExpanded ? Icons.expand_less : Icons.expand_more,
                      size: 20,
                      color: AppColors.textMuted,
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_thinkingExpanded)
            Container(
              constraints: const BoxConstraints(maxHeight: 320),
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppColors.bg,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.borderSoft),
              ),
              child: SingleChildScrollView(
                child: SelectableText(
                  turn.text,
                  style: const TextStyle(
                    fontSize: 12,
                    height: 1.5,
                    color: AppColors.textMuted,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  // ---------- 完成 ----------
  List<Widget> _buildDone(JobDetail job) {
    final result = job.result;
    final facts = <FactChipData>[
      if (result?.pieces != null) FactChipData('零件', '${result!.pieces} 块'),
      if (result?.layerCount != null)
        FactChipData('层数', '${result!.layerCount}'),
      if ((result?.colors.isNotEmpty ?? false))
        FactChipData('配色', '${result!.colors.length} 种'),
      if (result?.attempts != null)
        FactChipData('求解尝试', '${result!.attempts} 次'),
    ];
    final hasArtifacts =
        result?.modelPath != null && result?.solutionPath != null;
    return [
      const SizedBox(height: 14),
      outcomeBannerWidget(job),
      if (facts.isNotEmpty) ...[
        const SizedBox(height: 10),
        FactChips(facts: facts),
      ],
      const SizedBox(height: 16),
      SizedBox(
        width: double.infinity,
        child: FilledButton.icon(
          key: const Key('progress-view-work'),
          onPressed: hasArtifacts
              ? () => openWorkDetailPage(context, job.id, replace: true)
              : null,
          icon: const Icon(Icons.view_in_ar, size: 18),
          label: Text(hasArtifacts ? '查看作品' : '该任务没有可展示的 3D 产物'),
        ),
      ),
      const SizedBox(height: 8),
      Row(
        children: [
          Expanded(
            child: OutlinedButton(
              onPressed: () => openGenerationRecordPage(context, job.id),
              child: const Text('生成记录'),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: OutlinedButton(
              onPressed: _retryBusy ? null : () => _retry(job),
              child: Text(_retryBusy ? '重试中…' : retryLabel(job.mode)),
            ),
          ),
        ],
      ),
    ];
  }

  // ---------- 失败 / 取消 / 中断 ----------
  List<Widget> _buildTerminal(JobDetail job) {
    final info = failureInfo(job);
    final cancelled = job.isCancelled || job.outcome == JobOutcome.cancelled;
    final interrupted = job.isInterrupted;
    final where = info.stageLabel.isEmpty
        ? '没有记录到断点阶段'
        : '断在「${info.stageLabel}」阶段';
    return [
      const SizedBox(height: 14),
      if (cancelled)
        const InfoBanner(
          icon: '⏹️',
          tone: 'info',
          title: '已取消',
          text: '取消后不会再启动快速保底或新的模型调用。',
        )
      else if (interrupted)
        const InfoBanner(
          icon: '⏸️',
          tone: 'warn',
          title: '生成已中断',
          text: '服务重启前没有跑完，可以回看生成记录或按原模式重试。',
        )
      else
        InfoBanner(
          icon: '❌',
          tone: 'bad',
          title: '生成未完成',
          text: '${info.reason}\n$where',
        ),
      if (!cancelled && !interrupted) ...[
        const SizedBox(height: 8),
        Text(
          where,
          style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
        ),
      ],
      const SizedBox(height: 16),
      SizedBox(
        width: double.infinity,
        child: FilledButton.icon(
          key: const Key('progress-retry'),
          onPressed: _retryBusy ? null : () => _retry(job),
          icon: const Icon(Icons.refresh, size: 18),
          label: Text(_retryBusy ? '重试中…' : retryLabel(job.mode)),
        ),
      ),
      const SizedBox(height: 8),
      OutlinedButton(
        onPressed: () => openGenerationRecordPage(context, job.id),
        child: const Text('生成记录'),
      ),
    ];
  }
}
