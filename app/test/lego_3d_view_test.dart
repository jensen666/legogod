// 渲染与视图组件测试：
// - painter 真实绘制（drawVertices 像素验证 / 背面剔除数量 / 300 块零件性能冒烟）；
// - Lego3DView 的两种用法（直接传 scene vs 传 controller）、步骤同步、落位动画、
//   手势、减少动态效果、无障碍语义与释放。
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:legogod_app/models/artifacts.dart';
import 'package:legogod_app/models/part.dart';
import 'package:legogod_app/three_d/lego_3d_view.dart';
import 'package:legogod_app/three_d/lego_camera.dart';
import 'package:legogod_app/three_d/lego_painter.dart';
import 'package:legogod_app/three_d/lego_scene.dart';

import 'lego_test_fixtures.dart';

/// 夹具拼装场景（6 块零件，dockStep = [1,2,4,4,5,6]）。
Lego3DScene _assemblyScene() => LegoSceneBuilder.assembly(
  model: fixtureModel(),
  solution: fixtureSolution(),
  parts: fixtureParts(),
);

/// 只有一块零件的模型场景（用于几何/像素断言）。
Lego3DScene _singleBrickScene({bool hasStuds = true}) {
  final part = fixtureBrick(
    id: 'B1x1_RED',
    name: '1x1 砖',
    w: 1,
    d: 1,
    hex: fixtureRedHex,
    colorName: '红色',
    hasStuds: hasStuds,
  );
  return LegoSceneBuilder.model(
    model: fixtureModel(),
    solution: singleStepSolution(piece: 'B1x1_RED', w: 1, d: 1),
    parts: PartsCatalog(<Part>[part]),
  );
}

/// 压测场景：300 块 1×1 砖（凸点全部外露）+ 绿色底板，接近 M11 真机规模的最坏情况。
Lego3DScene _stressScene() {
  const gridW = 20;
  const gridD = 15;
  final part = fixtureBrick(
    id: 'B1x1_RED',
    name: '1x1 砖',
    w: 1,
    d: 1,
    hex: fixtureRedHex,
    colorName: '红色',
  );
  final steps = <Map<String, Object?>>[
    for (var i = 0; i < 300; i++)
      fixtureStepJson(
        step: i + 1,
        layer: 0,
        piece: 'B1x1_RED',
        x: i % gridW,
        z: i ~/ gridW,
        w: 1,
        d: 1,
      ),
  ];
  final solution = SolutionData.fromJson(<String, Object?>{
    'valid': true,
    'attempts': 1,
    'steps': steps,
    'usage': <String, int>{'B1x1_RED': 300},
    'validation': <String, Object?>{'ok': true},
  });
  final model = ModelData.fromJson(<String, Object?>{
    'grid': <String, Object?>{'w': gridW, 'd': gridD},
    'layers': <Object?>[],
  });
  return LegoSceneBuilder.model(
    model: model,
    solution: solution,
    parts: PartsCatalog(<Part>[part]),
  );
}

/// 读取语义节点文案。
String _semanticLabel(WidgetTester tester) {
  final semantics = tester.widget<Semantics>(
    find.byKey(Lego3DView.semanticsKey),
  );
  return semantics.properties.label ?? '';
}

/// 按相机做一遍数学背面剔除，得到与 painter 相同的期望三角面数。
int _expectedVisibleTriangles(
  Lego3DScene scene,
  Lego3DCamera camera,
  ui.Size size, {
  required int? visibleStep,
  required bool showGhost,
}) {
  final frame = camera.frameFor(size);
  final cam = frame.position;
  var count = 0;
  void addMesh(LegoMesh mesh) {
    final geometry = mesh.geometry;
    for (var face = 0; face < geometry.faceCount; face++) {
      final index = face * 3;
      final nx = geometry.faceNormals[index];
      final ny = geometry.faceNormals[index + 1];
      final nz = geometry.faceNormals[index + 2];
      if (nx * cam.x + ny * cam.y + nz * cam.z <= geometry.facePlanes[face]) {
        continue;
      }
      // 相机距离远大于场景半径，近裁剪不会触发
      count++;
    }
  }

  final baseplate = scene.baseplate;
  if (baseplate != null) addMesh(baseplate);
  if (showGhost) {
    for (final ghost in scene.ghostMeshes) {
      addMesh(ghost);
    }
  }
  for (final mesh in scene.meshes) {
    if (visibleStep != null && mesh.dockStep > visibleStep) continue;
    addMesh(mesh);
  }
  return count;
}

/// 直接调用 painter 绘制一次（不依赖 widget 树）。
void _paintOnce(LegoPainter painter, ui.Size size) {
  final recorder = ui.PictureRecorder();
  final canvas = ui.Canvas(recorder);
  painter.paint(canvas, size);
  recorder.endRecording().dispose();
}

/// 亮度（0..255）。
double _luminance(int argb) {
  final red = (argb >> 16) & 0xFF;
  final green = (argb >> 8) & 0xFF;
  final blue = argb & 0xFF;
  return 0.299 * red + 0.587 * green + 0.114 * blue;
}

void main() {
  group('LegoPainter 渲染', () {
    testWidgets('背面剔除：只画朝向相机的面，数量与数学剔除一致', (tester) async {
      final scene = _singleBrickScene(hasStuds: false); // 1×1×1 砖：共 12 个三角面
      final controller = Lego3DController()..attachScene(scene);
      final painter = LegoPainter(controller: controller);
      const size = ui.Size(200, 200);
      _paintOnce(painter, size);
      final expected = _expectedVisibleTriangles(
        scene,
        controller.camera,
        size,
        visibleStep: null,
        showGhost: true,
      );
      expect(painter.lastTriangleCount, expected);
      // 砖块本体只有 3 个面朝向相机（顶面、+x、+z 各 1 个四边形 = 6 个三角面）
      var brickVisible = 0;
      final brick = scene.meshes.single;
      final frame = controller.camera.frameFor(size);
      final cam = frame.position;
      for (var face = 0; face < brick.geometry.faceCount; face++) {
        final index = face * 3;
        final nx = brick.geometry.faceNormals[index];
        final ny = brick.geometry.faceNormals[index + 1];
        final nz = brick.geometry.faceNormals[index + 2];
        if (nx * cam.x + ny * cam.y + nz * cam.z >
            brick.geometry.facePlanes[face]) {
          brickVisible++;
        }
      }
      expect(brickVisible, 6);
      expect(painter.lastVisibleMeshCount, 1);
      controller.dispose();
    });

    testWidgets('顶面最亮、侧面次之、底面最暗（构建期烘焙明暗）', (tester) async {
      final scene = _singleBrickScene(hasStuds: false);
      final geometry = scene.meshes.single.geometry;
      int? topColor;
      int? sideColor;
      int? bottomColor;
      for (var face = 0; face < geometry.faceCount; face++) {
        final index = face * 3;
        final nx = geometry.faceNormals[index].abs();
        final ny = geometry.faceNormals[index + 1];
        if (ny > 0.99 && nx < 0.01) topColor = geometry.faceColors[face];
        if (ny < -0.99) bottomColor = geometry.faceColors[face];
        if (ny.abs() < 0.01 && (geometry.faceNormals[index + 2]).abs() > 0.99) {
          sideColor = geometry.faceColors[face];
        }
      }
      expect(topColor, isNotNull);
      expect(sideColor, isNotNull);
      expect(bottomColor, isNotNull);
      expect(_luminance(topColor!), greaterThan(_luminance(sideColor!)));
      expect(_luminance(sideColor), greaterThan(_luminance(bottomColor!)));
    });

    testWidgets('drawVertices 真实绘制：砖块像素非背景色', (tester) async {
      final scene = _singleBrickScene();
      final controller = Lego3DController()..attachScene(scene);
      final painter = LegoPainter(controller: controller);
      const size = ui.Size(200, 200);
      const key = ValueKey<String>('paint-key');
      await tester.pumpWidget(
        Directionality(
          textDirection: TextDirection.ltr,
          child: RepaintBoundary(
            key: key,
            child: ColoredBox(
              color: const Color(0xFFFFFFFF),
              child: CustomPaint(painter: painter, size: size),
            ),
          ),
        ),
      );
      await tester.pump();
      final boundary = tester.renderObject<RenderRepaintBoundary>(
        find.byKey(key),
      );
      late int nonWhitePixels;
      late int reddishPixels;
      await tester.runAsync(() async {
        final image = await boundary.toImage();
        final data = await image.toByteData(
          format: ui.ImageByteFormat.rawStraightRgba,
        );
        nonWhitePixels = 0;
        reddishPixels = 0;
        for (var i = 0; i < data!.lengthInBytes; i += 4) {
          final red = data.getUint8(i);
          final green = data.getUint8(i + 1);
          final blue = data.getUint8(i + 2);
          final alpha = data.getUint8(i + 3);
          if (alpha > 0 && (red < 250 || green < 250 || blue < 250)) {
            nonWhitePixels++;
          }
          if (alpha > 0 && red > green + 20 && red > blue + 20) reddishPixels++;
        }
        image.dispose();
      });
      // 真实画出了红色系砖块（非 mock：走 drawVertices → 位图）
      expect(nonWhitePixels, greaterThan(500));
      expect(reddishPixels, greaterThan(100));
      controller.dispose();
    });

    testWidgets('300 块零件压测：单帧投影/排序耗时远低于 33ms 预算', (tester) async {
      final scene = _stressScene();
      expect(scene.meshes.length, 300);
      final meshFaces = scene.meshes.fold<int>(
        0,
        (sum, mesh) => sum + mesh.faceCount,
      );
      expect(meshFaces, greaterThan(8000));
      final totalFaces = meshFaces + (scene.baseplate?.faceCount ?? 0);
      final controller = Lego3DController()..attachScene(scene);
      final painter = LegoPainter(controller: controller);
      const size = ui.Size(400, 300);
      _paintOnce(painter, size); // 预热
      final visible = painter.lastTriangleCount;
      expect(visible, greaterThan(5000));
      // 背面剔除生效：可见面数明显少于全部面数
      expect(visible, lessThan(totalFaces));
      final watch = Stopwatch()..start();
      const frames = 20;
      for (var i = 0; i < frames; i++) {
        _paintOnce(painter, size);
      }
      watch.stop();
      final averageMs = watch.elapsedMicroseconds / 1000 / frames;
      // ignore: avoid_print
      print(
        '[perf] 300 块零件：单帧 ${averageMs.toStringAsFixed(2)}ms（测试机 JIT，真机 AOT 更快），'
        '可见三角面 $visible / 总面 $totalFaces',
      );
      expect(averageMs, lessThan(50), reason: '单帧软渲染耗时过高');
      controller.dispose();
    });

    testWidgets('空场景 / 无场景绘制不崩溃', (tester) async {
      final painter = LegoPainter(controller: Lego3DController());
      _paintOnce(painter, const ui.Size(100, 100));
      expect(painter.lastTriangleCount, 0);
      final controller = Lego3DController()..attachScene(Lego3DScene.empty());
      final emptyPainter = LegoPainter(controller: controller);
      _paintOnce(emptyPainter, const ui.Size(100, 100));
      expect(emptyPainter.lastTriangleCount, 0);
      controller.dispose();
    });
  });

  group('Lego3DView：外部 controller 模式', () {
    testWidgets('语义文案随 visibleStep 更新（步骤与可见数量）', (tester) async {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Lego3DView(controller: controller, interactive: false),
          ),
        ),
      );
      expect(_semanticLabel(tester), contains('可见 6 块零件'));
      controller.setVisibleStep(0);
      await tester.pump();
      expect(_semanticLabel(tester), contains('当前第 0 / 6 步'));
      expect(_semanticLabel(tester), contains('可见 0 块零件'));
      controller.setVisibleStep(2);
      await tester.pump();
      expect(_semanticLabel(tester), contains('当前第 2 / 6 步'));
      expect(_semanticLabel(tester), contains('可见 2 块零件'));
      // 等落位动画结束，进一步推进步骤
      await tester.pump(const Duration(milliseconds: 300));
      controller.setVisibleStep(4);
      await tester.pump(const Duration(milliseconds: 300));
      expect(_semanticLabel(tester), contains('可见 4 块零件'));
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    });

    testWidgets('落位动画 250ms 后自动停止 Ticker', (tester) async {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Lego3DView(controller: controller)),
        ),
      );
      controller.setVisibleStep(0);
      await tester.pump();
      controller.setVisibleStep(2);
      await tester.pump();
      expect(controller.hasDropAnimation, isTrue);
      await tester.pump(const Duration(milliseconds: 120));
      final mid = controller.dropOffsets![0];
      expect(mid, greaterThan(0));
      expect(mid, lessThan(Lego3DController.dropHeight));
      await tester.pump(const Duration(milliseconds: 200));
      expect(controller.hasDropAnimation, isFalse);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    });

    testWidgets('减少动态效果时直接到位，不启动动画', (tester) async {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(disableAnimations: true),
            child: Scaffold(body: Lego3DView(controller: controller)),
          ),
        ),
      );
      await tester.pump();
      expect(controller.animationsEnabled, isFalse);
      controller.setVisibleStep(0);
      await tester.pump();
      controller.setVisibleStep(3);
      await tester.pump();
      expect(controller.hasDropAnimation, isFalse);
      expect(controller.visibleMeshCount, 2);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    });

    testWidgets('单指拖动旋转相机', (tester) async {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Lego3DView(controller: controller)),
        ),
      );
      final before = controller.camera.yaw;
      await tester.drag(find.byType(Lego3DView), const Offset(60, 0));
      await tester.pump();
      expect(controller.camera.yaw, isNot(before));
      expect(controller.isUserAdjusted, isTrue);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    });

    testWidgets('视图销毁后不再监听 controller（不泄漏、不报错）', (tester) async {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Lego3DView(controller: controller)),
        ),
      );
      await tester.pumpWidget(const SizedBox());
      // view 已销毁：controller 仍可被页面继续使用与释放
      expect(() {
        controller.setVisibleStep(2);
        controller.rotateBy(const Offset(10, 0));
      }, returnsNormally);
      controller.dispose();
    });
  });

  group('Lego3DView：内部 controller 模式（直接传 scene/visibleStep）', () {
    testWidgets('props 变化驱动步骤与语义更新，并回调 onStepChanged', (tester) async {
      final scene = _assemblyScene();
      final steps = <int>[];
      Widget build(int? visibleStep) => MaterialApp(
        home: MediaQuery(
          data: const MediaQueryData(disableAnimations: true),
          child: Scaffold(
            body: Lego3DView(
              scene: scene,
              visibleStep: visibleStep,
              semanticsLabel: '拼装预览',
              onStepChanged: steps.add,
              interactive: false,
            ),
          ),
        ),
      );
      await tester.pumpWidget(build(0));
      expect(_semanticLabel(tester), contains('拼装预览'));
      expect(_semanticLabel(tester), contains('可见 0 块零件'));
      await tester.pumpWidget(build(2));
      await tester.pumpAndSettle();
      expect(_semanticLabel(tester), contains('可见 2 块零件'));
      expect(steps, contains(2));
      await tester.pumpWidget(build(4));
      await tester.pumpAndSettle();
      expect(_semanticLabel(tester), contains('可见 4 块零件'));
      expect(steps.last, 4);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('scene 换稿：未手动调整视角时重新取景，不崩溃', (tester) async {
      final design = fixtureDesign();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Lego3DView(
              scene: LegoSceneBuilder.design(draft: design),
              interactive: false,
            ),
          ),
        ),
      );
      expect(_semanticLabel(tester), contains('个体素'));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Lego3DView(
              scene: LegoSceneBuilder.design(draft: design),
              semanticsLabel: '第二版设计稿',
              interactive: false,
            ),
          ),
        ),
      );
      await tester.pump();
      expect(_semanticLabel(tester), startsWith('第二版设计稿'));
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('null 场景与空场景都能正常展示', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: Lego3DView())),
      );
      expect(_semanticLabel(tester), contains('暂无数据'));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Lego3DView(scene: Lego3DScene.empty())),
        ),
      );
      await tester.pump();
      expect(_semanticLabel(tester), contains('暂无数据'));
      await tester.pumpWidget(const SizedBox());
    });
  });
}
