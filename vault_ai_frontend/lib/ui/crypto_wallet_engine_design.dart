

import 'package:flutter/material.dart';


const Color kWalletBgBase = Color(0xFF0B0E14);


const Color kWalletBgTint = Color(0xFF111726);


const Color kWalletSurface = Color(0xFF161B26);


const Color kWalletSurfaceElevated = Color(0xFF1B2030);


const Color kWalletBorder = Color(0xFF2A3142);


const Color kWalletBorderStrong = Color(0xFF3C4660);


const Color kWalletTextPrimary = Color(0xFFE7ECF5);


const Color kWalletTextSecondary = Color(0xFFAAB4C8);


const Color kWalletTextMuted = Color(0xFF7E8AA3);


const Color kWalletAccentPrimary = Color(0xFF6979FF);
const Color kWalletAccentPrimarySoft = Color(0xFF8E9CFF);


const Color kWalletAccentSuccess = Color(0xFF4ADE80);


const Color kWalletAccentWarning = Color(0xFFFFB763);


const Color kWalletAccentPrivacy = Color(0xFFFF9554);


const Color kWalletAccentDanger = Color(0xFFFF6B7A);


const Map<String, Color> kWalletAssetAccent = {
  'ETH':         Color(0xFF7C8DFF),
  'USDT_ERC20':  Color(0xFF26A17B),
  'USDC_ERC20':  Color(0xFF3AA1FF),
  'SOL':         Color(0xFF9B5BFF),
  'USDT_TRC20':  Color(0xFF14B8A6),
  'XMR':         Color(0xFFFF8A4A),
};


const Map<String, String> kWalletAssetGlyph = {
  'ETH':         'Ξ',
  'USDT_ERC20':  '₮',
  'USDC_ERC20':  '\$',
  'SOL':         'S',
  'USDT_TRC20':  '₮',
  'XMR':         'M',
};


const Key kWalletPageBackgroundKey = Key('crypto_wallet_engine_page_bg');

BoxDecoration walletPageBackground() {
  return const BoxDecoration(
    gradient: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [
        kWalletBgBase,
        kWalletBgTint,
      ],
    ),
  );
}


BoxDecoration walletDarkCard({
  Color? accent,
  bool elevated = false,
}) {
  final base = elevated ? kWalletSurfaceElevated : kWalletSurface;
  final borderColor = accent == null
      ? kWalletBorder
      : Color.alphaBlend(accent.withOpacity(0.35), kWalletBorder);
  return BoxDecoration(
    gradient: accent == null
        ? null
        : LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              Color.alphaBlend(accent.withOpacity(0.10), base),
              base,
            ],
          ),
    color: accent == null ? base : null,
    borderRadius: BorderRadius.circular(14),
    border: Border.all(color: borderColor, width: 1),
    boxShadow: const [
      BoxShadow(
        color: Color(0x66000000),
        blurRadius: 18,
        offset: Offset(0, 6),
      ),
    ],
  );
}


BoxDecoration walletAssetCard(String asset) {
  final accent = kWalletAssetAccent[asset] ?? kWalletAccentPrimary;
  return BoxDecoration(
    gradient: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [
        Color.alphaBlend(accent.withOpacity(0.18), kWalletSurface),
        kWalletSurface,
        Color.alphaBlend(accent.withOpacity(0.06), kWalletSurface),
      ],
      stops: const [0.0, 0.45, 1.0],
    ),
    borderRadius: BorderRadius.circular(16),
    border: Border.all(
      color: Color.alphaBlend(accent.withOpacity(0.35), kWalletBorder),
      width: 1,
    ),
    boxShadow: const [
      BoxShadow(
        color: Color(0x66000000),
        blurRadius: 20,
        offset: Offset(0, 8),
      ),
    ],
  );
}


BoxDecoration walletWarningPanel() {
  return BoxDecoration(
    color: const Color(0xFF2A1F0E),
    borderRadius: BorderRadius.circular(10),
    border: Border.all(
      color: kWalletAccentWarning.withOpacity(0.5),
      width: 1,
    ),
  );
}


BoxDecoration walletDangerPanel() {
  return BoxDecoration(
    color: const Color(0xFF2A1419),
    borderRadius: BorderRadius.circular(10),
    border: Border.all(
      color: kWalletAccentDanger.withOpacity(0.55),
      width: 1,
    ),
  );
}


BoxDecoration walletSuccessPanel() {
  return BoxDecoration(
    color: const Color(0xFF0F2519),
    borderRadius: BorderRadius.circular(10),
    border: Border.all(
      color: kWalletAccentSuccess.withOpacity(0.45),
      width: 1,
    ),
  );
}


enum WalletBadgeTone {
  live,
  comingNext,
  planned,
  privacy,
  testnet,
  paused,
  mainnet,
}

Color walletBadgeTint(WalletBadgeTone tone) {
  switch (tone) {
    case WalletBadgeTone.live:
      return kWalletAccentSuccess;
    case WalletBadgeTone.comingNext:
      return kWalletAccentPrimarySoft;
    case WalletBadgeTone.planned:
      return kWalletAssetAccent['USDT_TRC20'] ?? kWalletAccentSuccess;
    case WalletBadgeTone.privacy:
      return kWalletAccentPrivacy;
    case WalletBadgeTone.testnet:
      return kWalletAccentWarning;
    case WalletBadgeTone.paused:
      return kWalletAccentDanger;
    case WalletBadgeTone.mainnet:
      return kWalletAccentSuccess;
  }
}

Widget walletStatusBadge(
  String label, {
  required WalletBadgeTone tone,
  Key? key,
}) {
  final tint = walletBadgeTint(tone);
  return Container(
    key: key,
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
    decoration: BoxDecoration(
      color: tint.withOpacity(0.16),
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: tint.withOpacity(0.6), width: 1),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: tint,
        fontSize: 11,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.3,
      ),
    ),
  );
}


ButtonStyle walletPrimaryButtonStyle() {
  return ElevatedButton.styleFrom(
    backgroundColor: kWalletAccentPrimary,
    foregroundColor: Colors.white,
    disabledBackgroundColor: kWalletSurfaceElevated,
    disabledForegroundColor: kWalletTextMuted,
    elevation: 0,
    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    textStyle: const TextStyle(
      fontWeight: FontWeight.w700, letterSpacing: 0.2,
    ),
    minimumSize: const Size(0, 38),
  );
}


ButtonStyle walletSecondaryButtonStyle() {
  return ElevatedButton.styleFrom(
    backgroundColor: kWalletSurfaceElevated,
    foregroundColor: kWalletTextPrimary,
    elevation: 0,
    side: const BorderSide(color: kWalletBorderStrong, width: 1),
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    textStyle: const TextStyle(fontWeight: FontWeight.w600),
    minimumSize: const Size(0, 38),
  );
}


ButtonStyle walletGhostButtonStyle() {
  return OutlinedButton.styleFrom(
    foregroundColor: kWalletTextSecondary,
    side: const BorderSide(color: kWalletBorder, width: 1),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    textStyle: const TextStyle(fontWeight: FontWeight.w600),
    minimumSize: const Size(0, 36),
  );
}


Widget walletAssetIcon(
  String asset, {
  double size = 36,
}) {
  final accent = kWalletAssetAccent[asset] ?? kWalletAccentPrimary;
  final glyph = kWalletAssetGlyph[asset] ?? '◆';
  return Container(
    key: Key('crypto_wallet_engine_card_glyph_$asset'),
    width: size,
    height: size,
    decoration: BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          accent.withOpacity(0.95),
          Color.alphaBlend(Colors.black.withOpacity(0.35), accent),
        ],
      ),
      shape: BoxShape.circle,
      boxShadow: [
        BoxShadow(
          color: accent.withOpacity(0.35),
          blurRadius: 12,
          offset: const Offset(0, 4),
        ),
      ],
    ),
    alignment: Alignment.center,
    child: Text(
      glyph,
      style: TextStyle(
        color: Colors.white,
        fontWeight: FontWeight.w800,
        fontSize: size * 0.5,
        height: 1.0,
      ),
    ),
  );
}


const TextStyle kWalletHeadingStyle = TextStyle(
  color: kWalletTextPrimary,
  fontSize: 26,
  fontWeight: FontWeight.w800,
  letterSpacing: -0.2,
);

const TextStyle kWalletSubheadingStyle = TextStyle(
  color: kWalletTextSecondary,
  fontSize: 14,
  height: 1.4,
);

const TextStyle kWalletSectionHeadingStyle = TextStyle(
  color: kWalletTextPrimary,
  fontSize: 16,
  fontWeight: FontWeight.w800,
  letterSpacing: 0.1,
);

const TextStyle kWalletBodyStyle = TextStyle(
  color: kWalletTextSecondary,
  fontSize: 13,
  height: 1.45,
);

const TextStyle kWalletMutedStyle = TextStyle(
  color: kWalletTextMuted,
  fontSize: 12,
  height: 1.4,
);

const TextStyle kWalletMonoStyle = TextStyle(
  fontFamily: 'monospace',
  color: kWalletTextPrimary,
  fontSize: 12,
  height: 1.4,
);


ThemeData walletDarkPanelTheme(BuildContext context) {
  final base = Theme.of(context);
  return base.copyWith(
    scaffoldBackgroundColor: kWalletSurface,
    canvasColor: kWalletSurface,
    cardColor: kWalletSurfaceElevated,
    dividerColor: kWalletBorder,
    iconTheme: const IconThemeData(color: kWalletTextSecondary),
    textTheme: base.textTheme.apply(
      bodyColor: kWalletTextPrimary,
      displayColor: kWalletTextPrimary,
    ),
    colorScheme: base.colorScheme.copyWith(
      brightness: Brightness.dark,
      primary: kWalletAccentPrimary,
      onPrimary: Colors.white,
      surface: kWalletSurface,
      onSurface: kWalletTextPrimary,
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: kWalletSurfaceElevated,
      hintStyle: TextStyle(color: kWalletTextMuted),
      labelStyle: TextStyle(color: kWalletTextSecondary),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(10)),
        borderSide: BorderSide(color: kWalletBorder),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(10)),
        borderSide: BorderSide(color: kWalletBorder),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(10)),
        borderSide: BorderSide(color: kWalletAccentPrimary, width: 1.5),
      ),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: kWalletSurfaceElevated,
      contentTextStyle: TextStyle(color: kWalletTextPrimary),
      behavior: SnackBarBehavior.floating,
    ),
  );
}


class WalletDarkPanelScope extends StatelessWidget {
  final Widget child;

  const WalletDarkPanelScope({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: walletDarkPanelTheme(context),
      child: Material(
        type: MaterialType.canvas,
        color: kWalletSurface,
        child: DefaultTextStyle.merge(
          style: const TextStyle(color: kWalletTextPrimary),
          child: IconTheme.merge(
            data: const IconThemeData(color: kWalletTextSecondary),
            child: child,
          ),
        ),
      ),
    );
  }
}
