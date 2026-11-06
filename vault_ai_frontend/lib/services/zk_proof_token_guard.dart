// Prevent a numeric vault PIN from being mistaken for an OPAQUE action proof.
// This is a transport canary, not proof authentication; the server checks
// expiry, MAC, session binding, and one-use consumption.
final RegExp _numericVaultPinShape = RegExp(r'^[0-9]{6,64}$');

String rejectPinShapedZkProof(String proof) {
  if (_numericVaultPinShape.hasMatch(proof.trim())) {
    throw ArgumentError('A one-time action proof is required.');
  }
  return proof;
}
