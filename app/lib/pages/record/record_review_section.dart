// 生成记录「视觉评审与评审图」区块：
// 如实区分「真实评分 / 快速未评审 / 评审不可用 / 评审失败 / 评审过期 / 无记录」六种状态，
// 完整保留整体分、分项分、最差部位、缺失特征、改进建议、修订未完成原因与真实评审渲染图。
// 绝不把「未评审」显示成 0 分，也不把「评审不可用」写成加载失败。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/format.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../models/result.dart';
import '../../ui/widgets/common.dart';
import '../../ui/widgets/review_views.dart';

/// 收起状态下的评审摘要：先让用户知道评审是否可用，再决定是否展开。
String recordReviewSubtitle(JobDetail job) {
  final result = job.result;
  final review = result?.review;
  if (review != null && review.hasScores) {
    return result?.reviewStale == true ? '已有真实评分，但评审已过期' : '已记录真实视觉评分';
  }
  if (job.mode == 'fast') return '快速任务未进行视觉评审（不是 0 分）';
  if (result?.reviewUnavailable == true) return '评审不可用（本次没有评分，不是 0 分）';
  if (result?.reviewFailed == true) return '评审未通过（没有有效评分）';
  if (result?.reviewStale == true) return '评审已过期（最终稿未复审）';
  return '没有视觉评审记录';
}

/// 视觉评审与评审图区块。
class RecordReviewSection extends StatelessWidget {
  const RecordReviewSection({super.key, required this.job});

  /// 目标任务详情。
  final JobDetail job;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final result = job.result;
    final review = result?.review;
    final overall = review?.overall;
    final hasScores = review != null && review.hasScores && overall != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (hasScores)
          FactChips(
            facts: [
              FactChipData('整体分', '$overall/10'),
              for (final entry in reviewScoreLabels.entries)
                if (review.scores[entry.key] != null)
                  FactChipData(entry.value, '${review.scores[entry.key]}'),
            ],
          )
        else
          Text(
            _stateText(job, result),
            style: const TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.55),
          ),
        if (review != null) ..._details(review),
        if (hasScores && result?.reviewStale == true) _staleWarning(),
        if (result?.revisionIncomplete == true) _revisionWarning(result),
        const SizedBox(height: 12),
        const Text('评审渲染图', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        ReviewViewsGrid(
          views: job.views,
          urlOf: (path) => app.api.absoluteUrl(path),
          headers: app.api.artifactHeaders,
          emptyText: _viewsEmptyText(job),
        ),
      ],
    );
  }

  /// 没有真实评分时的状态文案：每种状态各自不同，不统一成「无评分」。
  String _stateText(JobDetail job, ResultData? result) {
    if (job.mode == 'fast') return fastNoReviewText;
    if (result?.reviewUnavailable == true) {
      return '视觉评审不可用（如实标记：本次没有视觉评分，不属于 0 分）。';
    }
    if (result?.reviewFailed == true) {
      final reason = result?.degradedReason;
      return '视觉评审未通过：本次没有可展示的有效评分'
          '${reason == null ? '' : '（$reason）'}。';
    }
    if (result?.reviewStale == true) {
      return '视觉评审已过期：评审稿与最终模型不一致，最终稿未复审，'
          '因此没有可展示的有效评分（不是 0 分）。';
    }
    return '本次运行没有记录视觉评审结论。';
  }

  /// 评审明细：最差部位、缺失特征、改进建议（有则展示，不因主界面简化而丢失）。
  List<Widget> _details(ReviewData review) {
    final widgets = <Widget>[];
    if (review.worstParts.isNotEmpty) {
      widgets.add(_itemBlock('最差部位', review.worstParts));
    }
    if (review.missingFeatures.isNotEmpty) {
      widgets.add(_itemBlock('缺失特征', review.missingFeatures));
    }
    if (review.suggestions.isNotEmpty) {
      widgets.add(_itemBlock('改进建议', review.suggestions));
    }
    return widgets;
  }

  /// 一组文本明细。
  Widget _itemBlock(String title, List<String> items) {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Text(
                '· $item',
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppColors.textMuted,
                  height: 1.45,
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 有评分但评审已过期：评分对应较早设计稿，不能据此判定视觉达标。
  Widget _staleWarning() {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Text(
        '评审已过期：以上评分对应较早的设计稿，最终稿未复审，不能据此判定视觉达标。',
        style: const TextStyle(fontSize: 11.5, color: AppColors.warn, height: 1.45),
      ),
    );
  }

  /// 视觉修订未完成原因（真实记录，有则保留）。
  Widget _revisionWarning(ResultData? result) {
    final reason = result?.revisionIncompleteReason;
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Text(
        '修订未完成：${reason == null || reason.isEmpty ? '视觉修订未完成' : reason}',
        style: const TextStyle(fontSize: 11.5, color: AppColors.warn, height: 1.45),
      ),
    );
  }

  /// 评审图空态文案：按快速未评审 / 评审不可用 / 未生成区分。
  String _viewsEmptyText(JobDetail job) {
    if (job.mode == 'fast') {
      return '快速任务不进行视觉评审，因此没有评审渲染图。';
    }
    if (job.result?.reviewUnavailable == true) {
      return '视觉评审不可用，本次没有评审图（不是加载失败）。';
    }
    return '本次运行没有生成评审图。';
  }
}
