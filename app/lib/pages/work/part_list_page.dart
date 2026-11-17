// 零件清单页：只展示本作品真实用量，按实际用量降序；
// 行内保留颜色点、颜色名+零件名、尺寸、库存与用量，未知零件 ID 明确红色报错（不静默省略）。
// 全部「形状 × 颜色」库存不在本页展开，只保留「查看全部库存」入口（→ PartsPage）。
// 数据来自真实方案文件与 /api/parts 零件目录；加载失败、空目录提供错误态 / 空态与重试。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../models/artifacts.dart';
import '../../models/job.dart';
import '../../models/part.dart';
import '../../ui/widgets/common.dart';
import '../parts/parts_page.dart';

/// 零件清单页。
class PartListPage extends StatefulWidget {
  const PartListPage({super.key, required this.jobId});

  /// 真实任务 ID（用量来自该任务的方案产物）。
  final String jobId;

  @override
  State<PartListPage> createState() => _PartListPageState();
}

class _PartListPageState extends State<PartListPage> {
  StudioArtifacts? _artifacts;
  String? _error;
  bool _loading = true;
  bool _loadInFlight = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  /// 加载任务详情与真实 3D 产物（方案用量 + 零件目录）。
  Future<void> _load() async {
    if (_loadInFlight) return;
    _loadInFlight = true;
    final app = AppScope.read(context);
    if (!app.configured) {
      setState(() {
        _loading = false;
        _error = null;
      });
      _loadInFlight = false;
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
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
      if (!mounted) {
        _loadInFlight = false;
        return;
      }
      setState(() {
        _artifacts = artifacts;
        _loading = false;
      });
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

  /// 打开完整零件目录（全部「形状 × 颜色」库存只在该页展开）。
  void _openCatalog() {
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => const PartsPage(),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('零件清单'),
        actions: [
          TextButton(
            key: const Key('part-list-open-catalog'),
            onPressed: _openCatalog,
            child: const Text('查看全部库存'),
          ),
        ],
      ),
      body: _buildBody(app),
    );
  }

  /// 主体：未连接 / 加载中 / 真实错误重试 / 空目录 / 用量内容。
  Widget _buildBody(AppState app) {
    if (!app.configured) {
      return const EmptyState(
        icon: '🔌',
        title: '尚未连接服务',
        message: '请先在「我的 → 服务连接」配置 LEGOGOD 服务地址。',
      );
    }
    if (_loading) return const LoadingBlock(text: '正在读取本作品零件用量……');
    if (_error != null) {
      return ErrorView(
        title: '零件清单加载失败',
        message: _error!,
        onRetry: _load,
      );
    }
    final artifacts = _artifacts;
    if (artifacts == null) {
      return const LoadingBlock(text: '正在读取本作品零件用量……');
    }
    final catalog = artifacts.parts;
    if (catalog.parts.isEmpty) {
      return EmptyState(
        icon: '🧩',
        title: '零件目录为空',
        message: '服务端没有返回任何零件（/api/parts 为空或不可用），'
            '无法展示零件名称、尺寸与库存。请检查服务端零件库配置后重试。',
        actions: [
          OutlinedButton(
            onPressed: () async {
              await app.refreshParts();
              if (mounted) await _load();
            },
            child: const Text('重新拉取'),
          ),
        ],
      );
    }
    return _buildUsage(artifacts);
  }

  /// 本作品用量内容（唯一允许的默认视图）。
  Widget _buildUsage(StudioArtifacts artifacts) {
    final solution = artifacts.solution;
    final catalog = artifacts.parts;
    final usage = solution.usage;
    final usageTotal = solution.usageTotal;
    final stepCount = solution.stepCount;
    final matches = solution.usageMatchesSteps;

    // 用量按实际用量降序；用量相同按零件 ID 稳定排序。
    final ids = usage.keys.toList()
      ..sort((a, b) {
        final byUsage = (usage[b] ?? 0).compareTo(usage[a] ?? 0);
        return byUsage != 0 ? byUsage : a.compareTo(b);
      });
    final used = <MapEntry<Part, int>>[];
    final unknown = <String>[];
    for (final id in ids) {
      final part = catalog.partOf(id);
      if (part == null) {
        unknown.add(id);
      } else {
        used.add(MapEntry(part, usage[id] ?? 0));
      }
    }

    return ListView(
      key: const Key('part-list-usage'),
      // 本作品用量行数有限：增大缓存区，保证未知零件提示与合计行也已完成构建。
      cacheExtent: 2400,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '本作品用量合计 $usageTotal 块',
                style:
                    const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              Text(
                matches
                    ? '与拼装步骤数 $stepCount 块一致。'
                    : '与拼装步骤数 $stepCount 块不一致，页面按真实方案文件如实展示，不伪造合计。',
                style: TextStyle(
                  fontSize: 12,
                  color: matches ? AppColors.textMuted : AppColors.warn,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '共 ${ids.length} 种「形状 × 颜色」零件 · 名称、尺寸与库存来自服务端 /api/parts',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textDim,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
        if (usage.isEmpty) ...[
          const SizedBox(height: 10),
          InfoBanner(
            icon: '⚠️',
            tone: 'warn',
            title: '用量表为空',
            text: '方案文件没有记录零件用量（步骤数 $stepCount 块），'
                '本页不伪造用量；可进入生成记录核对真实产物文件。',
          ),
        ],
        const SectionTitle(
          '本作品用量',
          padding: EdgeInsets.only(top: 14, bottom: 6),
        ),
        AppCard(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Column(
            children: [
              if (used.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 10),
                  child: Text(
                    '没有可展示的已知零件用量。',
                    style:
                        TextStyle(fontSize: 12, color: AppColors.textMuted),
                  ),
                )
              else
                for (var i = 0; i < used.length; i++) ...[
                  if (i > 0) const Divider(height: 1),
                  _usageRow(used[i].key, used[i].value),
                ],
              const Divider(height: 14),
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '合计',
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Text(
                    '用量 $usageTotal 块 · 步骤 $stepCount 块',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: matches ? AppColors.ok : AppColors.warn,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        if (unknown.isNotEmpty) ...[
          const SizedBox(height: 10),
          InfoBanner(
            icon: '❌',
            tone: 'bad',
            title: '未知零件 ID（零件目录未同步）',
            text: '以下零件 ID 不在服务端零件目录中，无法展示名称、尺寸与库存；'
                '本页不静默省略：\n'
                '${unknown.map((id) => '· $id（方案用量 ${usage[id] ?? 0} 块）').join('\n')}',
          ),
        ],
        const SizedBox(height: 12),
        const Text(
          '全部「形状 × 颜色」库存不在本页展开；请使用右上角「查看全部库存」进入零件目录。',
          style: TextStyle(
            fontSize: 11,
            color: AppColors.textDim,
            height: 1.45,
          ),
        ),
      ],
    );
  }

  /// 单条用量行：颜色点 + 颜色名/零件名 + 尺寸 + 库存 + 用量（大字体下换行不截断）。
  Widget _usageRow(Part part, int count) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: ColorDot(part.hex, size: 14),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${part.colorName} ${part.name}',
                  style: const TextStyle(fontSize: 12.5, height: 1.4),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '×$count',
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                  color: AppColors.yellowDeep,
                ),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(left: 22, top: 2),
            child: Text(
              '尺寸 ${part.w}×${part.d} · 库存 ${part.count} 块',
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.textMuted,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
