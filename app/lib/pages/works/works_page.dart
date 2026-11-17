// 作品页：进行中 / 已完成 / 全部记录三段合一。
// - 分段选择保留在 AppState.worksSegment，进行中分段显示真实进行中数量角标；
// - 进行中列表来自刷新接口，已完成来自独立分页查询，全部记录沿用服务端搜索/筛选/分页；
// - 已连接时所有分段支持下拉刷新；未连接时给「去连接」入口；
// - 卡片点击统一走 route_nav.openJobById，由落点判定进入进度 / 作品 / 记录。
import 'dart:async';

import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/route_nav.dart';
import '../../ui/widgets/common.dart';
import 'works_all_segment.dart';
import 'works_cards.dart';

/// 作品页。
class WorksPage extends StatefulWidget {
  const WorksPage({super.key});

  @override
  State<WorksPage> createState() => _WorksPageState();
}

class _WorksPageState extends State<WorksPage> {
  Timer? _elapsedTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refreshOnEnter());
    // 进行中卡片的「耗时」每秒刷新一次真实时长（不影响其它分段）。
    _elapsedTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      final app = AppScope.read(context);
      if (app.runningJobs.isEmpty || app.worksSegment != 'running') return;
      setState(() {});
    });
  }

  @override
  void dispose() {
    _elapsedTimer?.cancel();
    super.dispose();
  }

  /// 分段索引：running → 0 / done → 1 / all → 2。
  int _indexOf(String segment) {
    switch (segment) {
      case 'done':
        return 1;
      case 'all':
        return 2;
      default:
        return 0;
    }
  }

  /// 进入作品页时只刷新当前分段，不覆盖用户已保存的分段选择。
  void _refreshOnEnter() {
    if (!mounted) return;
    final app = AppScope.read(context);
    if (!app.configured) return;
    if (!app.worksSegmentRestored && app.lastSyncAt == null) {
      // AppState 启动同步尚未完成：由它拉取真实数据并落到默认分段；
      // 这里只补一次当前分段数据，确保首屏不空白，同时不修改分段选择。
      app.refreshWorksForSegment(silent: true);
      return;
    }
    if (!app.worksSegmentRestored) {
      // 服务是本次运行中稍后才配置的：启动同步不会再次执行，按真实数据补一次默认分段。
      app.setWorksSegment(app.defaultWorksSegment);
    }
    app.refreshWorksForSegment(silent: _hasData(app, app.worksSegment));
  }

  /// 当前分段是否已有可展示数据（有数据时静默刷新，避免闪加载态）。
  bool _hasData(AppState app, String segment) {
    switch (segment) {
      case 'done':
        return app.doneData != null;
      case 'all':
        return app.historyDataLoaded;
      default:
        // 进行中列表是轻量摘要，始终静默刷新。
        return true;
    }
  }

  /// 切换分段：写入 AppState 后按新分段重新拉取真实数据。
  void _onSegmentChanged(int index) {
    final app = AppScope.read(context);
    final segment = switch (index) {
      1 => 'done',
      2 => 'all',
      _ => 'running',
    };
    app.setWorksSegment(segment);
    app.refreshWorksForSegment(silent: _hasData(app, segment));
  }

  /// 下拉刷新：按当前分段重新拉取（失败时保留已展示数据并给出提示）。
  Future<void> _onRefresh() async {
    await AppScope.read(context).refreshWorksForSegment(silent: false);
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('作品'),
        actions: [
          IconButton(
            tooltip: '刷新当前分段',
            onPressed: app.configured
                ? () => app.refreshWorksForSegment(silent: false)
                : null,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: app.configured
            ? RefreshIndicator(
                onRefresh: _onRefresh,
                child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  children: [
                    SegmentedControl(
                      key: const Key('works-segments'),
                      index: _indexOf(app.worksSegment),
                      onChanged: _onSegmentChanged,
                      items: [
                        SegmentedItem(
                          '进行中',
                          badge: app.runningCount > 0 ? app.runningCount : null,
                        ),
                        const SegmentedItem('已完成'),
                        const SegmentedItem('全部记录'),
                      ],
                    ),
                    const SizedBox(height: 12),
                    ..._buildSegment(app),
                  ],
                ),
              )
            : _buildNotConnected(context),
      ),
    );
  }

  /// 按当前分段返回滚动列表内容。
  List<Widget> _buildSegment(AppState app) {
    switch (app.worksSegment) {
      case 'done':
        return _buildDone(app);
      case 'all':
        return const [AllRecordsSegment()];
      default:
        return _buildRunning(app);
    }
  }

  /// 进行中分段：真实进行中任务列表；空态给「去创作」。
  List<Widget> _buildRunning(AppState app) {
    final jobs = app.runningJobs;
    if (jobs.isEmpty) {
      if (app.listError != null) {
        return [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: ErrorView(
              title: '进行中作品加载失败',
              message: app.listError!,
              onRetry: () => app.refreshRunning(silent: false),
            ),
          ),
        ];
      }
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 32),
          child: EmptyState(
            icon: '⏳',
            title: '还没有进行中的作品',
            message: '去创作页描述并生成一个作品，运行中的作品会出现在这里。',
            actions: [
              FilledButton.icon(
                onPressed: () => gotoMainTab(context, 0),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('去创作'),
              ),
            ],
          ),
        ),
      ];
    }
    return [
      if (app.listError != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: InfoBanner(
            text: '刷新失败，当前显示上次数据：${app.listError}',
            icon: '⚠️',
            tone: 'warn',
          ),
        ),
      for (final job in jobs)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: RunningWorkCard(job: job),
        ),
    ];
  }

  /// 已完成分段：真实完成记录分页；空态区分「还有其它记录」与「完全没有作品」。
  List<Widget> _buildDone(AppState app) {
    final data = app.doneData;
    if (data == null) {
      if (app.doneError != null) {
        return [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: ErrorView(
              title: '已完成作品加载失败',
              message: app.doneError!,
              onRetry: () => app.refreshDoneWorks(),
            ),
          ),
        ];
      }
      return const [
        Padding(
          padding: EdgeInsets.symmetric(vertical: 32),
          child: LoadingBlock(text: '已完成作品加载中……', height: 160),
        ),
      ];
    }
    if (data.jobs.isEmpty) {
      return [_buildDoneEmpty(app)];
    }
    return [
      if (app.doneError != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: InfoBanner(
            text: '刷新失败，当前显示上次数据：${app.doneError}',
            icon: '⚠️',
            tone: 'warn',
          ),
        ),
      for (final job in data.jobs)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: WorkSummaryCard(job: job),
        ),
      if (data.pages > 1)
        WorksPager(
          key: const Key('works-pager'),
          data: data,
          onPrev: data.page > 1
              ? () => app.setDoneWorksPage(data.page - 1)
              : null,
          onNext: data.page < data.pages
              ? () => app.setDoneWorksPage(data.page + 1)
              : null,
        ),
    ];
  }

  /// 已完成空态：有其它记录时引导切到全部记录，否则给创作入口。
  Widget _buildDoneEmpty(AppState app) {
    final hasOther = (app.totalJobs ?? 0) > 0 || app.hasRunning;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 32),
      child: EmptyState(
        icon: '🧱',
        title: '还没有已完成的作品',
        message: hasOther
            ? '当前还有进行中或其他生成记录，可以切到「全部记录」查看。'
            : '去创作页描述并生成一个作品，完成后的作品会出现在这里。',
        actions: [
          if (hasOther)
            OutlinedButton(
              onPressed: () => _onSegmentChanged(2),
              child: const Text('查看全部记录'),
            ),
          FilledButton.icon(
            onPressed: () => gotoMainTab(context, 0),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('去创作'),
          ),
        ],
      ),
    );
  }

  /// 未连接服务：显示明确空态与连接入口（不下发任何请求）。
  Widget _buildNotConnected(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 24, 16, 24),
      children: [
        EmptyState(
          icon: '🔌',
          title: '尚未连接服务',
          message: '连接 LEGOGOD 服务后，才能查看进行中、已完成与全部生成记录。',
          actions: [
            FilledButton.icon(
              onPressed: () => openServicePage(context),
              icon: const Icon(Icons.link, size: 18),
              label: const Text('去连接'),
            ),
          ],
        ),
      ],
    );
  }
}
