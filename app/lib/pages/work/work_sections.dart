// 作品详情页的页头与非可交付状态视图：
// - 页头只保留作品名、真实状态标签与生成模式，不展开需求原文与技术 ID；
// - 进行中 / 失败 / 取消 / 中断 / 已完成但缺少产物时，首屏显示真实状态与原因摘要，
//   并给出「生成进度」/「生成记录」真实入口，绝不白屏或显示假成功。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';

/// 作品详情页头：作品名 + 简短真实状态 + 生成模式。
class WorkHeader extends StatelessWidget {
  const WorkHeader({super.key, required this.job});

  final JobDetail job;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                shortDesc(job.displayName, 50),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style:
                    const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
              ),
            ),
            const SizedBox(width: 8),
            StatusTag(meta: statusMeta(job), compact: true),
          ],
        ),
        const SizedBox(height: 6),
        ModeChip(mode: job.mode, modeSource: job.modeSource, compact: true),
      ],
    );
  }
}

/// 非可交付作品视图：真实状态 + 原因摘要 + 「生成进度」/「生成记录」入口。
class WorkNotReadyView extends StatelessWidget {
  const WorkNotReadyView({super.key, required this.job});

  final JobDetail job;

  @override
  Widget build(BuildContext context) {
    final running = job.isRunning;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
      children: [
        WorkHeader(job: job),
        const SizedBox(height: 14),
        if (running)
          _runningBanner(job)
        else if (!job.isDoneSuccess)
          _terminalBanner(job),
        if (!running && job.isDoneSuccess) ...[
          const SizedBox(height: 10),
          const InfoBanner(
            icon: '📦',
            tone: 'warn',
            title: '缺少 3D 产物',
            text: '任务已完成，但服务端没有提供可用的模型 / 方案产物文件，'
                '无法展示成品预览。可进入生成记录查看产物与统计信息。',
          ),
        ],
        const SizedBox(height: 14),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            if (running)
              FilledButton.tonalIcon(
                onPressed: () => openGenerationProgressPage(context, job.id),
                icon: const Icon(Icons.timelapse, size: 18),
                label: const Text('生成进度'),
              ),
            LabeledAction(
              icon: Icons.history,
              label: '生成记录',
              onPressed: () => openGenerationRecordPage(context, job.id),
            ),
          ],
        ),
        if (job.desc.isNotEmpty) ...[
          const SizedBox(height: 16),
          const SectionTitle('原始需求',
              padding: EdgeInsets.only(top: 0, bottom: 6)),
          AppCard(
            child: SelectableText(
              job.desc,
              style: const TextStyle(fontSize: 12.5, height: 1.55),
            ),
          ),
        ],
      ],
    );
  }

  /// 进行中：真实实时状态 / 阶段说明 / 求解进度 / 已耗时。
  Widget _runningBanner(JobDetail job) {
    final segments = <String>[];
    final live = job.live?.trim() ?? '';
    if (live.isNotEmpty) segments.add(live);
    final blurb = phaseBlurb(job.stage.current);
    if (blurb.isNotEmpty) segments.add(blurb);
    final progress = job.progress?.text ?? '';
    if (progress.isNotEmpty) segments.add(progress);
    segments.add('已耗时 ${fmtElapsed(job.startedAt)}');
    if (segments.length == 1) {
      segments.insert(0, '作品仍在生成中');
    }
    return InfoBanner(
      icon: '⏳',
      tone: 'run',
      title: '作品生成中',
      text: '${segments.join('；')}。完成后这里会自动更新为 3D 成品与开始拼装入口。',
    );
  }

  /// 终态（失败 / 取消 / 中断）：真实原因 + 断点阶段，不冒充成功。
  Widget _terminalBanner(JobDetail job) {
    final info = failureInfo(job);
    final stageText =
        info.stageLabel.isEmpty ? '' : '断在「${info.stageLabel}」阶段：';
    return InfoBanner(
      icon: '❌',
      tone: job.isFailed ? 'bad' : 'warn',
      title: statusMeta(job).text,
      text: '$stageText${info.reason}',
    );
  }
}
