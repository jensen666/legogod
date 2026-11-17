// 零件目录页：展示服务端真实「形状 × 颜色」库存与颜色变体。
// - 首屏只保留一行真实统计与更新时间，不重复标题卡、不展示实现说明；
// - 按形状分组，形状名已含尺寸时不重复追加尺寸，坡向差异始终保留；
// - 变体默认行只显示颜色与库存，零件 ID 与尺寸等细节点开变体后可查看；
// - 保留加载中 / 空目录 / 加载失败 / 缓存 / 未知零件提示，全部库存不与作品用量混排。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/format.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/part.dart';
import '../../ui/widgets/common.dart';

/// 零件目录页。
class PartsPage extends StatefulWidget {
  const PartsPage({super.key});

  @override
  State<PartsPage> createState() => _PartsPageState();
}

class _PartsPageState extends State<PartsPage> {
  bool _requested = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final app = AppScope.read(context);
      if (!app.configured) return;
      if (app.parts.parts.isEmpty && !_requested) {
        // 首次进入且没有缓存：显示加载态；已有缓存则静默校准。
        _requested = true;
        app.refreshParts();
      } else {
        app.refreshParts(silent: true);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('零件目录'),
        actions: [
          IconButton(
            tooltip: '刷新零件目录',
            onPressed: app.configured ? () => app.refreshParts() : null,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: app,
        builder: (context, _) {
          if (!app.configured) {
            return _buildNotConnected(context);
          }
          final catalog = app.parts;
          if (catalog.parts.isEmpty && app.partsLoading) {
            return const LoadingBlock(text: '零件目录加载中……');
          }
          if (catalog.parts.isEmpty && app.partsError != null) {
            return ErrorView(
              title: '零件目录加载失败',
              message: app.partsError!,
              onRetry: app.refreshParts,
            );
          }
          if (catalog.parts.isEmpty) {
            return EmptyState(
              icon: '🧩',
              title: '零件目录为空',
              message: '服务端没有返回任何零件，请检查服务端零件库配置后重试。',
              actions: [
                OutlinedButton(
                  onPressed: app.refreshParts,
                  child: const Text('重新拉取'),
                ),
              ],
            );
          }
          return _buildCatalog(context, app, catalog);
        },
      ),
    );
  }

  /// 未连接服务：只给连接入口，不展示任何虚构目录。
  Widget _buildNotConnected(BuildContext context) {
    return EmptyState(
      icon: '🔌',
      title: '尚未连接服务',
      message: '连接 LEGOGOD 服务后，这里会显示真实的形状、颜色与库存。',
      actions: [
        FilledButton.icon(
          onPressed: () => openServicePage(context),
          icon: const Icon(Icons.link, size: 18),
          label: const Text('去连接'),
        ),
      ],
    );
  }

  /// 目录正文：缓存 / 刷新失败 / 未知零件提示 + 统计行 + 形状分组。
  Widget _buildCatalog(BuildContext context, AppState app, PartsCatalog catalog) {
    final unknown = _unknownPartCount(catalog);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
      children: [
        if (app.partsError != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InfoBanner(
              text: '刷新失败，当前显示上次数据：${app.partsError}',
              icon: '⚠️',
              tone: 'warn',
            ),
          ),
        if (app.partsFromCache)
          const Padding(
            padding: EdgeInsets.only(bottom: 10),
            child: InfoBanner(
              text: '当前展示本地缓存的零件目录，正在等待服务端校准。',
              icon: '🗄️',
              tone: 'warn',
            ),
          ),
        if (unknown > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InfoBanner(
              text: '目录中有 $unknown 个零件缺少零件 ID，已按服务端原始数据展示；'
                  '这些零件在零件清单中可能无法精确定位。',
              icon: '❓',
              tone: 'warn',
            ),
          ),
        _CatalogStats(catalog: catalog, updatedAt: app.partsUpdatedAt),
        const SizedBox(height: 12),
        for (final group in catalog.groups) _ShapeGroupTile(group: group),
      ],
    );
  }

  /// 统计缺少 ID 的零件数（未知零件必须显式提示，不得静默省略）。
  int _unknownPartCount(PartsCatalog catalog) =>
      catalog.parts.where((part) => part.id.trim().isEmpty).length;
}

/// 目录顶部真实统计：形状数 · 变体数 · 颜色数 · 总库存 + 更新时间小字。
class _CatalogStats extends StatelessWidget {
  const _CatalogStats({required this.catalog, required this.updatedAt});

  final PartsCatalog catalog;
  final double? updatedAt;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${catalog.shapeCount} 种形状 · ${catalog.variantCount} 个「形状×颜色」变体 · '
          '${catalog.colorCount} 种颜色 · 总库存 ${catalog.totalStock} 块',
          style: const TextStyle(
            fontSize: 13,
            height: 1.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        if (updatedAt != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              '更新于 ${fmtDateTime(updatedAt)}',
              style: const TextStyle(fontSize: 11, color: AppColors.textDim),
            ),
          ),
      ],
    );
  }
}

/// 单个形状分组：标题含形状名 / 尺寸 / 坡向，展开后列出全部颜色变体。
class _ShapeGroupTile extends StatelessWidget {
  const _ShapeGroupTile({required this.group});

  final ShapeGroup group;

  @override
  Widget build(BuildContext context) {
    final first = group.first;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.borderSoft),
        ),
        clipBehavior: Clip.antiAlias,
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            leading: ColorDot(first.hex, size: 18, radius: 4),
            title: Text(
              _shapeTitle(first),
              style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
            ),
            subtitle: Text(
              '${group.variants.length} 个颜色变体',
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
            childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 8),
            children: [
              for (final part in group.variants) _VariantTile(part: part),
            ],
          ),
        ),
      ),
    );
  }

  /// 形状标题：名称已包含尺寸（如 2x4 / 2×4）时不重复追加；坡向非空时始终显示。
  String _shapeTitle(Part part) {
    final bits = <String>[part.name];
    final size = '${part.w}×${part.d}';
    final containsSize = part.name.contains('${part.w}x${part.d}') ||
        part.name.contains('${part.w}X${part.d}') ||
        part.name.contains(size);
    if (!containsSize) bits.add(size);
    final slope = part.slope;
    if (slope != null && slope.isNotEmpty) bits.add('坡向 $slope');
    return bits.join(' · ');
  }
}

/// 单个颜色变体：默认行只有颜色与库存，点开后可查看零件 ID 等细节。
class _VariantTile extends StatefulWidget {
  const _VariantTile({required this.part});

  final Part part;

  @override
  State<_VariantTile> createState() => _VariantTileState();
}

class _VariantTileState extends State<_VariantTile> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final part = widget.part;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          expanded: _open,
          button: true,
          label: '${part.colorName}，库存 ${part.count}，${_open ? '已展开详情' : '点按查看零件 ID 等详情'}',
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () => setState(() => _open = !_open),
            child: Container(
              constraints: const BoxConstraints(minHeight: 48),
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  ColorDot(part.hex, size: 16),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      part.colorName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 13),
                    ),
                  ),
                  Text(
                    '库存 ${part.count}',
                    style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                  ),
                  const SizedBox(width: 6),
                  Icon(
                    _open ? Icons.expand_less : Icons.expand_more,
                    size: 18,
                    color: AppColors.textDim,
                  ),
                ],
              ),
            ),
          ),
        ),
        if (_open) _buildDetails(part),
      ],
    );
  }

  /// 变体详情：零件 ID、尺寸、坡向与颜色标识，保证目录全部信息可访问。
  Widget _buildDetails(Part part) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(left: 26, bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.borderSoft),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _detailRow('零件 ID', part.id.trim().isEmpty ? '服务端未提供' : part.id),
          _detailRow('尺寸', '${part.w}×${part.d}（高 ${part.h}）'),
          if (part.slope != null && part.slope!.isNotEmpty)
            _detailRow('坡向', part.slope!),
          if (part.colorKey.isNotEmpty) _detailRow('颜色标识', part.colorKey),
        ],
      ),
    );
  }

  /// 详情行：标签 + 值，零件 ID 使用等宽字体便于核对。
  Widget _detailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: TextStyle(
                fontSize: 11.5,
                height: 1.4,
                color: AppColors.text,
                fontFamily: label == '零件 ID' ? 'monospace' : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
