// 生成规则页：面向用户完整说明快速 / 高保真两档模式、并发与重试规则，
// 以及「零件目录就是全部可用库存」这一真实约束；不堆砌实现术语。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/theme.dart';
import '../../ui/widgets/common.dart';

/// 生成规则页。
class RulesPage extends StatelessWidget {
  const RulesPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('生成规则')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Text(
              '两档模式对比',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
          _ModeComparisonCard(),
          const SectionTitle('生成规则'),
          AppCard(
            child: Text(
              generationRulesText,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.7,
                color: AppColors.textMuted,
              ),
            ),
          ),
          const SectionTitle('零件与库存'),
          const AppCard(
            child: Text(
              '生成时只会使用服务端零件目录里真实存在的形状、颜色与库存：'
              '目录里没有的形状不会凭空出现，库存不足时会按真实可用数量安排。'
              '你可以在「我的 → 零件目录」查看全部形状、颜色与库存。',
              style: TextStyle(
                fontSize: 12.5,
                height: 1.7,
                color: AppColors.textMuted,
              ),
            ),
          ),
          const SizedBox(height: 12),
          const InfoBanner(
            icon: '🧱',
            tone: 'info',
            text: '两档模式只影响是否追加视觉评审与视觉修订；结构与可拼性检查标准相同，'
                '作品最终以真实服务和零件库存为准。',
          ),
        ],
      ),
    );
  }
}

/// 两档模式对比卡：把统一文案按段落拆分渲染，便于大字体会话逐段阅读。
class _ModeComparisonCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final paragraphs = modeComparisonText.split('\n\n');
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < paragraphs.length; i++) ...[
            if (i > 0) const Divider(height: 22),
            _ModeParagraph(text: paragraphs[i]),
          ],
        ],
      ),
    );
  }
}

/// 单个模式段落：首段「快速：…」「高保真：…」拆成标题 + 正文，其余原文展示。
class _ModeParagraph extends StatelessWidget {
  const _ModeParagraph({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final index = text.indexOf('：');
    if (index > 0 && index <= 6) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            text.substring(0, index),
            style: const TextStyle(
              fontSize: 13.5,
              fontWeight: FontWeight.w700,
              color: AppColors.yellowDeep,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            text.substring(index + 1),
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.7,
              color: AppColors.textMuted,
            ),
          ),
        ],
      );
    }
    return Text(
      text,
      style: const TextStyle(fontSize: 12.5, height: 1.7, color: AppColors.textMuted),
    );
  }
}
