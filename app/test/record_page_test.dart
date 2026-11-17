// 生成记录页组件测试：
// - 首屏只展开结果横幅（Key('record-banner')），8 个分组默认收起（Key('record-section-*')）；
// - 展开「运行与需求信息」后可见需求原文、任务 ID、run_id；
// - 快速成功显示「未进行视觉评审」而不是 0 分；
// - 失败任务显示真实原因与断点阶段；
// - 技术区有统一导出入口 Key('record-open-export')。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/pages/record/generation_record_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 记录页成功用例：两次尝试 + 真实评审 + 思考/日志，用于覆盖 8 个分组。
Map<String, Object?> recordSuccessDetail() {
  return testJobDetailJson(
    id: 'done-1',
    logs: testLogs(),
    result: testResultJson(
      attemptsDetail: testAttemptsDetail(),
      review: testReviewJson(),
    ),
  );
}

/// 滚动到目标组件（未构建时按方向拖动列表，已构建时确保可见）。
Future<void> scrollTo(
  WidgetTester tester,
  Finder finder, {
  double delta = 300,
}) async {
  final scrollable = find.byType(Scrollable).first;
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(finder, delta, scrollable: scrollable);
  } else {
    await tester.ensureVisible(finder);
  }
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('首屏只展开结果横幅，8 个分组默认收起；展开后可见需求原文/任务 ID/run_id 与技术导出入口',
      (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['done-1'] = recordSuccessDetail();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationRecordPage(jobId: 'done-1')));
    await tester.pumpAndSettle();

    expect(find.text('生成记录'), findsOneWidget);
    // 唯一默认展开的结果横幅。
    expect(find.byKey(const Key('record-banner')), findsOneWidget);
    expect(find.text('高保真成功'), findsWidgets);

    // 8 个分组全部存在（依次向下滚动确认懒加载分组也已构建）。
    const List<String> sectionKeys = <String>[
      'record-section-run',
      'record-section-attempts',
      'record-section-review',
      'record-section-versions',
      'record-section-artifacts',
      'record-section-thinking',
      'record-section-logs',
      'record-section-tech',
    ];
    for (final key in sectionKeys) {
      await scrollTo(tester, find.byKey(Key(key)));
      expect(find.byKey(Key(key)), findsOneWidget, reason: '缺少分组 $key');
    }

    // 默认收起：分组内容未构建（不是只隐藏）。
    expect(find.text('需求原文'), findsNothing);
    expect(find.text('job_id'), findsNothing);
    expect(find.text('评审渲染图'), findsNothing);
    expect(find.textContaining('本次运行没有保留日志'), findsNothing);

    // 展开「运行与需求信息」：需求原文、任务 ID、run_id 可见。
    await scrollTo(tester, find.text('运行与需求信息'), delta: -300);
    await tester.tap(find.text('运行与需求信息'));
    await tester.pumpAndSettle();
    expect(find.text('需求原文'), findsOneWidget);
    expect(find.text('任务 ID'), findsOneWidget);
    expect(find.text('run_id'), findsOneWidget);
    expect(find.text('done-1'), findsOneWidget);
    expect(selectableTextContaining(testJobDesc), findsOneWidget);

    // 展开「技术信息与文件入口」：job_id 与统一导出入口。
    await scrollTo(tester, find.byKey(const Key('record-section-tech')));
    await tester.tap(find.text('技术信息与文件入口'));
    await tester.pumpAndSettle();
    expect(find.text('job_id'), findsOneWidget);
    expect(find.byKey(const Key('record-open-export')), findsOneWidget);
    expect(find.text('分享与导出'), findsWidgets);

    await disposePage(tester);
  });

  testWidgets('快速成功：明确「未进行视觉评审」，不显示 0 分', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['fast-1'] = testJobDetailJson(
      id: 'fast-1',
      mode: 'fast',
      outcome: 'fast_success',
      logs: testLogs(),
      result: testResultJson(outcome: 'fast_success'),
    );
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const GenerationRecordPage(jobId: 'fast-1')));
    await tester.pumpAndSettle();

    // 横幅与评审分组副标题都明确「快速未评审」。
    expect(find.textContaining('快速生成，未进行视觉评审'), findsWidgets);
    expect(find.textContaining('快速任务未进行视觉评审'), findsWidgets);

    await scrollTo(tester, find.text('视觉评审与评审图'));
    await tester.tap(find.text('视觉评审与评审图'));
    await tester.pumpAndSettle();
    expect(find.textContaining('快速生成，未进行视觉评审'), findsWidgets);
    expect(find.text('0/10'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('失败任务：显示真实原因与断点阶段', (tester) async {
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
        wrapApp(app, const GenerationRecordPage(jobId: 'failed-1')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('record-failure')), findsOneWidget);
    expect(find.textContaining('结构校验未通过：悬空 3 格'), findsWidgets);
    expect(find.textContaining('断在「造型」阶段'), findsWidgets);
    expect(find.text('生成失败'), findsWidgets);

    await disposePage(tester);
  });
}
