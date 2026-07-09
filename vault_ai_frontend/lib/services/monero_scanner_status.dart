

import 'package:flutter/foundation.dart' show kIsWeb;


String moneroClientPlatform() {


  if (kIsWeb) return kMoneroClientPlatformWeb;
  return kMoneroClientPlatformNative;
}


const String kMoneroScannerStatusSchemaV1 = 'monero_scanner_status_v1';



const String kMoneroScannerStatusDisabled       = 'disabled';
const String kMoneroScannerStatusNotConfigured  = 'not_configured';
const String kMoneroScannerStatusConfigured     = 'configured';
const String kMoneroScannerStatusSyncing        = 'syncing';
const String kMoneroScannerStatusReady          = 'ready';
const String kMoneroScannerStatusError          = 'error';

const Set<String> kAllowedMoneroScannerStatus = {
  kMoneroScannerStatusDisabled,
  kMoneroScannerStatusNotConfigured,
  kMoneroScannerStatusConfigured,
  kMoneroScannerStatusSyncing,
  kMoneroScannerStatusReady,
  kMoneroScannerStatusError,
};



const String kMoneroScannerReasonNotEnabled     = 'scanner_not_enabled';
const String kMoneroScannerReasonNotConfigured  = 'scanner_not_configured';
const String kMoneroScannerReasonViewKeyMissing = 'view_key_not_available';
const String kMoneroScannerReasonUnreachable    = 'scanner_unreachable';
const String kMoneroScannerReasonSyncing        = 'scanner_syncing';
const String kMoneroScannerReasonReady          = 'scanner_ready';
const String kMoneroScannerReasonError          = 'scanner_error';


const String kMoneroScannerReasonLocalAvailable = 'local_scanner_available';


const String kMoneroScannerReasonRequiresDesktop = 'scanner_requires_desktop';

const Set<String> kAllowedMoneroScannerReason = {
  kMoneroScannerReasonNotEnabled,
  kMoneroScannerReasonNotConfigured,
  kMoneroScannerReasonViewKeyMissing,
  kMoneroScannerReasonUnreachable,
  kMoneroScannerReasonSyncing,
  kMoneroScannerReasonReady,
  kMoneroScannerReasonError,
  kMoneroScannerReasonLocalAvailable,
  kMoneroScannerReasonRequiresDesktop,
};



const String kMoneroClientPlatformWeb     = 'web';
const String kMoneroClientPlatformNative  = 'native';
const String kMoneroClientPlatformUnknown = 'unknown';

const Set<String> kAllowedMoneroClientPlatform = {
  kMoneroClientPlatformWeb,
  kMoneroClientPlatformNative,
  kMoneroClientPlatformUnknown,
};




const String kMoneroScannerBalanceCopyNotEnabled =
    'Scanner not enabled';
const String kMoneroScannerBalanceCopyNotConfigured =
    'Scanner not configured';
const String kMoneroScannerBalanceCopyViewKeyMissing =
    'View-only scanning not available';
const String kMoneroScannerBalanceCopyUnreachable =
    'Scanner temporarily unavailable';
const String kMoneroScannerBalanceCopySyncing =
    'Scanner syncing';
const String kMoneroScannerBalanceCopyReady =
    'Balance unavailable';
const String kMoneroScannerBalanceCopyError =
    'Balance unavailable';
const String kMoneroScannerBalanceCopyLocalAvailable =
    'Local scanner available';
const String kMoneroScannerBalanceCopyRequiresDesktop =
    'Monero scanning requires the desktop app.';




const String kMoneroScannerActivityCopyNotEnabled =
    'Monero activity requires wallet scanning.';
const String kMoneroScannerActivityCopyNotConfigured =
    'Monero scanner is not configured.';
const String kMoneroScannerActivityCopyViewKeyMissing =
    'View-only scanning not available.';
const String kMoneroScannerActivityCopyUnreachable =
    'Monero scanner is temporarily unavailable.';
const String kMoneroScannerActivityCopySyncing =
    'Monero scanner is syncing.';
const String kMoneroScannerActivityCopyReady =
    'No activity yet.';
const String kMoneroScannerActivityCopyError =
    'Monero scanner is temporarily unavailable.';
const String kMoneroScannerActivityCopyLocalAvailable =
    'Start the local scanner to load Monero activity.';
const String kMoneroScannerActivityCopyRequiresDesktop =
    'Monero scanning requires the desktop app.';




const String kMoneroDashboardBalanceCopyDefault =
    'Scanner not enabled';
const String kMoneroDashboardScannerNoteCopyDefault =
    'Monero balance requires wallet scanning.';
const String kMoneroDashboardActivityChipCopyDefault =
    'Scanner not enabled';



String moneroScannerBalanceCopyForReason(String? reason) {
  switch (reason) {
    case kMoneroScannerReasonNotEnabled:
      return kMoneroScannerBalanceCopyNotEnabled;
    case kMoneroScannerReasonNotConfigured:
      return kMoneroScannerBalanceCopyNotConfigured;
    case kMoneroScannerReasonViewKeyMissing:
      return kMoneroScannerBalanceCopyViewKeyMissing;
    case kMoneroScannerReasonUnreachable:
      return kMoneroScannerBalanceCopyUnreachable;
    case kMoneroScannerReasonSyncing:
      return kMoneroScannerBalanceCopySyncing;
    case kMoneroScannerReasonReady:
      return kMoneroScannerBalanceCopyReady;
    case kMoneroScannerReasonError:
      return kMoneroScannerBalanceCopyError;
    case kMoneroScannerReasonLocalAvailable:
      return kMoneroScannerBalanceCopyLocalAvailable;
    case kMoneroScannerReasonRequiresDesktop:
      return kMoneroScannerBalanceCopyRequiresDesktop;
    default:
      return kMoneroScannerBalanceCopyNotEnabled;
  }
}


String moneroScannerActivityCopyForReason(String? reason) {
  switch (reason) {
    case kMoneroScannerReasonNotEnabled:
      return kMoneroScannerActivityCopyNotEnabled;
    case kMoneroScannerReasonNotConfigured:
      return kMoneroScannerActivityCopyNotConfigured;
    case kMoneroScannerReasonViewKeyMissing:
      return kMoneroScannerActivityCopyViewKeyMissing;
    case kMoneroScannerReasonUnreachable:
      return kMoneroScannerActivityCopyUnreachable;
    case kMoneroScannerReasonSyncing:
      return kMoneroScannerActivityCopySyncing;
    case kMoneroScannerReasonReady:
      return kMoneroScannerActivityCopyReady;
    case kMoneroScannerReasonError:
      return kMoneroScannerActivityCopyError;
    case kMoneroScannerReasonLocalAvailable:
      return kMoneroScannerActivityCopyLocalAvailable;
    case kMoneroScannerReasonRequiresDesktop:
      return kMoneroScannerActivityCopyRequiresDesktop;
    default:
      return kMoneroScannerActivityCopyNotEnabled;
  }
}



class MoneroScannerStatus {

  final String scannerStatus;
  final String reason;

  final bool canShowBalance;
  final bool canShowActivity;
  final bool canSend;

  final String mode;

  const MoneroScannerStatus({
    required this.scannerStatus,
    required this.reason,
    required this.canShowBalance,
    required this.canShowActivity,
    required this.canSend,
    this.mode = 'none',
  });


  static const MoneroScannerStatus disabled = MoneroScannerStatus(
    scannerStatus:   kMoneroScannerStatusDisabled,
    reason:          kMoneroScannerReasonNotEnabled,
    canShowBalance:  false,
    canShowActivity: false,
    canSend:         false,
    mode:            'none',
  );


  factory MoneroScannerStatus.fromJson(Map<String, dynamic> raw) {
    final rawStatus = (raw['scannerStatus'] ?? '').toString();
    final rawReason = (raw['reason'] ?? '').toString();
    final rawMode   = (raw['mode'] ?? 'none').toString();
    final safeStatus = kAllowedMoneroScannerStatus.contains(rawStatus)
        ? rawStatus
        : kMoneroScannerStatusDisabled;
    final safeReason = kAllowedMoneroScannerReason.contains(rawReason)
        ? rawReason
        : kMoneroScannerReasonNotEnabled;
    const allowedModes = <String>{
      'none', 'client_local', 'server_view_only',
    };
    final safeMode = allowedModes.contains(rawMode) ? rawMode : 'none';
    return MoneroScannerStatus(
      scannerStatus:   safeStatus,
      reason:          safeReason,
      canShowBalance:  raw['canShowBalance'] == true,
      canShowActivity: raw['canShowActivity'] == true,
      canSend:         raw['canSend'] == true,
      mode:            safeMode,
    );
  }


  String get balanceCopy    =>
      moneroScannerBalanceCopyForReason(reason);
  String get activityCopy   =>
      moneroScannerActivityCopyForReason(reason);


  bool get sendVisible => canSend;
}
