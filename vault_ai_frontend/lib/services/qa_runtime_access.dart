import 'file_v2_repository.dart';

/// QA-only capability probe. It exposes no token, MVK, or key material.
class QaRuntimeAccess {
  static bool get fileV2RepositoryAvailable =>
      FileV2Repository.current() != null;
}
