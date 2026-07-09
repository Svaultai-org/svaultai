


import 'dart:async';

import '../api_client.dart';




const String kBillingMeCodeOk = 'ok';
const String kBillingMeCodeTimeout = 'timeout';
const String kBillingMeCodeAuthExpired = 'auth_expired';
const String kBillingMeCodeDeviceUntrusted = 'device_untrusted';
const String kBillingMeCodeServerError = 'server_error';
const String kBillingMeCodeNotReachable = 'not_reachable';
const String kBillingMeCodeUnknownError = 'unknown_error';


const Set<String> kAllBillingMeCodes = {
  kBillingMeCodeOk,
  kBillingMeCodeTimeout,
  kBillingMeCodeAuthExpired,
  kBillingMeCodeDeviceUntrusted,
  kBillingMeCodeServerError,
  kBillingMeCodeNotReachable,
  kBillingMeCodeUnknownError,
};




class BillingMeClassifiedError {
  final String errorCode;
  final String statusLabel;

  const BillingMeClassifiedError({
    required this.errorCode,
    required this.statusLabel,
  });
}




final RegExp _kStatusCodeInMessage = RegExp(r'\bstatus[_ ]?code[ =:]?(\d{3})\b',
    caseSensitive: false);
final RegExp _kBareHttpStatus = RegExp(r'\b(4\d{2}|5\d{2})\b');




BillingMeClassifiedError classifyBillingMeError(Object error) {

  if (error is TimeoutException) {
    return const BillingMeClassifiedError(
      errorCode: kBillingMeCodeTimeout,
      statusLabel: 'timeout',
    );
  }

  if (error is AuthExpiredException) {
    return const BillingMeClassifiedError(
      errorCode: kBillingMeCodeAuthExpired,
      statusLabel: '401',
    );
  }

  if (error is DeviceNotTrustedException) {
    return const BillingMeClassifiedError(
      errorCode: kBillingMeCodeDeviceUntrusted,
      statusLabel: '403',
    );
  }

  final msg = error.toString();
  final low = msg.toLowerCase();


  final statusMatch = _kStatusCodeInMessage.firstMatch(msg)
      ?? _kBareHttpStatus.firstMatch(msg);
  if (statusMatch != null) {
    final code = int.tryParse(statusMatch.group(1) ?? '');
    if (code != null) {
      if (code == 401) {
        return const BillingMeClassifiedError(
          errorCode: kBillingMeCodeAuthExpired,
          statusLabel: '401',
        );
      }
      if (code == 403) {
        return const BillingMeClassifiedError(
          errorCode: kBillingMeCodeDeviceUntrusted,
          statusLabel: '403',
        );
      }
      if (code >= 500 && code <= 599) {
        return BillingMeClassifiedError(
          errorCode: kBillingMeCodeServerError,
          statusLabel: code.toString(),
        );
      }
      return BillingMeClassifiedError(
        errorCode: kBillingMeCodeUnknownError,
        statusLabel: code.toString(),
      );
    }
  }


  const netHints = [
    'socketexception', 'clientexception', 'connection refused',
    'no address associated', 'network is unreachable',
    'connection timed out', 'connection reset',
    'failed host lookup', 'handshakeexception',
  ];
  for (final h in netHints) {
    if (low.contains(h)) {
      return const BillingMeClassifiedError(
        errorCode: kBillingMeCodeNotReachable,
        statusLabel: 'network',
      );
    }
  }

  return const BillingMeClassifiedError(
    errorCode: kBillingMeCodeUnknownError,
    statusLabel: 'unknown',
  );
}




const String kBillingBannerCopyDefault =
    'Subscription status is temporarily unavailable.';
const String kBillingBannerCopyTimeout =
    'Subscription status is temporarily unavailable.';
const String kBillingBannerCopyAuthExpired =
    'Session expired. Please sign in to refresh subscription status.';
const String kBillingBannerCopyDeviceUntrusted =
    'This device is not yet trusted for subscription status.';
const String kBillingBannerCopyServerError =
    'Subscription status is temporarily unavailable.';
const String kBillingBannerCopyNotReachable =
    'Subscription status is unavailable while offline.';
const String kBillingBannerCopyUnknownError =
    'Subscription status is temporarily unavailable.';


String billingBannerCopyForCode(String code) {
  switch (code) {
    case kBillingMeCodeOk:
      return '';
    case kBillingMeCodeTimeout:
      return kBillingBannerCopyTimeout;
    case kBillingMeCodeAuthExpired:
      return kBillingBannerCopyAuthExpired;
    case kBillingMeCodeDeviceUntrusted:
      return kBillingBannerCopyDeviceUntrusted;
    case kBillingMeCodeServerError:
      return kBillingBannerCopyServerError;
    case kBillingMeCodeNotReachable:
      return kBillingBannerCopyNotReachable;
    case kBillingMeCodeUnknownError:
    default:
      return kBillingBannerCopyDefault;
  }
}




const Set<String> kBillingLogBannedTokens = {
  'stripe',
  'customer_id',
  'subscription_id',
  'email',
  '@',
  'card',
  'token',
  'authorization',
  'bearer',
};




bool billingDevLogLineIsSafe(String line) {
  final low = line.toLowerCase();
  for (final t in kBillingLogBannedTokens) {
    if (low.contains(t)) return false;
  }
  return true;
}
