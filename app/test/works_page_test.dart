// 作品页组件测试：
// - 进行中 / 已完成 / 全部记录三段 SegmentedControl 切换与三种空态；
// - 进行中卡片有「查看进度」，取消收在次要菜单，不出现平铺的「再次生成 / 重试」；
// - 已完成卡片整卡点击可导航到作品详情；
// - 一页时隐藏分页，多页时显示且第一页「上一页」禁用；
// - 全部记录搜索框 350ms 防抖后才请求服务端（请求带 q），筛选值真实下发。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/pages/work/work_detail_page.dart';
import 'package:legogod_app/pages/works/works_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 点击分段控件里的某个文案。
Future<void> tapSegment(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(
    of: find.byKey(const Key('works-segments')),
    matching: find.text(label),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('三段切换：进行中 / 已完成 / 全部记录各有真实空态', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const WorksPage()));
    await tester.pumpAndSettle();

    expect(find.text('作品'), findsOneWidget);
    expect(find.byKey(const Key('works-segments')), findsOneWidget);
    // 默认进入「进行中」分段（无进行中任务时的真实空态）。
    expect(find.text('还没有进行中的作品'), findsOneWidget);

    await tapSegment(tester, '已完成');
    expect(find.text('还没有已完成的作品'), findsOneWidget);

    await tapSegment(tester, '全部记录');
    expect(find.text('还没有生成记录'), findsOneWidget);

    await flushDebounce(tester);
    await disposePage(tester);
  });

  testWidgets('按分段拉取：单页隐藏分页、多页展示且第一页「上一页」禁用；已完成卡片整卡导航',
      (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');
    backend.jobsResponder = (Uri uri) {
      final status = uri.queryParameters['status'] ?? '';
      if (status == JobStatus.done) {
        return jobsPageBody(
          jobs: <Map<String, Object?>>[
            testJobSummaryJson(id: 'done-1', name: '已完成小城堡'),
          ],
          total: 1,
        );
      }
      return jobsPageBody(
        jobs: <Map<String, Object?>>[
          testJobSummaryJson(id: 'done-1', name: '已完成小城堡'),
          testJobSummaryJson(
            id: 'failed-1',
            name: '失败作品',
            status: 'error',
            outcome: 'failed',
            error: '结构校验未通过：悬空 3 格',
          ),
        ],
        total: 45,
        page: 1,
        pages: 3,
      );
    };
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const WorksPage()));
    await tester.pumpAndSettle();

    // 已完成：服务端仅一页 → 不显示分页栏。
    await tapSegment(tester, '已完成');
    expect(find.byKey(const Key('works-card-done-1')), findsOneWidget);
    expect(find.byKey(const Key('works-pager')), findsNothing);

    // 已完成卡片整卡点击 → 默认落点判定 → 作品详情。
    await tester.tap(find.byKey(const Key('works-card-done-1')));
    await tester.pumpAndSettle();
    expect(find.byType(WorkDetailPage), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    // 全部记录：服务端 3 页 → 显示分页，第一页「上一页」禁用、「下一页」可用。
    await tapSegment(tester, '全部记录');
    expect(find.byKey(const Key('works-pager')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('第 1 / 3 页'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('共 45 条记录'), findsOneWidget);
    final prev = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, '上一页'));
    expect(prev.onPressed, isNull);
    final next = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, '下一页'));
    expect(next.onPressed, isNotNull);

    await flushDebounce(tester);
    await disposePage(tester);
  });

  testWidgets('进行中卡片：有「查看进度」，取消在次要菜单，不出现平铺的再次生成/重试',
      (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const WorksPage()));
    await tester.pumpAndSettle();

    // 注入真实进行中摘要（后端保持空列表，避免测试内启动真实轮询器）。
    app.runningJobs = <JobSummary>[
      JobSummary.fromJson(testJobSummaryJson(
        id: 'run-1',
        status: 'running',
        name: '进行中的城堡',
        outcome: null,
        outcomeSource: null,
        pieces: null,
        layers: null,
        colors: const <Map<String, Object?>>[],
      )),
    ];
    app.notifyListeners();
    await tester.pump();

    expect(find.byKey(const Key('works-card-run-1')), findsOneWidget);
    expect(find.text('查看进度'), findsOneWidget);
    // 列表不再平铺「再次生成 / 重试」，它们只在详情/更多菜单出现。
    expect(find.text('再次生成'), findsNothing);
    expect(find.text('重试'), findsNothing);

    // 取消是次要菜单操作。
    final menuButton = find.byType(PopupMenuButton<String>);
    expect(menuButton, findsOneWidget);
    await tester.tap(menuButton);
    await tester.pumpAndSettle();
    expect(find.text('取消任务'), findsOneWidget);
    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();
    expect(find.text('取消任务'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('全部记录：搜索 350ms 防抖后带 q 请求服务端，筛选值真实下发', (tester) async {
    final backend = TestBackend();
    backend.jobsResponder = (Uri uri) {
      final query = uri.queryParameters['q'] ?? '';
      if (query == '小狗') {
        return jobsPageBody(
          jobs: <Map<String, Object?>>[
            testJobSummaryJson(id: 'search-1', name: '垂耳小狗'),
          ],
          total: 1,
        );
      }
      return jobsPageBody(
        jobs: <Map<String, Object?>>[
          testJobSummaryJson(id: 'other-1', name: '其它作品'),
        ],
        total: 1,
      );
    };
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const WorksPage()));
    await tester.pumpAndSettle();

    await tapSegment(tester, '全部记录');
    expect(find.byKey(const Key('works-search')), findsOneWidget);

    final callsBefore = backend.jobsRequests.length;
    await tester.enterText(find.byKey(const Key('works-search')), '小狗');
    await tester.pump(const Duration(milliseconds: 150));
    // 防抖窗口内不发起搜索请求。
    expect(backend.jobsRequests.length, callsBefore);
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(backend.lastJobsQuery['q'], '小狗');
    expect(find.text('垂耳小狗'), findsOneWidget);

    // 筛选面板默认收在「筛选」入口内，选择后按真实枚举下发。
    expect(find.text('执行状态'), findsNothing);
    await tester.tap(find.byKey(const Key('works-filter')));
    await tester.pumpAndSettle();
    expect(find.text('执行状态'), findsOneWidget);
    expect(find.text('交付结果'), findsOneWidget);
    await tester.tap(find.text('全部状态'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('失败').last);
    await tester.pumpAndSettle();
    expect(backend.lastJobsQuery['status'], 'error');

    await flushDebounce(tester);
    await disposePage(tester);
  });
}
