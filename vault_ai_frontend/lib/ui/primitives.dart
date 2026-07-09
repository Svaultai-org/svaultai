

import 'package:flutter/material.dart';
import 'tokens.dart';


class VaultCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radius;
  final Color? color;
  final Color? borderColor;
  final List<BoxShadow>? boxShadow;
  final VoidCallback? onTap;
  final BorderSide? accentSide;

  const VaultCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(VaultSpacing.xl),
    this.radius = VaultRadius.xl,
    this.color,
    this.borderColor,
    this.boxShadow,
    this.onTap,
    this.accentSide,
  });

  @override
  Widget build(BuildContext context) {
    final bg = color ?? VaultColors.surface;
    final border = borderColor ?? VaultColors.borderSubtle;
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(radius),
      side: BorderSide(color: border),
    );

    final inner = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: border),
        boxShadow: boxShadow ?? VaultShadows.e1,
        
        gradient: accentSide == null
            ? null
            : LinearGradient(
                begin: Alignment.centerLeft,
                end: Alignment.centerRight,
                colors: [
                  accentSide!.color.withValues(alpha: 0.10),
                  bg,
                ],
                stops: const [0.0, 0.18],
              ),
      ),
      child: child,
    );

    if (onTap == null) return inner;
    return Material(
      color: Colors.transparent,
      shape: shape,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        splashColor: VaultColors.accentSoft,
        highlightColor: VaultColors.surfaceHover,
        child: inner,
      ),
    );
  }
}


class SeverityChip extends StatelessWidget {
  final String level; 
  final String label;
  final IconData? icon;

  const SeverityChip({
    super.key,
    required this.level,
    required this.label,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final color = VaultColors.forSeverity(level);
    final bg = VaultColors.forSeveritySoft(level);
    
    
    return Semantics(
      container: true,
      label: '${_levelHint(level)}: $label',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.md,
          vertical: VaultSpacing.xs,
        ),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(VaultRadius.pill),
          border: Border.all(color: color.withValues(alpha: 0.30)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 14, color: color),
              const SizedBox(width: VaultSpacing.xs + 2),
            ] else ...[
              Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: VaultSpacing.sm),
            ],
            Text(
              label,
              style: VaultText.caption.copyWith(
                color: color,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.2,
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _levelHint(String level) {
    switch (level.toLowerCase()) {
      case 'critical': return 'Critical';
      case 'warning':  return 'Warning';
      case 'info':     return 'Info';
      case 'ok':       return 'OK';
      default:         return level;
    }
  }
}


class MetaPill extends StatelessWidget {
  final String label;
  final IconData? icon;
  final Color? tint;
  final bool dim;

  const MetaPill({
    super.key,
    required this.label,
    this.icon,
    this.tint,
    this.dim = false,
  });

  @override
  Widget build(BuildContext context) {
    final fg = tint ?? (dim ? VaultColors.textTertiary : VaultColors.textSecondary);
    final bg = (tint == null)
        ? VaultColors.surfaceMuted
        : tint!.withValues(alpha: 0.12);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: icon == null ? VaultSpacing.md : VaultSpacing.sm + 2,
        vertical: VaultSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(VaultRadius.pill),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: fg),
            const SizedBox(width: VaultSpacing.xs + 2),
          ],
          
          
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              softWrap: false,
              style: VaultText.caption.copyWith(
                color: fg,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


class IconBadge extends StatelessWidget {
  final IconData icon;
  final Color? color;
  final double size;
  final double radius;
  final bool soft;

  const IconBadge({
    super.key,
    required this.icon,
    this.color,
    this.size = 44,
    this.radius = VaultRadius.md,
    this.soft = true,
  });

  @override
  Widget build(BuildContext context) {
    final c = color ?? VaultColors.accent;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: soft ? c.withValues(alpha: 0.14) : c,
          borderRadius: BorderRadius.circular(radius),
        ),
        child: Icon(
          icon,
          color: soft ? c : VaultColors.textOnAccent,
          size: size * 0.5,
        ),
      ),
    );
  }
}


class CardHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData? icon;
  final Color? iconColor;
  final Widget? trailing;

  const CardHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.icon,
    this.iconColor,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        if (icon != null) ...[
          IconBadge(icon: icon!, color: iconColor, size: 40),
          const SizedBox(width: VaultSpacing.md),
        ],
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(title, style: VaultText.subtitle),
              if (subtitle != null) ...[
                const SizedBox(height: 2),
                Text(
                  subtitle!,
                  style: VaultText.caption,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ],
          ),
        ),
        if (trailing != null) ...[
          const SizedBox(width: VaultSpacing.md),
          trailing!,
        ],
      ],
    );
  }
}
