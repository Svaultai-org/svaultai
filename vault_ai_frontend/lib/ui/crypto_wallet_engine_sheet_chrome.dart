// 2026-07-13: shared chrome + presenter for every Crypto Wallet
// bottom-sheet. Previously each of the six `showModalBottomSheet`
// callers rendered its body bare — no drag handle, no close button, no
// title bar. On mobile the user had to tap the dimmed scrim to dismiss
// the sheet, which is not discoverable. Every crypto sheet now goes
// through `showCryptoWalletSheet` and gets:
//
//   * A drag handle rendered inside the sheet (Flutter's built-in
//     showDragHandle:true would work but its color tokens don't match
//     the wallet dark palette, so we render our own).
//   * An explicit close IconButton (Icons.close, top-right) that is
//     always visible even when the body scrolls — the chrome lives
//     outside the scrolling content.
//   * An optional title on the left.
//   * An optional back arrow on the left when the caller passes
//     `onBack` — for future multi-step flows.
//   * SafeArea and a maxHeight cap of 92% of screen so the sheet
//     never overshoots the notch on tall iPhones.
//   * Escape-to-close on desktop / web keyboards via `Actions`+
//     `Shortcuts` bound to `DismissIntent`.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'crypto_wallet_engine_design.dart';


/// Presents `child` as a modal bottom sheet with the shared wallet
/// chrome. Returns a Future that resolves when the sheet is dismissed
/// (matches `showModalBottomSheet`'s contract). Callers should NOT
/// wrap their body in another `SafeArea` / `SingleChildScrollView` —
/// the chrome supplies both.
Future<T?> showCryptoWalletSheet<T>({
  required BuildContext context,
  required String title,
  required Widget child,
  String sheetKey = 'crypto_wallet_engine_sheet',
  VoidCallback? onBack,
  double heightFraction = 0.92,
  // When true, the chrome does NOT wrap `child` in a
  // Flexible+SingleChildScrollView — the child manages its own scroll
  // and sticky footer (used by Send panels via `WalletSendScaffold`).
  // When false (default), the chrome scrolls the child, matching the
  // legacy Receive-panel behavior.
  bool bodyOwnsLayout = false,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    barrierColor: Colors.black.withOpacity(0.6),
    isDismissible: true,
    enableDrag: true,
    useSafeArea: true,
    builder: (sheetCtx) => CryptoWalletSheetChrome(
      title: title,
      sheetKey: sheetKey,
      onBack: onBack,
      heightFraction: heightFraction,
      bodyOwnsLayout: bodyOwnsLayout,
      child: child,
    ),
  );
}


/// The shared wallet-sheet frame. Rendered by [showCryptoWalletSheet].
/// Exposed publicly for widget tests that pump the chrome directly.
class CryptoWalletSheetChrome extends StatelessWidget {
  final String title;
  final Widget child;
  final String sheetKey;
  final VoidCallback? onBack;
  final double heightFraction;
  final bool bodyOwnsLayout;

  const CryptoWalletSheetChrome({
    super.key,
    required this.title,
    required this.child,
    this.sheetKey = 'crypto_wallet_engine_sheet',
    this.onBack,
    this.heightFraction = 0.92,
    this.bodyOwnsLayout = false,
  });

  @override
  Widget build(BuildContext context) {
    // 2026-07-13 mobile-keyboard fix:
    //
    // showModalBottomSheet does NOT automatically wrap the sheet in a
    // viewInsets.bottom padding on mobile Safari / iOS. We do it here,
    // at the sheet's outermost level, so the ENTIRE sheet (header +
    // scroll body + footer) lifts above the keyboard as one unit. The
    // header and close X therefore stay reachable at every keyboard
    // state, and the sticky footer (Review button) sits naturally at
    // the sheet's bottom edge -- just above the keyboard -- instead
    // of floating in the middle.
    //
    // The maxHeight cap also subtracts the keyboard inset so the
    // sheet doesn't demand more space than the keyboard-free area.
    // A 240dp floor prevents a huge keyboard from squashing the sheet
    // below usability.
    final mq = MediaQuery.of(context);
    final availableHeight =
        (mq.size.height - mq.viewInsets.bottom).clamp(0.0, mq.size.height);
    final maxHeight = (availableHeight * heightFraction).clamp(
      240.0, mq.size.height,
    );
    return Focus(
      autofocus: true,
      canRequestFocus: true,
      onKeyEvent: (node, event) {
        // Escape closes on desktop / web — the sheet always at least
        // pops itself; onBack is invoked when the caller provided one.
        if (event is KeyDownEvent
            && event.logicalKey == LogicalKeyboardKey.escape) {
          if (onBack != null) {
            onBack!();
          } else {
            Navigator.of(context).maybePop();
          }
          return KeyEventResult.handled;
        }
        return KeyEventResult.ignored;
      },
      child: AnimatedPadding(
        // Lift the whole sheet (header + body + footer as one unit)
        // above the keyboard. Animated so the transition matches the
        // OS keyboard's raise/dismiss animation.
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
        padding: EdgeInsets.only(bottom: mq.viewInsets.bottom),
        child: Container(
          key: Key(sheetKey),
          constraints: BoxConstraints(maxHeight: maxHeight),
          decoration: const BoxDecoration(
            color: kWalletBgBase,
            borderRadius: BorderRadius.vertical(
              top: Radius.circular(18),
            ),
            border: Border(
              top: BorderSide(color: kWalletBorder, width: 1),
              left: BorderSide(color: kWalletBorder, width: 1),
              right: BorderSide(color: kWalletBorder, width: 1),
            ),
          ),
          // ViewInsets are applied ONCE at the sheet's outer edge (in
          // the AnimatedPadding above). The inner Column, scroll body,
          // and any sticky footer do NOT add extra viewInsets padding
          // -- that double-padding was the "Review floats in the
          // middle" bug the 2026-07-13 mobile fix removed.
          //
          // NOTE: because the inner children now see
          // `MediaQuery.viewInsets.bottom` == 0 relative to their
          // parent's viewport (the padding consumed it), we wrap the
          // subtree in a MediaQuery override so `viewInsets.bottom`
          // reads as zero for descendants -- otherwise the descendant
          // WalletSendScaffold body-bottom-padding would grow twice on
          // the keyboard event.
          child: MediaQuery(
            data: mq.copyWith(
              viewInsets: mq.viewInsets.copyWith(bottom: 0.0),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _DragHandle(sheetKey: sheetKey),
                _Header(
                  title: title,
                  sheetKey: sheetKey,
                  onBack: onBack,
                ),
                const Divider(
                  key: Key('crypto_wallet_engine_sheet_divider'),
                  height: 1,
                  thickness: 1,
                  color: kWalletBorder,
                ),
                if (bodyOwnsLayout)
                  Flexible(child: child)
                else
                  Flexible(
                    child: SingleChildScrollView(
                      key: Key('${sheetKey}_scroll'),
                      padding: const EdgeInsets.fromLTRB(0, 0, 0, 0),
                      child: child,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}


class _DragHandle extends StatelessWidget {
  final String sheetKey;
  const _DragHandle({required this.sheetKey});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 4),
        child: Container(
          key: Key('${sheetKey}_drag_handle'),
          width: 42,
          height: 4,
          decoration: BoxDecoration(
            color: kWalletBorderStrong,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
      ),
    );
  }
}


class _Header extends StatelessWidget {
  final String title;
  final String sheetKey;
  final VoidCallback? onBack;

  const _Header({
    required this.title,
    required this.sheetKey,
    this.onBack,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 4, 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (onBack != null)
            IconButton(
              key: Key('${sheetKey}_back_btn'),
              icon: const Icon(Icons.arrow_back, color: kWalletTextPrimary),
              tooltip: 'Back',
              splashRadius: 22,
              onPressed: onBack,
            )
          else
            const SizedBox(width: 44),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Text(
                title,
                key: Key('${sheetKey}_title'),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
                textAlign: onBack == null
                    ? TextAlign.center
                    : TextAlign.center,
                style: const TextStyle(
                  color: kWalletTextPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.2,
                ),
              ),
            ),
          ),
          IconButton(
            key: Key('${sheetKey}_close_btn'),
            icon: const Icon(Icons.close, color: kWalletTextPrimary),
            tooltip: 'Close',
            splashRadius: 22,
            onPressed: () => Navigator.of(context).maybePop(),
          ),
        ],
      ),
    );
  }
}
