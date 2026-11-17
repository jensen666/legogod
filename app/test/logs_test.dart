// 日志展示整理与里程碑单元测试（对应 Web web/logview.js 的同一规则）。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/logs.dart';
import 'package:legogod_app/models/job.dart';

LogEntry entry(String kind, String text, {double ts = 1, String? phase, int? step}) =>
    LogEntry(kind: kind, text: text, ts: ts, phase: phase, step: step);

void main() {
  group('presentLogs', () {
    test('求解器连续明细合并为分组', () {
      final blocks = presentLogs([
        entry('solver', '铺第 1 层', ts: 1),
        entry('solver', '铺第 2 层', ts: 2),
        entry('info', '普通信息', ts: 3),
        entry('solver', '铺第 3 层', ts: 4),
        entry('solver', '铺第 4 层', ts: 5),
      ]);
      expect(blocks.length, 3);
      expect(blocks[0].type, 'solver');
      expect(blocks[0].items.length, 2);
      expect(blocks[1].type, 'line');
      expect(blocks[2].type, 'solver');
      expect(blocks[2].items.length, 2);
    });

    test('阶段事件独立成分隔块', () {
      final blocks = presentLogs([
        entry('phase', '—— 阶段：plan ——', phase: 'plan'),
        entry('info', '模型调用完成'),
      ]);
      expect(blocks[0].type, 'phase');
      expect(blocks[0].entry!.phase, 'plan');
      expect(blocks[1].type, 'line');
    });

    test('已配对 thought 被吸收进思考块标题、空 thought 丢弃', () {
      final blocks = presentLogs([
        entry('thinking', '思考原文', phase: 'plan', ts: 10),
        entry('thought', '中文摘要', phase: 'plan', ts: 11),
        entry('thought', '   ', phase: 'draw', ts: 12),
      ]);
      expect(blocks.length, 1);
      expect(blocks.first.entry!.kind, 'thinking');
      expect(blocks.first.thought, '中文摘要');
    });

    test('未配对的 thought 保留为普通行（非空）', () {
      final blocks = presentLogs([
        entry('thought', '孤立摘要', phase: 'plan'),
      ]);
      expect(blocks.length, 1);
      expect(blocks.first.type, 'line');
      expect(blocks.first.entry!.kind, 'thought');
    });

    test('空日志返回空块列表', () {
      expect(presentLogs(const <LogEntry>[]), isEmpty);
    });
  });

  group('milestoneLogs', () {
    test('只保留关键事件与关键求解事件', () {
      final milestones = milestoneLogs([
        entry('phase', '阶段', phase: 'plan'),
        entry('review', '视觉评审：6 分'),
        entry('solver', '求解成功'),
        entry('solver', '铺砖明细'),
        entry('version', '设计版本 r001 已保存'),
        entry('tool', '求解结束：失败'),
        entry('tool', '普通工具调用'),
        entry('error', '错误'),
        entry('info', '普通信息'),
        entry('thinking', '思考'),
      ]);
      final kinds = milestones.map((e) => e.kind).toList();
      expect(kinds, ['phase', 'review', 'solver', 'version', 'tool', 'error']);
    });

    test('无里程碑时返回空', () {
      expect(milestoneLogs([entry('info', '普通')]), isEmpty);
    });
  });
}
