// 作品详情页：3D 成品优先，其次最多 3 项核心规格与真实警告，最后是次要操作；
// 底部固定主按钮「开始拼装」，放在 Scaffold bottomNavigationBar 区域，不遮挡 3D 与核心信息。
// 「更多」菜单承载原始需求、作品信息、再次生成、生成记录、分享与导出，不再有两层 Tab。
// 所有展示均来自真实任务快照与真实产物文件；非可交付状态显示真实原因与入口，不白屏。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/job_snapshot.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../three_d/lego_3d_view.dart';
import '../../three_d/lego_camera.dart';
import '../../three_d/lego_scene.dart';
import '../../ui/share_export.dart';
import '../../ui/widgets/common.dart';
import 'work_info_sheet.dart';
import 'work_sections.dart';
import 'work_shared.dart';

/// 作品详情页。
class WorkDetailPage extends StatefulWidget {
  const WorkDetailPage({super.key, required this.jobId});

  /// 真实任务 ID（页面按该 ID 读取任务快照与产物，不复用其他任务数据）。
  final String jobId;

  @override
  State<WorkDetailPage> createState() => _WorkDetailPageState();
}

class _WorkDetailPageState extends State<WorkDetailPage> {
  final Lego3DController _modelController = Lego3DController();

  StudioArtifacts? _artifacts;
  Lego3DScene? _modelScene;

  /// 最终步与目标模型逐体素一致性检查结果（null 表示一致）。
  String? _consistencyError;
  String? _artifactsError;
  bool _artifactsLoading = false;
  bool _artifactsRequested = false;
  bool _artifactsInFlight = false;
  bool _retrying = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _bootstrap();
    });
  }

  @override
  void dispose() {
    _modelController.dispose();
    super.dispose();
  }

  /// 进入页面：切换当前任务并确保详情已加载，随后按真实产物加载 3D 成品。
  Future<void> _bootstrap() async {
    final app = AppScope.read(context);
    await app.selectJob(widget.jobId);
    try {
      await app.ensureJobLoaded(widget.jobId);
    } catch (_) {
      // 详情加载失败由页面主体展示并提供重试，这里不吞成假成功。
    }
    if (!mounted) return;
    await _maybeLoadArtifacts();
  }

  /// 任务是否具备可交付 3D 产物（与 route_nav 落点判定保持一致）。
  bool _isDeliverable(JobDetail? detail) {
    if (detail == null || !detail.isDoneSuccess) return false;
    final result = detail.result;
    return result?.modelPath != null && result?.solutionPath != null;
  }

  /// 构建期间不发起异步请求：可交付且尚未请求时，安排下一帧加载 3D 产物。
  void _scheduleArtifactsLoad(JobDetail detail) {
    if (!_isDeliverable(detail) || _artifactsRequested || _artifacts != null) {
      return;
    }
    _artifactsRequested = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _loadArtifacts();
    });
  }

  /// 任务就绪时加载 3D 产物；失败只影响 3D 区域，页面其余信息照常展示。
  Future<void> _maybeLoadArtifacts() async {
    final detail = AppScope.read(context).jobs[widget.jobId]?.detail;
    if (!_isDeliverable(detail)) return;
    await _loadArtifacts();
  }

  /// 读取真实产物并生成成品场景与逐体素一致性结论。
  Future<void> _loadArtifacts() async {
    if (_artifactsInFlight) return;
    final app = AppScope.read(context);
    final detail = app.jobs[widget.jobId]?.detail;
    if (!_isDeliverable(detail)) return;
    _artifactsInFlight = true;
    setState(() {
      _artifactsLoading = true;
      _artifactsError = null;
    });
    try {
      final artifacts = await app.loadStudioArtifacts(widget.jobId);
      final scene = LegoSceneBuilder.model(
        model: artifacts.model,
        solution: artifacts.solution,
        parts: artifacts.parts,
      );
      final consistencyError = artifacts.verifyModelSolutionConsistency();
      if (!mounted) return;
      _modelController.attachScene(scene);
      setState(() {
        _artifacts = artifacts;
        _modelScene = scene;
        _consistencyError = consistencyError;
        _artifactsLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _artifactsError = describeError(e);
        _artifactsLoading = false;
      });
    } finally {
      _artifactsInFlight = false;
    }
  }

  /// 3D 区域局部重试：先补齐任务详情，再重新读取产物。
  Future<void> _retryArtifacts() async {
    _artifactsRequested = true;
    setState(() {
      _artifactsLoading = true;
      _artifactsError = null;
    });
    try {
      await AppScope.read(context).ensureJobLoaded(widget.jobId);
    } catch (_) {
      // 详情仍失败时下面会继续尝试读产物并显示真实错误。
    }
    if (!mounted) return;
    final detail = AppScope.read(context).jobs[widget.jobId]?.detail;
    if (!_isDeliverable(detail)) {
      setState(() => _artifactsLoading = false);
      return;
    }
    await _loadArtifacts();
  }

  /// 任务详情加载失败后的重试。
  Future<void> _retryJobLoad() async {
    try {
      await AppScope.read(context).fetchJob(widget.jobId);
    } catch (e) {
      if (mounted) showNotice(context, describeError(e));
    }
    if (!mounted) return;
    await _maybeLoadArtifacts();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final snapshot = app.jobs[widget.jobId];
    final detail = snapshot?.detail;
    if (_isDeliverable(detail)) _scheduleArtifactsLoad(detail!);
    return Scaffold(
      appBar: AppBar(
        title: const Text('作品'),
        actions: [_buildMoreMenu(app, detail)],
      ),
      body: _buildBody(snapshot, detail),
      bottomNavigationBar: _isDeliverable(detail)
          ? BottomPrimaryBar(
              child: SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  key: const Key('work-start-assembly'),
                  onPressed: () => openAssemblyGuidePage(context, widget.jobId),
                  icon: const Icon(Icons.view_in_ar, size: 20),
                  label: const Text('开始拼装'),
                ),
              ),
            )
          : null,
    );
  }

  /// 主体：加载态 / 加载错误 / 非可交付状态 / 可交付作品详情。
  Widget _buildBody(JobSnapshot? snapshot, JobDetail? detail) {
    if (snapshot == null) return const LoadingBlock(text: '正在加载作品……');
    if (detail == null) {
      if (snapshot.error != null) {
        return ErrorView(
          message: snapshot.error!,
          title: '作品加载失败',
          onRetry: _retryJobLoad,
        );
      }
      return const LoadingBlock(text: '正在加载作品……');
    }
    if (!_isDeliverable(detail)) return WorkNotReadyView(job: detail);
    return _buildDeliverableBody(detail);
  }

  /// 可交付作品首屏：作品名 → 3D 成品 → 核心规格 → 警告 → 次要操作 → 可拼性检查。
  Widget _buildDeliverableBody(JobDetail detail) {
    final artifacts = _artifacts;
    final warnings = buildWorkWarnings(
      job: detail,
      artifacts: artifacts,
      consistencyError: _consistencyError,
    );
    return ListView(
      // 首屏信息量固定且不大：适度增大缓存区，保证小屏/大字体下首屏组件也已构建。
      cacheExtent: 1600,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        WorkHeader(job: detail),
        const SizedBox(height: 10),
        _buildStage3D(),
        const SizedBox(height: 6),
        Row(
          children: [
            const Expanded(
              child: Text(
                '成品预览 · 单指旋转 · 双指缩放/平移',
                style: TextStyle(fontSize: 11, color: AppColors.textMuted),
              ),
            ),
            TextButton.icon(
              onPressed: _modelController.resetView,
              icon: const Icon(Icons.center_focus_strong, size: 14),
              label: const Text('重置视角', style: TextStyle(fontSize: 11)),
            ),
          ],
        ),
        const SizedBox(height: 6),
        FactChips(
          key: const Key('work-specs'),
          facts: buildWorkSpecs(detail, artifacts),
        ),
        if (warnings.isNotEmpty) ...[
          const SizedBox(height: 12),
          Column(
            key: const Key('work-warning'),
            children: [
              for (final warning in warnings) WorkReasonTile(warning: warning),
            ],
          ),
        ],
        const SizedBox(height: 6),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            LabeledAction(
              key: const Key('work-part-list'),
              icon: Icons.list_alt,
              label: '零件清单',
              onPressed: () => openPartListPage(context, widget.jobId),
            ),
            LabeledAction(
              key: const Key('work-share-export'),
              icon: Icons.ios_share,
              label: '分享与导出',
              onPressed: () => showShareExportSheet(context, detail),
            ),
          ],
        ),
        if (artifacts != null) ...[
          const SizedBox(height: 12),
          WorkValidationSummary(
            key: const Key('work-validation'),
            solution: artifacts.solution,
          ),
        ],
      ],
    );
  }

  /// 3D 成品舞台：加载中 / 失败重试 / 真实成品场景三态，固定高度 300。
  Widget _buildStage3D() {
    Widget child;
    if (_artifacts != null && _modelScene != null) {
      child = Lego3DView(
        controller: _modelController,
        semanticsLabel: '成品预览：最终零件颜色与形状，单指旋转、双指缩放平移',
      );
    } else if (_artifactsLoading) {
      child = const LoadingBlock(text: '正在加载成品 3D……', height: 300);
    } else if (_artifactsError != null) {
      child = SingleChildScrollView(
        padding: const EdgeInsets.only(top: 40),
        child: ErrorView(
          message: _artifactsError!,
          title: '3D 成品加载失败',
          onRetry: _retryArtifacts,
        ),
      );
    } else {
      child = const LoadingBlock(text: '正在加载成品 3D……', height: 300);
    }
    return WorkStageBox(key: const Key('work-3d'), height: 300, child: child);
  }

  /// 「更多」菜单：原始需求 / 作品信息 / 再次生成 / 生成记录 / 分享与导出。
  Widget _buildMoreMenu(AppState app, JobDetail? detail) {
    final running = detail?.isRunning ?? false;
    return PopupMenuButton<String>(
      key: const Key('work-more'),
      tooltip: '更多操作',
      icon: const Icon(Icons.more_vert),
      onSelected: (value) => _onMenuSelected(app, value),
      itemBuilder: (context) => [
        _menuItem('desc', Icons.article_outlined, '原始需求'),
        _menuItem('info', Icons.info_outline, '作品信息'),
        PopupMenuItem<String>(
          value: 'retry',
          enabled: detail != null && !running,
          child: _menuRow(
            Icons.refresh,
            detail == null
                ? '再次生成'
                : (running ? '再次生成（进行中不可用）' : '再次生成'),
          ),
        ),
        _menuItem('record', Icons.history, '生成记录'),
        _menuItem('share', Icons.ios_share, '分享与导出'),
      ],
    );
  }

  PopupMenuItem<String> _menuItem(String value, IconData icon, String label) {
    return PopupMenuItem<String>(
      value: value,
      child: _menuRow(icon, label),
    );
  }

  Widget _menuRow(IconData icon, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18, color: AppColors.textMuted),
        const SizedBox(width: 10),
        Text(label, style: const TextStyle(fontSize: 13.5)),
      ],
    );
  }

  /// 菜单动作：全部基于真实任务快照，缺数据时明确提示而不静默。
  Future<void> _onMenuSelected(AppState app, String value) async {
    final detail = app.jobs[widget.jobId]?.detail;
    switch (value) {
      case 'desc':
        if (detail == null) {
          _noticeLoading();
          return;
        }
        await showRequirementSheet(context, desc: detail.desc);
      case 'info':
        if (detail == null) {
          _noticeLoading();
          return;
        }
        await showWorkInfoSheet(
          context,
          job: detail,
          artifacts: _artifacts,
          consistencyError: _consistencyError,
        );
      case 'retry':
        await _retryGeneration(app, detail);
      case 'record':
        openGenerationRecordPage(context, widget.jobId);
      case 'share':
        if (detail == null) {
          _noticeLoading();
          return;
        }
        await showShareExportSheet(context, detail);
    }
  }

  /// 作品信息尚未就绪的统一提示。
  void _noticeLoading() {
    showNotice(context, '作品信息还在加载中，请稍后重试');
  }

  /// 再次生成：仅非运行中可用，成功后用新任务替换当前路由进入生成进度页。
  Future<void> _retryGeneration(AppState app, JobDetail? detail) async {
    if (detail == null) {
      _noticeLoading();
      return;
    }
    if (detail.isRunning || _retrying) return;
    if (detail.desc.trim().isEmpty) {
      showNotice(context, '原任务缺少需求描述，无法再次生成');
      return;
    }
    setState(() => _retrying = true);
    try {
      final newId = await app.retryJob(widget.jobId);
      if (!mounted) return;
      await openGenerationProgressPage(context, newId, replace: true);
    } catch (e) {
      if (mounted) showNotice(context, '再次生成失败：${describeError(e)}');
    } finally {
      if (mounted) setState(() => _retrying = false);
    }
  }
}
