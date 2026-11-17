// 真实契约形态的测试数据：
// - /api/jobs 摘要与 /api/job/{id} 详情 JSON；
// - model_*.json / solution_*.json 产物 JSON（步骤与零件目录复用 lego_test_fixtures.dart，
//   保证页面测试与 3D/拼装测试使用同一份契约夹具）；
// - 实时设计稿快照、思考日志与评审结果。
// 所有字段均为服务端真实契约字段，不使用演示任务硬编码。
import 'dart:convert';

import 'lego_test_fixtures.dart';
import 'test_backend.dart';

/// 标准需求原文。
const String testJobDesc =
    '一座小城堡：四座角楼、城墙带垛口、正面大门，目标 300 块积木';

/// 思考原文标记（用于断言默认收起/展开可见）。
const String testThinkingMarker = '思考原文标记：先规划四座角楼再连墙体';

/// 思考摘要标记。
const String testThoughtSummary = '先搭四座角楼再连接城墙';

/// 夹具模型文件名。
const String testModelFile = 'model_fixture.json';

/// 夹具方案文件名。
const String testSolutionFile = 'solution_fixture.json';

/// 夹具步骤 Markdown 文件名（URL 会被编码，后端按解码后的文件名匹配）。
const String testStepsMdFile = '步骤.md';

/// 夹具独立 3D 页文件名。
const String testVizFile = 'viz_fixture.html';

/// 步骤 Markdown 原文（原始文件视图断言用）。
const String testStepsMarkdown = '# 拼装步骤\n\n'
    '## 第 1 步\n红色 2x2 砖 x=0..1，z=0..1\n\n'
    '## 第 2 步\n白色 2x2 砖 x=2..3，z=0..1\n\n'
    'RAW_STEPS_MARKER：服务端原始 Markdown\n';

/// 4×2 网格、3 层设计模型：与 [testSolutionJson] 的 6 个步骤逐体素一致
/// （y=0/y=1 各 8 格普通体素，y=2 两个斜面体素）。
Map<String, Object?> testModelJson() {
  return <String, Object?>{
    'name': '夹具小城堡',
    'slug': 'fixture-model',
    'grid': <String, Object?>{'w': 4, 'd': 2},
    'totalVoxels': 18,
    'layers': <Map<String, Object?>>[
      <String, Object?>{
        'y': 0,
        'rows': <String>['####', '####'],
        'module': <String>['车身'],
        'cells': <List<int>>[],
        'count': 8,
      },
      <String, Object?>{
        'y': 1,
        'rows': <String>['####', '####'],
        'module': <String>['车顶'],
        'cells': <List<int>>[],
        'count': 8,
      },
      <String, Object?>{
        'y': 2,
        'rows': <String>['./b.', '....'],
        'module': <String>['装饰'],
        'cells': <List<int>>[],
        'count': 2,
      },
    ],
    'revision': 3,
    'runId': 'run-fixture',
    'hasVoxelColors': true,
  };
}

/// 6 步装配方案（4 块砖 + 正斜坡 + 反斜坡），第 3、4 步属于预拼子组件。
/// [usage] 可替换用量（未知零件 ID 场景）；[validationOk] 控制统一校验结论。
Map<String, Object?> testSolutionJson({
  Map<String, int>? usage,
  bool validationOk = true,
  List<Map<String, Object?>>? subassemblies,
  List<Map<String, Object?>> colorFallbacks = const <Map<String, Object?>>[],
}) {
  return <String, Object?>{
    'model': 'fixture-model',
    'valid': true,
    'attempts': 1,
    'strategy': 'greedy',
    'steps': <Map<String, Object?>>[
      fixtureStepJson(step: 1, layer: 0, piece: 'B2x2_RED', x: 0, z: 0, w: 2, d: 2),
      fixtureStepJson(step: 2, layer: 0, piece: 'B2x2_WHITE', x: 2, z: 0, w: 2, d: 2),
      fixtureStepJson(step: 3, layer: 1, piece: 'B2x2_RED', x: 0, z: 0, w: 2, d: 2),
      fixtureStepJson(step: 4, layer: 1, piece: 'B2x2_WHITE', x: 2, z: 0, w: 2, d: 2),
      fixtureStepJson(step: 5, layer: 2, piece: 'SLOPE1_XP', x: 1, z: 0, w: 1, d: 1),
      fixtureStepJson(step: 6, layer: 2, piece: 'SLOPE1_INV', x: 2, z: 0, w: 1, d: 1, rotate: true),
    ],
    'usage': usage ??
        <String, int>{
          'B2x2_RED': 2,
          'B2x2_WHITE': 2,
          'SLOPE1_XP': 1,
          'SLOPE1_INV': 1,
        },
    'colors': <String, int>{'红色': 2, '白色': 2, '黄色': 2},
    'colorFallbacks': colorFallbacks,
    'subassemblies': subassemblies ??
        <Map<String, Object?>>[
          <String, Object?>{
            'id': 'sub1',
            'bricks': <int>[3, 4],
            'hangingBricks': <int>[],
            'anchorBricks': <int>[],
            'steps': <int>[3, 4],
          },
        ],
    'residualErrors': validationOk ? <String>[] : <String>['覆盖不足：3 个体素未被覆盖'],
    'validation': <String, Object?>{
      'ok': validationOk,
      'summary': validationOk ? '覆盖通过、库存通过、连通通过' : '覆盖未通过',
      'checks': <String, Object?>{
        'coverage': <String, Object?>{
          'ok': validationOk,
          'detail': validationOk ? '18 个体素全部被步骤覆盖' : '覆盖不足：3 个体素未被覆盖',
        },
        'inventory': <String, Object?>{'ok': true, 'detail': '库存满足'},
      },
    },
    'revision': 7,
    'runId': 'run-fixture',
    'modelHash': 'hash-fixture',
    'schemaVersion': 2,
  };
}

/// 实时设计稿快照（真实 palette/chars/colorRows 字段）。
Map<String, Object?> testDesignJson() {
  return <String, Object?>{
    'name': '设计稿夹具',
    'slug': 'design-fixture',
    'grid': <String, Object?>{'w': 3, 'd': 2},
    'layers': <Map<String, Object?>>[
      <String, Object?>{
        'y': 0,
        'rows': <String>['##.', '.#.'],
        'color': '红色',
        'colorRows': <String>['A..', '...'],
      },
      <String, Object?>{
        'y': 1,
        'rows': <String>['...', '.#.'],
        'color': '白色',
        'colorRows': null,
      },
    ],
    'totalVoxels': 4,
    'revision': 5,
    'palette': <String, String>{
      '红色': '#C91A09',
      '白色': '#F4F4F4',
      '蓝色': '#0055BF',
    },
    'chars': <String, String>{'A': '蓝色'},
    'stamp': 'stamp-fixture',
  };
}

/// 视觉评审结果（真实 review 字段）。
Map<String, Object?> testReviewJson({num overall = 8.5}) {
  return <String, Object?>{
    'scores': <String, num>{
      'overall': overall,
      'proportion': 8,
      'features': 9,
      'color': 8,
      'detail': 9,
    },
    'worst_parts': <String>['屋顶'],
    'missing_features': <String>['烟囱'],
    'suggestions': <String>['增加窗户'],
    'keep': <String>['大门'],
  };
}

/// 运行日志（含一轮可配对思考、阶段与结果事件）。
List<Map<String, Object?>> testLogs() {
  return <Map<String, Object?>>[
    <String, Object?>{
      'kind': 'phase',
      'text': '进入造型阶段',
      'ts': 1794717109.0,
      'phase': 'draw',
    },
    <String, Object?>{
      'kind': 'thinking',
      'text': testThinkingMarker,
      'ts': 1794717110.0,
      'phase': 'draw',
      'chars': 24,
    },
    <String, Object?>{
      'kind': 'thought',
      'text': testThoughtSummary,
      'ts': 1794717111.0,
      'phase': 'draw',
    },
    <String, Object?>{'kind': 'result', 'text': '拼装成功', 'ts': 1794717200.0},
  ];
}

/// 任务 result 对象（真实字段：统计、评审、尝试、产物路径）。
Map<String, Object?> testResultJson({
  String outcome = 'fidelity_success',
  bool ok = true,
  String name = '高保真小城堡',
  String? error,
  String? degradedReason,
  List<Map<String, Object?>> failures = const <Map<String, Object?>>[],
  List<Map<String, Object?>>? attemptsDetail,
  Map<String, Object?>? review,
  int pieces = 6,
  int voxels = 18,
  int layers = 3,
  double elapsedSeconds = 120,
  bool includeArtifacts = true,
  String runId = 'run-fixture',
}) {
  return <String, Object?>{
    'ok': ok,
    'outcome': outcome,
    'name': name,
    'pieces': pieces,
    'voxels': voxels,
    'layers': layers,
    'elapsed_s': elapsedSeconds,
    'run_id': runId,
    'colors': <String, int>{'红色': 2, '白色': 2, '黄色': 2},
    'grid': <String, int>{'w': 4, 'd': 2},
    'attempts': attemptsDetail?.length ?? 1,
    'attempts_detail': ?attemptsDetail,
    'review': ?review,
    'error': ?error,
    'degraded_reason': ?degradedReason,
    'failures': failures,
    'model_hash': 'hash-fixture',
    'revision': 2,
    if (includeArtifacts) ...<String, Object?>{
      'model_path': testModelFile,
      'solution_path': testSolutionFile,
      'md_path': testStepsMdFile,
      'viz_file': testVizFile,
    },
  };
}

/// 两次尝试明细（高保真失败 → 快速保底成功），用于生成记录「两次尝试」分组。
List<Map<String, Object?>> testAttemptsDetail() {
  return <Map<String, Object?>>[
    <String, Object?>{
      'mode': 'fidelity',
      'ok': false,
      'run_id': 'run-fidelity',
      'elapsed_s': 60,
      'error': '视觉评审未达标：整体 5.0 / 10',
      'failure': <String, Object?>{'kind': 'review', 'stage': 'review'},
    },
    <String, Object?>{
      'mode': 'fast',
      'ok': true,
      'run_id': 'run-fixture',
      'elapsed_s': 120,
    },
  ];
}

/// 任务详情 JSON（真实契约字段）。
/// - `status` 为 running 时 result/outcome 为空；其余状态默认构造一份 result。
/// - `design`/`thinking`/`progress` 按需传入（生成进度页使用）。
Map<String, Object?> testJobDetailJson({
  required String id,
  String status = 'done',
  String? outcome = 'fidelity_success',
  String outcomeSource = 'result',
  Map<String, Object?>? result,
  String desc = testJobDesc,
  String mode = 'fidelity',
  String? modeSource = 'job',
  String? retryOf,
  Map<String, Object?>? design,
  Map<String, Object?>? thinking,
  Map<String, Object?>? progress,
  Map<String, Object?>? stage,
  List<Map<String, Object?>> logs = const <Map<String, Object?>>[],
  String? live,
}) {
  final running = status == 'running';
  final effectiveOutcome = running ? null : (outcome ?? 'failed');
  final effectiveResult = running
      ? null
      : (result ??
          testResultJson(
            outcome: effectiveOutcome ?? 'failed',
            ok: status == 'done',
            error: status == 'error' ? '结构校验未通过：悬空 3 格' : null,
            failures: status == 'error'
                ? <Map<String, Object?>>[
                    <String, Object?>{'kind': 'structure', 'stage': 'draw'},
                  ]
                : const <Map<String, Object?>>[],
          ));
  return <String, Object?>{
    'id': id,
    'status': status,
    'live': live,
    'logs': logs,
    'result': effectiveResult,
    'desc': desc,
    'startedAt': 1794717108.1,
    'mode': mode,
    'modeSource': modeSource,
    'retryOf': retryOf,
    'outcome': effectiveOutcome,
    'outcomeSource': running ? 'none' : outcomeSource,
    'design': design,
    'progress': progress,
    'stage': stage ??
        (running
            ? <String, Object?>{
                'current': 'solve',
                'seen': <String>['plan', 'draw', 'solve'],
                'revise': 1,
              }
            : <String, Object?>{
                'current': 'artifacts',
                'seen': <String>['plan', 'draw', 'label', 'review', 'solve', 'artifacts'],
                'revise': 0,
              }),
    'views': <String, String>{},
    'thinking': thinking,
  };
}

/// 任务摘要 JSON（/api/jobs 的 jobs/running 项真实契约字段）。
Map<String, Object?> testJobSummaryJson({
  required String id,
  String status = 'done',
  String? name = '已完成小城堡',
  String desc = testJobDesc,
  String mode = 'fast',
  String? modeSource = 'job',
  String? outcome = 'fast_success',
  String? outcomeSource = 'result',
  int? pieces = 6,
  int? layers = 3,
  Map<String, Object?> grid = const <String, Object?>{'w': 4, 'd': 2},
  List<Map<String, Object?>> colors = const <Map<String, Object?>>[],
  String? error,
  double startedAt = 1794717108.1,
}) {
  return <String, Object?>{
    'id': id,
    'status': status,
    'name': name,
    'desc': desc,
    'mode': mode,
    'modeSource': modeSource,
    'outcome': outcome,
    'outcomeSource': outcomeSource,
    'pieces': pieces,
    'layers': layers,
    'grid': grid,
    'colors': colors,
    'error': ?error,
    'startedAt': startedAt,
  };
}

/// 把真实契约零件目录与 model/solution/md/viz 产物挂到测试后端。
void seedStudioArtifacts(TestBackend backend, {Map<String, int>? usage}) {
  backend.partsBody = <String, dynamic>{'parts': fixtureParts().toJson()['parts']};
  backend.files[testModelFile] = jsonEncode(testModelJson());
  backend.files[testSolutionFile] = jsonEncode(testSolutionJson(usage: usage));
  backend.files[testStepsMdFile] = testStepsMarkdown;
  backend.files[testVizFile] = '<!doctype html><title>fixture viz</title>';
}
