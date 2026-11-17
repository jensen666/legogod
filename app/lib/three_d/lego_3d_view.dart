// 3D 视图组件：把 LegoPainter 挂到 CustomPaint 上，处理手势、步骤同步、250ms 落位动画、
// 生命周期与无障碍语义。
// 两种用法都支持且互不冲突：
// 1) 直接传 scene / visibleStep / showGhost：widget 内部自建 controller 并同步 props；
// 2) 传已创建的 controller（页面自己 attachScene / setVisibleStep / resetView）：
//    widget 只消费 controller，不再用 props 覆盖页面状态，也不会重复监听。
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../core/theme.dart';
import 'lego_camera.dart';
import 'lego_painter.dart';
import 'lego_scene.dart';

/// LEGO 3D 场景视图（原生自绘，无 WebView / 三方 3D 插件）。
class Lego3DView extends StatefulWidget {
  const Lego3DView({
    super.key,
    this.controller,
    this.scene,
    this.visibleStep,
    this.showGhost = true,
    this.interactive = true,
    this.semanticsLabel,
    this.onStepChanged,
  });

  /// 页面自持有的控制器；为 null 时 widget 内部自建（此时只用 scene/visibleStep/showGhost 参数）。
  final Lego3DController? controller;

  /// 直接传场景（内部控制器模式）。
  final Lego3DScene? scene;

  /// 直接传可见步骤（内部控制器模式；拼装模拟用，null = 全部可见）。
  final int? visibleStep;

  /// 是否显示目标轮廓 ghost（内部控制器模式）。
  final bool showGhost;

  /// 是否响应手势（false 时只展示，适合卡片缩略图）。
  final bool interactive;

  /// 自定义无障碍描述；为空时使用场景 description + 步骤信息。
  final String? semanticsLabel;

  /// 可见步骤变化回调（页面据此更新文字，颜色不作为唯一信息）。
  final ValueChanged<int>? onStepChanged;

  /// 无障碍语义节点的 key（测试与页面定位用）。
  static const Key semanticsKey = Key('lego3d-view-semantics');

  @override
  State<Lego3DView> createState() => _Lego3DViewState();
}

class _Lego3DViewState extends State<Lego3DView>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late Lego3DController _controller;
  late LegoPainter _painter;
  bool _ownsController = false;

  Ticker? _dropTicker;
  bool _reducedMotion = false;
  bool _tickerModeEnabled = true;
  AppLifecycleState _lifecycleState = AppLifecycleState.resumed;

  /// prop 同步期间为 true：避免监听回调在 build 阶段触发 setState / 页面回调。
  bool _suppressNotifications = false;

  /// 监听回调重入保护（endDropAnimation 会再次 notify）。
  bool _inListener = false;

  int? _lastReportedStep;
  String _lastSemanticsSignature = '';
  double _lastScale = 1.0;
  Lego3DScene? _syncedScene;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _lifecycleState =
        WidgetsBinding.instance.lifecycleState ?? AppLifecycleState.resumed;
    _attachController(widget.controller);
    _syncFromWidget(initial: true);
    _lastReportedStep = _controller.visibleStep;
    _lastSemanticsSignature = _semanticsSignature();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _updateMotionPreferences();
  }

  @override
  void didUpdateWidget(covariant Lego3DView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(widget.controller, oldWidget.controller)) {
      // 外部控制器切换：先解绑（自建的会被 dispose），再绑定新的
      _detachController();
      _attachController(widget.controller);
      _syncFromWidget(initial: true);
      _lastReportedStep = _controller.visibleStep;
      _lastSemanticsSignature = _semanticsSignature();
      return;
    }
    if (_ownsController) _syncFromWidget();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _lifecycleState = state;
    if (state != AppLifecycleState.resumed) {
      // APP 不可见 / 不活跃：立即停止落位动画，不保留 Ticker
      _controller.endDropAnimation();
      _stopDropTicker();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _detachController();
    _dropTicker?.dispose();
    _dropTicker = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    Widget paint = LayoutBuilder(
      builder: (context, constraints) {
        _controller.setViewport(
          Size(constraints.maxWidth, constraints.maxHeight),
        );
        return SizedBox.expand(
          child: CustomPaint(
            painter: _painter,
            isComplex: true,
            willChange: true,
          ),
        );
      },
    );
    if (widget.interactive) {
      paint = GestureDetector(
        behavior: HitTestBehavior.opaque,
        onScaleStart: _onScaleStart,
        onScaleUpdate: _onScaleUpdate,
        child: paint,
      );
    }
    return Semantics(
      key: Lego3DView.semanticsKey,
      container: true,
      label: _semanticLabel(),
      child: ColoredBox(
        color: AppColors.stage,
        child: ClipRect(child: paint),
      ),
    );
  }

  /// 绑定控制器（外部传入或内部自建）并创建画笔。
  void _attachController(Lego3DController? external) {
    if (external != null) {
      _controller = external;
      _ownsController = false;
    } else {
      _controller = Lego3DController();
      _ownsController = true;
    }
    _controller.addListener(_handleControllerChange);
    _painter = LegoPainter(controller: _controller);
  }

  /// 解绑控制器：停止动画、移除监听，内部自建的立即释放。
  void _detachController() {
    _stopDropTicker();
    _controller.removeListener(_handleControllerChange);
    if (_ownsController) _controller.dispose();
  }

  /// 内部控制器模式下把 widget props 同步到 controller。
  /// 外部控制器模式下不覆盖页面状态（页面自己调用 attachScene / setVisibleStep）。
  void _syncFromWidget({bool initial = false}) {
    if (!_ownsController) return;
    _suppressNotifications = true;
    try {
      if (!identical(_syncedScene, widget.scene)) {
        _syncedScene = widget.scene;
        // 换稿：用户已手动调整过视角时保留视角，否则重新取景
        _controller.attachScene(widget.scene, keepCamera: true);
      }
      if (_controller.showGhost != widget.showGhost) {
        _controller.setShowGhost(widget.showGhost);
      }
      if (_controller.visibleStep != widget.visibleStep) {
        _controller.setVisibleStep(widget.visibleStep);
        if (!initial) _scheduleStepCallback(_controller.visibleStep);
      }
    } finally {
      _suppressNotifications = false;
    }
    _lastReportedStep = _controller.visibleStep;
  }

  /// 构建阶段不能安全回调页面（可能 catch 到 setState during build），推迟到下一帧。
  void _scheduleStepCallback(int? step) {
    if (step == null) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      widget.onStepChanged?.call(step);
    });
  }

  /// 控制器变化：启动/停止落位动画、上报步骤变化、按需刷新无障碍文案。
  void _handleControllerChange() {
    if (!mounted || _suppressNotifications) return;
    if (_inListener) return;
    _inListener = true;
    try {
      final step = _controller.visibleStep;
      if (step != _lastReportedStep) {
        _lastReportedStep = step;
        widget.onStepChanged?.call(step ?? 0);
      }
      _syncDropAnimation();
      final signature = _semanticsSignature();
      if (signature != _lastSemanticsSignature) {
        _lastSemanticsSignature = signature;
        setState(() {});
      }
    } finally {
      _inListener = false;
    }
  }

  /// 根据系统「减少动态效果」、TickerMode、前后台状态决定是否播放落位动画。
  void _syncDropAnimation() {
    final shouldAnimate =
        _controller.hasDropAnimation &&
        _controller.animationsEnabled &&
        !_reducedMotion &&
        _tickerModeEnabled &&
        _lifecycleState == AppLifecycleState.resumed;
    if (!shouldAnimate) {
      _stopDropTicker();
      if (_controller.hasDropAnimation) _controller.endDropAnimation();
      return;
    }
    final ticker = _dropTicker ??= createTicker(_onDropTick);
    if (!ticker.isActive) ticker.start();
  }

  /// 落位动画每帧推进（250ms，结束立即停 Ticker）。
  void _onDropTick(Duration elapsed) {
    final totalMicros = Lego3DController.dropDuration.inMicroseconds;
    final progress = totalMicros <= 0
        ? 1.0
        : elapsed.inMicroseconds / totalMicros;
    if (progress >= 1.0) {
      _controller.endDropAnimation();
      _stopDropTicker();
      return;
    }
    _controller.updateDropAnimation(progress);
  }

  /// 停止落位动画 Ticker。
  void _stopDropTicker() {
    final ticker = _dropTicker;
    if (ticker != null && ticker.isActive) ticker.stop();
  }

  /// 读取「减少动态效果」与 TickerMode 设置；不满足条件时立即结束动画（步骤内容不变）。
  void _updateMotionPreferences() {
    final media = MediaQuery.maybeOf(context);
    final reduced =
        media?.disableAnimations ??
        WidgetsBinding
            .instance
            .platformDispatcher
            .accessibilityFeatures
            .disableAnimations;
    final tickerMode = TickerMode.of(context);
    _reducedMotion = reduced;
    _tickerModeEnabled = tickerMode;
    _controller.animationsEnabled = !reduced;
    _syncDropAnimation();
  }

  /// 单指拖动旋转、双指缩放与平移。
  void _onScaleStart(ScaleStartDetails details) {
    _lastScale = 1.0;
  }

  /// 手势更新：双指走 zoom + pan，单指走 rotate。
  void _onScaleUpdate(ScaleUpdateDetails details) {
    if (details.pointerCount >= 2) {
      final scale = details.scale;
      if (scale > 0 && (scale - _lastScale).abs() > 1e-4) {
        _controller.zoomBy(scale / _lastScale);
        _lastScale = scale;
      }
      if (details.focalPointDelta != Offset.zero) {
        _controller.panBy(details.focalPointDelta);
      }
      return;
    }
    if (details.focalPointDelta != Offset.zero) {
      _controller.rotateBy(details.focalPointDelta);
    }
  }

  /// 无障碍文案：场景描述 + 当前步骤 + 可见数量（颜色不作为唯一信息）。
  String _semanticLabel() {
    final scene = _controller.scene;
    final base = widget.semanticsLabel ?? scene?.description ?? '3D 场景（暂无数据）';
    if (scene == null) return base;
    final buffer = StringBuffer(base);
    final step = _controller.visibleStep;
    if (scene.stepCount > 0) {
      buffer.write('；当前第 ${step ?? scene.stepCount} / ${scene.stepCount} 步');
    }
    buffer.write(
      '；可见 ${_controller.visibleMeshCount} ${_visibleNoun(scene.kind)}',
    );
    if (scene.warnings.isNotEmpty) {
      buffer.write('；有 ${scene.warnings.length} 条数据提示');
    }
    return buffer.toString();
  }

  /// 可见数量量词（按场景类型）。
  String _visibleNoun(LegoSceneKind kind) {
    switch (kind) {
      case LegoSceneKind.design:
        return '个体素';
      case LegoSceneKind.partsRow:
        return '种样品';
      case LegoSceneKind.assembly:
      case LegoSceneKind.model:
      case LegoSceneKind.empty:
        return '块零件';
    }
  }

  /// 语义文案签名：变化时才 setState，手势/动画帧不触发重建。
  String _semanticsSignature() {
    final scene = _controller.scene;
    return '${identityHashCode(scene)}|${_controller.visibleStep}|'
        '${_controller.visibleMeshCount}|${scene?.warnings.length ?? 0}|'
        '${widget.semanticsLabel}';
  }
}
