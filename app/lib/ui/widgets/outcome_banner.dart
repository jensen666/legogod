// 交付结果横幅：高保真成功/降级/快速保底/快速成功/失败/取消，
// 兼容推导（derived）用中性文案并说明来源；快速任务明确「未进行视觉评审」不显示 0 分。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../models/job.dart';
import 'common.dart';

/// 根据任务真实结果构造交付结果横幅。
Widget outcomeBannerWidget(JobDetail job) {
  final result = job.result;
  final outcome = job.outcome ?? result?.outcome ?? '';
  final derived = job.outcomeSource == OutcomeSource.derived;
  final meta = outcomeMeta(outcome, outcomeSource: job.outcomeSource, mode: job.mode);
  switch (outcome) {
    case JobOutcome.fastSuccess:
      return InfoBanner(
        icon: '✅',
        tone: 'ok',
        title: derived ? '生成成功（兼容推导）' : '快速成功',
        text: fastNoReviewText +
            (derived ? '\n该历史记录未显式记录交付结论，此处按状态与评审标记兼容推导。' : ''),
      );
    case JobOutcome.fidelitySuccess:
      return InfoBanner(
        icon: '✅',
        tone: 'ok',
        title: derived ? '生成成功（兼容推导）' : '高保真成功',
        text: '可拼方案 + 视觉评审达标。'
            '${derived ? '\n该历史记录未显式记录交付结论，此处按状态与评审标记兼容推导。' : ''}',
      );
    case JobOutcome.fidelityDegraded:
      return InfoBanner(
        icon: '⚠️',
        tone: 'warn',
        title: derived ? '生成成功（评审异常，兼容推导）' : '降级交付',
        text: '高保真产物已交付，但评审未完全通过'
            '（${result?.degradedReason ?? '视觉评分不足或评审不可用'}）——按规则不重跑快速保底。',
      );
    case JobOutcome.fastFallback:
      return InfoBanner(
        icon: '🛟️',
        tone: 'fb',
        title: '快速保底',
        text: '高保真生成失败，已提供快速保底方案（不计高保真成功）。'
            '高保真失败原因：${result?.fidelityAttemptError ?? '-'}',
      );
    default:
      return InfoBanner(
        icon: meta.icon,
        tone: meta.tone,
        title: meta.text,
        text: meta.note ?? '任务已结束。',
      );
  }
}
