// 2026-07-13: shared compact mobile layout for every crypto Send sheet
// (EVM ETH/USDT_ERC20/USDC_ERC20, Solana, TRON). Previously each send
// panel:
//
//   * Duplicated the sheet title inside the panel body ("Send Ethereum"
//     below the chrome "Send ETH").
//   * Rendered a full-width text network badge and one or more large
//     yellow/red warning boxes above the destination field.
//   * Placed the Review button at the natural end of the scroll body,
//     so the iPhone keyboard covered it and the form itself.
//   * Used the default rounded Material button style — visually weak.
//
// This shared module fixes those problems in one place so every Send
// sheet gets the same polished mobile behavior:
//
//   * `WalletSendScaffold` — a Column layout with a scrollable body
//     and a sticky primary-action footer that lifts above the
//     keyboard using `MediaQuery.viewInsetsOf(context).bottom`. The
//     footer stays reachable in every state: form, review, phrase.
//   * `walletSendNetworkChip` — one compact network chip (24dp tall)
//     that replaces the old full-width network badge text.
//   * `WalletSendWarning` — one concise warning row with icon + text,
//     no full-width bright-yellow/red blocks. Two tones only:
//     `subtle` (mainnet real-funds notice) and `critical`
//     (mainnet-send-disabled / paused). Both use the dark wallet
//     palette. Layout stays compact even at 320dp width.
//   * `walletSendSectionHeading` — the compact stage heading used
//     inside review stages ("Review send").
//   * `WalletSendKvRow` — narrow key + long selectable value row that
//     wraps cleanly at 320dp.

import 'package:flutter/material.dart';

import 'crypto_wallet_engine_design.dart';


/// A stage-agnostic keyboard-aware layout for every crypto Send sheet.
///
/// Callers hand it three logical regions:
///   * [header]  — the network chip (and optional balance chip). One
///                 compact row, rendered above the scroll body.
///   * [body]    — the scrollable form/review/phrase content.
///   * [footer]  — the sticky primary action (typically the Review or
///                 Confirm button). Rendered pinned to the bottom of
///                 the sheet, above the keyboard.
///
/// Passing `footer: null` hides the sticky footer entirely (used by
/// stages that don't need it, e.g. the disabled/paused banners).
///
/// 2026-07-13 mobile-keyboard fix: the sheet chrome already caps its
/// own maxHeight against (screen - viewInsets.bottom), so this
/// scaffold does NOT add extra `viewInsets.bottom` padding to the
/// footer. Doing so was the exact "Review action becomes a very
/// large fixed bar in the middle of the screen" bug — double
/// keyboard-inset accounting pushed the footer up over the body.
///
/// Callers may pass a [scrollController] to observe/drive scroll
/// (used by the Send panels to bring the focused text field above
/// the keyboard via Scrollable.ensureVisible on focus).
class WalletSendScaffold extends StatelessWidget {
  final Widget? header;
  final Widget body;
  final Widget? footer;
  final String sheetKey;
  final ScrollController? scrollController;

  const WalletSendScaffold({
    super.key,
    required this.body,
    this.header,
    this.footer,
    this.sheetKey = 'wallet_send',
    this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    // The scroll body needs breathing room above the footer so the
    // last focused field's caret and label sit comfortably above the
    // border, not glued to it. Grows a bit more when the keyboard is
    // open so ensureVisible has room to slide the field upward.
    final keyboardInset = MediaQuery.viewInsetsOf(context).bottom;
    final bodyBottomPad = keyboardInset > 0 ? 40.0 : 24.0;
    return Column(
      key: Key('${sheetKey}_scaffold'),
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (header != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 8, 18, 4),
            child: header!,
          ),
        Flexible(
          child: SingleChildScrollView(
            key: Key('${sheetKey}_scroll'),
            controller: scrollController,
            keyboardDismissBehavior:
                ScrollViewKeyboardDismissBehavior.manual,
            padding: EdgeInsets.fromLTRB(18, 8, 18, bodyBottomPad),
            child: body,
          ),
        ),
        if (footer != null)
          Container(
            key: Key('${sheetKey}_footer'),
            padding: const EdgeInsets.fromLTRB(18, 10, 18, 14),
            decoration: const BoxDecoration(
              color: kWalletBgBase,
              border: Border(
                top: BorderSide(color: kWalletBorder, width: 1),
              ),
            ),
            // SafeArea's bottom padding drops to zero when the
            // keyboard is up (the OS reports viewPadding - viewInsets),
            // so no double-padding here either.
            child: SafeArea(
              top: false,
              child: footer!,
            ),
          ),
      ],
    );
  }
}


/// A single compact chip row that identifies the network the send is
/// bound to. Mainnet chips use the warning tint; testnet chips use
/// the neutral secondary tint. The chip never grows wider than the
/// row — the label is ellipsised.
Widget walletSendNetworkChip({
  required String label,
  required bool isMainnet,
  Widget? trailing,
  Key? key,
}) {
  final tint = isMainnet
      ? kWalletAccentWarning
      : kWalletTextSecondary;
  return Row(
    key: key,
    mainAxisSize: MainAxisSize.max,
    children: [
      Flexible(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: tint.withOpacity(0.14),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: tint.withOpacity(0.55), width: 1),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                isMainnet
                    ? Icons.public_rounded
                    : Icons.science_outlined,
                size: 12,
                color: tint,
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  maxLines: 1,
                  style: TextStyle(
                    color: tint,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      if (trailing != null) ...[
        const SizedBox(width: 8),
        Flexible(child: trailing),
      ],
    ],
  );
}


/// Tones for [WalletSendWarning]. The design system deliberately only
/// exposes two: `subtle` for informational real-funds notices, and
/// `critical` for the mainnet-send-disabled and mainnet-paused states
/// where the user MUST know sending won't work.
enum WalletSendWarningTone { subtle, critical }


/// One compact icon+text warning row. Replaces the old full-width
/// bright yellow/red banner blocks. Wraps cleanly at 320dp.
class WalletSendWarning extends StatelessWidget {
  final String text;
  final WalletSendWarningTone tone;

  const WalletSendWarning({
    super.key,
    required this.text,
    this.tone = WalletSendWarningTone.subtle,
  });

  @override
  Widget build(BuildContext context) {
    final tint = tone == WalletSendWarningTone.critical
        ? kWalletAccentDanger
        : kWalletAccentWarning;
    final bgAlpha = tone == WalletSendWarningTone.critical ? 0.10 : 0.08;
    final borderAlpha = tone == WalletSendWarningTone.critical
        ? 0.55
        : 0.35;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        color: tint.withOpacity(bgAlpha),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: tint.withOpacity(borderAlpha), width: 1),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            tone == WalletSendWarningTone.critical
                ? Icons.error_outline_rounded
                : Icons.info_outline_rounded,
            size: 15,
            color: tint,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: tint,
                fontSize: 12,
                height: 1.35,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


/// A compact section heading used at the top of stages that need one
/// ("Review send"). Never used at form entry — the sheet chrome already
/// shows the sheet title there.
Widget walletSendSectionHeading(String text) {
  return Padding(
    padding: const EdgeInsets.only(top: 2, bottom: 6),
    child: Text(
      text,
      style: const TextStyle(
        color: kWalletTextPrimary,
        fontSize: 15,
        fontWeight: FontWeight.w800,
        letterSpacing: 0.1,
      ),
    ),
  );
}


/// A narrow key + long selectable value row used in review stages.
/// The key column is fixed at 92dp so labels line up cleanly at 320dp
/// without pushing the value column into overflow.
class WalletSendKvRow extends StatelessWidget {
  final String label;
  final String value;
  final bool mono;

  const WalletSendKvRow({
    super.key,
    required this.label,
    required this.value,
    this.mono = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 92,
            child: Text(
              label,
              style: const TextStyle(
                color: kWalletTextSecondary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: mono
                  ? kWalletMonoStyle
                  : const TextStyle(
                      color: kWalletTextPrimary,
                      fontSize: 13,
                      height: 1.35,
                    ),
            ),
          ),
        ],
      ),
    );
  }
}
