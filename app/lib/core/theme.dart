// LEGOGOD 明亮积木工坊视觉规范：浅色表面、乐高黄强调色；状态不只靠颜色区分。
import 'package:flutter/material.dart';

/// 主题色板。
class AppColors {
  AppColors._();

  static const bg = Color(0xFFF5F6F8);
  static const bgElevated = Color(0xFFFFFFFF);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceHigh = Color(0xFFEEF1F5);
  static const stage = Color(0xFFE9EEF3);
  static const border = Color(0xFFD7DDE5);
  static const borderSoft = Color(0xFFE5E9EF);
  static const text = Color(0xFF20242B);
  static const textMuted = Color(0xFF4B5563);
  static const textDim = Color(0xFF667085);
  static const yellow = Color(0xFFFFB02E);
  static const yellowDeep = Color(0xFF8A5500);
  static const yellowSoft = Color(0xFFFFF5DF);
  static const ok = Color(0xFF237A46);
  static const warn = Color(0xFF8A5A00);
  static const danger = Color(0xFFC4323B);
  static const run = Color(0xFF2468B4);
  static const fallback = Color(0xFF7A4B12);
  static const baseplate = Color(0xFF237841);

  /// 语义色调 → 颜色。
  static Color tone(String name) {
    switch (name) {
      case 'ok':
        return ok;
      case 'warn':
        return warn;
      case 'bad':
        return danger;
      case 'fb':
        return fallback;
      case 'run':
        return run;
      case 'info':
        return run;
      default:
        return textMuted;
    }
  }
}

/// 构建明亮积木工坊主题（Material 3 + 乐高黄强调色）。
ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: const ColorScheme.light(
      primary: AppColors.yellow,
      onPrimary: Color(0xFF201404),
      secondary: AppColors.yellow,
      surface: AppColors.surface,
      onSurface: AppColors.text,
      error: AppColors.danger,
      outline: AppColors.border,
    ),
    dividerColor: AppColors.borderSoft,
  );
  final textTheme = base.textTheme.apply(
    bodyColor: AppColors.text,
    displayColor: AppColors.text,
  );
  return base.copyWith(
    textTheme: textTheme.copyWith(
      titleLarge: textTheme.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
        fontSize: 20,
      ),
      titleMedium: textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
      bodyMedium: textTheme.bodyMedium?.copyWith(height: 1.5),
      bodySmall: textTheme.bodySmall?.copyWith(color: AppColors.textMuted),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      foregroundColor: AppColors.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: AppColors.borderSoft),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.bgElevated,
      hintStyle: const TextStyle(color: AppColors.textDim),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.yellowDeep, width: 1.4),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.danger),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.yellow,
        foregroundColor: const Color(0xFF201404),
        minimumSize: const Size(48, 52),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.text,
        minimumSize: const Size(48, 48),
        side: const BorderSide(color: AppColors.border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AppColors.yellowDeep,
        minimumSize: const Size(44, 44),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: AppColors.surface,
      labelStyle: const TextStyle(color: AppColors.text),
      side: const BorderSide(color: AppColors.border),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.bgElevated,
      indicatorColor: AppColors.yellow.withValues(alpha: 0.18),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 12,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w700
              : FontWeight.w500,
          color: states.contains(WidgetState.selected)
              ? AppColors.yellowDeep
              : AppColors.textMuted,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected)
              ? AppColors.yellowDeep
              : AppColors.textMuted,
        ),
      ),
      height: 64,
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: AppColors.yellowDeep,
      linearMinHeight: 4,
    ),
    sliderTheme: base.sliderTheme.copyWith(
      activeTrackColor: AppColors.yellowDeep,
      thumbColor: AppColors.yellowDeep,
      inactiveTrackColor: AppColors.border,
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AppColors.surfaceHigh,
      contentTextStyle: TextStyle(color: AppColors.text),
      behavior: SnackBarBehavior.floating,
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: AppColors.bgElevated,
      surfaceTintColor: Colors.transparent,
    ),
    dialogTheme: const DialogThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
    ),
    tabBarTheme: const TabBarThemeData(
      labelColor: AppColors.yellowDeep,
      unselectedLabelColor: AppColors.textMuted,
      indicatorColor: AppColors.yellow,
      dividerColor: AppColors.borderSoft,
    ),
  );
}
