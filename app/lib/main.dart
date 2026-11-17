// LEGOGOD 手机 APP 入口：只负责初始化绑定并启动根组件。
import 'package:flutter/material.dart';

import 'app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const LegogodApp());
}
