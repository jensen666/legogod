// 服务连接页（由旧设置页迁移）：连接状态、地址 / Bearer 令牌配置、测试连接、
// 令牌安全说明与断开服务连接；原始网络错误只在本页与「诊断与高级」展示。
// 不显示任何模型密钥；令牌默认遮蔽且不进入日志。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../ui/widgets/common.dart';
import '../settings/service_form.dart';
import '../shell/root_tabs.dart';

/// 服务连接页。
class ServicePage extends StatelessWidget {
  const ServicePage({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('服务连接')),
      body: ListenableBuilder(
        listenable: app,
        builder: (context, _) {
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              _buildStatusCard(context, app),
              const SectionTitle('服务地址与令牌'),
              AppCard(
                child: Column(
                  children: [
                    _buildServiceForm(context, app),
                    const SizedBox(height: 14),
                    const InfoBanner(
                      icon: '🔐',
                      tone: 'info',
                      text: '令牌只保存在系统安全存储中，只在请求头 Authorization 中使用；'
                          'APP 不保存模型 API Key，模型密钥只在服务端。',
                    ),
                  ],
                ),
              ),
              const SectionTitle('服务管理'),
              _buildManagementCard(context),
            ],
          );
        },
      ),
    );
  }

  /// 当前连接状态卡：在线 / 离线 / 未知 / 未配置，原始错误只在这里展示。
  Widget _buildStatusCard(BuildContext context, AppState app) {
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
        ? '尚未配置服务'
        : online
            ? '服务已连接'
            : offline
                ? '服务不可达（当前显示缓存数据）'
                : '连接状态未知';
    final error = app.lastNetworkError;
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
                if (error != null && error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      '最近错误：$error',
                      style: const TextStyle(fontSize: 11.5, color: AppColors.danger),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 服务连接表单：地址、Bearer 令牌、测试连接与保存（保存后展示真实检查结果）。
  Widget _buildServiceForm(BuildContext context, AppState app) {
    return Container(
      key: const Key('service-form'),
      child: ServiceForm(
        initialUrl: app.address?.url ?? '',
        initialToken: app.tokenForInput,
        saveLabel: '保存配置',
        onTestConnection: (url, token) =>
            app.testConnection(rawUrl: url, token: token),
        onSave: (url, token) async {
          final check = await app.applyService(rawUrl: url, token: token);
          if (context.mounted) {
            showNotice(
              context,
              check.ok
                  ? '服务配置已保存，连接正常'
                  : '配置已保存，但连接检查未通过：${check.error ?? '请稍后重试'}',
            );
          }
          return check;
        },
      ),
    );
  }

  /// 服务管理：切换服务清空旧缓存说明 + 断开连接（二次确认，保留服务端任务）。
  Widget _buildManagementCard(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '切换服务地址会自动清空旧服务的任务、产物与零件缓存，避免不同服务的数据混用。',
            style: TextStyle(color: AppColors.textMuted, fontSize: 12, height: 1.5),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.danger,
              side: BorderSide(color: AppColors.danger.withValues(alpha: 0.5)),
              minimumSize: const Size(48, 48),
            ),
            onPressed: () => _disconnect(context),
            icon: const Icon(Icons.link_off, size: 18),
            label: const Text('断开服务连接'),
          ),
        ],
      ),
    );
  }

  /// 断开服务连接：先确认，再清除本地配置与缓存（服务端任务不受影响）。
  Future<void> _disconnect(BuildContext context) async {
    final app = AppScope.read(context);
    final confirmed = await showConfirmDialog(
      context,
      title: '断开服务连接',
      message: '将清除本地保存的服务地址与令牌，以及本地缓存的界面数据。'
          '服务端任务不会被删除或取消。',
      confirmText: '断开',
      danger: true,
    );
    if (!confirmed) return;
    await app.disconnectService();
    if (!context.mounted) return;
    // 断开后回到创作 Tab 并关闭压在主界面上的页面；单独挂载在本页的测试环境只关闭路由。
    final tabs = context.getInheritedWidgetOfExactType<RootTabsScope>();
    tabs?.notifier?.select(0);
    Navigator.of(context).popUntil((route) => route.isFirst);
  }
}
