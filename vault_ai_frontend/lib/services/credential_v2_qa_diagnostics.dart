import 'package:flutter/foundation.dart';

const bool qaV2DiagnosticsEnabled =
    bool.fromEnvironment('QA_AUTH_DIAGNOSTICS', defaultValue: false);
const String qaV2TargetRecordId = 'generated-1d1c9d799b70b2c919d2cb558bec682f';
final ValueNotifier<String> qaV2HydrationDiagnostic = ValueNotifier<String>('');
final Map<String, String> _state = <String, String>{};
void qaV2HydrationTrace(String stage, {String? error}) {
  if (!qaV2DiagnosticsEnabled || !stage.startsWith('target_')) return;
  _state[stage] = 'true';
  if (error != null) _state['target_safe_error_category'] = error;
  for (final failed in const [
    'target_parse_exception',
    'target_decrypt_exception'
  ]) {
    if (_state.containsKey(failed))
      _state['first_failed_target_stage'] = failed;
  }
  qaV2HydrationDiagnostic.value =
      _state.entries.map((e) => '${e.key}=${e.value}').join(';');
}
