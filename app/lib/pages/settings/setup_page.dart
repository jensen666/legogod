// 首次启动连接引导：尚未配置服务地址时展示，不展示任何虚构任务或零件。
import 'package:flutter/material.dart';

import '../../app_scope.dart';
import '../../core/theme.dart';
import '../../ui/widgets/common.dart';
import 'service_form.dart';

/// 首次连接设置页。
class SetupPage extends StatelessWidget {
  const SetupPage({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: app,
          builder: (context, _) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 28, 20, 32),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('🧱', style: TextStyle(fontSize: 44)),
                const SizedBox(height: 10),
                const Text(
                  'LEGOGOD',
                  style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: AppColors.yellowDeep,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  '连接你的 LEGOGOD 服务，开始用手机拼装。',
                  style: TextStyle(color: AppColors.textMuted, fontSize: 14),
                ),
                const SizedBox(height: 20),
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        '首次连接设置',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'APP 不内置任何服务地址、模型密钥或离线假数据；所有作品都由你配置的真实服务端生成。'
                        '局域网自托管可以用 http，公网服务请使用 https 并配置访问令牌。',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                          height: 1.5,
                        ),
                      ),
                      const SizedBox(height: 16),
                      ServiceForm(
                        initialUrl: app.address?.url ?? '',
                        initialToken: app.tokenForInput,
                        firstRun: true,
                        saveLabel: '保存并进入',
                        onTestConnection: (url, token) =>
                            app.testConnection(rawUrl: url, token: token),
                        onSave: (url, token) async {
                          // 首次进入必须先通过真实连接检查（健康 + 鉴权），
                          // 避免进入后展示一片假空态。
                          final check = await app.testConnection(
                            rawUrl: url,
                            token: token,
                          );
                          if (!check.ok) return check;
                          return app.applyService(rawUrl: url, token: token);
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                const InfoBanner(
                  icon: 'ℹ️',
                  text:
                      '服务端启动示例：python -m legogod api --host 0.0.0.0 --port 8600；'
                      '非回环监听需要用 LEGOGOD_API_TOKEN 配置令牌，手机与电脑需在同一局域网。',
                  tone: 'info',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
