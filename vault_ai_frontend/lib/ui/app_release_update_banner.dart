/// 2026-07-14 (Round 11 — real controller wiring): the update
/// banner rendered when the running Flutter bundle disagrees with
/// what the server reports at `/release.json`.
///
/// The banner is an overlay stacked ABOVE the current route. It
/// only appears when `updateAvailableNotifier.value == true`. It
/// exposes a single "Update now" action that:
///
///   * calls `AppReleaseController.applyUpdateAndReload(
///       reloadAllowed: () => !broadcastInFlight)`
///   * defers the reload if a Send is mid-broadcast — the
///     controller records the intent and re-attempts on the next
///     safe opportunity.
///
/// The banner's text is intentionally short so it does not push
/// content around: it sits pinned at the top with a subtle
/// backdrop.

library;

import 'package:flutter/material.dart';

import '../services/app_release_controller.dart';
import '../services/app_release_controller_scope.dart';


const String kAppReleaseUpdateBannerKey =
    'vaultai_app_release_update_banner';
const String kAppReleaseUpdateBannerCopy =
    'VaultAI was updated.';
const String kAppReleaseUpdateBannerActionLabel = 'Update now';


class AppReleaseUpdateBanner extends StatelessWidget {
  const AppReleaseUpdateBanner({
    super.key,
    required this.child,
    this.reloadAllowed,
  });

  final Widget child;

  /// Optional predicate the banner passes into `applyUpdateAndReload`
  /// so a mid-broadcast Send can defer the reload. If null the
  /// reload proceeds immediately.
  final bool Function()? reloadAllowed;

  @override
  Widget build(BuildContext context) {
    final ctl = AppReleaseControllerScope.maybeOf(context);
    if (ctl == null) return child;
    return Stack(children: [
      child,
      Positioned(
        top: 0,
        left: 0,
        right: 0,
        child: SafeArea(
          child: ValueListenableBuilder<bool>(
            valueListenable: ctl.updateAvailableNotifier,
            builder: (context, updateAvailable, _) {
              if (!updateAvailable) return const SizedBox.shrink();
              return _BannerBody(
                controller: ctl,
                reloadAllowed: reloadAllowed,
              );
            },
          ),
        ),
      ),
    ]);
  }
}


class _BannerBody extends StatelessWidget {
  const _BannerBody({
    required this.controller,
    required this.reloadAllowed,
  });

  final AppReleaseController controller;
  final bool Function()? reloadAllowed;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key(kAppReleaseUpdateBannerKey),
      color: const Color(0xFF10A37F),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(
        children: [
          const Icon(Icons.system_update_alt, color: Colors.white),
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              kAppReleaseUpdateBannerCopy,
              style: TextStyle(color: Colors.white, fontSize: 14),
            ),
          ),
          TextButton(
            key: const Key('${kAppReleaseUpdateBannerKey}_action'),
            onPressed: () => controller.applyUpdateAndReload(
              reloadAllowed: reloadAllowed,
            ),
            style: TextButton.styleFrom(
              foregroundColor: Colors.white,
            ),
            child: const Text(kAppReleaseUpdateBannerActionLabel),
          ),
        ],
      ),
    );
  }
}
