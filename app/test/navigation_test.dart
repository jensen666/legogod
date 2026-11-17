// 导航与默认落点测试：
// - 底部三个入口（创作 / 作品 / 我的）与「作品」进行中数量角标（0 时隐藏）；
// - 非「创作」Tab 按返回先回创作；RootTabsController 索引切换；
// - landingOf 三分支：进行中→进度、可交付完成→作品、其余（失败/取消/中断/缺产物）→记录；
// - 页面按钮调用 openJobById 后 push 的页面标题符合落点。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/route_nav.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/pages/progress/generation_progress_page.dart';
import 'package:legogod_app/pages/record/generation_record_page.dart';
import 'package:legogod_app/pages/shell/root_shell.dart';
import 'package:legogod_app/pages/shell/root_tabs.dart';
import 'package:legogod_app/pages/work/work_detail_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 落点探针页：只有三个按钮，点击后统一走 route_nav.openJobById。
class _LandingProbe extends StatelessWidget {
  const _LandingProbe();

  static const List<String> ids = <String>['run-1', 'done-1', 'failed-1'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('落点测试')),
      body: Column(
        children: <Widget>[
          for (final id in ids)
            TextButton(
              onPressed: () => unawaited(openJobById(context, id)),
              child: Text('打开 $id'),
            ),
        ],
      ),
    );
  }
}

void main() {
  test('landingOf 三分支：进行中→进度、可交付完成→作品、其余→记录', () {
    // 进行中：无论是否有旧结果，一律进生成进度。
    expect(
      landingOf(JobDetail.fromJson(
          testJobDetailJson(id: 'running-1', status: 'running'))),
      JobLanding.progress,
    );
    // done + result.ok + modelPath + solutionPath → 作品。
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(id: 'done-1'))),
      JobLanding.work,
    );
    // 完成但缺少产物路径 → 记录（不能进作品页白屏）。
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(
        id: 'done-no-artifacts',
        result: testResultJson(includeArtifacts: false),
      ))),
      JobLanding.record,
    );
    // 完成但 result.ok=false → 记录。
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(
        id: 'done-failed',
        result: testResultJson(ok: false, outcome: 'failed'),
      ))),
      JobLanding.record,
    );
    // 失败 / 取消 / 中断 → 记录。
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(
        id: 'error-1',
        status: 'error',
        outcome: 'failed',
        result: testResultJson(ok: false, outcome: 'failed'),
      ))),
      JobLanding.record,
    );
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(
        id: 'cancelled-1',
        status: 'cancelled',
        outcome: 'cancelled',
        result: testResultJson(ok: false, outcome: 'cancelled'),
      ))),
      JobLanding.record,
    );
    expect(
      landingOf(JobDetail.fromJson(testJobDetailJson(
        id: 'interrupted-1',
        status: 'interrupted',
        outcome: 'failed',
        result: testResultJson(ok: false, outcome: 'failed', includeArtifacts: false),
      ))),
      JobLanding.record,
    );
  });

  test('RootTabsController：切换索引并通知，重复选择不重复通知', () {
    final controller = RootTabsController();
    addTearDown(controller.dispose);
    var notifications = 0;
    controller.addListener(() => notifications += 1);

    expect(controller.index, 0);
    controller.select(0);
    expect(notifications, 0);
    controller.select(1);
    expect(controller.index, 1);
    expect(notifications, 1);
    controller.select(2);
    expect(controller.index, 2);
    expect(notifications, 2);
  });

  testWidgets('底部导航：创作/作品/我的三个入口，作品角标随进行中数量显示与隐藏', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const RootShell()));
    await tester.pumpAndSettle();

    final navFinder = find.byType(NavigationBar);
    expect(navFinder, findsOneWidget);
    final nav = tester.widget<NavigationBar>(navFinder);
    expect(nav.destinations.length, 3);
    expect(nav.selectedIndex, 0);
    for (final label in <String>['创作', '作品', '我的']) {
      expect(find.descendant(of: navFinder, matching: find.text(label)),
          findsOneWidget);
    }

    // 无进行中任务：角标隐藏。
    expect(app.runningCount, 0);
    expect(find.byType(Badge), findsNothing);

    // 注入真实进行中摘要：角标显示数量。
    app.runningJobs = <JobSummary>[
      JobSummary.fromJson(testJobSummaryJson(
        id: 'run-1',
        status: 'running',
        outcome: null,
        outcomeSource: null,
        pieces: null,
        layers: null,
        colors: const <Map<String, Object?>>[],
      )),
    ];
    app.notifyListeners();
    await tester.pump();
    expect(find.byType(Badge), findsOneWidget);
    expect(
      find.descendant(of: find.byType(Badge), matching: find.text('1')),
      findsOneWidget,
    );

    // 进行中清零后角标隐藏。
    app.runningJobs = const <JobSummary>[];
    app.notifyListeners();
    await tester.pump();
    expect(find.byType(Badge), findsNothing);

    await disposePage(tester);
  });

  testWidgets('返回规则：非创作 Tab 按返回先回创作，创作 Tab 才允许退出', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const RootShell()));
    await tester.pumpAndSettle();

    final navFinder = find.byType(NavigationBar);
    expect(tester.widget<NavigationBar>(navFinder).selectedIndex, 0);
    // 创作 Tab：PopScope 允许系统返回退出。
    PopScope<dynamic> rootPopScope() =>
        tester.widget<PopScope<dynamic>>(find.byWidgetPredicate(
          (widget) => widget is PopScope,
        ));
    expect(rootPopScope().canPop, isTrue);

    // 切到作品：PopScope 阻止直接退出。
    await tester.tap(
        find.descendant(of: navFinder, matching: find.text('作品')));
    await tester.pumpAndSettle();
    expect(tester.widget<NavigationBar>(navFinder).selectedIndex, 1);
    expect(rootPopScope().canPop, isFalse);

    // 模拟系统返回：先回创作 Tab。
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();
    expect(tester.widget<NavigationBar>(navFinder).selectedIndex, 0);
    expect(rootPopScope().canPop, isTrue);

    // 我的 Tab 同样先回创作。
    await tester.tap(find.descendant(of: navFinder, matching: find.text('我的')));
    await tester.pumpAndSettle();
    expect(tester.widget<NavigationBar>(navFinder).selectedIndex, 2);
    expect(rootPopScope().canPop, isFalse);
    await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();
    expect(tester.widget<NavigationBar>(navFinder).selectedIndex, 0);

    await disposePage(tester);
  });

  testWidgets('openJobById：进行中任务 push 生成进度页（标题「生成进度」）', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    // 本地已有真实快照（进行中），落点判定不依赖网络。
    seedJobSnapshot(
      app,
      testJobDetailJson(
        id: 'run-1',
        status: 'running',
        design: testDesignJson(),
        thinking: <String, Object?>{
          'phase': 'draw',
          'text': testThinkingMarker,
          'elapsed': 12.5,
          'done': false,
          'partial': true,
          'chars': 400,
        },
      ),
    );
    // 页面内部会重新拉取一次详情：返回终态避免持续轮询。
    backend.jobDetails['run-1'] = testJobDetailJson(id: 'run-1');

    await tester.pumpWidget(wrapApp(app, const _LandingProbe()));
    await tester.pumpAndSettle();
    await tester.tap(find.text('打开 run-1'));
    await tester.pumpAndSettle();

    expect(find.byType(GenerationProgressPage), findsOneWidget);
    expect(find.text('生成进度'), findsOneWidget);

    await disposePage(tester);
  });

  testWidgets('openJobById：可交付完成 push 作品详情（标题「作品」）', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    seedJobSnapshot(app, testJobDetailJson(id: 'done-1'));
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');

    await tester.pumpWidget(wrapApp(app, const _LandingProbe()));
    await tester.pumpAndSettle();
    await tester.tap(find.text('打开 done-1'));
    await tester.pumpAndSettle();

    expect(find.byType(WorkDetailPage), findsOneWidget);
    expect(find.text('作品'), findsOneWidget);

    await disposePage(tester);
  });

  testWidgets('openJobById：失败任务 push 生成记录（标题「生成记录」）', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    final failed = testJobDetailJson(
      id: 'failed-1',
      status: 'error',
      outcome: 'failed',
      result: testResultJson(
        ok: false,
        outcome: 'failed',
        error: '结构校验未通过：悬空 3 格',
        failures: <Map<String, Object?>>[
          <String, Object?>{'kind': 'structure', 'stage': 'draw'},
        ],
        includeArtifacts: false,
      ),
    );
    seedJobSnapshot(app, failed);
    backend.jobDetails['failed-1'] = failed;

    await tester.pumpWidget(wrapApp(app, const _LandingProbe()));
    await tester.pumpAndSettle();
    await tester.tap(find.text('打开 failed-1'));
    await tester.pumpAndSettle();

    expect(find.byType(GenerationRecordPage), findsOneWidget);
    expect(find.text('生成记录'), findsOneWidget);
    expect(find.textContaining('断在「造型」阶段'), findsWidgets);

    await disposePage(tester);
  });
}
