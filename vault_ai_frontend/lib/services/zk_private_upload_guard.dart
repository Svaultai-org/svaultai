/// Preserve a private V2 upload's key and vault binding across queue setup.
library;

import 'package:cryptography/cryptography.dart';

enum ZkFileUploadMode { legacy, privateV2 }

/// V2 stores independent encrypted files. It cannot yet reproduce the
/// legacy import batch, folder duplicate, or name-conflict decisions. Do not
/// silently change those semantics for a bearer whose old create route is
/// signed off. The selected files stay in the composer for a later retry.
bool signedCreateBatchNeedsParity({
  required bool signedCreateOffered,
  required bool hasFolderContext,
  required bool isMultiFileBatch,
}) => signedCreateOffered && (hasFolderContext || isMultiFileBatch);

/// A signed create offer belongs to the current OPAQUE bearer, so it must
/// select V2 before the caller obtains a legacy PIN. An unoffered bearer keeps
/// the older uploader during the signed-create rollout. The existing
/// coordinated V2 pilot remains available when signed-create is disabled.
ZkFileUploadMode selectZkFileUploadMode({
  required bool hasFiles,
  required bool signedCreateClientEnabled,
  required bool signedCreateOffered,
  required bool strictPinFreeFiles,
  required bool writerEnabled,
  required bool readerEnabled,
  required bool hasOpaqueHandle,
  required bool hasActiveMvk,
}) {
  if (!hasFiles) return ZkFileUploadMode.legacy;
  final privateRequired = signedCreateOffered ||
      (strictPinFreeFiles && (hasOpaqueHandle || hasActiveMvk));
  if (privateRequired) {
    if (!writerEnabled || !readerEnabled) {
      throw StateError('Private file upload needs an updated app.');
    }
    return ZkFileUploadMode.privateV2;
  }
  if (signedCreateClientEnabled) return ZkFileUploadMode.legacy;
  return writerEnabled && (hasOpaqueHandle || hasActiveMvk)
      ? ZkFileUploadMode.privateV2
      : ZkFileUploadMode.legacy;
}

({SecretKey mvk, String vaultId}) requirePrivateV2UploadBinding({
  required SecretKey? activeMvk,
  required String? activeKeyVaultId,
  required String? vaultId,
}) {
  if (activeMvk == null ||
      vaultId == null ||
      vaultId.isEmpty ||
      activeKeyVaultId != vaultId) {
    throw StateError('Private upload access changed. Unlock and retry.');
  }
  return (mvk: activeMvk, vaultId: vaultId);
}

SecretKey? selectV2UploadKey({
  required SecretKey? activeMvk,
  required String? activeVaultId,
  required bool writerEnabled,
  required bool readerEnabled,
  SecretKey? requiredPrivateMvk,
  String? requiredPrivateVaultId,
}) {
  if (requiredPrivateMvk == null && requiredPrivateVaultId != null) {
    throw StateError('Private upload binding is incomplete');
  }
  if (requiredPrivateMvk != null) {
    if (!writerEnabled ||
        !readerEnabled ||
        requiredPrivateVaultId == null ||
        requiredPrivateVaultId.isEmpty ||
        activeVaultId != requiredPrivateVaultId ||
        !identical(activeMvk, requiredPrivateMvk)) {
      throw StateError('Private upload access changed. Unlock and retry.');
    }
    return requiredPrivateMvk;
  }
  return writerEnabled ? activeMvk : null;
}

String? uploadAccompanyingText({
  required String? text,
  required SecretKey? requiredPrivateMvk,
}) =>
    requiredPrivateMvk == null ? text : null;
