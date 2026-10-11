/// The server-owned storage family. A deferred downgrade may verify the
/// current product while the purchased target is scheduled for renewal.
const googlePlayStorageProductIdAllowlist = {
  'svaultai_storage_50gb',
  'svaultai_storage_100gb',
  'svaultai_storage_150gb',
  'svaultai_storage_200gb',
  'svaultai_storage_250gb',
  'svaultai_storage_300gb',
  'svaultai_storage_500gb',
  'svaultai_storage_1tb',
};

/// A safe activation failure. Purchase tokens and backend text are never kept
/// in the public error or its user-facing messages.
class GooglePlayPurchaseVerificationException implements Exception {
  final int? statusCode;
  final String? _code;

  const GooglePlayPurchaseVerificationException({
    this.statusCode,
    String? code,
  }) : _code = code;

  static const _safeCodes = {
    'google_play_verification_unavailable',
    'google_play_verification_retry',
    'google_play_billing_not_configured',
    'purchase_already_bound',
    'subscription_bound_to_another_active_account',
    'active_storage_billing_owner',
    'google_play_replacement_required',
    'google_play_purchase_superseded',
    'google_play_purchase_invalid',
    'invalid_verification_response',
    'unconfirmed_verification',
    'invalid_reconciliation_response',
    'unconfirmed_reconciliation',
    'google_play_request_failed',
    'google_play_context_changed',
    'invalid_google_play_billing_response',
    'invalid_google_play_providers_response',
  };

  /// Only stable, known codes cross the client boundary. An unexpected backend
  /// code may contain private diagnostics and must not reach logs or the UI.
  String? get code => _safeCodes.contains(_code) ? _code : null;

  bool get isTransient {
    if (statusCode == null) return _code == null;
    if (statusCode! < 500 || statusCode! >= 600) return false;
    return !const {
      'google_play_verification_unavailable',
      'google_play_billing_not_configured',
      'purchase_already_bound',
      'subscription_bound_to_another_active_account',
      'active_storage_billing_owner',
      'google_play_replacement_required',
      'google_play_purchase_superseded',
      'google_play_purchase_invalid',
      'invalid_verification_response',
      'unconfirmed_verification',
      'invalid_reconciliation_response',
      'unconfirmed_reconciliation',
      'google_play_request_failed',
      'google_play_context_changed',
      'invalid_google_play_billing_response',
      'invalid_google_play_providers_response',
    }.contains(code);
  }

  String get userMessage {
    const recovery =
        'Do not purchase again. Use Restore Purchases to refresh the existing purchase.';
    if (code == 'google_play_context_changed') {
      return 'The vault session changed while Google Play storage was loading. '
          'Use Restore Purchases in the vault used for this purchase. '
          'Do not purchase again.';
    }
    if (code == 'google_play_purchase_superseded') {
      return 'A newer Google Play storage plan already manages this vault\'s subscription. '
          '$recovery';
    }
    if (code == 'purchase_already_bound' ||
        code == 'subscription_bound_to_another_active_account') {
      return 'This Google Play subscription is linked to a different SVaultAI vault. '
          'Sign in to the vault used for this purchase, then use Restore Purchases. '
          'Do not purchase again.';
    }
    if (code == 'active_storage_billing_owner') {
      return 'Another store manages this vault\'s storage subscription. '
          'Contact support to resolve the billing link. Do not purchase again.';
    }
    if (code == 'google_play_replacement_required') {
      return 'Google Play needs to replace the existing storage subscription. '
          'Use Restore Purchases to refresh your current plan before changing it. '
          'Do not purchase again.';
    }
    if (code == 'google_play_verification_unavailable' ||
        code == 'google_play_billing_not_configured' ||
        statusCode == 404) {
      return 'SVaultAI cannot activate this Google Play purchase right now. '
          'Please contact support. $recovery';
    }
    if (statusCode == 401 || statusCode == 403) {
      return 'This vault session could not activate the Google Play purchase. '
          'Sign in again and use Restore Purchases. Do not purchase again.';
    }
    if (isTransient) {
      return 'Google Play purchase activation is still pending because the '
          'verification service could not be reached. $recovery';
    }
    return 'SVaultAI could not verify this Google Play purchase yet. '
        'Please contact support if restoring does not help. $recovery';
  }

  String get userTitle => code == 'google_play_purchase_superseded'
      ? 'Storage plan already updated'
      : statusCode == 409
          ? 'Subscription link needs attention'
          : 'Purchase activation pending';

  @override
  String toString() => 'Google Play purchase activation failed '
      '(${statusCode ?? 'network'}; ${code ?? 'unavailable'}).';
}
