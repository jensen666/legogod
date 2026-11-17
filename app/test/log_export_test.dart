// 运行日志 Markdown 导出测试：完整日志全部导出、不因展示折叠丢内容。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/log_export.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/models/result.dart';

void main() {
  test('导出包含全部日志条目与任务信息', () {
    final logs = <LogEntry>[
      const LogEntry(kind: 'phase', text: '—— 阶段：plan ——', ts: 100, phase: 'plan'),
      const LogEntry(kind: 'thinking', text: '思考原文', ts: 101, phase: 'plan', chars: 4),
      const LogEntry(kind: 'solver', text: '铺第 1 层', ts: 102),
      const LogEntry(kind: 'solver', text: '铺第 2 层', ts: 103),
      const LogEntry(kind: 'error', text: '失败原因', ts: 104),
    ];
    final job = JobDetail(
      id: 'abcd1234',
      status: JobStatus.done,
      live: null,
      logs: logs,
      result: ResultData({
        'ok': true,
        'name': '站立小狗',
        'slug': 'standing-puppy',
        'pieces': 80,
        'voxels': 280,
        'attempts': 2,
        'run_id': 'run001',
        'outcome': 'fast_success',
      }),
      desc: '一只站着的小狗',
      startedAt: 10,
      mode: 'fast',
      modeSource: 'job',
      retryOf: null,
      outcome: 'fast_success',
      outcomeSource: 'result',
      design: null,
      progress: null,
      stage: StageInfo.empty,
      views: const <String, String>{},
      thinking: null,
    );
    final markdown = buildRunLogMarkdown(job);
    expect(markdown, contains('# LEGOGOD 运行日志 · 站立小狗'));
    expect(markdown, contains('任务 ID：abcd1234'));
    expect(markdown, contains('run_id：run001'));
    expect(markdown, contains('思考原文'));
    expect(markdown, contains('铺第 1 层'));
    expect(markdown, contains('铺第 2 层'));
    expect(markdown, contains('失败原因'));
    // 每条日志都有时间线标题，折叠合并不会减少导出条目。
    expect('### ['.allMatches(markdown).length, logs.length);
  });

  test('文件名可识别作品且安全', () {
    final job = JobDetail(
      id: 'j1',
      status: JobStatus.error,
      live: null,
      logs: const <LogEntry>[],
      result: ResultData({'ok': false, 'name': '带/斜杠 的名字', 'slug': null}),
      desc: '',
      startedAt: 1,
      mode: 'fast',
      modeSource: 'job',
      retryOf: null,
      outcome: 'failed',
      outcomeSource: 'result',
      design: null,
      progress: null,
      stage: StageInfo.empty,
      views: const <String, String>{},
      thinking: null,
    );
    final name = runLogFileName(job);
    expect(name.endsWith('.md'), isTrue);
    expect(name.contains('/'), isFalse);
    expect(name, contains('带'));
  });
}
