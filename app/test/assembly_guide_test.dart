// 拼装指导页组件测试：
// - 模拟 / 分层步骤视图切换；
// - 上一步 / 下一步 / 滑块边界（第 0 步禁用上一步、最终步禁用下一步）；
// - 从分层列表点击某一步后 3D 与当前步骤卡片同步（断言当前步骤数）；
// - 子组件提示「预拼子模块」仅在实际存在时出现；
// - StudioUiState 按任务隔离并可从持久化状态恢复。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/app_state.dart';
import 'package:legogod_app/core/storage.dart';
import 'package:legogod_app/pages/work/assembly_guide_page.dart';
import 'package:legogod_app/three_d/lego_3d_view.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

/// 装配指导页测试底座：两个任务共用同一份真实产物。
Future<AppState> pumpGuide(
  WidgetTester tester,
  TestBackend backend, {
  String jobId = 'jobA',
}) async {
  backend.jobDetails['jobA'] = testJobDetailJson(id: 'jobA');
  backend.jobDetails['jobB'] = testJobDetailJson(id: 'jobB');
  final app = await createTestApp(backend);
  await tester.pumpWidget(wrapApp(app, AssemblyGuidePage(jobId: jobId)));
  await tester.pumpAndSettle();
  return app;
}

/// 当前 3D 视图组件的可见步骤数。
int visibleStepOf(WidgetTester tester) =>
    tester.widget<Lego3DView>(find.byType(Lego3DView)).visibleStep ?? -1;

void main() {
  testWidgets('模拟/分层切换、子模块提示、步数边界与 3D 同步', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await pumpGuide(tester, backend);
    addTearDown(app.dispose);

    expect(find.text('拼装指导'), findsOneWidget);
    expect(find.byKey(const Key('guide-3d')), findsOneWidget);
    expect(find.byKey(const Key('guide-views')), findsOneWidget);
    expect(find.text('模拟'), findsOneWidget);
    expect(find.text('分层步骤'), findsOneWidget);

    // 初始第 0 步：上一步禁用、下一步可用、滑块范围 0..6。
    expect(tester.widget<IconButton>(find.byKey(const Key('guide-prev'))).onPressed,
        isNull);
    expect(tester.widget<IconButton>(find.byKey(const Key('guide-next'))).onPressed,
        isNotNull);
    expect(find.text('0 / 6'), findsOneWidget);
    expect(
        find.text('绿色底板上还没有零件 —— 点击「播放」或拖动滑块，看拼装方案逐块成型。'),
        findsOneWidget);
    final slider = tester.widget<Slider>(find.byKey(const Key('guide-slider')));
    expect(slider.min, 0);
    expect(slider.max, 6);
    expect(slider.divisions, 6);
    expect(slider.value, 0);

    // 夹具方案真实存在预拼子组件：模拟视图显示提示（在首屏下方，需滚动构建）。
    await reveal(tester, find.text('预拼子模块'));
    expect(find.text('预拼子模块'), findsOneWidget);

    // 切到分层步骤：按层分组展示真实步骤，底层默认展开。
    await tester.tap(find.text('分层步骤'));
    await tester.pumpAndSettle();
    expect(find.textContaining('按层查看全部拼装步骤'), findsOneWidget);
    await reveal(tester, find.text('y=0 · 车身 · 2 块'));
    expect(find.text('y=0 · 车身 · 2 块'), findsOneWidget);
    expect(find.byKey(const Key('guide-step-1')), findsOneWidget);
    expect(find.byKey(const Key('guide-step-3')), findsNothing);

    // 展开 y=1 层并点击第 4 步：3D 与当前步骤卡片同步，并切回模拟视图。
    await reveal(tester, find.text('y=1 · 车顶 · 2 块'));
    await tester.tap(find.text('y=1 · 车顶 · 2 块'));
    await tester.pumpAndSettle();
    await reveal(tester, find.byKey(const Key('guide-step-4')));
    await tester.tap(find.byKey(const Key('guide-step-4')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('guide-slider')), findsOneWidget);
    expect(visibleStepOf(tester), 4);
    // 控制行在视图顶部：此时上一步已可用。
    expect(tester.widget<IconButton>(find.byKey(const Key('guide-prev'))).onPressed,
        isNotNull);
    await reveal(tester, find.text('第 4 步'));
    expect(find.text('第 4 步'), findsOneWidget);
    expect(find.text('进度 4 / 6'), findsOneWidget);
    await reveal(tester, find.text('预拼子模块 sub1（整组落位）'));
    expect(find.text('预拼子模块 sub1（整组落位）'), findsWidgets);

    // 走到最终步：滚动回控制行后逐步前进，最终步禁用下一步。
    await reveal(tester, find.byKey(const Key('guide-next')), delta: -200);
    await tester.tap(find.byKey(const Key('guide-next')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('guide-next')));
    await tester.pumpAndSettle();
    expect(visibleStepOf(tester), 6);
    expect(find.text('6 / 6'), findsOneWidget);
    expect(tester.widget<IconButton>(find.byKey(const Key('guide-next'))).onPressed,
        isNull);
    await reveal(tester, find.text('最终步'));
    expect(find.text('最终步'), findsOneWidget);
    await reveal(tester, find.text('完成 6 / 6'));
    expect(find.text('完成 6 / 6'), findsOneWidget);
    expect(find.text('与目标模型逐体素一致 ✅'), findsOneWidget);

    // 重置回第 0 步：上一步再次禁用。
    await reveal(tester, find.byKey(const Key('guide-reset')), delta: -200);
    await tester.tap(find.byKey(const Key('guide-reset')));
    await tester.pumpAndSettle();
    expect(visibleStepOf(tester), 0);
    expect(find.text('0 / 6'), findsOneWidget);
    expect(tester.widget<IconButton>(find.byKey(const Key('guide-prev'))).onPressed,
        isNull);

    await flushDebounce(tester);
    await disposePage(tester);
  });

  testWidgets('StudioUiState 按任务隔离：任务 B 不受任务 A 的步数影响，任务 A 可恢复', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await pumpGuide(tester, backend);
    addTearDown(app.dispose);

    // 任务 A：切到分层步骤并选中第 4 步。
    await tester.tap(find.text('分层步骤'));
    await tester.pumpAndSettle();
    await reveal(tester, find.text('y=1 · 车顶 · 2 块'));
    await tester.tap(find.text('y=1 · 车顶 · 2 块'));
    await tester.pumpAndSettle();
    await reveal(tester, find.byKey(const Key('guide-step-4')));
    await tester.tap(find.byKey(const Key('guide-step-4')));
    await tester.pumpAndSettle();
    await flushDebounce(tester);

    final stateA = app.studioStateOf('jobA');
    expect(stateA.step, 4);
    expect(stateA.tab, 'sim');
    // 任务 B 尚无任何界面状态（默认 sim / 0），不混用任务 A 的步数。
    final stateB = app.studioStateOf('jobB');
    expect(stateB.step, 0);
    expect(stateB.tab, 'sim');
    expect(stateB, isNot(const StudioUiState(tab: 'sim', step: 4)));

    // 切到任务 B：从自己的默认状态开始。
    await tester.pumpWidget(wrapApp(app, const AssemblyGuidePage(jobId: 'jobB')));
    await tester.pumpAndSettle();
    expect(find.text('0 / 6'), findsOneWidget);
    expect(visibleStepOf(tester), 0);
    await flushDebounce(tester);

    // 回到任务 A：按任务恢复第 4 步。
    await tester.pumpWidget(wrapApp(app, const AssemblyGuidePage(jobId: 'jobA')));
    await tester.pumpAndSettle();
    expect(visibleStepOf(tester), 4);
    expect(find.text('进度 4 / 6'), findsOneWidget);
    await flushDebounce(tester);

    await disposePage(tester);
  });
}
