// 应用根组件：初始化状态、注册生命周期监听、挂载主题与页面路由。
import 'dart:async';

import 'package:flutter/material.dart';

import 'app_scope.dart';
import 'core/app_state.dart';
import 'core/theme.dart';
import 'pages/boot/boot_gate.dart';

/// LEGOGOD 根组件。
class LegogodApp extends StatefulWidget {
  const LegogodApp({super.key, this.state});

  /// 可注入状态（组件测试/集成测试用）；为空时创建真实状态。
  final AppState? state;

  @override
  State<LegogodApp> createState() => _LegogodAppState();
}

class _LegogodAppState extends State<LegogodApp> with WidgetsBindingObserver {
  late final AppState _app = widget.state ?? AppState();
  bool get _ownsState => widget.state == null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_app.init());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _app.onLifecycleChanged(state);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (_ownsState) _app.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: _app,
      child: MaterialApp(
        title: 'LEGOGOD',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: const BootGate(),
      ),
    );
  }
}
