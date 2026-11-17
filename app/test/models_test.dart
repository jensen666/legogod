// 数据模型防御性解析测试：真实 API 契约字段、旧记录缺字段、类型异常都不能让页面崩溃，
// 并且 modeSource/outcomeSource 必须与显式记录/兼容推导准确对应。
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/models/artifacts.dart';
import 'package:legogod_app/models/design.dart';
import 'package:legogod_app/models/job.dart';
import 'package:legogod_app/models/part.dart';
import 'package:legogod_app/models/result.dart';

void main() {
  group('JobSummary', () {
    test('解析真实摘要字段（含来源字段）', () {
      final summary = JobSummary.fromJson({
        'id': '45a2b3dc',
        'status': 'done',
        'name': '两层灰色小塔楼',
        'slug': 'two-story-tower',
        'pieces': 94,
        'desc': '一座两层小塔楼',
        'error': null,
        'mode': 'fast',
        'modeSource': 'result',
        'retryOf': null,
        'outcome': 'fast_success',
        'outcomeSource': 'derived',
        'startedAt': 1794717108.1,
        'grid': {'w': 10, 'd': 10},
        'layers': 12,
        'colors': [
          {'name': '深灰', 'count': 56, 'hex': '#6C6E68', 'share': 0.6},
        ],
      });
      expect(summary.id, '45a2b3dc');
      expect(summary.displayName, '两层灰色小塔楼');
      expect(summary.mode, 'fast');
      expect(summary.modeSource, 'result');
      expect(summary.outcomeSource, 'derived');
      expect(summary.specText, '10×10 · 94 块 · 12 层');
      expect(summary.colors.length, 1);
      expect(summary.isRunning, isFalse);
    });

    test('旧记录缺字段时安全默认且来源可识别', () {
      final summary = JobSummary.fromJson({
        'id': 'old1',
        'status': 'done',
        'mode': 'fidelity',
      });
      expect(summary.name, isNull);
      expect(summary.pieces, isNull);
      expect(summary.modeSource, isNull);
      expect(summary.outcome, isNull);
      expect(summary.colors, isEmpty);
      expect(summary.mode, 'fidelity');
    });

    test('非法来源值归一为 null（不冒充已知来源）', () {
      final summary = JobSummary.fromJson({
        'id': 'x',
        'status': 'done',
        'modeSource': 'something',
        'outcomeSource': 'magic',
      });
      expect(summary.modeSource, isNull);
      expect(summary.outcomeSource, isNull);
    });

    test('序列化往返保持关键字段', () {
      final summary = JobSummary.fromJson({
        'id': 'a1',
        'status': 'error',
        'mode': 'fast',
        'modeSource': 'job',
        'outcome': 'failed',
        'outcomeSource': 'result',
        'grid': {'w': 4, 'd': 5},
        'layers': 3,
        'colors': [
          {'name': '红色', 'count': 3}
        ],
      });
      final restored = JobSummary.fromJson(jsonDecode(jsonEncode(summary.toJson())));
      expect(restored.id, 'a1');
      expect(restored.gridW, 4);
      expect(restored.layerCount, 3);
      expect(restored.colors.first.name, '红色');
    });
  });

  group('JobDetail', () {
    test('解析详情并优先使用服务端 outcome/outcomeSource', () {
      final detail = JobDetail.fromJson({
        'id': 'j1',
        'status': 'done',
        'live': null,
        'logs': [
          {'kind': 'phase', 'text': '—— 阶段：plan ——', 'ts': 1.2, 'phase': 'plan'},
          {'kind': 'thinking', 'text': '思考', 'ts': 2, 'chars': 2, 'truncated': true},
        ],
        'result': {'ok': true, 'outcome': 'fast_success', 'pieces': 10},
        'desc': '需求原文',
        'startedAt': 100,
        'mode': 'fast',
        'modeSource': 'job',
        'retryOf': 'prev',
        'outcome': 'fast_success',
        'outcomeSource': 'result',
        'design': null,
        'progress': {'layer': 2, 'total': 10, 'round': 1, 'y': 1},
        'stage': {
          'current': 'solve',
          'seen': ['plan', 'draw', 'solve'],
          'revise': 2
        },
        'views': {
          'front': '/views/a_front.png',
          'empty': ''
        },
        'thinking': {'phase': 'draw', 'text': '实时', 'chars': 2},
      });
      expect(detail.logs.length, 2);
      expect(detail.logs[1].isThinking, isTrue);
      expect(detail.logs[0].isPhase, isTrue);
      expect(detail.result!.ok, isTrue);
      expect(detail.outcome, 'fast_success');
      expect(detail.outcomeSource, 'result');
      expect(detail.stage.revise, 2);
      expect(detail.stage.allSeen, ['plan', 'draw', 'solve']);
      expect(detail.progress!.text, contains('正在铺第 2 层'));
      expect(detail.views.keys, ['front']);
      expect(detail.thinking!.isUsable, isTrue);
      expect(detail.retryOf, 'prev');
    });

    test('结果里带 outcome 而顶层缺失时仍可展示', () {
      final detail = JobDetail.fromJson({
        'id': 'j2',
        'status': 'done',
        'logs': [],
        'result': {'ok': true, 'outcome': 'fidelity_degraded'},
        'mode': 'fidelity',
        'stage': {},
        'views': null,
      });
      expect(detail.outcome, 'fidelity_degraded');
      expect(detail.views, isEmpty);
      expect(detail.stage.current, isNull);
    });

    test('序列化往返保持日志与状态', () {
      final detail = JobDetail.fromJson({
        'id': 'j3',
        'status': 'cancelled',
        'logs': [
          {'kind': 'error', 'text': '取消', 'ts': 1}
        ],
        'result': {'ok': false, 'outcome': 'cancelled'},
        'desc': 'x',
        'startedAt': 5,
        'mode': 'fast',
        'outcome': 'cancelled',
        'outcomeSource': 'result',
        'stage': {
          'current': 'draw',
          'seen': ['draw'],
          'revise': 0
        },
        'views': {'iso': '/views/x_iso.png'},
      });
      final raw = jsonDecode(jsonEncode(detail.toJson())) as Map<String, dynamic>;
      final restored = JobDetail.fromJson(raw);
      expect(restored.status, 'cancelled');
      expect(restored.logs.single.text, '取消');
      expect(restored.outcome, 'cancelled');
      expect(restored.views['iso'], '/views/x_iso.png');
    });
  });

  group('ResultData', () {
    test('统计、评审、两次尝试与失败信息', () {
      final result = ResultData({
        'ok': false,
        'outcome': 'fidelity_degraded',
        'pieces': 128,
        'voxels': 1084,
        'layers': 12,
        'elapsed_s': 494.6,
        'run_id': 'run1',
        'attempts': 2,
        'grid': {'w': 12, 'd': 12},
        'colors': {'深灰': 56, '浅灰': 38},
        'review': {
          'scores': {'overall': 6, 'proportion': 4},
          'worst_parts': ['正面门洞'],
        },
        'review_flag': 'review_failed',
        'review_failed': true,
        'degraded_reason': '视觉评审修订后仍未达标',
        'revisionIncomplete': true,
        'revisionIncompleteReason': '视觉修订请求打满',
        'attempts_detail': [
          {'mode': 'fidelity', 'ok': false, 'error': '视觉未达标', 'failure': {'kind': 'visual'}},
          {'mode': 'fast', 'ok': true, 'run_id': 'run2', 'elapsed_s': 40},
        ],
        'run_record': {'mode': 'fidelity', 'desc': '原文'},
        'model_path': 'model_x.json',
        'solution_path': 'solution_x.json',
        'md_path': 'steps_x.md',
        'viz_file': 'lego_x.html',
      });
      expect(result.pieces, 128);
      expect(result.layerCount, 12);
      expect(result.review.overall, 6);
      expect(result.reviewFailed, isTrue);
      expect(result.degradedReason, contains('视觉评审'));
      expect(result.attemptsDetail.length, 2);
      expect(result.attemptsDetail[1].ok, isTrue);
      expect(result.attemptsDetail[0].failureKind, 'visual');
      expect(result.colors.length, 2);
      expect(result.runRecord['mode'], 'fidelity');
      expect(result.revisionIncomplete, isTrue);
      expect(result.inconsistentWith(filePieces: 100, fileVoxels: 1084), isTrue);
      expect(result.inconsistentWith(filePieces: 128, fileVoxels: 1084), isFalse);
    });

    test('缺字段/异常类型不崩溃', () {
      final result = ResultData({'pieces': 'abc', 'layers': [1, 2], 'colors': 'x'});
      expect(result.pieces, isNull);
      expect(result.layerCount, isNull);
      expect(result.colors, isEmpty);
      expect(result.review.overall, isNull);
      expect(result.attemptsDetail, isEmpty);
    });
  });

  group('设计稿 DesignDraft', () {
    test('提取彩色体素与颜色回退', () {
      final design = DesignDraft.fromJson({
        'name': '小狗',
        'grid': {'w': 3, 'd': 2},
        'layers': [
          {
            'y': 0,
            'rows': ['#..', '.##'],
            'colorRows': ['R..', '.K#'],
          }
        ],
        'totalVoxels': 3,
        'palette': {'红色': '#C4281B', '黑色': '#1B1B1B'},
        'chars': {'R': '红色', 'K': '黑色'},
        'stamp': 'abc',
      });
      expect(design.isEmpty, isFalse);
      expect(design.voxelCount, 3);
      final voxels = design.voxels;
      expect(voxels.length, 3);
      expect(voxels[0].colorName, '红色');
      expect(voxels.any((v) => v.colorName == '黑色'), isTrue);
      expect(design.hexOf('红色'), '#C4281B');
      expect(design.hexOf('未知色'), '#A0A5A9');
    });
  });

  group('零件目录', () {
    test('解析、分组、统计与未知 ID', () {
      final catalog = PartsCatalog.fromJson([
        {'id': 'B1x1', 'shape': 'B1x1', 'name': '1x1 砖', 'w': 1, 'd': 1, 'color': '#237841', 'colorName': '绿色', 'count': 2000, 'hasStuds': true},
        {'id': 'B1x1_RED', 'shape': 'B1x1', 'name': '1x1 砖', 'w': 1, 'd': 1, 'color': '#C4281B', 'colorName': '红色', 'count': 10},
        {'id': 'SLOPE_XP', 'shape': 'SLOPE_XP', 'name': '斜坡', 'w': 1, 'd': 1, 'color': '#A0A5A9', 'colorName': '浅灰', 'count': 5, 'hasStuds': false, 'slope': '/'},
      ]);
      expect(catalog.shapeCount, 2);
      expect(catalog.variantCount, 3);
      expect(catalog.colorCount, 3);
      expect(catalog.totalStock, 2015);
      expect(catalog.groups.first.variants.length, 2);
      expect(catalog.partOf('SLOPE_XP')!.isSlope, isTrue);
      expect(catalog.partOf('NOPE'), isNull);
    });

    test('缺失字段使用安全默认', () {
      final part = Part.fromJson({'id': 'X'});
      expect(part.shape, 'X');
      expect(part.w, 1);
      expect(part.hasStuds, isTrue);
      expect(part.hex, '#FF00FF');
    });
  });

  group('模型与方案产物', () {
    test('模型体素（普通 + 斜面）', () {
      final model = ModelData.fromJson({
        'name': '测试',
        'grid': {'w': 2, 'd': 2},
        'totalVoxels': 3,
        'layers': [
          {'y': 0, 'rows': ['#/', '.#'], 'cells': [[0, 0]], 'module': ['底']},
        ],
      });
      expect(model.normalVoxels.length, 2);
      expect(model.slopeVoxels['/']!.length, 1);
      expect(model.allVoxels.length, 3);
    });

    test('方案步骤、用量、子组件与统一校验', () {
      final solution = SolutionData.fromJson({
        'valid': true,
        'attempts': 2,
        'strategy': '精确铺砖',
        'steps': [
          {'step': 1, 'layer': 0, 'piece': 'B2x2', 'x': 0, 'z': 0, 'w': 2, 'd': 2, 'rotate': true},
          {'step': 2, 'layer': 1, 'piece': 'B1x1', 'x': 0, 'z': 0, 'w': 1, 'd': 1},
        ],
        'usage': {'B2x2': 1, 'B1x1': 1},
        'colors': {'红色': 2},
        'colorFallbacks': [
          {'layer': 1, 'target': '紫色', 'used': {'红色': 1}}
        ],
        'subassemblies': [
          {'id': 'sub1', 'bricks': [1], 'steps': [1, 2]}
        ],
        'validation': {
          'ok': true,
          'summary': '覆盖通过、稳定性通过',
          'stability': {'detail': '重心投影落在底层支撑范围内'},
          'checks': {
            'coverage': {'ok': true, 'detail': '覆盖 2/2 体素'}
          },
        },
      });
      expect(solution.stepCount, 2);
      expect(solution.usageTotal, 2);
      expect(solution.usageMatchesSteps, isTrue);
      expect(solution.colorFallbacks.single.text, contains('回退使用 红色×1'));
      expect(solution.subassemblies.single.dockStep, 2);
      expect(solution.validationOk, isTrue);
      expect(solution.validationSummary, contains('覆盖通过'));
      expect(solution.stabilityDetail, contains('重心'));
      expect(solution.validationChecks.single.key, 'coverage');
    });

    test('最终模型与方案逐体素一致性校验', () {
      final model = ModelData.fromJson({
        'grid': {'w': 2, 'd': 2},
        'layers': [
          {'y': 0, 'rows': ['##', '##']}
        ],
      });
      final ok = StudioArtifacts(
        model: model,
        solution: SolutionData.fromJson({
          'steps': [
            {'step': 1, 'layer': 0, 'piece': 'B2x2', 'x': 0, 'z': 0, 'w': 2, 'd': 2}
          ],
          'usage': {'B2x2': 1},
        }),
        parts: PartsCatalog.empty,
      );
      expect(ok.verifyModelSolutionConsistency(), isNull);

      final missing = StudioArtifacts(
        model: model,
        solution: SolutionData.fromJson({
          'steps': [
            {'step': 1, 'layer': 0, 'piece': 'B1x1', 'x': 0, 'z': 0, 'w': 1, 'd': 1}
          ],
          'usage': {'B1x1': 1},
        }),
        parts: PartsCatalog.empty,
      );
      expect(missing.verifyModelSolutionConsistency(), isNotNull);

      final outOfModel = StudioArtifacts(
        model: model,
        solution: SolutionData.fromJson({
          'steps': [
            {'step': 1, 'layer': 3, 'piece': 'B1x1', 'x': 0, 'z': 0, 'w': 1, 'd': 1}
          ],
          'usage': {'B1x1': 1},
        }),
        parts: PartsCatalog.empty,
      );
      expect(outOfModel.verifyModelSolutionConsistency(), contains('不存在'));
    });
  });
}
