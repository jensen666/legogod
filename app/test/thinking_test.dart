// 思考过程配对与展示单元测试（对应 Web web/thinking.js 的同一规则）。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/thinking.dart';
import 'package:legogod_app/models/job.dart';

LogEntry thinking(String text, {String? phase, double ts = 1, int? chars}) => LogEntry(
      kind: 'thinking',
      text: text,
      ts: ts,
      phase: phase,
      chars: chars,
      done: true,
    );

LogEntry thought(String text, {String? phase, double ts = 1.1}) => LogEntry(
      kind: 'thought',
      text: text,
      ts: ts,
      phase: phase,
    );

void main() {
  group('pairThoughtEntries', () {
    test('同一 phase 的下一条 thought 配对到前一条 thinking', () {
      final pairs = pairThoughtEntries([
        thinking('设计思路 A', phase: 'plan'),
        thought('规划摘要', phase: 'plan'),
      ]);
      expect(pairs.length, 1);
      expect(pairs.first.thought, '规划摘要');
      expect(pairs.first.thoughtEntry, isNotNull);
    });

    test('phase 不匹配不配对', () {
      final pairs = pairThoughtEntries([
        thinking('设计思路 A', phase: 'plan'),
        thought('别的阶段摘要', phase: 'draw'),
      ]);
      expect(pairs.length, 1);
      expect(pairs.first.thought, isEmpty);
    });

    test('一个 thought 只配对一次（下一条 thinking 之后重新开始）', () {
      final pairs = pairThoughtEntries([
        thinking('第一轮', phase: 'plan'),
        thought('摘要一', phase: 'plan'),
        thinking('第二轮', phase: 'plan'),
        thought('摘要二', phase: 'plan'),
      ]);
      expect(pairs.length, 2);
      expect(pairs[0].thought, '摘要一');
      expect(pairs[1].thought, '摘要二');
    });

    test('空 thought 不产生摘要', () {
      final pairs = pairThoughtEntries([
        thinking('思路', phase: 'plan'),
        thought('   ', phase: 'plan'),
      ]);
      expect(pairs.first.thought, isEmpty);
    });
  });

  group('pickThinkingTurns', () {
    test('抽取全部回合并携带元信息', () {
      final turns = pickThinkingTurns([
        thinking('第一轮原文', phase: 'plan', chars: 1234, ts: 10),
        thought('规划摘要', phase: 'plan'),
        thinking('第二轮原文', phase: 'draw', chars: 20, ts: 20),
      ]);
      expect(turns.length, 2);
      expect(turns[0].phaseLabel, '规划');
      expect(turns[0].chars, 1234);
      expect(turns[0].metaText, contains('1,234 字'));
      expect(turns[0].thought, '规划摘要');
      expect(turns[1].phaseLabel, '造型');
      expect(turns[1].key, 'tk1');
    });

    test('空正文回合被丢弃', () {
      final turns = pickThinkingTurns([
        thinking('', phase: 'plan'),
        thinking('有内容', phase: 'draw'),
      ]);
      expect(turns.length, 1);
      expect(turns.first.text, '有内容');
    });

    test('截断与未完成标记出现在元信息里', () {
      const entry = LogEntry(
        kind: 'thinking',
        text: '正文',
        ts: 1,
        phase: 'solve',
        chars: 20000,
        truncated: true,
        partial: true,
      );
      final turn = pickThinkingTurns([entry]).first;
      expect(turn.metaText, contains('已截断'));
      expect(turn.metaText, contains('未完成'));
    });
  });

  group('currentThinking', () {
    test('实时通道优先于已落盘回合', () {
      final job = _job(
        thinking: const ThinkingLive(
          phase: 'draw',
          text: '实时内容',
          elapsed: 3,
          done: false,
          partial: false,
          chars: 4,
        ),
        logs: [thinking('历史内容', phase: 'plan')],
      );
      final turn = currentThinking(job)!;
      expect(turn.live, isTrue);
      expect(turn.text, '实时内容');
      expect(turn.phaseLabel, '造型');
    });

    test('无实时通道时取最后一条落盘回合', () {
      final job = _job(logs: [thinking('历史一', phase: 'plan', ts: 1), thinking('历史二', phase: 'draw', ts: 2)]);
      final turn = currentThinking(job)!;
      expect(turn.live, isFalse);
      expect(turn.text, '历史二');
    });

    test('完全没有思考返回 null', () {
      expect(currentThinking(_job()), isNull);
    });
  });
}

JobDetail _job({List<LogEntry> logs = const <LogEntry>[], ThinkingLive? thinking}) {
  return JobDetail(
    id: 'j1',
    status: JobStatus.running,
    live: null,
    logs: logs,
    result: null,
    desc: '需求',
    startedAt: 1,
    mode: 'fast',
    modeSource: 'job',
    retryOf: null,
    outcome: null,
    outcomeSource: 'none',
    design: null,
    progress: null,
    stage: StageInfo.empty,
    views: const <String, String>{},
    thinking: thinking,
  );
}
