// 作品页「全部记录」分段：
// - 服务端搜索（350ms 防抖）、执行状态 / 交付结果完整筛选默认收在「筛选」入口内、重置；
// - 服务端分页（仅多页时显示）、总条数、三种空态与后台刷新失败不清空列表的提示；
// - 卡片整卡单一跳转（openJobById），不显示任务 ID、不放置「再次生成 / 重试」。
import 'dart:async';

import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/storage.dart';
import '../../core/theme.dart';
import '../../models/job.dart';
import '../../ui/widgets/common.dart';
import 'works_cards.dart';

/// 执行状态筛选项（取值与 API 枚举、旧历史页完全一致，不做任何改写）。
const List<List<String>> worksStatusOptions = [
  ['', '全部状态'],
  ['running', '进行中'],
  ['done', '已完成'],
  ['error', '失败'],
  ['cancelled', '已取消'],
  ['interrupted', '已中断'],
];

/// 交付结果筛选项（取值与服务端 outcome 枚举、旧历史页完全一致）。
const List<List<String>> worksOutcomeOptions = [
  ['', '全部交付结果'],
  ['fidelity_success', '高保真成功'],
  ['fidelity_degraded', '降级交付'],
  ['fast_fallback', '快速保底'],
  ['fast_success', '快速成功'],
  ['failed', '生成失败'],
  ['cancelled', '已取消'],
];

/// 「全部记录」分段内容（作为作品页滚动列表的一段，不自带滚动容器）。
class AllRecordsSegment extends StatefulWidget {
  const AllRecordsSegment({super.key});

  @override
  State<AllRecordsSegment> createState() => _AllRecordsSegmentState();
}

class _AllRecordsSegmentState extends State<AllRecordsSegment> {
  final TextEditingController _searchCtrl = TextEditingController();
  Timer? _debounce;

  /// 筛选面板默认收起，点「筛选」才展开。
  bool _filterOpen = false;

  @override
  void initState() {
    super.initState();
    // 恢复已持久化的搜索词（AppState 在启动时读取本地筛选状态）。
    _searchCtrl.text = AppScope.read(context).historyQuery.q;
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _searchCtrl.dispose();
    super.dispose();
  }

  /// 搜索输入：先立即刷新清除按钮，再按 350ms 防抖提交到服务端查询。
  void _onSearchChanged(String value) {
    setState(() {});
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), () {
      if (!mounted) return;
      AppScope.read(context).setHistoryFilter(q: value.trim());
    });
  }

  /// 只清除搜索词，保留执行状态与交付结果筛选。
  void _clearSearch() {
    _debounce?.cancel();
    _searchCtrl.clear();
    setState(() {});
    AppScope.read(context).setHistoryFilter(q: '');
  }

  /// 重置搜索与筛选（AppState 会回到第 1 页并重新拉取）。
  void _resetAll() {
    _debounce?.cancel();
    _searchCtrl.clear();
    setState(() {});
    AppScope.read(context).resetHistoryFilter();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final query = app.historyQuery;
    final data = app.historyData;
    final hasFilter =
        query.q.isNotEmpty || query.status.isNotEmpty || query.outcome.isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          key: const Key('works-search'),
          controller: _searchCtrl,
          onChanged: _onSearchChanged,
          textInputAction: TextInputAction.search,
          decoration: InputDecoration(
            hintText: '搜索作品名称、需求或任务 ID',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _searchCtrl.text.isEmpty
                ? null
                : IconButton(
                    tooltip: '清除搜索',
                    icon: const Icon(Icons.clear),
                    onPressed: _clearSearch,
                  ),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            OutlinedButton.icon(
              key: const Key('works-filter'),
              onPressed: () => setState(() => _filterOpen = !_filterOpen),
              icon: Icon(
                _filterOpen ? Icons.filter_alt : Icons.filter_alt_outlined,
                size: 18,
              ),
              label: const Text('筛选'),
            ),
            const SizedBox(width: 4),
            TextButton.icon(
              onPressed: _resetAll,
              icon: const Icon(Icons.filter_alt_off, size: 16),
              label: const Text('重置'),
            ),
            const Spacer(),
            if (data != null)
              Text(
                '共 ${data.total} 条',
                style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
              ),
          ],
        ),
        if (_filterOpen) _buildFilterPanel(app, query),
        if (hasFilter && !_filterOpen)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              '当前筛选：${_filterSummary(query)}',
              style: const TextStyle(fontSize: 11, color: AppColors.textDim),
            ),
          ),
        const SizedBox(height: 10),
        ..._buildList(app, data, hasFilter),
      ],
    );
  }

  /// 筛选面板：执行状态 + 交付结果两个下拉，值直接写入 AppState（回到第 1 页）。
  Widget _buildFilterPanel(AppState app, HistoryQueryState query) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        children: [
          Expanded(
            child: DropdownButtonFormField<String>(
              key: ValueKey<String>('works-status-${query.status}'),
              initialValue: query.status,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '执行状态',
                contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              ),
              items: [
                for (final option in worksStatusOptions)
                  DropdownMenuItem<String>(value: option[0], child: Text(option[1])),
              ],
              onChanged: (value) => app.setHistoryFilter(status: value ?? ''),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: DropdownButtonFormField<String>(
              key: ValueKey<String>('works-outcome-${query.outcome}'),
              initialValue: query.outcome,
              isExpanded: true,
              decoration: const InputDecoration(
                labelText: '交付结果',
                contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              ),
              items: [
                for (final option in worksOutcomeOptions)
                  DropdownMenuItem<String>(value: option[0], child: Text(option[1])),
              ],
              onChanged: (value) => app.setHistoryFilter(outcome: value ?? ''),
            ),
          ),
        ],
      ),
    );
  }

  /// 当前生效筛选的中文摘要（面板收起时仍能看到真实筛选条件）。
  String _filterSummary(HistoryQueryState query) {
    final bits = <String>[];
    if (query.q.isNotEmpty) bits.add('搜索「${shortDesc(query.q, 20)}」');
    final statusLabel = _optionLabel(worksStatusOptions, query.status);
    if (statusLabel != null) bits.add('执行状态：$statusLabel');
    final outcomeLabel = _optionLabel(worksOutcomeOptions, query.outcome);
    if (outcomeLabel != null) bits.add('交付结果：$outcomeLabel');
    return bits.join(' · ');
  }

  String? _optionLabel(List<List<String>> options, String value) {
    if (value.isEmpty) return null;
    for (final option in options) {
      if (option[0] == value) return option[1];
    }
    // 未知枚举按原始值展示，不冒充任何已知选项。
    return value;
  }

  /// 列表内容：加载态 / 失败态 / 三种空态 / 真实卡片与分页。
  List<Widget> _buildList(AppState app, HistoryPageData? data, bool hasFilter) {
    if (data == null) {
      if (app.historyError != null) {
        return [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: ErrorView(
              title: '生成记录加载失败',
              message: app.historyError!,
              onRetry: app.refreshHistory,
            ),
          ),
        ];
      }
      return const [
        Padding(
          padding: EdgeInsets.symmetric(vertical: 32),
          child: LoadingBlock(text: '生成记录加载中……', height: 160),
        ),
      ];
    }
    if (data.jobs.isEmpty) {
      return [_emptyState(hasFilter, data.total)];
    }
    return [
      if (app.historyError != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: InfoBanner(
            text: '后台刷新失败，当前显示的是上次数据：${app.historyError}',
            icon: '⚠️',
            tone: 'warn',
          ),
        ),
      if (app.historyFromCache)
        const Padding(
          padding: EdgeInsets.only(bottom: 8),
          child: InfoBanner(
            text: '当前展示本地缓存的生成记录，正在等待服务端校准。',
            icon: '🗄️',
            tone: 'warn',
          ),
        ),
      for (final job in data.jobs)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: WorkSummaryCard(job: job),
        ),
      if (data.pages > 1 && data.jobs.isNotEmpty)
        WorksPager(
          key: const Key('works-pager'),
          data: data,
          onPrev: data.page > 1
              ? () => app.setHistoryFilter(page: data.page - 1)
              : null,
          onNext: data.page < data.pages
              ? () => app.setHistoryFilter(page: data.page + 1)
              : null,
        ),
    ];
  }

  /// 全部记录的两种空态：无任何记录（给创作入口）与当前条件无匹配（给清除入口）。
  Widget _emptyState(bool hasFilter, int total) {
    if (hasFilter || total > 0) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 28),
        child: EmptyState(
          icon: '🔍',
          title: '没有匹配的记录',
          message: '当前搜索或筛选没有结果，可清除条件查看全部记录。',
          actions: [
            OutlinedButton(onPressed: _resetAll, child: const Text('清除搜索与筛选')),
          ],
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 28),
      child: EmptyState(
        icon: '🧱',
        title: '还没有生成记录',
        message: '去创作页描述并生成第一个作品，完成与失败的记录都会出现在这里。',
        actions: [
          FilledButton.icon(
            onPressed: () => gotoMainTab(context, 0),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('去创作'),
          ),
        ],
      ),
    );
  }
}
