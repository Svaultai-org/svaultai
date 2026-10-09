import 'dart:async';
import 'dart:collection';

/// A safe, structured activation failure. Never contains the signed receipt.
class ApplePurchaseVerificationException implements Exception {
  final int? statusCode;
  final String? code;

  const ApplePurchaseVerificationException({this.statusCode, this.code});

  bool get isTransient =>
      statusCode == null ||
      (statusCode! >= 500 &&
          statusCode! < 600 &&
          code != 'apple_billing_not_configured');

  String get userMessage {
    const recovery =
        'Do not purchase again. Use Restore Purchases to activate the existing purchase.';
    if (code == 'apple_transaction_superseded') {
      return 'A newer App Store storage plan already owns this vault\'s subscription. '
          'Use Restore Purchases to refresh the current plan. Do not purchase again.';
    }
    if (code == 'subscription_bound_to_another_active_account') {
      return 'This App Store subscription is linked to a different SVaultAI vault. '
          'Sign in to the vault used for this purchase, then use Restore Purchases. '
          'Do not purchase again.';
    }
    if (code == 'active_storage_billing_owner') {
      return 'Another store currently manages this vault\'s storage subscription. '
          'Contact support to resolve the billing link. Do not purchase again.';
    }
    if (code == 'apple_billing_not_configured' || statusCode == 404) {
      return 'Apple accepted the purchase, but SVaultAI activation is temporarily '
          'unavailable. Please contact support. $recovery';
    }
    if (statusCode == 401 || statusCode == 403) {
      return 'Apple accepted the purchase, but this vault session could not activate it. '
          'Sign in again and use Restore Purchases. Do not purchase again.';
    }
    if (isTransient) {
      return 'Apple accepted the purchase, but activation is still pending because '
          'the verification service could not be reached. $recovery';
    }
    return 'Apple accepted the purchase, but SVaultAI could not verify it yet. '
        'Please contact support if restoring does not help. $recovery';
  }

  String get userTitle => code == 'apple_transaction_superseded'
      ? 'Storage plan already updated'
      : statusCode == 409
          ? 'Subscription link needs attention'
          : 'Purchase activation pending';

  @override
  String toString() =>
      'Apple purchase activation failed (${statusCode ?? 'network'}; ${code ?? 'unavailable'}).';
}

class ApplePurchaseRecoveryResult {
  final bool handled;
  final Map<String, dynamic> verification;

  const ApplePurchaseRecoveryResult({
    required this.handled,
    required this.verification,
  });
}

/// Serializes duplicate callbacks for the same vault/transaction. Retries only
/// verification of the SAME signed transaction, never checkout or a new charge.
class ApplePurchaseRecovery {
  ApplePurchaseRecovery({Future<void> Function(Duration)? delay})
      : _delay = delay ?? Future<void>.delayed;

  final Future<void> Function(Duration) _delay;
  final Map<String, Future<Map<String, dynamic>>> _inFlight = {};
  final LinkedHashMap<String, Map<String, dynamic>> _completed =
      LinkedHashMap();

  Future<ApplePurchaseRecoveryResult> recover({
    required String accountKey,
    required String transactionKey,
    required Future<Map<String, dynamic>> Function() verify,
    required Future<void> Function() finish,
  }) async {
    // Account scoping prevents a previous vault's result authorizing another.
    final key = '$accountKey:$transactionKey';
    final completed = _completed[key];
    if (completed != null) {
      return ApplePurchaseRecoveryResult(
        handled: false,
        verification: completed,
      );
    }
    final pending = _inFlight[key];
    if (pending != null) {
      return ApplePurchaseRecoveryResult(
        handled: false,
        verification: await pending,
      );
    }
    final operation = _verifyAndFinish(verify: verify, finish: finish);
    _inFlight[key] = operation;
    try {
      final verification = await operation;
      _completed[key] = verification;
      // Only a bounded in-memory dedupe cache; Apple/backend remain authority.
      if (_completed.length > 100) _completed.remove(_completed.keys.first);
      return ApplePurchaseRecoveryResult(
        handled: true,
        verification: verification,
      );
    } finally {
      _inFlight.remove(key);
    }
  }

  Future<Map<String, dynamic>> _verifyAndFinish({
    required Future<Map<String, dynamic>> Function() verify,
    required Future<void> Function() finish,
  }) async {
    for (var attempt = 0; attempt < 3; attempt++) {
      Map<String, dynamic> verification;
      try {
        verification = await verify();
      } on ApplePurchaseVerificationException catch (error) {
        if (!error.isTransient || attempt == 2) rethrow;
        await _delay(Duration(milliseconds: 500 * (attempt + 1)));
        continue;
      }
      if (verification['verified'] != true) {
        throw const ApplePurchaseVerificationException(
          statusCode: 200,
          code: 'unconfirmed_verification',
        );
      }
      // Never finish a rejected/pending transaction. A failed finish is left
      // recoverable by redelivery/Restore, without initiating another purchase.
      await finish();
      return verification;
    }
    throw StateError('Unreachable Apple verification retry state.');
  }
}
