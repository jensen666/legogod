// 生成进度页组件测试：
// - 思考面板默认收起，点击展开显示真实原文，且轮询刷新不重置用户展开状态；
// - 进行中显示当前阶段与设计稿区域（Key('progress-design')）；
// - 完成后出现「查看作品」主按钮；
// - 取消入口存在且必须二次确认（确认文案包含「不会再启动快速保底」）；
// - 失败任务显示真实原因与断点阶段。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/pages/progress/generation_progress_page.dart';
import 'package:legogod_app/three_d/lego_3d_view.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 构造进行中的真实快照（含设计稿、求解进度、阶段、实时思考）。
Map<String, Object?> runningDetail({String thinkingText = testThinkingMarker}) {
  return testJobDetailJson(
    id: 'run-1',
    status: 'running',
    design: testDesignJson(),
    thinking: <String, Object?>{
      'phase': 'draw',
      'text': thinkingText,
      'elapsed': 12.5,
      'done': false,
      'partial': true,
      'chars': 400,
    },
    progress: <String, Object?>{'layer': 2, 'total': 3, 'round': 1},
    stage: <String, Object?>{
      'current': 'solve',
      'seen': <String>['plan', 'draw', 'solve'],
      'revise': 1,
    },
  );
}

/// 把任务改成终态，让独立轮询器在下一轮拉取后自然停止（避免测试结束残留定时器）。
Future<void> stopProgressPoller(WidgetTester tester, TestBackend backend) async {
  backend.jobDetails['run-1'] = testJobDetailJson(id: 'run-1');
  await tester.pump(const Duration(milliseconds: 1000));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('进行中：显示当前阶段与设计稿，思考默认收起；展开后轮询刷新不重置展开状态',
      (tester) async {
    final backend = TestBackend();
    backend.jobDetails['run-1'] = runningDetail();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationProgressPage(jobId: 'run-1')));
    await tester.pumpAndSettle();

    expect(find.text('生成进度'), findsOneWidget);
    // 当前阶段：真实阶段「求解」+ 一句阶段说明。
    expect(find.byKey(const Key('progress-stage')), findsOneWidget);
    expect(find.text('求解'), findsOneWidget);
    expect(find.textContaining('正在把设计稿铺成可拼的零件'), findsOneWidget);
    // 设计稿主视觉区域（含真实 3D 设计稿）。
    expect(find.byKey(const Key('progress-design')), findsOneWidget);
    expect(find.byType(Lego3DView), findsOneWidget);

    // 思考默认收起：只有摘要行，不显示原文。
    expect(find.byKey(const Key('thinking-summary')), findsOneWidget);
    expect(find.textContaining('思考原文标记', findRichText: true), findsNothing);

    // 用户展开：显示真实思考原文。
    await tester.tap(find.byKey(const Key('thinking-summary')));
    await tester.pumpAndSettle();
    expect(find.textContaining('思考原文标记', findRichText: true), findsOneWidget);

    // 轮询拿到新快照（思考文本更新、阶段推进）：展开状态不被重置。
    backend.jobDetails['run-1'] = runningDetail(
      thinkingText: '思考原文标记：轮询刷新后仍保持用户展开状态',
    );
    await tester.pump(const Duration(milliseconds: 1000));
    await tester.pumpAndSettle();
    expect(find.textContaining('轮询刷新后仍保持用户展开状态', findRichText: true),
        findsOneWidget);
    expect(find.textContaining('思考原文标记：先规划四座角楼', findRichText: true),
        findsNothing);

    await stopProgressPoller(tester, backend);
    await disposePage(tester);
  });

  testWidgets('完成后出现「查看作品」主按钮，进行中的取消入口消失', (tester) async {
    final backend = TestBackend();
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationProgressPage(jobId: 'done-1')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('progress-view-work')), findsOneWidget);
    expect(find.text('查看作品'), findsOneWidget);
    final viewWork = tester.widget<FilledButton>(
        find.byKey(const Key('progress-view-work')));
    expect(viewWork.onPressed, isNotNull);
    // 完成态不再显示取消任务，也不显示进行中的阶段/设计稿区域。
    expect(find.byKey(const Key('progress-cancel')), findsNothing);
    expect(find.byKey(const Key('progress-design')), findsNothing);

    await disposePage(tester);
  });

  testWidgets('取消任务：入口存在，点击先进入确认弹窗且文案说明不再启动快速保底', (tester) async {
    final backend = TestBackend();
    backend.jobDetails['run-1'] = runningDetail();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationProgressPage(jobId: 'run-1')));
    await tester.pumpAndSettle();

    // 取消按钮在首屏下方（列表懒构建）：滚动到可见后再断言与点击。
    await reveal(tester, find.byKey(const Key('progress-cancel')));
    expect(find.byKey(const Key('progress-cancel')), findsOneWidget);
    await tester.tap(find.byKey(const Key('progress-cancel')));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('取消任务'), findsWidgets);
    expect(find.textContaining('不会再启动快速保底'), findsOneWidget);
    expect(find.text('确认取消'), findsOneWidget);

    // 取消弹窗关闭（不真正提交取消）：任务继续展示真实快照。
    await tester.tap(find.descendant(
      of: find.byType(AlertDialog),
      matching: find.text('取消'),
    ));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('生成进度'), findsOneWidget);

    await stopProgressPoller(tester, backend);
    await disposePage(tester);
  });

  testWidgets('失败任务：显示真实原因与断点阶段，并可按原模式重试', (tester) async {
    final backend = TestBackend();
    backend.jobDetails['failed-1'] = testJobDetailJson(
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
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationProgressPage(jobId: 'failed-1')));
    await tester.pumpAndSettle();

    expect(find.text('生成未完成'), findsOneWidget);
    expect(find.textContaining('结构校验未通过：悬空 3 格'), findsWidgets);
    expect(find.textContaining('断在「造型」阶段'), findsWidgets);
    expect(find.byKey(const Key('progress-retry')), findsOneWidget);
    expect(find.text('携带评审意见重试'), findsOneWidget);

    await disposePage(tester);
  });
}
