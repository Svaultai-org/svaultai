

import 'package:flutter/material.dart';


class VaultColors {
  VaultColors._();

  
  static const Color canvas           = Color(0xFF0F1115);
  static const Color surface          = Color(0xFF171A20);
  static const Color surfaceElevated  = Color(0xFF1E2229);
  static const Color surfaceMuted     = Color(0xFF21262E);
  static const Color surfaceHover     = Color(0xFF252A33);

  
  static const Color borderSubtle     = Color(0x0FFFFFFF); 
  static const Color borderStrong     = Color(0x1FFFFFFF); 
  static const Color borderAccent     = Color(0x4010A37F); 

  
  static const Color textPrimary      = Color(0xFFECECEC);
  static const Color textSecondary    = Color(0xFFA0A6B0);
  static const Color textTertiary     = Color(0xFF6E7480);
  static const Color textOnAccent     = Color(0xFFFFFFFF);

  
  static const Color accent           = Color(0xFF10A37F);
  static const Color accentBright     = Color(0xFF14B58C);
  static const Color accentSoft       = Color(0x2210A37F); 
  static const Color accentGlow       = Color(0x3310A37F);

  
  static const Color severityInfo     = Color(0xFF60A5FA); 
  static const Color severityInfoSoft = Color(0x2260A5FA);
  static const Color severityWarn     = Color(0xFFFBBF24); 
  static const Color severityWarnSoft = Color(0x22FBBF24);
  static const Color severityCrit     = Color(0xFFF87171); 
  static const Color severityCritSoft = Color(0x22F87171);
  static const Color severityOk       = Color(0xFF34D399); 
  static const Color severityOkSoft   = Color(0x2234D399);

  
  static const Color bubbleUserA      = Color(0xFF10A37F);
  static const Color bubbleUserB      = Color(0xFF0E8F70);
  static const Color bubbleAssistant  = Color(0xFF1E2229);

  
  static const Color shadowAmbient    = Color(0x33000000); 
  static const Color shadowKey        = Color(0x66000000); 

  
  static Color forSeverity(String level) {
    switch (level.toLowerCase()) {
      case 'critical': return severityCrit;
      case 'warning':  return severityWarn;
      case 'info':     return severityInfo;
      case 'ok':
      case 'success':  return severityOk;
      default:         return textSecondary;
    }
  }

  static Color forSeveritySoft(String level) {
    switch (level.toLowerCase()) {
      case 'critical': return severityCritSoft;
      case 'warning':  return severityWarnSoft;
      case 'info':     return severityInfoSoft;
      case 'ok':
      case 'success':  return severityOkSoft;
      default:         return surfaceMuted;
    }
  }
}


class VaultSpacing {
  VaultSpacing._();

  static const double xxs = 2;
  static const double xs  = 4;
  static const double sm  = 8;
  static const double md  = 12;
  static const double lg  = 16;
  static const double xl  = 20;
  static const double xl2 = 24;
  static const double xl3 = 32;
  static const double xl4 = 40;
  static const double xl5 = 56;
}


class VaultRadius {
  VaultRadius._();

  static const double sm   = 8;
  static const double md   = 12;
  static const double lg   = 16;
  static const double xl   = 20;
  static const double xl2  = 24;
  static const double pill = 999;
}


class VaultMotion {
  VaultMotion._();

  static const Duration fast        = Duration(milliseconds: 150);
  static const Duration standard    = Duration(milliseconds: 220);
  static const Duration emphasized  = Duration(milliseconds: 320);
  static const Duration slow        = Duration(milliseconds: 520);

  
  static const Curve curveStandard    = Curves.easeOutCubic;
  static const Curve curveEmphasized  = Curves.easeOutQuint;
  static const Curve curveBounce      = Curves.easeOutBack;
  static const Curve curveLinear      = Curves.linear;
}


class VaultText {
  VaultText._();

  static const TextStyle caption = TextStyle(
    fontSize: 12,
    height: 1.33,
    letterSpacing: 0.15,
    fontWeight: FontWeight.w500,
    color: VaultColors.textSecondary,
  );

  static const TextStyle bodySm = TextStyle(
    fontSize: 13,
    height: 1.5,
    fontWeight: FontWeight.w400,
    color: VaultColors.textPrimary,
  );

  static const TextStyle body = TextStyle(
    fontSize: 14,
    height: 1.55,
    fontWeight: FontWeight.w400,
    color: VaultColors.textPrimary,
  );

  static const TextStyle bodyLg = TextStyle(
    fontSize: 15,
    height: 1.6,
    fontWeight: FontWeight.w400,
    color: VaultColors.textPrimary,
  );

  static const TextStyle subtitle = TextStyle(
    fontSize: 16,
    height: 1.4,
    letterSpacing: -0.1,
    fontWeight: FontWeight.w600,
    color: VaultColors.textPrimary,
  );

  static const TextStyle title = TextStyle(
    fontSize: 18,
    height: 1.35,
    letterSpacing: -0.2,
    fontWeight: FontWeight.w700,
    color: VaultColors.textPrimary,
  );

  static const TextStyle titleLg = TextStyle(
    fontSize: 22,
    height: 1.3,
    letterSpacing: -0.3,
    fontWeight: FontWeight.w700,
    color: VaultColors.textPrimary,
  );

  static const TextStyle headline = TextStyle(
    fontSize: 28,
    height: 1.25,
    letterSpacing: -0.4,
    fontWeight: FontWeight.w800,
    color: VaultColors.textPrimary,
  );

  static const TextStyle display = TextStyle(
    fontSize: 36,
    height: 1.18,
    letterSpacing: -0.5,
    fontWeight: FontWeight.w800,
    color: VaultColors.textPrimary,
  );

  
  static const TextStyle mono = TextStyle(
    fontSize: 13,
    height: 1.4,
    letterSpacing: 0.2,
    fontFeatures: [FontFeature.tabularFigures()],
    color: VaultColors.textPrimary,
  );
}


class VaultShadows {
  VaultShadows._();

  static const List<BoxShadow> none = <BoxShadow>[];

  
  static const List<BoxShadow> e1 = [
    BoxShadow(
      color: VaultColors.shadowAmbient,
      offset: Offset(0, 1),
      blurRadius: 2,
    ),
    BoxShadow(
      color: VaultColors.shadowAmbient,
      offset: Offset(0, 4),
      blurRadius: 12,
    ),
  ];

  
  static const List<BoxShadow> e2 = [
    BoxShadow(
      color: VaultColors.shadowAmbient,
      offset: Offset(0, 2),
      blurRadius: 4,
    ),
    BoxShadow(
      color: VaultColors.shadowKey,
      offset: Offset(0, 12),
      blurRadius: 28,
    ),
  ];

  
  static const List<BoxShadow> accentGlow = [
    BoxShadow(
      color: VaultColors.accentGlow,
      blurRadius: 24,
      spreadRadius: 0,
    ),
  ];
}
