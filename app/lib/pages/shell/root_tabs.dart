// 底部主导航切换控制：页面（如历史「查看进度」）可据此回到创作页展示实时过程。
import 'package:flutter/widgets.dart';

/// 主导航控制器。
class RootTabsController extends ChangeNotifier {
  int _index = 0;

  int get index => _index;

  void select(int index) {
    if (index == _index) return;
    _index = index;
    notifyListeners();
  }
}

/// 主导航作用域。
class RootTabsScope extends InheritedNotifier<RootTabsController> {
  const RootTabsScope({super.key, required RootTabsController controller, required super.child})
      : super(notifier: controller);

  static RootTabsController of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<RootTabsScope>();
    assert(scope?.notifier != null, 'RootTabsScope 未找到');
    return scope!.notifier!;
  }

  static RootTabsController read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<RootTabsScope>();
    assert(scope?.notifier != null, 'RootTabsScope 未找到');
    return scope!.notifier!;
  }
}
