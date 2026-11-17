// 作品详情页组件测试：
// - 首屏可见 3D 成品（Key('work-3d')）与「开始拼装」主按钮；
// - 核心规格最多 3 项（零件数 / 层数 / 配色数，Key('work-specs')）；
// - 降级交付显示简短警告并可按需展开真实原因（Key('work-warning')）；
// - 「更多」菜单含原始需求、作品信息、再次生成、生成记录、分享与导出；
// - 技术 ID（job_id / run_id）不出现在主视图。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/pages/work/work_detail_page.dart';
import 'package:legogod_app/three_d/lego_3d_view.dart';
import 'package:legogod_app/ui/widgets/common.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

void main() {
  testWidgets('首屏：3D 成品、开始拼装、最多 3 项核心规格，技术 ID 不在主视图', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const WorkDetailPage(jobId: 'done-1')));
    await tester.pumpAndSettle();

    expect(find.text('作品'), findsOneWidget);
    // 3D 成品真实渲染（CustomPainter，无平台依赖）。
    expect(find.byKey(const Key('work-3d')), findsOneWidget);
    expect(find.byType(Lego3DView), findsOneWidget);
    // 底部固定主按钮「开始拼装」。
    expect(find.byKey(const Key('work-start-assembly')), findsOneWidget);
    expect(find.text('开始拼装'), findsOneWidget);

    // 核心规格最多 3 项，且为真实产物统计（6 块 / 3 层 / 3 种配色）。
    final specsFinder = find.byKey(const Key('work-specs'));
    expect(specsFinder, findsOneWidget);
    final specs = tester.widget<FactChips>(specsFinder);
    expect(specs.facts.length, 3);
    expect(specs.facts.map((fact) => fact.label).toList(),
        <String>['零件数', '层数', '配色数']);
    expect(specs.facts[0].value, '6 块');
    expect(specs.facts[1].value, '3 层');
    expect(specs.facts[2].value, '3 种');

    // 次要操作入口。
    expect(find.byKey(const Key('work-part-list')), findsOneWidget);
    expect(find.byKey(const Key('work-share-export')), findsOneWidget);

    // 技术 ID 不在主视图。
    expect(find.textContaining('job_id'), findsNothing);
    expect(find.textContaining('run_id'), findsNothing);
    expect(find.textContaining('model_path'), findsNothing);

    // 「更多」菜单包含五项。
    await tester.tap(find.byKey(const Key('work-more')));
    await tester.pumpAndSettle();
    expect(find.text('原始需求'), findsOneWidget);
    expect(find.text('作品信息'), findsOneWidget);
    expect(find.text('再次生成'), findsOneWidget);
    expect(find.text('生成记录'), findsOneWidget);
    expect(find.text('分享与导出'), findsWidgets);
    // 关闭菜单，避免弹出层影响后续清理。
    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();
    expect(find.text('原始需求'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('降级交付：显示简短警告，点击「展开原因」后可见真实降级原因', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['degraded-1'] = testJobDetailJson(
      id: 'degraded-1',
      outcome: 'fidelity_degraded',
      result: testResultJson(
        outcome: 'fidelity_degraded',
        degradedReason: '视觉评分不足（整体 6.2/10）',
      ),
    );
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(
        wrapApp(app, const WorkDetailPage(jobId: 'degraded-1')));
    await tester.pumpAndSettle();

    // 警告摘要位于 3D 与规格下方（列表懒构建）：滚动到可见后断言。
    await reveal(tester, find.text('作品已生成，视觉评审未完全通过'));
    expect(find.byKey(const Key('work-warning')), findsOneWidget);
    expect(find.text('作品已生成，视觉评审未完全通过'), findsOneWidget);
    // 默认收起：完整原因不可见。
    expect(find.textContaining('降级原因：视觉评分不足'), findsNothing);
    expect(find.text('展开原因'), findsWidgets);

    await tester.tap(find.text('展开原因'));
    await tester.pumpAndSettle();
    expect(find.textContaining('降级原因：视觉评分不足'), findsOneWidget);
    expect(find.text('收起原因'), findsWidgets);

    await disposePage(tester);
  });
}
