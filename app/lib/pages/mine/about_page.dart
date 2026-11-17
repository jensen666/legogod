// 关于页：版本号、支持平台与数据来源说明；不展示任何账号 / 会员 / 社交入口。
import 'package:flutter/material.dart';

import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../ui/widgets/common.dart';

/// 关于页。
class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('关于')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 20, 16, 32),
        children: [
          const Center(child: Text('🧱', style: TextStyle(fontSize: 52))),
          const SizedBox(height: 10),
          const Center(
            child: Text(
              'LEGOGOD 手机 APP',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: AppColors.yellowDeep,
              ),
            ),
          ),
          const SizedBox(height: 6),
          const Center(
            child: Text(
              '版本 ${AppState.appVersion} · Android',
              style: TextStyle(fontSize: 12, color: AppColors.textMuted),
            ),
          ),
          const SizedBox(height: 24),
          const AppCard(
            child: Text(
              '所有作品均由真实服务端生成；APP 不内置 mock 数据，不保存模型密钥。',
              style: TextStyle(fontSize: 13, height: 1.6),
            ),
          ),
          const SizedBox(height: 12),
          const AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '支持平台',
                  style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700),
                ),
                SizedBox(height: 6),
                Text(
                  '本期仅支持 Android；iOS 未在本期支持范围内，'
                  '因此不会提供 iOS 安装包或 iPad 适配说明。',
                  style: TextStyle(
                    fontSize: 12.5,
                    height: 1.6,
                    color: AppColors.textMuted,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const InfoBanner(
            icon: 'ℹ️',
            tone: 'info',
            text: 'APP 不内置任何服务地址或演示数据；首次使用需在「我的 → 服务连接」'
                '配置你的 LEGOGOD 服务地址，必要时再填写访问令牌。',
          ),
        ],
      ),
    );
  }
}
