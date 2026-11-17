// 通用界面组件：状态标签、模式徽章、横幅、空态、错误态、配色条、规格徽章等。
// 视觉规范：明亮积木工坊 + 乐高黄强调色；状态必须有图标+文字，不只靠颜色区分。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/theme.dart';
import '../../models/result.dart';

/// 状态标签（图标 + 文字 + 语义色调）。
class StatusTag extends StatelessWidget {
  const StatusTag({super.key, required this.meta, this.compact = false});

  final OutcomeMeta meta;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color = AppColors.tone(meta.tone);
    return Semantics(
      label: '状态：${meta.text}',
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 8 : 10,
          vertical: compact ? 3 : 5,
        ),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: color.withValues(alpha: 0.45)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(meta.icon, style: TextStyle(fontSize: compact ? 12 : 13)),
            const SizedBox(width: 5),
            Text(
              meta.text,
              style: TextStyle(
                color: color,
                fontSize: compact ? 12 : 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 模式徽章：只有真实模式才显示；完全未记录时显示中性「未记录」说明。
class ModeChip extends StatelessWidget {
  const ModeChip({
    super.key,
    required this.mode,
    this.modeSource,
    this.compact = false,
  });

  final String? mode;
  final String? modeSource;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final text = modeBadgeText(mode) ?? '未记录';
    final isFast = mode == 'fast';
    final color = isFast ? AppColors.run : AppColors.yellowDeep;
    return Semantics(
      label: '生成模式：${modeDisplay(mode, modeSource)}',
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 7 : 9,
          vertical: compact ? 2 : 4,
        ),
        decoration: BoxDecoration(
          color: isFast
              ? AppColors.run.withValues(alpha: 0.08)
              : AppColors.yellowSoft,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: color,
            fontSize: compact ? 11 : 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

/// 区块标题。
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing, this.padding});

  final String text;
  final Widget? trailing;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding ?? const EdgeInsets.only(top: 18, bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// 信息横幅（成功/警告/错误/提示）。
class InfoBanner extends StatelessWidget {
  const InfoBanner({
    super.key,
    required this.text,
    this.icon,
    this.tone = 'info',
    this.action,
    this.title,
  });

  final String text;
  final String? icon;
  final String tone;
  final String? title;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final color = AppColors.tone(tone);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (icon != null) ...[
            Text(icon!, style: const TextStyle(fontSize: 16)),
            const SizedBox(width: 8),
          ],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (title != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      title!,
                      style: TextStyle(
                        color: color,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                Text(text, style: const TextStyle(height: 1.45)),
                if (action != null) ...[const SizedBox(height: 8), action!],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 空态。
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.actions = const <Widget>[],
  });

  final String icon;
  final String title;
  final String? message;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(icon, style: const TextStyle(fontSize: 44)),
            const SizedBox(height: 12),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            if (message != null) ...[
              const SizedBox(height: 8),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textMuted, height: 1.5),
              ),
            ],
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 16),
              Wrap(spacing: 10, runSpacing: 10, children: actions),
            ],
          ],
        ),
      ),
    );
  }
}

/// 错误态（带重试）。
class ErrorView extends StatelessWidget {
  const ErrorView({
    super.key,
    required this.message,
    this.onRetry,
    this.retryLabel = '重试',
    this.title = '加载失败',
  });

  final String message;
  final VoidCallback? onRetry;
  final String retryLabel;
  final String title;

  @override
  Widget build(BuildContext context) {
    return EmptyState(
      icon: '⚠️',
      title: title,
      message: message,
      actions: [
        if (onRetry != null)
          OutlinedButton(onPressed: onRetry, child: Text(retryLabel)),
      ],
    );
  }
}

/// 加载中块。
class LoadingBlock extends StatelessWidget {
  const LoadingBlock({super.key, this.text = '加载中……', this.height});

  final String text;
  final double? height;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
            const SizedBox(height: 10),
            Text(text, style: const TextStyle(color: AppColors.textMuted)),
          ],
        ),
      ),
    );
  }
}

/// 卡片容器。
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.child, this.padding, this.onTap});

  final Widget child;
  final EdgeInsetsGeometry? padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final content = Container(
      width: double.infinity,
      padding: padding ?? const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.borderSoft),
      ),
      child: child,
    );
    if (onTap == null) return content;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: content,
    );
  }
}

/// 颜色小方块。
class ColorDot extends StatelessWidget {
  const ColorDot(this.hex, {super.key, this.size = 12, this.radius = 3});

  final String? hex;
  final double size;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final color = parseHexColor(hex);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: AppColors.border, width: 0.8),
      ),
    );
  }
}

/// 配色条（历史卡片/作品信息用）。
class PaletteStrip extends StatelessWidget {
  const PaletteStrip({super.key, required this.colors, this.height = 6});

  final List<ColorShare> colors;
  final double height;

  @override
  Widget build(BuildContext context) {
    if (colors.isEmpty) {
      return SizedBox(
        height: height,
        child: Container(
          decoration: BoxDecoration(
            color: AppColors.borderSoft,
            borderRadius: BorderRadius.circular(99),
          ),
        ),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(99),
      child: SizedBox(
        height: height,
        child: Row(
          children: [
            for (final color in colors)
              Expanded(
                flex: color.count.clamp(1, 1000000),
                child: Container(color: parseHexColor(color.hex)),
              ),
          ],
        ),
      ),
    );
  }
}

/// 规格徽章组（零件/体素/层数/占地/配色等）。
class FactChips extends StatelessWidget {
  const FactChips({super.key, required this.facts, this.wrap = true});

  final List<FactChipData> facts;
  final bool wrap;

  @override
  Widget build(BuildContext context) {
    final children = [
      for (final fact in facts)
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.surfaceHigh,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppColors.borderSoft),
          ),
          child: RichText(
            text: TextSpan(
              style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
              children: [
                TextSpan(text: '${fact.label} '),
                TextSpan(
                  text: fact.value,
                  style: const TextStyle(
                    color: AppColors.text,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
    ];
    if (wrap) return Wrap(spacing: 8, runSpacing: 8, children: children);
    return Row(
      children: [
        for (var i = 0; i < children.length; i++) ...[
          if (i > 0) const SizedBox(width: 8),
          children[i],
        ],
      ],
    );
  }
}

/// 单个规格徽章数据。
class FactChipData {
  const FactChipData(this.label, this.value);

  final String label;
  final String value;
}

/// 确认对话框：危险操作前必须明确确认。
Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  String confirmText = '确认',
  String cancelText = '取消',
  bool danger = false,
}) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(cancelText),
        ),
        FilledButton(
          style: danger
              ? FilledButton.styleFrom(backgroundColor: AppColors.danger)
              : null,
          onPressed: () => Navigator.of(context).pop(true),
          child: Text(confirmText),
        ),
      ],
    ),
  );
  return result ?? false;
}

/// 轻提示。
void showNotice(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// 解析 #RRGGBB / #AARRGGBB 颜色，非法值返回中性灰（不崩溃）。
Color parseHexColor(String? hex) {
  final text = (hex ?? '').trim();
  if (text.isEmpty) return AppColors.textDim;
  var value = text.startsWith('#') ? text.substring(1) : text;
  if (value.length == 6) value = 'FF$value';
  if (value.length != 8) return AppColors.textDim;
  final parsed = int.tryParse(value, radix: 16);
  if (parsed == null) return AppColors.textDim;
  return Color(parsed);
}

// ============================================================
// 信息架构简化重构新增通用组件（分段控件 / 可展开区块 / 底部主操作栏）
// ============================================================

/// 分段控件的一项。
class SegmentedItem {
  const SegmentedItem(this.label, {this.badge});

  final String label;

  /// 数量角标（>0 时显示），用于进行中数量等真实计数。
  final int? badge;
}

/// 紧凑分段控件：等宽、44dp 高、选中态乐高黄，带可访问选中态。
class SegmentedControl extends StatelessWidget {
  const SegmentedControl({
    super.key,
    required this.items,
    required this.index,
    required this.onChanged,
  });

  final List<SegmentedItem> items;
  final int index;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 44,
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderSoft),
      ),
      child: Row(
        children: [
          for (var i = 0; i < items.length; i++)
            Expanded(
              child: Padding(
                padding: EdgeInsets.only(left: i == 0 ? 0 : 3),
                child: MergeSemantics(
                  child: Semantics(
                    selected: i == index,
                    button: true,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(9),
                      onTap: () => onChanged(i),
                      child: Container(
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: i == index
                              ? AppColors.yellow
                              : Colors.transparent,
                          borderRadius: BorderRadius.circular(9),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              items[i].label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: i == index
                                    ? FontWeight.w700
                                    : FontWeight.w500,
                                color: i == index
                                    ? const Color(0xFF201404)
                                    : AppColors.textMuted,
                              ),
                            ),
                            if (items[i].badge != null &&
                                items[i].badge! > 0) ...[
                              const SizedBox(width: 4),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 5,
                                  vertical: 1,
                                ),
                                decoration: BoxDecoration(
                                  color: i == index
                                      ? const Color(0xFF201404)
                                      : AppColors.yellowDeep,
                                  borderRadius: BorderRadius.circular(999),
                                ),
                                child: Text(
                                  '${items[i].badge}',
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.w700,
                                    color: i == index
                                        ? AppColors.yellow
                                        : const Color(0xFF201404),
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 可展开区块：默认收起，标题行满足 48dp 触控，带展开语义。
class ExpandableSection extends StatefulWidget {
  const ExpandableSection({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
    this.initiallyExpanded = false,
    this.trailing,
    this.onExpansionChanged,
  });

  final String title;
  final String? subtitle;
  final Widget child;
  final bool initiallyExpanded;
  final Widget? trailing;
  final ValueChanged<bool>? onExpansionChanged;

  @override
  State<ExpandableSection> createState() => _ExpandableSectionState();
}

class _ExpandableSectionState extends State<ExpandableSection> {
  late bool _open = widget.initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.borderSoft),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MergeSemantics(
            child: Semantics(
              expanded: _open,
              button: true,
              child: InkWell(
                onTap: () {
                  setState(() => _open = !_open);
                  widget.onExpansionChanged?.call(_open);
                },
                child: Container(
                  constraints: const BoxConstraints(minHeight: 48),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              widget.title,
                              style: const TextStyle(
                                fontSize: 13.5,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            if (widget.subtitle != null)
                              Padding(
                                padding: const EdgeInsets.only(top: 2),
                                child: Text(
                                  widget.subtitle!,
                                  style: const TextStyle(
                                    fontSize: 11.5,
                                    color: AppColors.textMuted,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                      if (widget.trailing != null) widget.trailing!,
                      Icon(
                        _open ? Icons.expand_less : Icons.expand_more,
                        size: 20,
                        color: AppColors.textMuted,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (_open)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: widget.child,
            ),
        ],
      ),
    );
  }
}

/// 固定底部主操作栏：安全区适配，不与内容重叠（Scaffold bottomNavigationBar 使用）。
class BottomPrimaryBar extends StatelessWidget {
  const BottomPrimaryBar({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        16,
        10,
        16,
        10 + MediaQuery.of(context).padding.bottom,
      ),
      decoration: const BoxDecoration(
        color: AppColors.bgElevated,
        border: Border(top: BorderSide(color: AppColors.borderSoft)),
      ),
      child: child,
    );
  }
}

/// 图标 + 文案的次要操作（≥48dp 触控目标）。
class LabeledAction extends StatelessWidget {
  const LabeledAction({
    super.key,
    required this.icon,
    required this.label,
    required this.onPressed,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 44),
        padding: const EdgeInsets.symmetric(horizontal: 12),
      ),
      icon: Icon(icon, size: 18),
      label: Text(label, style: const TextStyle(fontSize: 13)),
    );
  }
}

/// 键值信息行（生成记录 / 作品信息使用）。
class KeyValueRow extends StatelessWidget {
  const KeyValueRow({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 92,
            child: Text(
              label,
              style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(fontSize: 12, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }
}
