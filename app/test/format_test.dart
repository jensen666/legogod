// 展示文案与状态语义单元测试：模式来源、交付结果来源、阶段、失败原因、评分。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/format.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/models/result.dart';

void main() {
  group('时间/文本格式化', () {
    test('fmtClock', () {
      expect(fmtClock(0), '0分00秒');
      expect(fmtClock(61), '1分01秒');
      expect(fmtClock(-5), '0分00秒');
    });

    test('fmtElapsed 使用给定时刻', () {
      final now = DateTime.fromMillisecondsSinceEpoch(1000000);
      expect(fmtElapsed(985, now: now), '0分15秒');
      expect(fmtElapsed(null), '—');
    });

    test('shortDesc 折叠空白并截断', () {
      expect(shortDesc('  一只\n\n小狗  ', 10), '一只 小狗');
      expect(shortDesc('abcdefghij', 5), 'abcde…');
      expect(shortDesc(''), '');
    });
  });

  group('模式语义', () {
    test('modeLabel/modeBadgeText', () {
      expect(modeLabel('fast'), '快速');
      expect(modeLabel('fidelity'), '高保真');
      expect(modeLabel('unknown'), '未记录');
      expect(modeBadgeText('fast'), '快速');
      expect(modeBadgeText(''), isNull);
    });

    test('modeDisplay 区分未记录回退', () {
      expect(modeDisplay('fidelity', ModeSource.defaultValue),
          '未记录（重试按高保真处理）');
      expect(modeDisplay('fidelity', ModeSource.job), '高保真');
      expect(modeDisplay('fast', ModeSource.result), '快速');
    });

    test('modeSourceHint 四种来源', () {
      expect(modeSourceHint(ModeSource.job), contains('任务字段'));
      expect(modeSourceHint(ModeSource.result), contains('兼容补取'));
      expect(modeSourceHint(ModeSource.runRecord), contains('兼容补取'));
      expect(modeSourceHint(ModeSource.defaultValue), contains('未记录'));
    });

    test('retryLabel 快速不承诺评审继承', () {
      expect(retryLabel('fast'), '按快速模式重试');
      expect(retryLabel('fidelity'), '携带评审意见重试');
    });
  });

  group('交付结果语义', () {
    test('显式结果使用原语义', () {
      final meta = outcomeMeta('fidelity_success', outcomeSource: 'result');
      expect(meta.text, '高保真成功');
      expect(meta.neutral, isFalse);
    });

    test('兼容推导使用中性文案并说明来源', () {
      final meta = outcomeMeta('fast_success', outcomeSource: 'derived');
      expect(meta.text, '生成成功');
      expect(meta.neutral, isTrue);
      expect(meta.note, contains('兼容推导'));
      final degraded = outcomeMeta('fidelity_degraded', outcomeSource: 'derived');
      expect(degraded.text, contains('评审异常'));
    });

    test('无记录明确标注', () {
      final meta = outcomeMeta(null, outcomeSource: 'none');
      expect(meta.text, '无交付记录');
      expect(meta.neutral, isTrue);
    });

    test('未知枚举不崩溃', () {
      final meta = outcomeMeta('something_new', outcomeSource: 'result');
      expect(meta.text, contains('未知'));
    });

    test('快速成功不显示 0 分说明', () {
      expect(fastNoReviewText, contains('未进行视觉评审'));
      expect(fastNoReviewText, contains('没有视觉评分'));
    });
  });

  group('阶段与失败原因', () {
    test('阶段中文名与叙述', () {
      expect(phaseLabel('plan'), '规划');
      expect(phaseLabel('solve'), '求解');
      expect(phaseLabel('custom_phase'), 'custom_phase');
      expect(phaseBlurb('draw'), contains('彩色体素'));
      expect(phaseLabel(null), '');
    });

    test('failureInfo 优先使用 result.failure.stage', () {
      final job = JobDetail(
        id: 'j1',
        status: JobStatus.error,
        live: null,
        logs: const <LogEntry>[],
        result: ResultData({
          'ok': false,
          'error': '覆盖不足',
          'failures': [
            {'kind': 'structure', 'stage': 'draw'}
          ],
        }),
        desc: '测试需求',
        startedAt: 1,
        mode: 'fast',
        modeSource: 'job',
        retryOf: null,
        outcome: 'failed',
        outcomeSource: 'result',
        design: null,
        progress: null,
        stage: const StageInfo(current: 'solve', seen: <String>[], revise: 0),
        views: const <String, String>{},
        thinking: null,
      );
      final info = failureInfo(job);
      expect(info.reason, '覆盖不足');
      expect(info.stage, 'draw');
      expect(info.stageLabel, '造型');
    });

    test('取消任务原因回退真实文案', () {
      final job = JobDetail(
        id: 'j2',
        status: JobStatus.cancelled,
        live: null,
        logs: const <LogEntry>[],
        result: null,
        desc: '',
        startedAt: 1,
        mode: 'fast',
        modeSource: 'job',
        retryOf: null,
        outcome: 'cancelled',
        outcomeSource: 'result',
        design: null,
        progress: null,
        stage: StageInfo.empty,
        views: const <String, String>{},
        thinking: null,
      );
      expect(failureInfo(job).reason, '已由用户取消');
    });
  });

  group('尝试摘要', () {
    test('成功尝试不显示未知原因', () {
      const attempt = AttemptData(
        mode: 'fast',
        ok: true,
        runId: 'r1',
        elapsedSeconds: 12.5,
        error: null,
        failureKind: null,
        failureStage: null,
      );
      final text = attemptSummary(attempt);
      expect(text, contains('成功'));
      expect(text, contains('run_id r1'));
      expect(text, isNot(contains('未知原因')));
    });

    test('失败尝试保留真实类别与原因', () {
      const attempt = AttemptData(
        mode: 'fidelity',
        ok: false,
        runId: null,
        elapsedSeconds: null,
        error: '视觉评审不达标',
        failureKind: 'visual',
        failureStage: 'review',
      );
      final text = attemptSummary(attempt);
      expect(text, contains('失败类别 visual'));
      expect(text, contains('视觉评审不达标'));
    });
  });
}
