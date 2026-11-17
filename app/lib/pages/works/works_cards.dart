// 作品页卡片与分页控件：
// - 进行中卡片：名称、模式、真实耗时与「查看进度」主操作，取消收在右上角次要菜单；
// - 已完成 / 全部记录卡片：整卡单一跳转，不显示任务 ID，不放「再次生成 / 重试」；
// - 分页栏：仅在服务端返回多页时显示，边界按钮禁用，展示真实页码与总数。
// 所有卡片点击统一走 route_nav.openJobById，由落点判定决定进入进度 / 作品 / 记录。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 进行中作品卡片：整卡与「查看进度」都进入生成进度；取消是明确的次要菜单操作。
class RunningWorkCard extends StatelessWidget {
  const RunningWorkCard({super.key, required this.job});

  final JobSummary job;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      key: Key('works-card-${job.id}'),
      padding: const EdgeInsets.fromLTRB(14, 8, 6, 10),
      onTap: () => openJobById(context, job.id),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    shortDesc(job.displayName, 60),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
              PopupMenuButton<String>(
                tooltip: '更多操作',
                onSelected: (value) {
                  if (value == 'cancel') _cancelRunningJob(context, job);
                },
                itemBuilder: (context) => const [
                  PopupMenuItem<String>(
                    value: 'cancel',
                    child: Row(
                      children: [
                        Icon(Icons.cancel_outlined, size: 18, color: AppColors.danger),
                        SizedBox(width: 8),
                        Text('取消任务'),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              ModeChip(mode: job.mode, modeSource: job.modeSource, compact: true),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '耗时 ${fmtElapsed(job.startedAt)}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: () => openJobById(context, job.id),
              icon: const Icon(Icons.play_arrow, size: 18),
              label: const Text('查看进度'),
            ),
          ),
        ],
      ),
    );
  }
}

/// 取消进行中任务：必须先确认，取消只影响该任务，失败时展示真实错误。
Future<void> _cancelRunningJob(BuildContext context, JobSummary job) async {
  final app = AppScope.read(context);
  final confirmed = await showConfirmDialog(
    context,
    title: '取消任务',
    message: '确定取消「${shortDesc(job.displayName, 24)}」？'
        '取消后该任务不会再启动新的模型调用或保底，其他任务不受影响。',
    confirmText: '确认取消',
    danger: true,
  );
  if (!confirmed) return;
  try {
    await app.cancelJob(job.id);
    if (context.mounted) showNotice(context, '已提交取消请求');
  } catch (e) {
    if (context.mounted) showNotice(context, '取消失败：${describeError(e)}');
  }
}

/// 已完成 / 全部记录共用的摘要卡片：整卡点击进入默认落点，卡片上不出现技术 ID 与重试按钮。
class WorkSummaryCard extends StatelessWidget {
  const WorkSummaryCard({super.key, required this.job, this.showError = true});

  final JobSummary job;

  /// 是否展示失败原因摘要（全部记录需要；已完成记录按真实字段展示）。
  final bool showError;

  @override
  Widget build(BuildContext context) {
    final meta = summaryStatusMeta(job);
    final error = (job.error ?? '').trim();
    final spec = job.specText.isEmpty ? '规格未记录' : job.specText;
    return AppCard(
      key: Key('works-card-${job.id}'),
      padding: const EdgeInsets.all(14),
      onTap: () => openJobById(context, job.id),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  shortDesc(job.displayName, 60),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                ),
              ),
              const SizedBox(width: 8),
              const Padding(
                padding: EdgeInsets.only(top: 2),
                child: Icon(Icons.chevron_right, size: 18, color: AppColors.textDim),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              StatusTag(meta: meta, compact: true),
              const Spacer(),
              Text(
                fmtDateTime(job.startedAt),
                style: const TextStyle(fontSize: 11, color: AppColors.textDim),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            spec,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
          ),
          if (job.colors.isNotEmpty) ...[
            const SizedBox(height: 8),
            PaletteStrip(colors: job.colors, height: 5),
          ],
          if (showError && error.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '失败原因：${shortDesc(error, 80)}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11.5, color: AppColors.danger),
            ),
          ],
        ],
      ),
    );
  }
}

/// 服务端分页栏：仅在多页且列表非空时由页面渲染；上一页 / 下一页按真实边界禁用。
class WorksPager extends StatelessWidget {
  const WorksPager({
    super.key,
    required this.data,
    required this.onPrev,
    required this.onNext,
  });

  final HistoryPageData data;

  /// 上一页回调；为空表示已在第一页（按钮禁用）。
  final VoidCallback? onPrev;

  /// 下一页回调；为空表示已在最后一页（按钮禁用）。
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        children: [
          OutlinedButton(onPressed: onPrev, child: const Text('上一页')),
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '第 ${data.page} / ${data.pages} 页',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                ),
                const SizedBox(height: 2),
                Text(
                  '共 ${data.total} 条记录',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 11, color: AppColors.textDim),
                ),
              ],
            ),
          ),
          OutlinedButton(onPressed: onNext, child: const Text('下一页')),
        ],
      ),
    );
  }
}
