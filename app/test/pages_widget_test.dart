// 创作页组件测试：
// 首屏「想拼什么？」与示例、模式分段切换、空白需求拦截、主按钮文案、无实时舞台、
// 模式说明弹层、生成规则默认收起、草稿与模式恢复。
// 同时保留首次连接引导与通用状态组件的回归覆盖（原 pages_widget_test 的职责迁移）。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/app.dart';
import 'package:legogod_app/core/format.dart';
import 'package:legogod_app/pages/create/create_page.dart';
import 'package:legogod_app/ui/widgets/common.dart';

import 'test_backend.dart';

void main() {
  testWidgets('首次启动且未配置服务：显示连接引导，不展示虚构任务或作品内容', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend, configure: false);
    addTearDown(app.dispose);
    await tester.pumpWidget(LegogodApp(state: app));
    await tester.pumpAndSettle();

    expect(find.text('首次连接设置'), findsOneWidget);
    expect(find.byKey(const Key('service-url-field')), findsOneWidget);
    expect(find.byKey(const Key('service-token-field')), findsOneWidget);
    expect(find.byKey(const Key('service-save-button')), findsOneWidget);
    // 未连接时不出现任何作品/任务/零件内容。
    expect(find.text('想拼什么？'), findsNothing);
    expect(find.text('历史任务'), findsNothing);
    expect(find.text('我的'), findsNothing);
  });

  testWidgets('首次连接：非法地址与非回环缺令牌在提交前本地拦截，不发请求', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend, configure: false);
    addTearDown(app.dispose);
    await tester.pumpWidget(LegogodApp(state: app));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('service-url-field')), 'ftp://bad');
    await tester.tap(find.text('测试连接'));
    await tester.pumpAndSettle();
    expect(find.textContaining('协议只支持 http 或 https'), findsOneWidget);

    await tester.enterText(
        find.byKey(const Key('service-url-field')), '192.168.0.2:8600');
    await tester.tap(find.text('测试连接'));
    await tester.pumpAndSettle();
    expect(find.textContaining('非回环服务必须配置访问令牌'), findsOneWidget);
    // 本地校验失败，不应下发健康检查请求。
    expect(backend.healthCalls, 0);
  });

  testWidgets('创作页首屏：需求卡、三个示例、模式分段、主按钮「生成作品」且无实时舞台', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    // AppBar 标题「创作」，设置入口已迁移到「我的」。
    expect(find.text('创作'), findsOneWidget);
    expect(find.text('想拼什么？'), findsOneWidget);
    expect(find.byKey(const Key('requirement-input')), findsOneWidget);
    for (final example in examplePrompts) {
      expect(find.text(example[0]), findsOneWidget, reason: '示例 chip：${example[0]}');
    }

    // 模式分段：快速 / 高保真。
    final segment = find.byKey(const Key('mode-segment'));
    expect(find.descendant(of: segment, matching: find.text('快速')), findsOneWidget);
    expect(find.descendant(of: segment, matching: find.text('高保真')), findsOneWidget);
    expect(app.draftMode, 'fast');
    expect(find.text(fastModeLine), findsOneWidget);

    // 主按钮文案「生成作品」；旧文案「开始拼装」不再出现。
    expect(find.byKey(const Key('start-build-button')), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '生成作品'), findsOneWidget);
    expect(find.text('开始拼装'), findsNothing);

    // 创作页不再内嵌实时舞台：没有「生成详情」/「取消任务」。
    expect(find.text('生成详情'), findsNothing);
    expect(find.text('取消任务'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('示例 chip 填充完整需求并同步 AppState 草稿', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('垂耳小狗'));
    await tester.pumpAndSettle();

    expect(app.draftDesc, contains('一只站着的小狗'));
    final field = tester.widget<TextField>(find.byKey(const Key('requirement-input')));
    expect(field.controller!.text, contains('一只站着的小狗'));
    // 草稿落盘去抖 600ms：触发后确认真实持久化。
    await flushDebounce(tester);
    expect(app.storage.draft?['desc'], contains('一只站着的小狗'));

    await disposePage(tester);
  });

  testWidgets('模式分段切换：快速 ↔ 高保真，模式说明文案随真实模式更新', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    final segment = find.byKey(const Key('mode-segment'));
    await tester.tap(find.descendant(of: segment, matching: find.text('高保真')));
    await tester.pumpAndSettle();
    expect(app.draftMode, 'fidelity');
    expect(find.text(fidelityModeLine), findsOneWidget);
    expect(find.text(fastModeLine), findsNothing);
    final control =
        tester.widget<SegmentedControl>(find.byType(SegmentedControl));
    expect(control.index, 1);

    await tester.tap(find.descendant(of: segment, matching: find.text('快速')));
    await tester.pumpAndSettle();
    expect(app.draftMode, 'fast');
    expect(find.text(fastModeLine), findsOneWidget);

    await disposePage(tester);
  });

  testWidgets('模式说明弹层：打开可见两档完整对比文案，可关闭', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('mode-help')));
    await tester.pumpAndSettle();

    expect(find.textContaining('快速：跳过视觉评审与视觉修订'), findsOneWidget);
    expect(find.textContaining('高保真：在快速基础上追加多视角视觉评审'), findsOneWidget);

    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(find.textContaining('高保真：在快速基础上追加多视角视觉评审'), findsNothing);

    await disposePage(tester);
  });

  testWidgets('空白需求提交被本地拦截，且不发起创建任务请求', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('start-build-button')));
    await tester.pumpAndSettle();

    expect(find.textContaining('请先描述想拼的作品'), findsOneWidget);
    expect(backend.buildCalls, 0);
    // 拦截后主按钮仍是「生成作品」，没有进入提交态。
    expect(find.text('生成作品'), findsOneWidget);

    await disposePage(tester);
  });

  testWidgets('生成规则默认收起，点击后展开真实规则全文', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    expect(find.text('生成规则'), findsOneWidget);
    expect(find.textContaining('两档生成模式：快速跳过视觉评审'), findsNothing);

    await tester.tap(find.text('生成规则'));
    await tester.pumpAndSettle();
    expect(find.textContaining('两档生成模式：快速跳过视觉评审'), findsOneWidget);

    await disposePage(tester);
  });

  testWidgets('草稿与模式从本地存储恢复：启动即回填需求与分段', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(
      backend,
      prefs: <String, Object>{
        'legogod.v1.draft': jsonEncode(<String, Object?>{
          'desc': '恢复的需求草稿：一只垂耳小狗',
          'mode': 'fidelity',
        }),
      },
    );
    addTearDown(app.dispose);

    expect(app.draftDesc, contains('恢复的需求草稿'));
    expect(app.draftMode, 'fidelity');
    await tester.pumpWidget(wrapApp(app, const CreatePage()));
    await tester.pumpAndSettle();

    expect(find.textContaining('恢复的需求草稿'), findsOneWidget);
    expect(find.text(fidelityModeLine), findsOneWidget);
    final control = tester.widget<SegmentedControl>(find.byType(SegmentedControl));
    expect(control.index, 1);

    await disposePage(tester);
  });

  testWidgets('通用状态组件：图标 + 文字，不只依赖颜色', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: Column(
          children: [
            StatusTag(
              meta: OutcomeMeta(
                text: '快速成功',
                icon: '✅',
                tone: 'ok',
                neutral: false,
              ),
            ),
            ModeChip(mode: 'fast'),
            ModeChip(mode: 'fidelity', modeSource: 'job'),
            EmptyState(icon: '🧱', title: '空态标题', message: '空态说明'),
          ],
        ),
      ),
    ));
    expect(find.text('快速成功'), findsOneWidget);
    expect(find.text('✅'), findsOneWidget);
    expect(find.text('快速'), findsOneWidget);
    expect(find.text('高保真'), findsOneWidget);
    expect(find.text('空态标题'), findsOneWidget);
  });
}
