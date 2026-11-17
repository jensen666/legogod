// 应用状态注入：所有页面通过 AppScope 获取 AppState（InheritedNotifier 自动订阅）。
import 'package:flutter/widgets.dart';

import 'core/app_state.dart';

/// 全局状态作用域。
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
      : super(notifier: state);

  /// 获取状态并订阅变化（build 中使用）。
  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope?.notifier != null, 'AppScope 未找到：组件必须在 LegogodApp 内使用');
    return scope!.notifier!;
  }

  /// 只读取状态、不订阅（事件回调中使用）。
  static AppState read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<AppScope>();
    assert(scope?.notifier != null, 'AppScope 未找到：组件必须在 LegogodApp 内使用');
    return scope!.notifier!;
  }
}
