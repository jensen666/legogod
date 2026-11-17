// 生成记录「运行与需求信息」「两次尝试及最终交付来源」区块：
// - 需求原文完整展示（不截断，长文在固定高度区域内滚动查看）；
// - 任务 ID、模式与来源、发起时间、总耗时、交付结果与来源、重试关系集中在此；
// - 两次尝试逐条保留成功产物归属与失败原因，不删减任何一次尝试的数据。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../models/result.dart';
import '../../ui/widgets/common.dart';
import 'record_texts.dart';

/// 运行与需求信息区块。
class RecordRunInfoSection extends StatelessWidget {
  const RecordRunInfoSection({super.key, required this.job});

  /// 目标任务详情。
  final JobDetail job;

  @override
  Widget build(BuildContext context) {
    final result = job.result;
    final outcome = job.outcome ?? result?.outcome;
    final retryOf = job.retryOf;
    final name = result?.name;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 作品名称：结果里记录的真实名称（旧页头展示的信息，不因改版丢失）。
        if (name != null && name.isNotEmpty) ...[
          KeyValueRow(label: '作品名称', value: name),
          const SizedBox(height: 8),
        ],
        // 需求原文：完整保留服务端记录原文，不做折叠空白或截断。
        const Text('需求原文', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        if (job.desc.isEmpty)
          const Text(
            '该任务没有记录需求原文。',
            style: TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.5),
          )
        else
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxHeight: 220),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.bg,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppColors.borderSoft),
            ),
            child: SingleChildScrollView(
              child: SelectableText(
                job.desc,
                style: const TextStyle(fontSize: 12.5, height: 1.55),
              ),
            ),
          ),
        const SizedBox(height: 12),
        KeyValueRow(label: '任务 ID', value: job.id),
        if (result?.runId != null) KeyValueRow(label: 'run_id', value: result!.runId!),
        KeyValueRow(label: '模式', value: modeDisplay(job.mode, job.modeSource)),
        KeyValueRow(label: '模式来源', value: modeSourceHint(job.modeSource)),
        KeyValueRow(label: '发起时间', value: fmtDateTime(job.startedAt)),
        KeyValueRow(label: '总耗时', value: recordElapsedText(job)),
        KeyValueRow(
          label: '交付结果',
          value: outcome == null || outcome.isEmpty ? '无交付记录' : JobOutcome.label(outcome),
        ),
        KeyValueRow(
          label: '交付结果来源',
          value: recordOutcomeSourceText(job.outcomeSource),
        ),
        if (retryOf != null && retryOf.isNotEmpty)
          _RetrySourceRow(sourceId: retryOf, currentJobId: job.id),
      ],
    );
  }
}

/// 重试来源行：可点击打开来源任务。
/// 使用 push 打开（不自动替换或递归跳转），返回即回到本页；来源与当前任务相同则不提供跳转。
class _RetrySourceRow extends StatelessWidget {
  const _RetrySourceRow({required this.sourceId, required this.currentJobId});

  /// 来源任务 ID（job.retryOf）。
  final String sourceId;

  /// 当前任务 ID，用于避免自我循环跳转。
  final String currentJobId;

  @override
  Widget build(BuildContext context) {
    final isSelf = sourceId == currentJobId;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(
            width: 92,
            child: Text('重试自', style: TextStyle(fontSize: 12, color: AppColors.textMuted)),
          ),
          Expanded(
            child: Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                SelectableText(
                  sourceId,
                  style: const TextStyle(fontSize: 12, height: 1.4, fontFamily: 'monospace'),
                ),
                if (isSelf)
                  const Text(
                    '来源与当前任务相同，不重复打开',
                    style: TextStyle(fontSize: 11.5, color: AppColors.textMuted),
                  )
                else
                  TextButton(
                    style: TextButton.styleFrom(
                      minimumSize: const Size(48, 40),
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                    ),
                    onPressed: () => openJobById(context, sourceId),
                    child: const Text('打开来源任务', style: TextStyle(fontSize: 12)),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 两次尝试及最终交付来源区块（只在尝试次数大于 1 时展示）。
class RecordAttemptsSection extends StatelessWidget {
  const RecordAttemptsSection({super.key, required this.result});

  /// 任务结果（含 attempts_detail 原始明细）。
  final ResultData result;

  @override
  Widget build(BuildContext context) {
    final attempts = result.attemptsDetail;
    var lastOk = -1;
    for (var i = 0; i < attempts.length; i++) {
      if (attempts[i].ok) lastOk = i;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < attempts.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(
              '${attempts[i].ok ? '✅' : '❌'} ${attempts[i].title}：'
              '${attemptSummary(attempts[i])}'
              '${i == lastOk && attempts[i].ok ? ' · 该次产物为最终交付产物' : ''}',
              style: TextStyle(
                fontSize: 12,
                height: 1.5,
                color: attempts[i].ok ? AppColors.text : AppColors.danger,
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text(
            lastOk < 0
                ? '两次尝试都没有成功，本次没有可交付产物。'
                : '最终交付来源：第 ${lastOk + 1} 次尝试（${attempts[lastOk].title}）',
            style: const TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.45),
          ),
        ),
      ],
    );
  }
}
