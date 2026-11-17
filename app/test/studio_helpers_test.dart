// 3D 工作室展示辅助测试：预拼子组件成组可见、墙面区域名、当前步信息。
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/studio_helpers.dart';
import 'package:legogod_app/models/artifacts.dart';

SolutionData solutionWithSub() => SolutionData.fromJson({
      'steps': [
        for (var i = 1; i <= 5; i++)
          {'step': i, 'layer': i - 1, 'piece': 'B1x1', 'x': 0, 'z': 0, 'w': 1, 'd': 1}
      ],
      'usage': {'B1x1': 5},
      'subassemblies': [
        {
          'id': 'sub1',
          'bricks': [3, 4],
          'steps': [3, 4]
        }
      ],
    });

void main() {
  group('SubAssemblyPlan', () {
    test('子组件成员在扣合完成步前不可见，普通砖按步骤可见', () {
      final plan = SubAssemblyPlan.fromSolution(solutionWithSub());
      expect(plan.subCount, 1);
      // 普通砖：索引 0/1 对应第 1/2 步
      expect(plan.brickVisibleAtStep(0, 0), isFalse);
      expect(plan.brickVisibleAtStep(0, 1), isTrue);
      expect(plan.brickVisibleAtStep(1, 1), isFalse);
      // 子组件成员（索引 2/3，步骤 3/4，扣合完成步 4）：第 3 步仍不可见
      expect(plan.brickVisibleAtStep(2, 3), isFalse);
      expect(plan.brickVisibleAtStep(2, 4), isTrue);
      expect(plan.brickVisibleAtStep(3, 4), isTrue);
      // 普通砖（索引 4，步骤 5）
      expect(plan.brickVisibleAtStep(4, 4), isFalse);
      expect(plan.brickVisibleAtStep(4, 5), isTrue);
    });

    test('成组落位步返回整组方案步骤索引', () {
      final plan = SubAssemblyPlan.fromSolution(solutionWithSub());
      expect(plan.bricksDockingAt(4), [2, 3]);
      expect(plan.bricksDockingAt(3), isEmpty);
      expect(plan.subOfStep[3], 1);
      expect(plan.subOfStep[4], 1);
    });

    test('损坏的子组件数据不崩溃', () {
      final plan = SubAssemblyPlan.fromSolution(SolutionData.fromJson({
        'steps': [
          {'step': 1, 'layer': 0, 'piece': 'B1x1', 'x': 0, 'z': 0, 'w': 1, 'd': 1}
        ],
        'subassemblies': [
          {'id': 'bad', 'steps': [99]}
        ],
      }));
      expect(plan.subCount, 1);
      expect(plan.bricksDockingAt(99), isEmpty);
      expect(plan.brickVisibleAtStep(0, 1), isTrue);
    });
  });

  group('zoneName', () {
    ModelData modelWithModules(List<String> modules) => ModelData.fromJson({
          'grid': {'w': 4, 'd': 4},
          'layers': [
            {'y': 0, 'rows': ['####'], 'module': modules}
          ],
        });

    BrickStep stepAt({required int x, required int z, int w = 1, int d = 1}) =>
        BrickStep.fromJson({
          'step': 1,
          'layer': 0,
          'piece': 'B1x1',
          'x': x,
          'z': z,
          'w': w,
          'd': d,
        });

    test('墙模块按位置细分前后左右与转角', () {
      final model = modelWithModules(['前墙']);
      expect(zoneName(stepAt(x: 1, z: 0), model), '前墙');
      expect(zoneName(stepAt(x: 1, z: 3), model), '后墙');
      expect(zoneName(stepAt(x: 0, z: 1), model), '左墙');
      expect(zoneName(stepAt(x: 3, z: 1), model), '右墙');
      expect(zoneName(stepAt(x: 1, z: 1), model), '墙体');
    });

    test('非墙模块使用模块名，缺模块用「模型」', () {
      expect(zoneName(stepAt(x: 0, z: 0), modelWithModules(['屋顶', '烟囱'])), '屋顶·烟囱');
      expect(zoneName(stepAt(x: 0, z: 0), modelWithModules([])), '模型');
    });
  });

  group('stepInfoOf', () {
    test('子组件步骤带整组落位说明，最后一步标记完成', () {
      final solution = solutionWithSub();
      final model = ModelData.fromJson({
        'grid': {'w': 2, 'd': 2},
        'layers': [
          for (var i = 0; i < 5; i++) {'y': i, 'rows': ['#'], 'module': ['主体']}
        ],
      });
      final plan = SubAssemblyPlan.fromSolution(solution);
      final info = stepInfoOf(
        step: solution.steps[3],
        model: model,
        solution: solution,
        plan: plan,
      );
      expect(info.step, 4);
      expect(info.subLabel, contains('sub1'));
      expect(info.isFinal, isFalse);
      expect(info.rangeText, 'x=0..0，z=0..0');

      final finalInfo = stepInfoOf(
        step: solution.steps.last,
        model: model,
        solution: solution,
        plan: plan,
      );
      expect(finalInfo.isFinal, isTrue);
      expect(finalInfo.subLabel, isEmpty);
    });
  });
}
