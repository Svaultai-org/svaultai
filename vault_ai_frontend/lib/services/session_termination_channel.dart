library;

/// Peer-tab termination channel — stub (non-web).
///
/// Native builds don't have multiple concurrent tabs into the same
/// process; every method is a safe no-op. Web builds get the real
/// implementation via conditional import in
/// `session_termination.dart`.

import 'session_termination.dart' show SessionTerminationCode;

typedef PeerTabListener = void Function(
    int generation, SessionTerminationCode code);

class SessionTerminationChannel {
  void broadcast(int generation, SessionTerminationCode code) {
    // no-op on native
  }

  void listen(PeerTabListener listener) {
    // no-op on native
  }

  void close() {
    // no-op on native
  }
}
