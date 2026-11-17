// 分享与导出面板测试：
// - 打开面板后出现「常用 / 高级文件」分组与五项真实产物入口；
// - 无产物时该行显示不可用原因，点击不进入预览；
// - 「拼装步骤」默认进入结构化可读步骤（共 N 块零件 + 步骤号），
//   点击「查看原始文件」后展示服务端 Markdown 原文（需 MockClient 提供 /files/步骤.md）。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/app_state.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/ui/share_export.dart';
import 'package:legogod_app/ui/structured_steps_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 打开「分享与导出」面板的宿主页面。
Future<void> openExportSheet(
  WidgetTester tester,
  AppState app,
  JobDetail job,
) async {
  await tester.pumpWidget(wrapApp(
    app,
    Scaffold(
      body: Builder(
        builder: (context) => Center(
          child: FilledButton(
            onPressed: () => showShareExportSheet(context, job),
            child: const Text('打开导出面板'),
          ),
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
  await tester.tap(find.text('打开导出面板'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('面板分组与五项产物入口（有真实产物时全部可用）', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    seedJobSnapshot(
        app, testJobDetailJson(id: 'done-1', logs: testLogs()));
    final job = app.jobs['done-1']!.detail!;

    await openExportSheet(tester, app, job);

    expect(find.text('分享与导出'), findsOneWidget);
    expect(find.text('常用'), findsOneWidget);
    expect(find.text('高级文件'), findsOneWidget);
    for (final label in <String>[
      '拼装步骤',
      '独立 3D 页',
      '设计 JSON',
      '方案 JSON',
      '运行日志 Markdown',
    ]) {
      expect(find.text(label), findsOneWidget, reason: '缺少导出项：$label');
    }

    // 关闭面板。
    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();
    expect(find.text('常用'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('无产物：每行显示不可用原因，点击不进入预览', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    final job = JobDetail.fromJson(testJobDetailJson(
      id: 'no-artifacts-1',
      result: testResultJson(
        outcome: 'fast_success',
        includeArtifacts: false,
      ),
    ));

    await openExportSheet(tester, app, job);

    expect(find.text('该任务没有拼装步骤产物'), findsOneWidget);
    expect(find.text('该任务没有独立 3D 页产物'), findsOneWidget);
    expect(find.text('该任务没有设计 JSON 产物'), findsOneWidget);
    expect(find.text('该任务没有方案 JSON 产物'), findsOneWidget);
    expect(find.text('该任务没有保留运行日志'), findsOneWidget);

    // 不可用行点击后不会进入预览页。
    await tester.tap(find.text('拼装步骤'));
    await tester.pumpAndSettle();
    expect(find.byType(StructuredStepsPage), findsNothing);

    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();
    await disposePage(tester);
  });

  testWidgets('拼装步骤：默认结构化视图（共 N 块零件 + 步骤），可切换原始 Markdown 原文', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    seedJobSnapshot(
        app, testJobDetailJson(id: 'done-1', logs: testLogs()));
    final job = app.jobs['done-1']!.detail!;

    await openExportSheet(tester, app, job);
    await tester.tap(find.text('拼装步骤'));
    await tester.pumpAndSettle();

    // 默认结构化可读步骤：汇总行 + 层分组 + 步骤号。
    expect(find.byType(StructuredStepsPage), findsOneWidget);
    expect(find.textContaining('共 6 块零件'), findsOneWidget);
    expect(find.text('拼装步骤'), findsWidgets);
    expect(find.text('1'), findsWidgets);
    expect(find.textContaining('红色 2x2 砖'), findsWidgets);

    // 切换原始文件：展示服务端 Markdown 原文。
    await tester.tap(find.text('查看原始文件'));
    await tester.pumpAndSettle();
    expect(
      find.text('原始文件：服务端「拼装步骤.md」原文（默认视图为结构化步骤）'),
      findsOneWidget,
    );
    expect(selectableTextContaining('RAW_STEPS_MARKER'), findsOneWidget);
    // 可以再切回结构化内容。
    await tester.tap(find.text('查看结构化内容'));
    await tester.pumpAndSettle();
    expect(find.textContaining('共 6 块零件'), findsOneWidget);

    await disposePage(tester);
  });
}
