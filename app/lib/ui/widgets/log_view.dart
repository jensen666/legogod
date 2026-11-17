// 运行日志视图：阶段分隔条 + 求解器明细合并 + 长文本折叠 + 实时状态条。
// 折叠/合并只影响展示，导出使用完整原始日志（见 core/log_export.dart）。
import 'package:flutter/material.dart';

import '../../core/format.dart';
import '../../core/logs.dart';
import '../../core/theme.dart';
import '../../core/thinking.dart';
import '../../models/job.dart';
import 'thinking_panel.dart';

/// 日志列表。
class LogListView extends StatefulWidget {
  const LogListView({
    super.key,
    required this.logs,
    this.running = false,
    this.liveText,
    this.shrinkWrap = false,
    this.height,
    this.emptyText = '还没有运行日志。',
  });

  final List<LogEntry> logs;
  final bool running;

  /// 服务端 live 状态文本（仅进行中展示）。
  final String? liveText;
  final bool shrinkWrap;
  final double? height;
  final String emptyText;

  @override
  State<LogListView> createState() => _LogListViewState();
}

class _LogListViewState extends State<LogListView> {
  final ScrollController _scroll = ScrollController();
  final Set<String> _expanded = <String>{};
  int _lastLogCount = 0;

  @override
  void initState() {
    super.initState();
    _lastLogCount = widget.logs.length;
    WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
  }

  @override
  void didUpdateWidget(covariant LogListView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.logs.length != _lastLogCount) {
      final wasNearBottom =
          !_scroll.hasClients ||
          _scroll.position.maxScrollExtent - _scroll.position.pixels < 80;
      _lastLogCount = widget.logs.length;
      if (wasNearBottom) {
        // 用户正在看历史时不强行拉回底部。
        WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToBottom());
      }
    }
  }

  void _jumpToBottom() {
    if (!_scroll.hasClients) return;
    _scroll.jumpTo(_scroll.position.maxScrollExtent);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final blocks = presentLogs(widget.logs);
    final liveText = widget.running ? widget.liveText : null;
    final content = blocks.isEmpty && (liveText == null || liveText.isEmpty)
        ? Center(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                widget.emptyText,
                style: const TextStyle(color: AppColors.textMuted),
              ),
            ),
          )
        : null;
    final list = ListView.builder(
      controller: _scroll,
      shrinkWrap: widget.shrinkWrap,
      physics: widget.shrinkWrap ? const NeverScrollableScrollPhysics() : null,
      padding: const EdgeInsets.all(10),
      itemCount:
          blocks.length + (liveText != null && liveText.isNotEmpty ? 1 : 0),
      itemBuilder: (context, index) {
        if (index >= blocks.length) {
          return _LiveBar(text: liveText ?? '');
        }
        return _blockWidget(blocks[index], index);
      },
    );
    if (widget.height != null) {
      return SizedBox(height: widget.height, child: content ?? list);
    }
    return content ?? list;
  }

  Widget _blockWidget(LogBlock block, int index) {
    switch (block.type) {
      case 'phase':
        final entry = block.entry;
        final label = phaseLabel(entry?.phase).isEmpty
            ? (entry?.text ?? '阶段')
            : phaseLabel(entry?.phase);
        return Container(
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.yellow.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(6),
            border: Border(left: BorderSide(color: AppColors.yellow, width: 3)),
          ),
          child: Text(
            '◆ 阶段 · $label',
            style: const TextStyle(color: AppColors.yellowDeep, fontSize: 12),
          ),
        );
      case 'solver':
        final key = _entryKey(block.items.first, index);
        return _ExpandableBlock(
          key: ValueKey(key),
          title: '求解器明细 · ${block.items.length} 条',
          initiallyExpanded: _expanded.contains(key),
          onToggle: (open) => _setExpanded(key, open),
          children: [
            for (var i = 0; i < block.items.length; i++)
              _line(block.items[i], '$key-$i'),
          ],
        );
      default:
        final entry =
            block.entry ??
            block.items.firstOrNull ??
            const LogEntry(kind: 'info', text: '', ts: null);
        return _line(entry, _entryKey(entry, index), thought: block.thought);
    }
  }

  String _entryKey(LogEntry entry, int index) =>
      '${entry.ts ?? 'i$index'}-${entry.kind}-${entry.text.hashCode}';

  void _setExpanded(String key, bool open) {
    setState(() {
      if (open) {
        _expanded.add(key);
      } else {
        _expanded.remove(key);
      }
    });
  }

  Widget _line(LogEntry entry, String key, {String thought = ''}) {
    if (entry.isThinking) {
      final turn = ThinkingTurn.fromLog(entry, thought: thought, key: key);
      return ThinkingTurnPanel(
        key: ValueKey('log-think-$key'),
        turn: turn,
        initiallyExpanded: _expanded.contains(key),
      );
    }
    final time = entry.ts != null ? fmtLogTime(entry.ts) : '';
    final step = entry.step != null ? 'S${entry.step}' : '';
    final text = entry.text;
    final longText = text.length > 260;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (time.isNotEmpty)
                Text(
                  time,
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.textDim,
                    fontFamily: 'monospace',
                  ),
                ),
              if (step.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(left: 6),
                  child: Text(
                    step,
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.run,
                      fontFamily: 'monospace',
                    ),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: Text(
                  '[${entry.kind}]',
                  style: TextStyle(fontSize: 11, color: _kindColor(entry.kind)),
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: longText && !_expanded.contains(key)
                    ? Text(
                        '${text.substring(0, 240)} ……（点击展开全部 ${text.length} 字）',
                        style: const TextStyle(fontSize: 12, height: 1.45),
                      )
                    : Text(
                        text,
                        style: const TextStyle(fontSize: 12, height: 1.45),
                      ),
              ),
              if (longText)
                IconButton(
                  visualDensity: VisualDensity.compact,
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 40,
                    minHeight: 40,
                  ),
                  tooltip: _expanded.contains(key) ? '收起' : '展开全部',
                  icon: Icon(
                    _expanded.contains(key)
                        ? Icons.expand_less
                        : Icons.expand_more,
                    size: 18,
                    color: AppColors.textMuted,
                  ),
                  onPressed: () => _setExpanded(key, !_expanded.contains(key)),
                ),
            ],
          ),
        ],
      ),
    );
  }

  static Color _kindColor(String kind) {
    switch (kind) {
      case 'error':
        return AppColors.danger;
      case 'review':
        return AppColors.fallback;
      case 'result':
        return AppColors.ok;
      case 'version':
      case 'revise':
        return AppColors.warn;
      case 'plan':
        return AppColors.yellowDeep;
      default:
        return AppColors.textMuted;
    }
  }
}

class _ExpandableBlock extends StatelessWidget {
  const _ExpandableBlock({
    super.key,
    required this.title,
    required this.initiallyExpanded,
    required this.onToggle,
    required this.children,
  });

  final String title;
  final bool initiallyExpanded;
  final void Function(bool open) onToggle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        initiallyExpanded: initiallyExpanded,
        onExpansionChanged: onToggle,
        tilePadding: const EdgeInsets.symmetric(horizontal: 4),
        childrenPadding: const EdgeInsets.only(left: 12, bottom: 6),
        title: Text(
          title,
          style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
        ),
        children: children,
      ),
    );
  }
}

class _LiveBar extends StatelessWidget {
  const _LiveBar({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    if (text.isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.run.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.run.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 12,
            height: 12,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: AppColors.run,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 12, color: AppColors.run),
            ),
          ),
        ],
      ),
    );
  }
}
