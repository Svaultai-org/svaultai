
import 'dart:math' as math;

import 'package:flutter/material.dart';




class VaultBreakpoints {
  VaultBreakpoints._();




  static const double compactMax   =  600;

  static const double mediumMax    =  900;

  static const double expandedMax  = 1200;


  static const double phoneMin     =  320;

  static const double phoneNarrow  =  360;

  static const double phoneStandard=  390;

  static const double phoneLarge   =  430;

  static const double tabletMin    =  600;
}




class VaultResponsive {
  final double width;
  final double height;
  final EdgeInsets viewInsets;
  final EdgeInsets viewPadding;

  const VaultResponsive({
    required this.width,
    required this.height,
    required this.viewInsets,
    required this.viewPadding,
  });

  factory VaultResponsive.of(BuildContext context) {
    final mq = MediaQuery.of(context);
    return VaultResponsive(
      width:       mq.size.width,
      height:      mq.size.height,
      viewInsets:  mq.viewInsets,
      viewPadding: mq.viewPadding,
    );
  }


  bool get isMobile       => width < VaultBreakpoints.compactMax;

  bool get isNarrowMobile => width <= VaultBreakpoints.phoneNarrow;

  bool get isTablet       => width >= VaultBreakpoints.compactMax
                             && width < VaultBreakpoints.expandedMax;

  bool get isDesktop      => width >= VaultBreakpoints.expandedMax;




  double get pageHorizontalPadding {
    if (isNarrowMobile) return 12;
    if (isMobile)       return 16;
    if (isTablet)       return 24;
    return 32;
  }


  double get cardInsetPadding {
    if (isMobile) return 16;
    if (isTablet) return 20;
    return 24;
  }


  double get sectionSpacing {
    if (isMobile) return 12;
    return 16;
  }




  double get headingXlSize {
    if (isNarrowMobile) return 22;
    if (isMobile)       return 24;
    if (isTablet)       return 28;
    return 32;
  }

  double get headingLgSize {
    if (isNarrowMobile) return 18;
    if (isMobile)       return 20;
    return 22;
  }

  double get headingMdSize {
    if (isMobile) return 16;
    return 18;
  }




  // Design-token-parallel families. Each returns the fontSize that should
  // replace the corresponding VaultText.* hardcoded desktop value at this
  // viewport, preserving the visual hierarchy display > headline > titleLg
  // and never crossing tiers at any breakpoint.

  /// Scales VaultText.display (desktop 36). Use for hero numeric metrics
  /// (balance, big-value cards, landing hero). Narrow phone gets 26 so a
  /// long value like "1,234,567" still fits ~half the SE width.
  double get displaySize {
    if (isNarrowMobile) return 26;
    if (isMobile)       return 28;
    if (isTablet)       return 32;
    return 36;
  }

  /// Scales VaultText.headline (desktop 28). Use for page-hero headings
  /// (page title at the top of a screen). ChatGPT / 1Password / Bitwarden
  /// mobile page titles are ~22, matching iOS "large title" behaviour.
  double get headlineSize {
    if (isNarrowMobile) return 20;
    if (isMobile)       return 22;
    if (isTablet)       return 26;
    return 28;
  }

  /// Scales VaultText.titleLg (desktop 22). Use for card/section headers.
  /// Preserves ≥ 2pt gap under headlineSize at every tier.
  double get titleLgSize {
    if (isNarrowMobile) return 17;
    if (isMobile)       return 18;
    return 22;
  }

  /// Metric value inside a small card (e.g. "5", "12h", "342 GB"). Prominent
  /// but not hero-sized. Shrinks aggressively so a wider unit label like
  /// "days" still fits alongside on narrow phones.
  double get metricSize {
    if (isNarrowMobile) return 22;
    if (isMobile)       return 26;
    if (isTablet)       return 30;
    return 34;
  }

  static TextStyle applySize(TextStyle base, double size) =>
      base.copyWith(fontSize: size);




  double get drawerWidth =>
      math.min(width * 0.86, 340.0);


  double get drawerHeaderPadding => isMobile ? 12 : 16;
  double get drawerBodyPadding   => isMobile ? 10 : 14;




  double get composerVerticalPadding   => isMobile ? 6 : 10;
  double get composerHorizontalPadding => isMobile ? 8 : 12;
  double get composerIconButtonSize    => isMobile ? 36 : 40;
  double get composerSendButtonSize    => isMobile ? 36 : 44;

  int get composerMinLines => 1;

  int get composerMaxLines => isMobile ? 5 : 6;




  double get keyboardInset => math.max(0.0, viewInsets.bottom);
  double get bottomSafeInset => math.max(0.0, viewPadding.bottom);

  double get bottomComposerInset =>
      keyboardInset > 0 ? keyboardInset : bottomSafeInset;
}


/// Sugar: pull the responsive font size at the call-site with a single import.
///
///   Text(l.pageTitle, style: VaultText.headline.copyWith(
///     fontSize: vrHeadline(context),
///   ))
double vrDisplay(BuildContext context) =>
    VaultResponsive.of(context).displaySize;
double vrHeadline(BuildContext context) =>
    VaultResponsive.of(context).headlineSize;
double vrTitleLg(BuildContext context) =>
    VaultResponsive.of(context).titleLgSize;
double vrMetric(BuildContext context) =>
    VaultResponsive.of(context).metricSize;





class ResponsiveActionBar extends StatelessWidget {
  final Widget heading;
  final List<Widget> actions;
  final double breakpoint;
  final double actionSpacing;
  final double headingBottomSpacing;
  final CrossAxisAlignment mobileCrossAxis;

  const ResponsiveActionBar({
    super.key,
    required this.heading,
    required this.actions,
    this.breakpoint = VaultBreakpoints.compactMax,
    this.actionSpacing = 8,
    this.headingBottomSpacing = 10,
    this.mobileCrossAxis = CrossAxisAlignment.stretch,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow = constraints.maxWidth < breakpoint;
        if (narrow) {


          return Column(
            crossAxisAlignment: mobileCrossAxis,
            children: [
              SizedBox(width: double.infinity, child: heading),
              SizedBox(height: headingBottomSpacing),
              Wrap(
                spacing: actionSpacing,
                runSpacing: actionSpacing,
                children: actions,
              ),
            ],
          );
        }

        return Row(
          children: [
            Expanded(child: heading),
            for (int i = 0; i < actions.length; i++) ...[
              if (i > 0) SizedBox(width: actionSpacing),
              actions[i],
            ],
          ],
        );
      },
    );
  }
}
