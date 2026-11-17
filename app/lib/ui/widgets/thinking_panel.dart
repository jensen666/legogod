// 思考过程面板：实时回合默认展开、内容增长自动贴底；用户手动收起后不被轮询覆盖；
// 历史回合逐轮可展开，模型输出全部按纯文本展示。
import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../core/thinking.dart';

/// 单个思考回合折叠面板。
class ThinkingTurnPanel extends StatefulWidget {
  const ThinkingTurnPanel({
    super.key,
    required this.turn,
    this.live = false,
    this.initiallyExpanded = false,
  });

  final ThinkingTurn turn;
  final bool live;
  final bool initiallyExpanded;

  @override
  State<ThinkingTurnPanel> createState() => _ThinkingTurnPanelState();
}

class _ThinkingTurnPanelState extends State<ThinkingTurnPanel> {
  late bool _expanded = widget.initiallyExpanded;
  bool _userToggled = false;
  final ScrollController _bodyScroll = ScrollController();

  @override
  void didUpdateWidget(covariant ThinkingTurnPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 同一阶段「实时 → 落盘」切换不算新回合：保留用户手动展开/收起选择。
    final phaseChanged = oldWidget.turn.phase != widget.turn.phase;
    final liveChanged = oldWidget.live != widget.live;
    if (phaseChanged || (liveChanged && !_userToggled)) {
      _userToggled = false;
      _expanded = widget.initiallyExpanded || widget.live;
    }
    if (widget.live && _expanded) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!_bodyScroll.hasClients) return;
        final position = _bodyScroll.position;
        final nearBottom = position.maxScrollExtent - position.pixels < 40;
        if (nearBottom) {
          _bodyScroll.jumpTo(position.maxScrollExtent);
        }
      });
    }
  }

  @override
  void dispose() {
    _bodyScroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final turn = widget.turn;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: widget.live ? AppColors.surfaceHigh : AppColors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: widget.live
              ? AppColors.yellow.withValues(alpha: 0.45)
              : AppColors.borderSoft,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => setState(() {
              _expanded = !_expanded;
              _userToggled = true;
            }),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  Text(
                    widget.live ? '💭' : '💭',
                    style: const TextStyle(fontSize: 14),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          turn.metaText,
                          style: TextStyle(
                            fontSize: 12,
                            color: widget.live
                                ? AppColors.yellowDeep
                                : AppColors.textMuted,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        if (turn.thought.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 3),
                            child: Text(
                              turn.thought,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 12, height: 1.4),
                            ),
                          ),
                      ],
                    ),
                  ),
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    color: AppColors.textMuted,
                    size: 20,
                  ),
                ],
              ),
            ),
          ),
          if (_expanded)
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
                controller: _bodyScroll,
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
}

/// 历史思考回合列表（逐轮展开，不只保留最后一轮）。
class ThinkingTurnsList extends StatelessWidget {
  const ThinkingTurnsList({super.key, required this.turns, this.maxDisplay});

  final List<ThinkingTurn> turns;

  /// 最多展示条数（null 表示全部；复盘页使用全部）。
  final int? maxDisplay;

  @override
  Widget build(BuildContext context) {
    if (turns.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Text(
          '本次运行没有保留可展示的思考回合。',
          style: TextStyle(color: AppColors.textMuted),
        ),
      );
    }
    final shown = maxDisplay == null ? turns : turns.take(maxDisplay!).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final turn in shown)
          ThinkingTurnPanel(
            key: ValueKey('think-${turn.key}'),
            turn: turn,
            initiallyExpanded: false,
          ),
      ],
    );
  }
}
