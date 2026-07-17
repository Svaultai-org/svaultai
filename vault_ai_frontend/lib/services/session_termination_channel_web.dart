library;

/// Peer-tab termination channel — web (BroadcastChannel).
///
/// Every tab of the app in the same origin subscribes to a shared
/// `vaultai:session_terminated` broadcast channel. When any tab
/// terminates locally due to a coded 401 (or a manual logout that
/// wants to fan out), it publishes `{generation, code}`; every other
/// tab picks up the message and runs its own local termination
/// exactly once per generation.
///
/// Messages are plain JSON-encoded strings — no auth material, no
/// token identifiers, no vault ids. The generation is a monotonic
/// int local to the sender's process; the receiver compares against
/// its own generation to reject self-echoes and stale broadcasts.

// ignore_for_file: deprecated_member_use
// dart:html — same rationale as file_downloader_web.dart et al.

import 'dart:convert';
import 'dart:html' as html;

import 'session_termination.dart' show SessionTerminationCode;

typedef PeerTabListener = void Function(
    int generation, SessionTerminationCode code);

const String _channelName = 'vaultai:session_terminated:v1';

class SessionTerminationChannel {
  html.BroadcastChannel? _bc;
  PeerTabListener? _listener;

  SessionTerminationChannel() {
    try {
      _bc = html.BroadcastChannel(_channelName);
      _bc!.onMessage.listen(_onMessage);
    } catch (_) {
      // BroadcastChannel unsupported (very old browsers, or a
      // non-browser web environment): the singleton silently
      // degrades to no cross-tab handoff. Local termination still
      // runs.
      _bc = null;
    }
  }

  void broadcast(int generation, SessionTerminationCode code) {
    final bc = _bc;
    if (bc == null) return;
    try {
      bc.postMessage(jsonEncode(<String, dynamic>{
        'g': generation,
        'c': _codeToWire(code),
      }));
    } catch (_) {
      // Best-effort. If postMessage fails the local cleanup still
      // ran.
    }
  }

  void listen(PeerTabListener listener) {
    _listener = listener;
  }

  void close() {
    try {
      _bc?.close();
    } catch (_) {}
    _bc = null;
    _listener = null;
  }

  void _onMessage(html.MessageEvent event) {
    final listener = _listener;
    if (listener == null) return;
    try {
      final data = event.data;
      if (data is! String) return;
      final decoded = jsonDecode(data);
      if (decoded is! Map) return;
      final g = decoded['g'];
      final c = decoded['c'];
      if (g is! int || c is! String) return;
      final code = _codeFromWire(c);
      if (code == null) return;
      listener(g, code);
    } catch (_) {
      // Malformed peer message. Ignore.
    }
  }
}

String _codeToWire(SessionTerminationCode code) {
  switch (code) {
    case SessionTerminationCode.superseded:
      return 'session_superseded';
    case SessionTerminationCode.expired:
      return 'session_expired';
    case SessionTerminationCode.revoked:
      return 'session_revoked';
    case SessionTerminationCode.invalid:
      return 'invalid_session';
  }
}

SessionTerminationCode? _codeFromWire(String s) {
  switch (s) {
    case 'session_superseded':
      return SessionTerminationCode.superseded;
    case 'session_expired':
      return SessionTerminationCode.expired;
    case 'session_revoked':
      return SessionTerminationCode.revoked;
    case 'invalid_session':
      return SessionTerminationCode.invalid;
    default:
      return null;
  }
}
