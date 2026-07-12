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
    final maxHeight = MediaQuery.of(context).size.height * heightFraction;
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
        // The chrome itself does NOT bake `viewInsets.bottom` into the
        // frame — panels that want a sticky action footer above the
        // keyboard (all Send panels via `WalletSendScaffold`) handle
        // that inside their body so the header/close X stays fully
        // reachable on the header. For panels that pass a plain body
        // (e.g. Receive sheets), we still respect the keyboard by
        // scrolling the inner content.
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
