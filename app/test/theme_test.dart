import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:legogod_app/core/theme.dart';
import 'package:legogod_app/three_d/lego_3d_view.dart';
import 'package:legogod_app/ui/widgets/common.dart';

double contrast(Color foreground, Color background) {
  final first = foreground.computeLuminance();
  final second = background.computeLuminance();
  final high = first > second ? first : second;
  final low = first > second ? second : first;
  return (high + 0.05) / (low + 0.05);
}

void main() {
  test('明亮积木工坊：浅色 Material 主题与黄底深字主按钮', () {
    final theme = buildTheme();

    expect(theme.brightness, Brightness.light);
    expect(theme.colorScheme.brightness, Brightness.light);
    expect(theme.scaffoldBackgroundColor, AppColors.bg);
    expect(theme.colorScheme.surface, AppColors.surface);
    expect(theme.cardTheme.color, AppColors.surface);
    expect(theme.inputDecorationTheme.fillColor, AppColors.bgElevated);
    expect(theme.dialogTheme.backgroundColor, AppColors.surface);

    final buttonStyle = theme.filledButtonTheme.style;
    expect(
      buttonStyle?.backgroundColor?.resolve(const <WidgetState>{}),
      AppColors.yellow,
    );
    expect(
      buttonStyle?.foregroundColor?.resolve(const <WidgetState>{}),
      const Color(0xFF201404),
    );
    final selectedLabel = theme.navigationBarTheme.labelTextStyle?.resolve(
      const <WidgetState>{WidgetState.selected},
    );
    expect(selectedLabel?.color, AppColors.yellowDeep);
    expect(theme.tabBarTheme.labelColor, AppColors.yellowDeep);
  });

  test('正文、弱提示和状态文字在浅底上达到 4.5:1', () {
    final pairs = <(Color, Color)>[
      (AppColors.text, AppColors.bg),
      (AppColors.textMuted, AppColors.surface),
      (AppColors.textDim, AppColors.bg),
      (AppColors.yellowDeep, AppColors.yellowSoft),
      (AppColors.ok, AppColors.surface),
      (AppColors.warn, AppColors.surface),
      (AppColors.danger, AppColors.surface),
      (AppColors.run, AppColors.surface),
      (AppColors.fallback, AppColors.surface),
      (const Color(0xFF201404), AppColors.yellow),
    ];
    for (final (foreground, background) in pairs) {
      expect(
        contrast(foreground, background),
        greaterThanOrEqualTo(4.5),
        reason: '$foreground / $background',
      );
    }
    expect(contrast(Colors.white, AppColors.danger), greaterThanOrEqualTo(4.5));
  });

  testWidgets('原生 3D 统一使用浅色舞台', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Scaffold(
          body: SizedBox(width: 320, height: 240, child: Lego3DView()),
        ),
      ),
    );

    final stage = tester.widget<ColoredBox>(
      find.descendant(
        of: find.byType(Lego3DView),
        matching: find.byType(ColoredBox),
      ),
    );
    expect(stage.color, AppColors.stage);
  });

  testWidgets('白色和浅灰零件色块保留可见边界', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Scaffold(body: ColorDot('#F2F3F2')),
      ),
    );

    final container = tester.widget<Container>(
      find.descendant(
        of: find.byType(ColorDot),
        matching: find.byType(Container),
      ),
    );
    final decoration = container.decoration! as BoxDecoration;
    final border = decoration.border! as Border;
    expect(border.top.color, AppColors.border);
  });
}
