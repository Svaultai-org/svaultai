

String friendlyVaultFileOpenError(Object error) {
  final raw = error.toString();
  if (_looksLikeNotFound(raw)) {
    return 'This file record exists, but the file content could not '
        'be found. Please refresh or contact support.';
  }
  if (_looksLikeAuthExpired(raw)) {
    return 'Your session expired. Sign in again to open this file.';
  }
  if (_looksLikePinFailure(raw)) {
    return 'PIN check failed. Re-enter your PIN and try again.';
  }
  if (_looksLikeNetwork(raw)) {
    return 'Could not reach the vault server. Check your '
        'connection and try again.';
  }
  return 'Could not open this file. Please try again or contact '
      'support if it keeps failing.';
}


String unsupportedPreviewMessage({
  required String? mimeType,
}) {
  final mt = (mimeType ?? '').trim();
  if (mt.isEmpty) {
    return 'Preview is not available for this file type in the app. '
        'You can download this file.';
  }
  return 'Preview is not available for $mt files yet. You can '
      'download this file.';
}


String pdfPreviewFailedMessage() {
  return 'Preview could not load. You can download this file.';
}


bool isInAppPreviewableMime(String? mimeType) {
  final mt = (mimeType ?? '').trim().toLowerCase();
  if (mt.isEmpty) return false;
  return mt == 'application/pdf' ||
      mt.startsWith('image/') ||
      mt == 'text/plain' ||
      mt == 'text/html';
}

bool _looksLikeNotFound(String raw) {
  final low = raw.toLowerCase();
  return low.contains('404') ||
      low.contains('not found') ||
      low.contains('file not found') ||
      low.contains('file record');
}

bool _looksLikeAuthExpired(String raw) {
  final low = raw.toLowerCase();
  return low.contains('session expired') ||
      low.contains('401') ||
      low.contains('unauthorized') ||
      low.contains('token expired');
}

bool _looksLikePinFailure(String raw) {
  final low = raw.toLowerCase();
  return low.contains('invalid pin') ||
      low.contains('pin verification failed') ||
      low.contains('wrong pin');
}

bool _looksLikeNetwork(String raw) {
  final low = raw.toLowerCase();
  return low.contains('failed to fetch') ||
      low.contains('connection refused') ||
      low.contains('socket') ||
      low.contains('clientexception') ||
      low.contains('network is unreachable');
}
