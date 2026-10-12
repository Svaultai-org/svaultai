import 'dart:convert';

const savedItemUpdateRequiredMessage =
    'Update SVaultAI to edit saved items. Your saved data is still available.';

class SavedItemUpdateRequiredException implements Exception {
  const SavedItemUpdateRequiredException();
  @override
  String toString() => savedItemUpdateRequiredMessage;
}

/// Only this exact structured backend code is an update requirement.
/// Never echo a provider response or confuse a normal duplicate/conflict.
void throwIfSavedItemUpdateRequired(int statusCode, String responseBody) {
  if (statusCode != 409) return;
  Object? decoded;
  try {
    decoded = jsonDecode(responseBody);
  } on FormatException {
    return;
  }
  if (decoded is! Map) return;
  final detail = decoded['detail'];
  if (detail is Map && detail['code'] == 'update_app_required') {
    throw const SavedItemUpdateRequiredException();
  }
}
