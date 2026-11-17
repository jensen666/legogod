// 相机与控制器单元测试：透视投影、边界 clamp、自动取景、换场景保留视角、
// visibleStep 过滤与 250ms 落位动画状态。
import 'dart:math' as math;
import 'dart:ui' show Offset, Size;

import 'package:flutter_test/flutter_test.dart';

import 'package:legogod_app/models/design.dart';
import 'package:legogod_app/three_d/lego_camera.dart';
import 'package:legogod_app/three_d/lego_scene.dart';

import 'lego_test_fixtures.dart';

/// 夹具拼装场景（6 步，dockStep = [1,2,4,4,5,6]）。
Lego3DScene _assemblyScene() => LegoSceneBuilder.assembly(
  model: fixtureModel(),
  solution: fixtureSolution(),
  parts: fixtureParts(),
);

/// 第二份设计稿（网格更大，用于换稿取景断言）。
DesignDraft _biggerDesign() => DesignDraft.fromJson(<String, Object?>{
  'name': '更大的设计稿',
  'grid': <String, Object?>{'w': 8, 'd': 6},
  'layers': <Map<String, Object?>>[
    <String, Object?>{
      'y': 0,
      'rows': <String>['########', '########', '########'],
      'color': '红色',
    },
  ],
  'palette': <String, String>{'红色': '#C91A09'},
  'chars': <String, String>{},
  'stamp': 'bigger',
});

void main() {
  group('透视投影', () {
    test('target 投影到屏幕中心，+x 在右、+y 在上', () {
      final camera = Lego3DCamera(yaw: 0, pitch: 0, distance: 10);
      const viewport = Size(200, 200);
      final center = camera.project(Vec3.zero, viewport);
      expect(center, isNotNull);
      expect(center!.dx, closeTo(100, 1e-6));
      expect(center.dy, closeTo(100, 1e-6));

      final rightPoint = camera.project(const Vec3(1, 0, 0), viewport);
      expect(rightPoint!.dx, greaterThan(100));
      expect(rightPoint.dy, closeTo(100, 1e-6));

      final upPoint = camera.project(const Vec3(0, 1, 0), viewport);
      expect(upPoint!.dy, lessThan(100));
      expect(upPoint.dx, closeTo(100, 1e-6));
    });

    test('相机后方的点投影为 null，视深随距离线性变化', () {
      final camera = Lego3DCamera(yaw: 0, pitch: 0, distance: 10);
      const viewport = Size(200, 200);
      expect(camera.project(const Vec3(0, 0, 20), viewport), isNull);
      final frame = camera.frameFor(viewport);
      expect(frame.depthOf(Vec3.zero), closeTo(10, 1e-6));
      expect(frame.depthOf(const Vec3(0, 0, 1)), closeTo(9, 1e-6));
      // 视口中心与焦距：focal = halfHeight / tan(fov/2)
      expect(
        frame.focalPixels,
        closeTo(100 / math.tan(20 * math.pi / 180), 1e-6),
      );
    });

    test('沿视线方向移动不改变投影横纵坐标（透视中心稳定）', () {
      final camera = Lego3DCamera(yaw: 0.539, pitch: 0.653, distance: 30);
      const viewport = Size(320, 480);
      final frame = camera.frameFor(viewport);
      final target = camera.target;
      final center = frame.project(target);
      expect(center!.dx, closeTo(160, 1e-6));
      expect(center.dy, closeTo(240, 1e-6));
    });
  });

  group('相机边界与操作', () {
    test('pitch clamp 在 [-1.4, 1.4]', () {
      final camera = Lego3DCamera(yaw: 0, pitch: 0, distance: 10);
      camera.rotateBy(const Offset(0, 100000));
      expect(camera.pitch, Lego3DCamera.maxPitch);
      camera.rotateBy(const Offset(0, -200000));
      expect(camera.pitch, Lego3DCamera.minPitch);
    });

    test('单指拖动：水平改 yaw、垂直改 pitch', () {
      final camera = Lego3DCamera(yaw: 0, pitch: 0, distance: 10);
      camera.rotateBy(const Offset(10, 10));
      expect(camera.yaw, closeTo(-10 * Lego3DCamera.yawPerPixel, 1e-9));
      expect(camera.pitch, closeTo(10 * Lego3DCamera.pitchPerPixel, 1e-9));
      // 非法输入被忽略，不产生 NaN
      camera.rotateBy(const Offset(double.nan, 0));
      expect(camera.yaw.isNaN, isFalse);
    });

    test('双指缩放有最小值，非法 scale 被忽略', () {
      final camera = Lego3DCamera(distance: 10);
      camera.applyBoundsLimits(Bounds.empty);
      expect(camera.minDistance, 1.0);
      camera.zoomBy(2);
      expect(camera.distance, closeTo(5, 1e-9));
      camera.zoomBy(1e9);
      expect(camera.distance, camera.minDistance);
      expect(camera.distance, greaterThan(0));
      final before = camera.distance;
      camera.zoomBy(0);
      camera.zoomBy(-1);
      camera.zoomBy(double.nan);
      expect(camera.distance, before);
    });

    test('双指平移让内容跟随手指（右移 → target 左移）', () {
      final camera = Lego3DCamera(yaw: 0, pitch: 0, distance: 10);
      const viewport = Size(200, 200);
      final before = camera.target;
      camera.panBy(const Offset(10, 0), viewport: viewport);
      expect(camera.target.x, lessThan(before.x));
      expect(camera.target.z, closeTo(0, 1e-9));
      camera.panBy(const Offset(0, 10), viewport: viewport);
      expect(camera.target.y, greaterThan(before.y));
    });

    test('fitTo 按包围盒中心取景，resetAngles 恢复默认朝向', () {
      final bounds = Bounds(const Vec3(0, 0, 0), const Vec3(4, 3.6, 2));
      final camera = Lego3DCamera(yaw: 1, pitch: 0.2, distance: 1);
      camera.fitTo(bounds, resetAngles: true);
      expect(camera.target.x, closeTo(2, 1e-9));
      expect(camera.target.y, closeTo(1.8, 1e-9));
      expect(camera.target.z, closeTo(1, 1e-9));
      expect(camera.yaw, Lego3DCamera.defaultYaw);
      expect(camera.pitch, Lego3DCamera.defaultPitch);
      expect(camera.distance, greaterThan(bounds.radius));
      expect(camera.position.length.isFinite, isTrue);
    });

    test('空包围盒取景也不产生 NaN', () {
      final camera = Lego3DCamera(distance: 0.01);
      camera.fitTo(Bounds.empty, resetAngles: true);
      expect(camera.distance.isFinite, isTrue);
      expect(camera.distance, greaterThanOrEqualTo(camera.minDistance));
      expect(camera.target, Vec3.zero);
    });

    test('缩放下限不低于场景包围球半径（相机不会钻进模型）', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      final radius = controller.scene!.bounds.radius;
      controller.zoomBy(1e9);
      expect(controller.camera.distance, greaterThanOrEqualTo(radius));
      expect(controller.camera.position.length.isFinite, isTrue);
      controller.dispose();
    });
  });

  group('控制器：场景与步骤', () {
    test('attachScene 首帧自动取景，visibleStep 默认 null 表示全部可见', () {
      final controller = Lego3DController();
      final scene = _assemblyScene();
      controller.attachScene(scene);
      expect(controller.scene, same(scene));
      expect(controller.visibleStep, isNull);
      expect(controller.visibleMeshCount, 6);
      expect(controller.stepCount, 6);
      expect(controller.camera.target.x, closeTo(scene.bounds.center.x, 1e-9));
      expect(controller.camera.target.y, closeTo(scene.bounds.center.y, 1e-9));
      controller.dispose();
    });

    test('visibleStep 过滤 dockStep 并 clamp 到 stepCount', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.setVisibleStep(0);
      expect(controller.visibleMeshCount, 0);
      controller.setVisibleStep(2);
      expect(controller.visibleMeshCount, 2);
      // 子组件成员 dockStep=4：第 3 步时仍不可见
      controller.setVisibleStep(3);
      expect(controller.visibleMeshCount, 2);
      controller.setVisibleStep(4);
      expect(controller.visibleMeshCount, 4);
      expect(controller.visibleMeshes.length, 4);
      controller.setVisibleStep(999);
      expect(controller.visibleStep, 6);
      expect(controller.visibleMeshCount, 6);
      controller.setVisibleStep(-5);
      expect(controller.visibleStep, 0);
      controller.setVisibleStep(null);
      expect(controller.visibleMeshCount, 6);
      controller.dispose();
    });

    test('visibleStep 增加时对新出现零件做落位动画，到 1 秒结束', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.setVisibleStep(0);
      expect(controller.hasDropAnimation, isFalse); // 初始同步不播动画
      controller.setVisibleStep(2);
      expect(controller.hasDropAnimation, isTrue);
      final offsets = controller.dropOffsets!;
      expect(offsets.length, 6);
      expect(offsets[0], closeTo(Lego3DController.dropHeight, 1e-9));
      expect(offsets[1], closeTo(Lego3DController.dropHeight, 1e-9));
      expect(offsets[2], 0); // dockStep=4 的零件还未出现
      controller.updateDropAnimation(0.5);
      expect(controller.dropOffsets![0], greaterThan(0));
      expect(controller.dropOffsets![0], lessThan(Lego3DController.dropHeight));
      controller.updateDropAnimation(1);
      expect(controller.hasDropAnimation, isFalse);
      expect(controller.dropOffsets, isNull);
      controller.dispose();
    });

    test('减少动态效果（animationsEnabled=false）时直接到位，不播动画', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.animationsEnabled = false;
      controller.setVisibleStep(0);
      controller.setVisibleStep(2);
      expect(controller.visibleMeshCount, 2);
      expect(controller.hasDropAnimation, isFalse);
      // 重新开启后仍可播放
      controller.animationsEnabled = true;
      controller.setVisibleStep(3);
      controller.setVisibleStep(4);
      expect(controller.hasDropAnimation, isTrue);
      controller.dispose();
    });

    test('步骤回退 / attachScene 会取消进行中的动画', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.setVisibleStep(0);
      controller.setVisibleStep(2);
      expect(controller.hasDropAnimation, isTrue);
      controller.setVisibleStep(1); // 回退：立即取消，不播动画
      expect(controller.hasDropAnimation, isFalse);
      controller.setVisibleStep(2);
      expect(controller.hasDropAnimation, isTrue);
      controller.attachScene(_assemblyScene());
      expect(controller.hasDropAnimation, isFalse);
      controller.dispose();
    });
  });

  group('控制器：换场景与视角', () {
    test('用户手动调整过视角后，换稿（keepCamera=true）保留视角', () {
      final controller = Lego3DController();
      final draftA = fixtureDesign();
      controller.attachScene(LegoSceneBuilder.design(draft: draftA));
      expect(controller.isUserAdjusted, isFalse);
      controller.rotateBy(const Offset(40, 10));
      controller.zoomBy(1.5);
      final yaw = controller.camera.yaw;
      final pitch = controller.camera.pitch;
      final target = controller.camera.target;
      expect(controller.isUserAdjusted, isTrue);

      controller.attachScene(
        LegoSceneBuilder.design(draft: _biggerDesign()),
        keepCamera: true,
      );
      expect(controller.camera.yaw, yaw);
      expect(controller.camera.pitch, pitch);
      expect(controller.camera.target.x, closeTo(target.x, 1e-9));
      expect(controller.camera.target.z, closeTo(target.z, 1e-9));
      controller.dispose();
    });

    test('未手动调整视角时换稿会自动重新取景', () {
      final controller = Lego3DController();
      controller.attachScene(LegoSceneBuilder.design(draft: fixtureDesign()));
      final smallerTarget = controller.camera.target;
      controller.attachScene(
        LegoSceneBuilder.design(draft: _biggerDesign()),
        keepCamera: true,
      );
      final biggerTarget = controller.camera.target;
      expect(controller.isUserAdjusted, isFalse);
      expect(biggerTarget.x, greaterThan(smallerTarget.x));
      expect(biggerTarget.x, closeTo(4.0, 1e-6)); // (0..8) 体素网格中心
      controller.dispose();
    });

    test('attachScene 显式不保留视角时重新取景', () {
      final controller = Lego3DController()
        ..attachScene(LegoSceneBuilder.design(draft: fixtureDesign()));
      controller.rotateBy(const Offset(80, 0));
      controller.attachScene(LegoSceneBuilder.design(draft: _biggerDesign()));
      expect(controller.camera.target.x, closeTo(4.0, 1e-6));
      controller.dispose();
    });

    test('resetView 恢复默认朝向并重新取景', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.rotateBy(const Offset(120, 30));
      controller.zoomBy(8);
      controller.panBy(const Offset(30, 20));
      controller.resetView();
      final scene = controller.scene!;
      expect(controller.isUserAdjusted, isFalse);
      expect(controller.camera.yaw, Lego3DCamera.defaultYaw);
      expect(controller.camera.pitch, Lego3DCamera.defaultPitch);
      expect(controller.camera.target.x, closeTo(scene.bounds.center.x, 1e-9));
      expect(controller.camera.target.y, closeTo(scene.bounds.center.y, 1e-9));
      controller.dispose();
    });

    test('attachScene(null) 清空场景并回到默认视角', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.setVisibleStep(3);
      controller.rotateBy(const Offset(50, 0));
      controller.attachScene(null);
      expect(controller.scene, isNull);
      expect(controller.visibleStep, isNull);
      expect(controller.visibleMeshCount, 0);
      expect(controller.stepCount, 0);
      expect(controller.camera.yaw, Lego3DCamera.defaultYaw);
      controller.dispose();
    });
  });

  group('控制器：通知与释放', () {
    test('只在状态真正变化时通知；setViewport 不触发重绘', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      var notifications = 0;
      controller.addListener(() => notifications++);
      controller.setShowGhost(false);
      expect(notifications, 1);
      controller.setShowGhost(false);
      expect(notifications, 1);
      controller.setVisibleStep(3);
      expect(notifications, 2);
      controller.setVisibleStep(3);
      expect(notifications, 2);
      controller.rotateBy(Offset.zero);
      expect(notifications, 2);
      controller.setViewport(const Size(100, 100));
      expect(notifications, 2);
      expect(controller.viewport, const Size(100, 100));
      controller.dispose();
    });

    test('dispose 后调用方法不会抛异常（防止页面晚到回调）', () {
      final controller = Lego3DController()..attachScene(_assemblyScene());
      controller.dispose();
      expect(() => controller.setShowGhost(false), returnsNormally);
      expect(() => controller.setVisibleStep(99), returnsNormally);
      expect(() => controller.rotateBy(const Offset(1, 1)), returnsNormally);
    });
  });
}
