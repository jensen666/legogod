// 我的页：只作为工具容器，不新增账号、会员、社交或云同步入口。
// - 顶部服务连接状态卡：在线只显示「服务已连接」+ 地址 + 服务连接入口；
//   离线显示「连接已断开，当前为缓存数据」+ 重试，原始错误与诊断收进「诊断与高级」；
// - 分组入口：零件目录、服务连接、生成规则、诊断与高级、关于（每行不小于 48dp）。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/route_nav.dart';
import '../../core/theme.dart';
import '../../models/part.dart';
import '../../ui/widgets/common.dart';
import '../parts/parts_page.dart';
import 'about_page.dart';

/// 我的页。
class MinePage extends StatelessWidget {
  const MinePage({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
        children: [
          _ConnectionCard(app: app),
          const SizedBox(height: 16),
          _buildEntries(context, app),
        ],
      ),
    );
  }

  /// 工具入口分组列表。
  Widget _buildEntries(BuildContext context, AppState app) {
    final parts = app.parts;
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          _MineEntry(
            key: const Key('mine-parts'),
            icon: Icons.extension_outlined,
            title: '零件目录',
            subtitle: _partsSubtitle(parts),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const PartsPage()),
            ),
          ),
          const Divider(height: 1, indent: 56),
          _MineEntry(
            key: const Key('mine-service'),
            icon: Icons.dns_outlined,
            title: '服务连接与令牌',
            subtitle: app.address?.url ?? '配置服务地址与访问令牌',
            onTap: () => openServicePage(context),
          ),
          const Divider(height: 1, indent: 56),
          _MineEntry(
            key: const Key('mine-rules'),
            icon: Icons.menu_book_outlined,
            title: '生成规则',
            subtitle: '两档生成模式与库存规则说明',
            onTap: () => openRulesPage(context),
          ),
          const Divider(height: 1, indent: 56),
          _MineEntry(
            key: const Key('mine-diagnostics'),
            icon: Icons.monitor_heart_outlined,
            title: '诊断与高级',
            subtitle: '连接诊断、原始错误与调试日志',
            onTap: () => openDiagnosticsPage(context),
          ),
          const Divider(height: 1, indent: 56),
          _MineEntry(
            key: const Key('mine-about'),
            icon: Icons.info_outline,
            title: '关于',
            subtitle: '版本、支持平台与数据说明',
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const AboutPage()),
            ),
          ),
        ],
      ),
    );
  }

  /// 零件目录副标题：已加载时展示真实的形状数与变体数，未加载时给功能说明。
  String _partsSubtitle(PartsCatalog catalog) {
    if (catalog.parts.isEmpty) return '查看全部形状、颜色与库存';
    return '${catalog.shapeCount} 种形状 · ${catalog.variantCount} 个变体';
  }
}

/// 服务连接状态卡：区分在线 / 离线 / 未知 / 未配置四种真实状态。
class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard({required this.app});

  final AppState app;

  @override
  Widget build(BuildContext context) {
    final unconfigured = !app.configured;
    final online = app.connection == ServiceConnection.online;
    final offline = app.connection == ServiceConnection.offline;
    final icon = unconfigured
        ? Icons.link_off
        : online
            ? Icons.cloud_done
            : offline
                ? Icons.cloud_off
                : Icons.cloud_queue;
    final color = unconfigured
        ? AppColors.textMuted
        : online
            ? AppColors.ok
            : offline
                ? AppColors.danger
                : AppColors.textMuted;
    final title = unconfigured
        ? '尚未连接服务'
        : online
            ? '服务已连接'
            : offline
                ? '连接已断开，当前为缓存数据'
                : '连接状态未知';
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Icon(icon, color: color, size: 22),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 3),
                Text(
                  app.address?.url ?? '未配置服务地址',
                  style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
                ),
                if (offline)
                  const Padding(
                    padding: EdgeInsets.only(top: 3),
                    child: Text(
                      '网络恢复后可点「重试」重新同步；详细原因见「诊断与高级」。',
                      style: TextStyle(fontSize: 11, color: AppColors.textDim),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 6),
          if (unconfigured)
            TextButton(
              onPressed: () => openServicePage(context),
              child: const Text('去连接'),
            )
          else if (offline)
            OutlinedButton(
              onPressed: () async {
                final state = AppScope.read(context);
                await state.refreshRunning(silent: false);
                await state.refreshParts();
              },
              child: const Text('重试'),
            )
          else
            TextButton(
              onPressed: () => openServicePage(context),
              child: const Text('服务连接'),
            ),
        ],
      ),
    );
  }
}

/// 「我的」分组入口行（整行可点，触控高度不小于 48dp）。
class _MineEntry extends StatelessWidget {
  const _MineEntry({
    super.key,
    required this.icon,
    required this.title,
    required this.onTap,
    this.subtitle,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      minVerticalPadding: 12,
      leading: Icon(icon, color: AppColors.yellowDeep),
      title: Text(
        title,
        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      ),
      subtitle: subtitle == null
          ? null
          : Text(
              subtitle!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11.5, color: AppColors.textMuted),
            ),
      trailing: const Icon(Icons.chevron_right, size: 20, color: AppColors.textDim),
    );
  }
}
