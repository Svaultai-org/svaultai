/// Obtains a fresh PIN only for an OPAQUE action proof. The PIN stays local to
/// [verifyPin]; callers send only the returned proof to content routes.
Future<String?> resolveZkActionProof({
  required bool promptForPrivateSession,
  required Future<String?> Function() promptPin,
  required Future<String> Function() cachedPin,
  required Future<String> Function(String pin) verifyPin,
}) async {
  final pin = promptForPrivateSession ? await promptPin() : await cachedPin();
  if (pin == null) return null;
  return verifyPin(pin);
}
