// 启动门：读取本地配置后决定进入首次连接引导还是主界面。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/theme.dart';
import '../settings/setup_page.dart';
import '../shell/root_shell.dart';

/// 启动门。
class BootGate extends StatelessWidget {
  const BootGate({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return ListenableBuilder(
      listenable: app,
      builder: (context, _) {
        if (!app.booted) {
          return const _SplashView();
        }
        if (!app.configured) {
          return const SetupPage();
        }
        return const RootShell();
      },
    );
  }
}

class _SplashView extends StatelessWidget {
  const _SplashView();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.bg,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('🧱', style: TextStyle(fontSize: 56)),
            SizedBox(height: 16),
            Text(
              'LEGOGOD',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w800,
                color: AppColors.yellowDeep,
              ),
            ),
            SizedBox(height: 8),
            Text(
              '正在读取本地配置……',
              style: TextStyle(color: AppColors.textMuted, fontSize: 13),
            ),
            SizedBox(height: 20),
            SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2.2),
            ),
          ],
        ),
      ),
    );
  }
}
