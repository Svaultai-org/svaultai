

import 'package:flutter/material.dart';
import 'tokens.dart';

class VaultTheme {
  VaultTheme._();

  
  static ThemeData dark() {
    final base = ThemeData.dark(useMaterial3: true);

    final colorScheme = const ColorScheme.dark(
      brightness:    Brightness.dark,
      surface:       VaultColors.canvas,
      onSurface:     VaultColors.textPrimary,
      primary:       VaultColors.accent,
      onPrimary:     VaultColors.textOnAccent,
      secondary:     VaultColors.accentBright,
      onSecondary:   VaultColors.textOnAccent,
      error:         VaultColors.severityCrit,
      onError:       VaultColors.textOnAccent,
    );

    return base.copyWith(
      colorScheme: colorScheme,
      scaffoldBackgroundColor: VaultColors.canvas,
      canvasColor:             VaultColors.canvas,
      cardColor:               VaultColors.surface,
      dividerColor:            VaultColors.borderSubtle,
      hoverColor:              VaultColors.surfaceHover,
      splashFactory:           InkSparkle.splashFactory,

      textTheme: base.textTheme
          .apply(
            bodyColor:    VaultColors.textPrimary,
            displayColor: VaultColors.textPrimary,
          )
          .copyWith(
            displayLarge:  VaultText.display,
            headlineLarge: VaultText.headline,
            titleLarge:    VaultText.titleLg,
            titleMedium:   VaultText.title,
            titleSmall:    VaultText.subtitle,
            bodyLarge:     VaultText.bodyLg,
            bodyMedium:    VaultText.body,
            bodySmall:     VaultText.bodySm,
            labelLarge:    VaultText.subtitle,
            labelMedium:   VaultText.caption,
            labelSmall:    VaultText.caption,
          ),

      appBarTheme: const AppBarTheme(
        elevation: 0,
        backgroundColor: VaultColors.canvas,
        foregroundColor: VaultColors.textPrimary,
        surfaceTintColor: Colors.transparent,
        centerTitle: false,
      ),

      dialogTheme: DialogThemeData(
        backgroundColor: VaultColors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(VaultRadius.xl),
          side: const BorderSide(color: VaultColors.borderSubtle),
        ),
        titleTextStyle: VaultText.titleLg,
        contentTextStyle: VaultText.body,
      ),

      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: VaultColors.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(
            top: Radius.circular(VaultRadius.xl2),
          ),
        ),
      ),

      drawerTheme: const DrawerThemeData(
        backgroundColor: VaultColors.canvas,
        surfaceTintColor: Colors.transparent,
      ),

      cardTheme: CardThemeData(
        color: VaultColors.surface,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(VaultRadius.xl),
          side: const BorderSide(color: VaultColors.borderSubtle),
        ),
        margin: EdgeInsets.zero,
      ),

      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: VaultColors.surface,
        hintStyle: const TextStyle(
          color: VaultColors.textTertiary,
          fontSize: 14,
        ),
        labelStyle: const TextStyle(
          color: VaultColors.textSecondary,
          fontSize: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(VaultRadius.lg),
          borderSide: const BorderSide(color: VaultColors.borderSubtle),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(VaultRadius.lg),
          borderSide: const BorderSide(color: VaultColors.borderSubtle),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(VaultRadius.lg),
          borderSide: const BorderSide(color: VaultColors.accent, width: 1.4),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(VaultRadius.lg),
          borderSide: const BorderSide(color: VaultColors.severityCrit),
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.lg,
          vertical: VaultSpacing.md + 2,
        ),
      ),

      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: VaultColors.accent,
          foregroundColor: VaultColors.textOnAccent,
          textStyle: VaultText.subtitle,
          padding: const EdgeInsets.symmetric(
            horizontal: VaultSpacing.xl,
            vertical: VaultSpacing.md + 2,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(VaultRadius.md),
          ),
          elevation: 0,
        ),
      ),

      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: VaultColors.textPrimary,
          textStyle: VaultText.subtitle,
          side: const BorderSide(color: VaultColors.borderStrong),
          padding: const EdgeInsets.symmetric(
            horizontal: VaultSpacing.xl,
            vertical: VaultSpacing.md + 2,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(VaultRadius.md),
          ),
        ),
      ),

      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: VaultColors.accentBright,
          textStyle: VaultText.subtitle,
          padding: const EdgeInsets.symmetric(
            horizontal: VaultSpacing.md,
            vertical: VaultSpacing.sm,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(VaultRadius.md),
          ),
        ),
      ),

      iconTheme: const IconThemeData(
        color: VaultColors.textSecondary,
        size: 20,
      ),

      snackBarTheme: SnackBarThemeData(
        backgroundColor: VaultColors.surfaceElevated,
        contentTextStyle: VaultText.body,
        actionTextColor: VaultColors.accentBright,
        elevation: 0,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(VaultRadius.md),
          side: const BorderSide(color: VaultColors.borderSubtle),
        ),
      ),

      tooltipTheme: TooltipThemeData(
        decoration: BoxDecoration(
          color: VaultColors.surfaceElevated,
          borderRadius: BorderRadius.circular(VaultRadius.sm),
          border: Border.all(color: VaultColors.borderSubtle),
        ),
        textStyle: VaultText.bodySm,
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.md,
          vertical: VaultSpacing.sm,
        ),
        waitDuration: const Duration(milliseconds: 400),
      ),

      dividerTheme: const DividerThemeData(
        color: VaultColors.borderSubtle,
        thickness: 1,
        space: 1,
      ),

      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: VaultColors.accent,
        linearTrackColor: VaultColors.surfaceMuted,
        circularTrackColor: VaultColors.surfaceMuted,
      ),

      chipTheme: ChipThemeData(
        backgroundColor: VaultColors.surfaceMuted,
        labelStyle: VaultText.caption,
        side: const BorderSide(color: VaultColors.borderSubtle),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(VaultRadius.pill),
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.md,
          vertical: VaultSpacing.xs,
        ),
      ),
    );
  }
}
