// 我的 / 零件目录 / 服务连接页组件测试：
// - 我的页五个入口 Key 齐全，点击「生成规则」「诊断与高级」能打开对应页面；
// - 零件目录页统计行、形状分组与坡向（全部库存只在目录页展开）；
// - 服务连接页含服务表单 Key('service-form')。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/pages/mine/mine_page.dart';
import 'package:legogod_app/pages/mine/rules_page.dart';
import 'package:legogod_app/pages/mine/diagnostics_page.dart';
import 'package:legogod_app/pages/mine/service_page.dart';
import 'package:legogod_app/pages/parts/parts_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

void main() {
  testWidgets('我的页：五个入口齐全，生成规则与诊断与高级可打开', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const MinePage()));
    await tester.pumpAndSettle();

    expect(find.text('我的'), findsOneWidget);
    expect(find.text('服务已连接'), findsOneWidget);
    for (final key in <String>[
      'mine-parts',
      'mine-service',
      'mine-rules',
      'mine-diagnostics',
      'mine-about',
    ]) {
      expect(find.byKey(Key(key)), findsOneWidget, reason: '缺少入口 $key');
    }

    // 生成规则：两档模式完整对比 + 真实规则说明。
    await tester.tap(find.byKey(const Key('mine-rules')));
    await tester.pumpAndSettle();
    expect(find.byType(RulesPage), findsOneWidget);
    expect(find.text('两档模式对比'), findsOneWidget);
    expect(find.text('零件与库存'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    // 诊断与高级：诊断摘要、复制诊断日志、调试日志折叠区。
    await tester.tap(find.byKey(const Key('mine-diagnostics')));
    await tester.pumpAndSettle();
    expect(find.byType(DiagnosticsPage), findsOneWidget);
    expect(find.text('诊断摘要'), findsOneWidget);
    expect(find.text('复制诊断日志'), findsOneWidget);
    expect(find.text('调试日志'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await disposePage(tester);
  });

  testWidgets('零件目录页：真实统计行、形状分组与坡向', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const PartsPage()));
    await tester.pumpAndSettle();

    expect(find.text('零件目录'), findsOneWidget);
    // 3 种形状（B2x2 / SLOPE1_XP / SLOPE1_INV）· 4 个变体 · 3 种颜色 · 总库存 300。
    expect(
      find.textContaining('3 种形状 · 4 个「形状×颜色」变体 · 3 种颜色 · 总库存 300 块'),
      findsOneWidget,
    );
    expect(find.text('2x2 砖'), findsOneWidget);
    // 斜坡形状保留坡向差异。
    expect(find.textContaining('坡向 /'), findsOneWidget);

    // 展开形状分组：颜色变体默认只显示颜色与库存。
    await tester.tap(find.text('2x2 砖'));
    await tester.pumpAndSettle();
    expect(find.text('红色'), findsOneWidget);
    expect(find.text('白色'), findsOneWidget);
    expect(find.text('库存 100'), findsWidgets);

    await disposePage(tester);
  });

  testWidgets('服务连接页：连接状态、服务表单与断开入口', (tester) async {
    final backend = TestBackend();
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const ServicePage()));
    await tester.pumpAndSettle();

    expect(find.text('服务连接'), findsOneWidget);
    expect(find.byKey(const Key('service-form')), findsOneWidget);
    expect(find.byKey(const Key('service-url-field')), findsOneWidget);
    expect(find.byKey(const Key('service-token-field')), findsOneWidget);
    expect(find.text('服务地址与令牌'), findsOneWidget);
    expect(find.text('断开服务连接'), findsOneWidget);

    await disposePage(tester);
  });
}
