// 拼装指导页：顶部 3D 舞台 + 「模拟 / 分层步骤」同页联动。
// - 模拟视图保留重置/上一步/播放暂停/下一步/滑块/目标轮廓/减少动态效果提示与当前步骤卡片；
// - 分层步骤视图按层展示真实步骤，点任一步回传后切回模拟并同步 3D（同一 _step 状态源）；
// - 第 0 步、最终步逐体素一致性、子组件按扣合完成步成组落位、可拼性检查摘要语义不变；
// - 视图与步数按任务隔离持久化（AppState.studioStateOf / setStudioState），不同任务不混用。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../../app_scope.dart';
import '../../core/route_nav.dart';
import '../../core/storage.dart';
import '../../core/studio_helpers.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../three_d/lego_3d_view.dart';
import '../../three_d/lego_camera.dart';
import '../../three_d/lego_scene.dart';
import '../../ui/widgets/common.dart';
import 'assembly_guide_sim.dart';
import 'assembly_guide_steps.dart';
import 'work_shared.dart';

/// 拼装指导页。
class AssemblyGuidePage extends StatefulWidget {
  const AssemblyGuidePage({super.key, required this.jobId});

  /// 真实任务 ID（产物、步数与视图状态都按该任务隔离）。
  final String jobId;

  @override
  State<AssemblyGuidePage> createState() => _AssemblyGuidePageState();
}

class _AssemblyGuidePageState extends State<AssemblyGuidePage> {
  StudioArtifacts? _artifacts;
  SubAssemblyPlan? _plan;

  /// 最终步与目标模型逐体素一致性检查结果（null 表示一致）。
  String? _consistencyError;

  String? _error;
  bool _loading = true;
  bool _loadInFlight = false;
  bool _playing = false;
  bool _showGhost = true;

  /// 当前视图：sim（模拟）/ steps（分层步骤）。
  String _tab = 'sim';

  /// 当前步数：0 = 绿色底板空载，total = 完成。
  int _step = 0;

  Timer? _playTimer;
  final Lego3DController _controller = Lego3DController();

  int get _total => _artifacts?.solution.stepCount ?? 0;

  @override
  void initState() {
    super.initState();
    // 恢复该任务上次的视图与步数（步数在产物加载后夹到 [0, total]）。
    final saved = AppScope.read(context).studioStateOf(widget.jobId);
    _tab = saved.tab == 'steps' ? 'steps' : 'sim';
    _step = saved.step < 0 ? 0 : saved.step;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  @override
  void didUpdateWidget(covariant AssemblyGuidePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.jobId == widget.jobId) return;
    // 任务切换：立即停止播放并清空上一任务产物，重新恢复新任务自己的状态。
    _playTimer?.cancel();
    _playTimer = null;
    _playing = false;
    final saved = AppScope.read(context).studioStateOf(widget.jobId);
    _tab = saved.tab == 'steps' ? 'steps' : 'sim';
    _step = saved.step < 0 ? 0 : saved.step;
    _artifacts = null;
    _plan = null;
    _consistencyError = null;
    _error = null;
    _loading = true;
    // 解绑旧场景与重新加载都推迟到下一帧，避免在组件更新阶段触发控制器通知。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _controller.attachScene(null);
      _load();
    });
  }

  @override
  void dispose() {
    _playTimer?.cancel();
    _playTimer = null;
    _controller.dispose();
    super.dispose();
  }

  /// 加载任务详情与真实 3D 产物；失败只显示错误与重试，不白屏。
  Future<void> _load() async {
    if (_loadInFlight) return;
    _loadInFlight = true;
    setState(() {
      _loading = true;
      _error = null;
    });
    final app = AppScope.read(context);
    await app.selectJob(widget.jobId);
    try {
      await app.ensureJobLoaded(widget.jobId);
    } catch (_) {
      // 详情失败时下面继续尝试读产物并展示真实错误。
    }
    if (!mounted) {
      _loadInFlight = false;
      return;
    }
    try {
      final artifacts = await app.loadStudioArtifacts(widget.jobId);
      final plan = SubAssemblyPlan.fromSolution(artifacts.solution);
      final scene = LegoSceneBuilder.assembly(
        model: artifacts.model,
        solution: artifacts.solution,
        parts: artifacts.parts,
      );
      final consistencyError = artifacts.verifyModelSolutionConsistency();
      if (!mounted) {
        _loadInFlight = false;
        return;
      }
      final total = artifacts.solution.stepCount;
      final clamped = _clampStep(_step, total);
      _controller.attachScene(scene);
      _controller.setShowGhost(_showGhost);
      _controller.setVisibleStep(clamped);
      setState(() {
        _artifacts = artifacts;
        _plan = plan;
        _consistencyError = consistencyError;
        _step = clamped;
        _loading = false;
      });
      _persistState();
    } catch (e) {
      if (!mounted) {
        _loadInFlight = false;
        return;
      }
      setState(() {
        _error = describeError(e);
        _loading = false;
      });
    } finally {
      _loadInFlight = false;
    }
  }

  /// 把步数夹到合法区间 [0, total]。
  int _clampStep(int step, int total) {
    if (step < 0) return 0;
    if (step > total) return total;
    return step;
  }

  /// 设置当前步数：同步 3D、持久化状态，到终点自动停止播放。
  void _setStep(int next, {bool animate = true}) {
    if (_artifacts == null) return;
    final total = _total;
    final clamped = _clampStep(next, total);
    if (clamped != _step) setState(() => _step = clamped);
    _controller.setVisibleStep(clamped);
    _persistState();
    if (animate && clamped >= total && _playing) _setPlaying(false);
  }

  /// 播放 / 暂停：间隔 750ms，播放期间采样 3 秒真实帧耗时。
  void _setPlaying(bool on) {
    _playTimer?.cancel();
    _playTimer = null;
    if (on && _total == 0) return;
    setState(() => _playing = on);
    if (!on) return;
    // 真机性能采样：播放 3D 拼装动画期间统计真实帧耗时（不影响交互）。
    _startFrameProbe();
    final total = _total;
    if (_step >= total) {
      // 播放到终点后再次播放从头开始。
      _setStep(0, animate: false);
    }
    _playTimer = Timer.periodic(const Duration(milliseconds: 750), (_) {
      if (!mounted) return;
      final current = _step;
      if (current >= total) {
        _setPlaying(false);
        return;
      }
      _setStep(current + 1);
      if (_step >= total) _setPlaying(false);
    });
  }

  /// 播放期间采样 3 秒帧耗时并输出统计（供真机性能验收与诊断使用）。
  void _startFrameProbe() {
    final frames = <FrameTiming>[];
    void collect(List<FrameTiming> timings) => frames.addAll(timings);
    SchedulerBinding.instance.addTimingsCallback(collect);
    Timer(const Duration(seconds: 3), () {
      SchedulerBinding.instance.removeTimingsCallback(collect);
      if (frames.isEmpty) {
        debugPrint('[perf] 3D 播放帧统计：无帧数据');
        return;
      }
      final spans = frames.map((f) => f.totalSpan.inMicroseconds).toList()
        ..sort();
      final avg = spans.reduce((a, b) => a + b) / spans.length;
      final p95 =
          spans[(spans.length * 0.95).floor().clamp(0, spans.length - 1)];
      debugPrint(
        '[perf] 3D 播放帧统计 frames=${frames.length} '
        'avg=${(avg / 1000).toStringAsFixed(2)}ms '
        'p95=${(p95 / 1000).toStringAsFixed(2)}ms '
        'fps=${(1000000 / avg).toStringAsFixed(1)}',
      );
    });
  }

  /// 视图切换并持久化。
  void _setTab(String tab) {
    if (tab == _tab) return;
    setState(() => _tab = tab);
    _persistState();
  }

  /// 分层步骤列表选中某一步：停止播放、同步 3D，并切回「模拟」视图。
  void _selectStepFromList(int step) {
    _setPlaying(false);
    _setStep(step, animate: false);
    _setTab('sim');
  }

  /// 目标轮廓开关。
  void _toggleGhost(bool value) {
    setState(() => _showGhost = value);
    _controller.setShowGhost(value);
  }

  /// 按任务持久化视图与步数（不同任务互不混用）。
  void _persistState() {
    AppScope.read(context).setStudioState(
      widget.jobId,
      StudioUiState(tab: _tab, step: _step),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('拼装指导'),
        actions: [
          TextButton.icon(
            key: const Key('guide-part-list'),
            onPressed: () => openPartListPage(context, widget.jobId),
            icon: const Icon(Icons.list_alt, size: 18),
            label: const Text('零件清单'),
          ),
        ],
      ),
      body: _buildBody(context),
    );
  }

  /// 主体：加载态 / 真实错误重试 / 3D 舞台 + 视图分段 + 内容区。
  Widget _buildBody(BuildContext context) {
    if (_loading) return const LoadingBlock(text: '正在加载拼装产物……');
    if (_error != null) {
      return ErrorView(
        title: '拼装产物加载失败',
        message: _error!,
        onRetry: _load,
      );
    }
    final artifacts = _artifacts;
    if (artifacts == null) {
      return const LoadingBlock(text: '正在加载拼装产物……');
    }
    final total = artifacts.solution.stepCount;
    final plan = _plan ?? SubAssemblyPlan.fromSolution(artifacts.solution);
    // 横屏等矮视口下按可用高度收缩 3D 舞台，保证播放控制与步骤内容仍可见。
    return LayoutBuilder(
      builder: (context, constraints) {
        final available = constraints.maxHeight;
        final stageHeight = (available >= 500
                ? 280.0
                : available - 180)
            .clamp(120.0, 280.0)
            .toDouble();
        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
              child: WorkStageBox(
                key: const Key('guide-3d'),
                height: stageHeight,
                child: Lego3DView(
                  controller: _controller,
                  visibleStep: _step,
                  showGhost: _showGhost,
                  semanticsLabel: '拼装模拟：第 $_step 步，共 $total 步',
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: KeyedSubtree(
                key: const Key('guide-views'),
                child: SegmentedControl(
                  items: const [SegmentedItem('模拟'), SegmentedItem('分层步骤')],
                  index: _tab == 'steps' ? 1 : 0,
                  onChanged: (index) => _setTab(index == 0 ? 'sim' : 'steps'),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Expanded(
              child: _tab == 'steps'
                  ? AssemblyGuideStepsView(
                      model: artifacts.model,
                      solution: artifacts.solution,
                      parts: artifacts.parts,
                      currentStep: _step,
                      onSelectStep: _selectStepFromList,
                    )
                  : AssemblyGuideSimView(
                      artifacts: artifacts,
                      plan: plan,
                      step: _step,
                      total: total,
                      playing: _playing,
                      showGhost: _showGhost,
                      reducedMotion: MediaQuery.of(context).disableAnimations,
                      consistencyError: _consistencyError,
                      onReset: () {
                        _setPlaying(false);
                        _setStep(0, animate: false);
                      },
                      onPrev: () {
                        _setPlaying(false);
                        _setStep(_step - 1, animate: false);
                      },
                      onNext: () {
                        _setPlaying(false);
                        _setStep(_step + 1);
                      },
                      onTogglePlay: () => _setPlaying(!_playing),
                      onSeek: (value) {
                        _setPlaying(false);
                        _setStep(value, animate: false);
                      },
                      onToggleGhost: _toggleGhost,
                    ),
            ),
          ],
        );
      },
    );
  }
}
