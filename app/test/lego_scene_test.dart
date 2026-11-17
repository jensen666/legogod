// 场景层单元测试：真实契约数据 → Lego3DScene 的数量 / 颜色 / 几何 / 告警 / 步骤语义。
import 'package:flutter_test/flutter_test.dart';

import 'package:legogod_app/models/artifacts.dart';
import 'package:legogod_app/models/design.dart';
import 'package:legogod_app/models/part.dart';
import 'package:legogod_app/three_d/lego_scene.dart';

import 'lego_test_fixtures.dart';

void main() {
  group('设计稿场景', () {
    test('体素数量与颜色映射来自 palette/chars/colorRows', () {
      final scene = LegoSceneBuilder.design(draft: fixtureDesign());
      expect(scene.kind, LegoSceneKind.design);
      expect(scene.meshes.length, 4);
      expect(scene.isEmpty, isFalse);
      expect(scene.stepCount, 0);
      expect(scene.bounds.isEmpty, isFalse);
      // (0,0,0) 的 colorRows 为 'A'，chars['A']='蓝色' → palette 命中 #0055BF
      expect(scene.meshes[0].color, 0xFF0055BF);
      // (1,0,0) 的 colorRows 为 '.'，回退层设计色「红色」 → #C91A09
      expect(scene.meshes[1].color, 0xFFC91A09);
      expect(scene.meshes[0].kind, LegoMeshKind.voxel);
      expect(scene.meshes[0].label, '蓝色');
    });

    test('未知颜色名回退中性灰且不崩溃', () {
      final draft = DesignDraft.fromJson(<String, Object?>{
        'layers': <Map<String, Object?>>[
          <String, Object?>{
            'y': 0,
            'rows': <String>['#'],
            'color': '不存在的颜色',
          },
        ],
        'palette': <String, String>{},
        'chars': <String, String>{},
        'stamp': 's1',
      });
      final scene = LegoSceneBuilder.design(draft: draft);
      expect(scene.meshes.length, 1);
      expect(scene.meshes.single.color, 0xFFA0A5A9);
    });

    test('空设计稿：isEmpty 为真、写入 warning、包围盒为空', () {
      final draft = DesignDraft.fromJson(<String, Object?>{
        'layers': <Object?>[],
        'palette': <String, String>{},
        'chars': <String, String>{},
        'stamp': 'empty',
      });
      final scene = LegoSceneBuilder.design(draft: draft);
      expect(scene.isEmpty, isTrue);
      expect(scene.meshes, isEmpty);
      expect(scene.bounds.isEmpty, isTrue);
      expect(scene.warnings, contains('设计稿还没有体素'));
    });
  });

  group('目标模型场景', () {
    test('步骤数量、零件颜色、层高与网格尺寸符合 Web viewer 语义', () {
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      expect(scene.kind, LegoSceneKind.model);
      expect(scene.meshes.length, 6);
      expect(scene.stepCount, 6);
      expect(scene.warnings, isEmpty);
      expect(scene.baseplate, isNotNull);
      expect(scene.ghostMeshes, isEmpty);
      // 第 1 步 2×2 红砖：颜色与包围盒
      final first = scene.meshes[0];
      expect(first.color, 0xFFC91A09);
      expect(first.partId, 'B2x2_RED');
      expect(first.center.y, closeTo(legoLayerHeight / 2, 1e-6));
      expect(first.bounds.min.x, closeTo(0, 1e-6));
      expect(first.bounds.max.x, closeTo(2, 1e-6));
      expect(first.bounds.min.z, closeTo(0, 1e-6));
      expect(first.bounds.max.z, closeTo(2, 1e-6));
      // 第 3 步在 y=1 层：几何整体抬高 1.2（砖体上表面 = 2.4）
      expect(scene.meshes[2].bounds.min.y, closeTo(legoLayerHeight, 1e-6));
      expect(
        scene.meshes[2].bounds.max.y,
        closeTo(legoLayerHeight * 2 + legoStudHeight, 1e-6),
      );
    });

    test('凸点只在未被上层覆盖的顶面显示', () {
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      // 第 1 步上方（y=1）被第 3 步完全覆盖 → 无凸点，只剩 12 个三角面的长方体
      expect(scene.meshes[0].faceCount, 12);
      // 第 2 步同样被第 4 步覆盖
      expect(scene.meshes[1].faceCount, 12);
      // 隔离场景：没有上层覆盖时 2×2 砖有 4 个凸点（每个 18 个三角面）
      final isolated = singleStepModel(
        fixtureBrick(
          id: 'B2x2_RED',
          name: '2x2 砖',
          w: 2,
          d: 2,
          hex: fixtureRedHex,
          colorName: '红色',
        ),
        w: 2,
        d: 2,
      );
      expect(isolated.meshes.single.faceCount, 12 + 4 * 18);
    });

    test('斜坡几何：正斜坡为斜楔、反斜坡顶部平且底面斜挑', () {
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      final normalSlope = scene.meshes.firstWhere(
        (mesh) => mesh.partId == 'SLOPE1_XP',
      );
      expect(normalSlope.kind, LegoMeshKind.slope);
      expect(normalSlope.faceCount, 12); // hasStuds=false → 6 个四边形 = 12 个三角面
      // 正斜坡 '/'：高边在 +x，斜面法线朝 -x/+y
      expect(
        hasFaceNormal(normalSlope, (nx, ny, nz) => nx < -0.4 && ny > 0.5),
        isTrue,
      );
      // 低端高度 = 0.35H，高端满高
      expect(normalSlope.bounds.min.y, closeTo(legoLayerHeight * 2, 1e-6));
      expect(normalSlope.bounds.max.y, closeTo(legoLayerHeight * 3, 1e-6));

      final inverseSlope = scene.meshes.firstWhere(
        (mesh) => mesh.partId == 'SLOPE1_INV',
      );
      expect(inverseSlope.faceCount, 10); // 反斜坡 5 个四边形 = 10 个三角面
      // 反斜坡 'b'：顶部平（法线 +y），底面斜挑（法线朝 +x/-y）
      expect(hasFaceNormal(inverseSlope, (nx, ny, nz) => ny > 0.99), isTrue);
      expect(
        hasFaceNormal(inverseSlope, (nx, ny, nz) => nx > 0.4 && ny < -0.4),
        isTrue,
      );
    });

    test('斜坡方向字符映射与 web/viewer.js 一致', () {
      const positiveExpectations =
          <String, bool Function(double, double, double)>{
            '/': _positiveXm,
            r'\': _positiveXp,
            '^': _positiveZp,
            'v': _positiveZm,
          };
      positiveExpectations.forEach((char, matcher) {
        final part = fixtureSlope(
          id: 'SLOPE_${char.codeUnitAt(0)}',
          name: '正斜坡 $char',
          slope: char,
          w: 1,
          d: 1,
        );
        final scene = singleStepModel(part, w: 1, d: 1);
        expect(
          hasFaceNormal(scene.meshes.single, matcher),
          isTrue,
          reason: '正斜坡字符 $char 的斜面朝向不符合 Web 映射',
        );
      });

      const inverseExpectations =
          <String, bool Function(double, double, double)>{
            'b': _inverseXp,
            'd': _inverseXm,
            'p': _inverseZp,
            'q': _inverseZm,
          };
      inverseExpectations.forEach((char, matcher) {
        final part = fixtureSlope(
          id: 'ISLOPE_${char.codeUnitAt(0)}',
          name: '反斜坡 $char',
          slope: char,
          w: 1,
          d: 1,
        );
        final scene = singleStepModel(part, w: 1, d: 1);
        expect(
          hasFaceNormal(scene.meshes.single, matcher),
          isTrue,
          reason: '反斜坡字符 $char 的底面朝向不符合 Web 映射',
        );
      });
    });

    test('rotate 90° 时 studMask 按 Web 语义交换 (i,j)', () {
      final part = fixtureSlope(
        id: 'SLOPE2_XP',
        name: '2 格正斜坡(/ 高端在东)',
        slope: '/',
        w: 2,
        d: 1,
        hasStuds: true,
        studMask: <List<int>>[
          <int>[1, 0],
        ],
      );
      final catalog = PartsCatalog(<Part>[part]);
      final plain = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: singleStepSolution(piece: 'SLOPE2_XP', w: 2, d: 1),
        parts: catalog,
      ).meshes.single;
      // 未旋转：掩码 (1,0) 满格单元在 x∈[1,2]、z∈[0,1]
      expect(hasHorizontalTopAt(plain, 1.5, 0.5), isTrue);
      expect(hasHorizontalTopAt(plain, 0.5, 0.5), isFalse);

      final rotated = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: singleStepSolution(
          piece: 'SLOPE2_XP',
          w: 1,
          d: 2,
          rotate: true,
        ),
        parts: catalog,
      ).meshes.single;
      // 旋转后掩码 (1,0) → (0,1)：满格单元在 x∈[0,1]、z∈[1,2]
      expect(hasHorizontalTopAt(rotated, 0.5, 1.5), isTrue);
      expect(hasHorizontalTopAt(rotated, 0.5, 0.5), isFalse);
    });

    test('未知零件写 warning 并跳过，不崩溃', () {
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': false,
        'steps': <Map<String, Object?>>[
          fixtureStepJson(
            step: 1,
            layer: 0,
            piece: 'NOT_IN_CATALOG',
            x: 0,
            z: 0,
            w: 2,
            d: 2,
          ),
          fixtureStepJson(
            step: 2,
            layer: 0,
            piece: 'B2x2_RED',
            x: 0,
            z: 0,
            w: 2,
            d: 2,
          ),
        ],
        'usage': <String, int>{'NOT_IN_CATALOG': 1, 'B2x2_RED': 1},
      });
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: solution,
        parts: fixtureParts(),
      );
      expect(scene.meshes.length, 1);
      expect(scene.meshes.single.partId, 'B2x2_RED');
      expect(scene.warnings.length, 1);
      expect(scene.warnings.single, contains('不在零件目录中'));
      expect(scene.warnings.single, contains('NOT_IN_CATALOG'));
    });

    test('越界 / 非法尺寸步骤写 warning 并跳过', () {
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': false,
        'steps': <Map<String, Object?>>[
          fixtureStepJson(
            step: 1,
            layer: 0,
            piece: 'B2x2_RED',
            x: 10,
            z: 0,
            w: 2,
            d: 2,
          ),
          fixtureStepJson(
            step: 2,
            layer: 0,
            piece: 'B2x2_RED',
            x: 0,
            z: 0,
            w: 0,
            d: 2,
          ),
          fixtureStepJson(
            step: 3,
            layer: -1,
            piece: 'B2x2_RED',
            x: 0,
            z: 0,
            w: 2,
            d: 2,
          ),
        ],
        'usage': <String, int>{},
      });
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: solution,
        parts: fixtureParts(),
      );
      expect(scene.meshes, isEmpty);
      expect(scene.warnings.length, 3);
      expect(scene.warnings[0], contains('越界'));
      expect(scene.warnings[1], contains('尺寸非法'));
      expect(scene.warnings[2], contains('层号非法'));
      // 空实体场景仍然有底板，可正常取景
      expect(scene.isEmpty, isTrue);
      expect(scene.baseplate, isNotNull);
      expect(scene.bounds.isEmpty, isFalse);
    });

    test('空方案不崩溃：isEmpty、stepCount=0、无 ghost', () {
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': true,
        'steps': <Object?>[],
        'usage': <String, int>{},
      });
      final scene = LegoSceneBuilder.model(
        model: fixtureModel(),
        solution: solution,
        parts: fixtureParts(),
      );
      expect(scene.isEmpty, isTrue);
      expect(scene.stepCount, 0);
      expect(scene.meshes, isEmpty);
      expect(scene.ghostMeshes, isEmpty);
      expect(scene.visibleMeshCountAt(null), 0);
      expect(scene.visibleMeshCountAt(0), 0);
    });
  });

  group('拼装模拟场景', () {
    test('子组件成员 dockStep 统一到子组件扣合完成步', () {
      final scene = LegoSceneBuilder.assembly(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      expect(scene.kind, LegoSceneKind.assembly);
      expect(scene.meshes.length, 6);
      expect(
        <int>[for (final mesh in scene.meshes) mesh.dockStep],
        <int>[1, 2, 4, 4, 5, 6],
      );
      expect(scene.stepCount, 6);
      expect(scene.warnings, isEmpty);
    });

    test('ghost 为目标体素半透明方块且数量与模型体素一致', () {
      final scene = LegoSceneBuilder.assembly(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      expect(scene.ghostMeshes.length, 19); // 8 + 8 + 3 个体素
      final alpha =
          (scene.ghostMeshes.first.geometry.faceColors.first >> 24) & 0xFF;
      expect(alpha, greaterThan(10));
      expect(alpha, lessThan(80));
      expect(scene.ghostMeshes.first.color, legoGhostColor);
    });

    test('visibleMeshCountAt 按 dockStep 过滤，0 时只剩底板与 ghost', () {
      final scene = LegoSceneBuilder.assembly(
        model: fixtureModel(),
        solution: fixtureSolution(),
        parts: fixtureParts(),
      );
      expect(scene.visibleMeshCountAt(null), 6);
      expect(scene.visibleMeshCountAt(0), 0);
      expect(scene.visibleMeshCountAt(1), 1);
      expect(scene.visibleMeshCountAt(2), 2);
      // 第 3 步属于子组件（dockStep=4），直到第 4 步才整组出现
      expect(scene.visibleMeshCountAt(3), 2);
      expect(scene.visibleMeshCountAt(4), 4);
      expect(scene.visibleMeshCountAt(5), 5);
      expect(scene.visibleMeshCountAt(6), 6);
    });

    test('空模型 + 空方案：无崩溃、无 ghost', () {
      final emptyModel = ModelData.fromJson(<String, Object?>{
        'grid': <String, Object?>{'w': 0, 'd': 0},
        'layers': <Object?>[],
      });
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': true,
        'steps': <Object?>[],
        'usage': <String, int>{},
      });
      final scene = LegoSceneBuilder.assembly(
        model: emptyModel,
        solution: solution,
        parts: PartsCatalog.empty,
      );
      expect(scene.isEmpty, isTrue);
      expect(scene.ghostMeshes, isEmpty);
      expect(scene.bounds.isEmpty, isFalse); // 兜底底板
    });
  });

  group('零件库场景', () {
    test('只展示本方案实际用到的零件，按用量降序且最多 14 个', () {
      final scene = LegoSceneBuilder.partsRow(
        parts: fixtureParts().parts,
        solution: fixtureSolution(),
      );
      expect(scene.kind, LegoSceneKind.partsRow);
      expect(
        <String>[for (final mesh in scene.meshes) mesh.partId],
        <String>['B2x2_RED', 'B2x2_WHITE', 'SLOPE1_XP', 'SLOPE1_INV'],
      );
      // 样品沿 +x 排一行，间距 = 零件宽 + 1.7
      expect(scene.meshes[0].center.x, lessThan(scene.meshes[1].center.x));
      expect(
        scene.meshes[1].center.x - scene.meshes[0].center.x,
        closeTo(2 + 1.7, 1e-6),
      );
      expect(scene.stepCount, 0);
    });

    test('超过 14 个用量零件时只取前 14 个', () {
      final parts = <Part>[
        for (var i = 0; i < 20; i++)
          fixtureBrick(
            id: 'B1x1_C$i',
            name: '1x1 砖 $i',
            w: 1,
            d: 1,
            hex: fixtureWhiteHex,
            colorName: '白色',
          ),
      ];
      final usage = <String, int>{
        for (var i = 0; i < 20; i++) 'B1x1_C$i': 20 - i,
      };
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': true,
        'steps': <Object?>[],
        'usage': usage,
      });
      final scene = LegoSceneBuilder.partsRow(parts: parts, solution: solution);
      expect(scene.meshes.length, LegoSceneBuilder.maxPartSamples);
      expect(scene.meshes.first.partId, 'B1x1_C0');
      expect(scene.meshes[13].partId, 'B1x1_C13');
    });

    test('方案未使用任何零件时：空场景 + warning', () {
      final solution = SolutionData.fromJson(<String, Object?>{
        'valid': true,
        'steps': <Object?>[],
        'usage': <String, int>{},
      });
      final scene = LegoSceneBuilder.partsRow(
        parts: fixtureParts().parts,
        solution: solution,
      );
      expect(scene.isEmpty, isTrue);
      expect(scene.warnings.single, contains('没有可展示的零件样品'));
    });

    test('斜坡样品包含斜楔几何', () {
      final scene = LegoSceneBuilder.partsRow(
        parts: fixtureParts().parts,
        solution: fixtureSolution(),
      );
      final slopeSample = scene.meshes.firstWhere(
        (mesh) => mesh.partId == 'SLOPE1_XP',
      );
      expect(slopeSample.kind, LegoMeshKind.partSample);
      expect(
        hasFaceNormal(slopeSample, (nx, ny, nz) => nx < -0.4 && ny > 0.5),
        isTrue,
      );
    });
  });
}

// 斜坡方向断言：面法线方向（与 web/viewer.js 的 SLOPE_DIR / INV_SLOPE_DIR 对应）
bool _positiveXm(double nx, double ny, double nz) => nx < -0.4 && ny > 0.5;
bool _positiveXp(double nx, double ny, double nz) => nx > 0.4 && ny > 0.5;
bool _positiveZp(double nx, double ny, double nz) => nz > 0.4 && ny > 0.5;
bool _positiveZm(double nx, double ny, double nz) => nz < -0.4 && ny > 0.5;
bool _inverseXp(double nx, double ny, double nz) => nx > 0.4 && ny < -0.4;
bool _inverseXm(double nx, double ny, double nz) => nx < -0.4 && ny < -0.4;
bool _inverseZp(double nx, double ny, double nz) => nz > 0.4 && ny < -0.4;
bool _inverseZm(double nx, double ny, double nz) => nz < -0.4 && ny < -0.4;
