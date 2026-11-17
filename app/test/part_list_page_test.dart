// 零件清单页组件测试：
// - 本作品真实用量合计与步骤数一致性提示；
// - 未知零件 ID 明确报错（不静默省略）；
// - 「查看全部库存」入口存在，本页不同屏展开全部库存。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/pages/work/part_list_page.dart';
import 'package:legogod_app/pages/parts/parts_page.dart';

import 'test_backend.dart';
import 'test_payloads.dart';

void main() {
  testWidgets('零件清单：用量合计与步骤数一致提示、库存行与「查看全部库存」入口', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(backend);
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const PartListPage(jobId: 'done-1')));
    await tester.pumpAndSettle();

    expect(find.text('零件清单'), findsOneWidget);
    expect(find.byKey(const Key('part-list-open-catalog')), findsOneWidget);
    expect(find.text('本作品用量合计 6 块'), findsOneWidget);
    expect(find.text('与拼装步骤数 6 块一致。'), findsOneWidget);

    // 真实用量行：颜色名 + 零件名 + 尺寸/库存 + 用量。
    expect(find.textContaining('红色 2x2 砖'), findsWidgets);
    expect(find.textContaining('库存 100 块'), findsWidgets);
    expect(find.text('合计'), findsOneWidget);
    expect(find.text('用量 6 块 · 步骤 6 块'), findsOneWidget);

    // 全部库存不在本页展开，仅提供目录入口。
    expect(find.textContaining('全部「形状 × 颜色」库存不在本页展开'), findsOneWidget);
    expect(find.textContaining('种形状 ·'), findsNothing);
    expect(find.byType(PartsPage), findsNothing);

    await disposePage(tester);
  });

  testWidgets('零件清单：未知零件 ID 明确提示，不静默省略', (tester) async {
    final backend = TestBackend();
    seedStudioArtifacts(
      backend,
      usage: <String, int>{
        'B2x2_RED': 2,
        'B2x2_WHITE': 2,
        'SLOPE1_XP': 1,
        'MYSTERY_PIECE': 1,
      },
    );
    backend.jobDetails['done-1'] = testJobDetailJson(id: 'done-1');
    final app = await createTestApp(backend);
    addTearDown(app.dispose);

    await tester.pumpWidget(wrapApp(app, const PartListPage(jobId: 'done-1')));
    await tester.pumpAndSettle();

    expect(find.text('未知零件 ID（零件目录未同步）'), findsOneWidget);
    expect(find.textContaining('MYSTERY_PIECE'), findsOneWidget);
    expect(find.textContaining('方案用量 1 块'), findsOneWidget);
    // 已知零件仍正常展示。
    expect(find.textContaining('红色 2x2 砖'), findsWidgets);

    await disposePage(tester);
  });
}
