

import 'package:flutter/material.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../responsive.dart';
import '../tokens.dart';


class DashboardScaffold extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData? icon;
  final Color? iconColor;
  final List<Widget> actions;
  final Widget body;
  final bool isMobile;
  final double maxContentWidth;

  const DashboardScaffold({
    super.key,
    required this.title,
    required this.body,
    this.subtitle,
    this.icon,
    this.iconColor,
    this.actions = const [],
    this.isMobile = false,
    this.maxContentWidth = 1080,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: EdgeInsets.symmetric(
        horizontal: isMobile ? VaultSpacing.md : VaultSpacing.xl2,
        vertical: isMobile ? VaultSpacing.md : VaultSpacing.xl,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxContentWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FadeSlideIn(
                child: _DashboardHeader(
                  title: title,
                  subtitle: subtitle,
                  icon: icon,
                  iconColor: iconColor,
                  actions: actions,
                ),
              ),
              SizedBox(height: isMobile ? VaultSpacing.md : VaultSpacing.lg),
              body,
            ],
          ),
        ),
      ),
    );
  }
}

class _DashboardHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData? icon;
  final Color? iconColor;
  final List<Widget> actions;

  const _DashboardHeader({
    required this.title,
    this.subtitle,
    this.icon,
    this.iconColor,
    this.actions = const [],
  });

  @override
  Widget build(BuildContext context) {
    // 2026-07-12: header was a rigid Row that squeezed the title
    // area between a 52dp badge, a subtitle wrapping to 3+ lines,
    // and a full-width action button on narrow phones (320-430dp).
    // Now the header uses LayoutBuilder + responsive font sizes so:
    //   * < 600dp: badge + title/subtitle stack on top; actions
    //     drop below on their own row, wrapping if there are many.
    //   * >= 600dp: original single-row layout (icon + title/sub +
    //     actions trailing).
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow =
            constraints.maxWidth < VaultBreakpoints.compactMax;
        return VaultCard(
          padding: EdgeInsets.all(
            narrow ? VaultSpacing.lg : VaultSpacing.xl,
          ),
          child: narrow
              ? _buildNarrow(context)
              : _buildWide(context),
        );
      },
    );
  }

  Widget _buildTitleColumn(BuildContext context, {required bool narrow}) {
    final titleStyle = VaultText.headline.copyWith(
      fontSize: narrow ? vrHeadline(context) : null,
    );
    final subtitleStyle = VaultText.bodyLg.copyWith(
      color: VaultColors.textSecondary,
      fontSize: narrow ? 14 : null,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(title, style: titleStyle),
        if (subtitle != null) ...[
          const SizedBox(height: VaultSpacing.xs + 2),
          Text(subtitle!, style: subtitleStyle),
        ],
      ],
    );
  }

  Widget _buildWide(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        if (icon != null) ...[
          IconBadge(icon: icon!, color: iconColor, size: 52),
          const SizedBox(width: VaultSpacing.lg),
        ],
        Expanded(child: _buildTitleColumn(context, narrow: false)),
        if (actions.isNotEmpty) ...[
          const SizedBox(width: VaultSpacing.md),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.sm,
            children: actions,
          ),
        ],
      ],
    );
  }

  Widget _buildNarrow(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            if (icon != null) ...[
              IconBadge(icon: icon!, color: iconColor, size: 40),
              const SizedBox(width: VaultSpacing.md),
            ],
            Expanded(child: _buildTitleColumn(context, narrow: true)),
          ],
        ),
        if (actions.isNotEmpty) ...[
          const SizedBox(height: VaultSpacing.md),
          Wrap(
            alignment: WrapAlignment.start,
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.sm,
            children: actions,
          ),
        ],
      ],
    );
  }
}


class DashboardSection extends StatelessWidget {
  final String title;
  final String? hint;
  final IconData? icon;
  final Widget child;
  final Widget? trailing;

  const DashboardSection({
    super.key,
    required this.title,
    required this.child,
    this.hint,
    this.icon,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: VaultSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.only(
              left: VaultSpacing.xs,
              right: VaultSpacing.xs,
              bottom: VaultSpacing.sm,
            ),
            child: Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: 16, color: VaultColors.textSecondary),
                  const SizedBox(width: VaultSpacing.sm),
                ],
                Expanded(
                  child: Text(title, style: VaultText.subtitle),
                ),
                if (trailing != null) trailing!,
              ],
            ),
          ),
          if (hint != null)
            Padding(
              padding: const EdgeInsets.only(
                left: VaultSpacing.xs,
                bottom: VaultSpacing.sm,
              ),
              child: Text(hint!, style: VaultText.caption),
            ),
          child,
        ],
      ),
    );
  }
}


class DashboardLoading extends StatelessWidget {
  final String? message;
  const DashboardLoading({super.key, this.message});

  @override
  Widget build(BuildContext context) {
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.xl2),
      child: Column(
        children: [
          const SizedBox(
            width: 28,
            height: 28,
            child: CircularProgressIndicator(strokeWidth: 2.4),
          ),
          if (message != null) ...[
            const SizedBox(height: VaultSpacing.md),
            Text(message!, style: VaultText.caption),
          ],
        ],
      ),
    );
  }
}

class DashboardEmpty extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData icon;

  const DashboardEmpty({
    super.key,
    required this.title,
    this.subtitle,
    this.icon = Icons.spa_outlined,
  });

  @override
  Widget build(BuildContext context) {
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.xl2),
      child: Column(
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: VaultColors.severityOkSoft,
              borderRadius: BorderRadius.circular(VaultRadius.lg),
            ),
            child: Icon(icon, size: 28, color: VaultColors.severityOk),
          ),
          const SizedBox(height: VaultSpacing.md),
          Text(title, style: VaultText.subtitle, textAlign: TextAlign.center),
          if (subtitle != null) ...[
            const SizedBox(height: VaultSpacing.sm),
            Text(
              subtitle!,
              style: VaultText.caption,
              textAlign: TextAlign.center,
            ),
          ],
        ],
      ),
    );
  }
}

class DashboardError extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;

  const DashboardError({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return VaultCard(
      accentSide: const BorderSide(color: VaultColors.severityCrit, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.xl),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          const Icon(
            Icons.error_outline,
            color: VaultColors.severityCrit,
            size: 28,
          ),
          const SizedBox(width: VaultSpacing.md),
          Expanded(child: Text(message, style: VaultText.body)),
          if (onRetry != null) ...[
            const SizedBox(width: VaultSpacing.md),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh, size: 18),
              label: Text(AppLocalizations.of(context).commonRetry),
            ),
          ],
        ],
      ),
    );
  }
}
