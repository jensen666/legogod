// 主导航壳：创作 / 作品 / 我的 三个底部入口。
// - 作品入口显示真实进行中数量角标，数量为 0 时隐藏（从原「任务」入口迁移）。
// - 返回键规则：先返回主导航（非创作 Tab → 切到创作），在创作页再按返回才退出。
// - 离线横幅只显示用户可理解的提示与重试，原始错误与诊断日志保留在「我的 → 诊断与高级」。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../create/create_page.dart';
import '../mine/mine_page.dart';
import '../works/works_page.dart';
import 'root_tabs.dart';

/// 主界面外壳。
class RootShell extends StatefulWidget {
  const RootShell({super.key});

  @override
  State<RootShell> createState() => _RootShellState();
}

class _RootShellState extends State<RootShell> {
  final RootTabsController _tabs = RootTabsController();

  @override
  void initState() {
    super.initState();
    _tabs.addListener(_onTabChanged);
  }

  void _onTabChanged() {
    setState(() {});
    final app = AppScope.read(context);
    if (_tabs.index == 1) {
      // 切到作品页时主动刷新最新状态（不阻塞页面渲染）；已有数据时静默刷新。
      app.refreshRunning(silent: true);
      app.refreshWorksForSegment(silent: true);
    } else if (_tabs.index == 2 && app.parts.parts.isEmpty) {
      app.refreshParts();
    }
  }

  @override
  void dispose() {
    _tabs.removeListener(_onTabChanged);
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final index = _tabs.index;
    return RootTabsScope(
      controller: _tabs,
      child: PopScope(
        canPop: index == 0,
        onPopInvokedWithResult: (didPop, result) {
          if (didPop) return;
          if (index != 0) {
            _tabs.select(0);
          }
        },
        child: Scaffold(
          body: Column(
            children: [
              _ConnectionBanner(app: app),
              Expanded(
                child: IndexedStack(
                  index: index,
                  children: const [CreatePage(), WorksPage(), MinePage()],
                ),
              ),
            ],
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: index,
            onDestinationSelected: _tabs.select,
            destinations: [
              const NavigationDestination(
                icon: Icon(Icons.edit_outlined),
                selectedIcon: Icon(Icons.edit),
                label: '创作',
              ),
              NavigationDestination(
                icon: _WorksIcon(count: app.runningCount, selected: false),
                selectedIcon: _WorksIcon(
                  count: app.runningCount,
                  selected: true,
                ),
                label: '作品',
              ),
              const NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon: Icon(Icons.person),
                label: '我的',
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 作品图标 + 进行中数量角标（为 0 时隐藏）。
class _WorksIcon extends StatelessWidget {
  const _WorksIcon({required this.count, required this.selected});

  final int count;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final icon = Icon(selected ? Icons.grid_view : Icons.grid_view_outlined);
    if (count <= 0) return icon;
    return Badge(
      label: Text('$count'),
      backgroundColor: AppColors.yellow,
      textColor: const Color(0xFF201404),
      child: icon,
    );
  }
}

/// 服务不可达横幅：只显示用户能理解的缓存提示与重试（详细诊断在「我的」）。
class _ConnectionBanner extends StatelessWidget {
  const _ConnectionBanner({required this.app});

  final AppState app;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: app,
      builder: (context, _) {
        if (app.connection != ServiceConnection.offline) {
          return const SizedBox.shrink();
        }
        return Container(
          width: double.infinity,
          color: AppColors.danger.withValues(alpha: 0.10),
          padding: EdgeInsets.only(
            top: MediaQuery.of(context).padding.top + 6,
            left: 12,
            right: 8,
            bottom: 6,
          ),
          child: Row(
            children: [
              const Icon(Icons.cloud_off, size: 16, color: AppColors.danger),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  '连接已断开，当前为缓存数据',
                  style: TextStyle(fontSize: 12, color: AppColors.danger),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              TextButton(
                onPressed: () async {
                  await app.refreshRunning(silent: false);
                  await app.refreshParts();
                },
                child: const Text('重试', style: TextStyle(fontSize: 12)),
              ),
            ],
          ),
        );
      },
    );
  }
}
