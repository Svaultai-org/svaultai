// vaultai-opaque-init.js — glue between the vendored
// @serenity-kit/opaque ESM bundle and Dart via dart:js_interop.
//
// This file is intentionally tiny. It:
//   1. Imports the ESM module.
//   2. Awaits its `ready` Promise (WASM instantiation).
//   3. Attaches only the CLIENT half to `globalThis` under the
//      SVaultAI namespace, so Dart's JS interop can call it.
//   4. Sets `globalThis.vaultaiOpaqueReady` to a Promise that
//      resolves once the WASM is instantiated. Dart awaits this
//      before making any client.* call.
//
// The SERVER half of the bundle is deliberately NOT exposed to
// window. The client-side has no legitimate need to run the server
// role. Attaching only `client` closes off the accidental
// "startServerLogin in the browser" foot-gun.
//
// The bundle contains the audited RFC 9807 opaque-ke Rust core as
// WebAssembly. No custom cryptography lives in this file.

import * as opaque from "./serenity-kit-opaque.esm.js";

// Marker used by Dart to double-check the vendored bundle version.
// Bump manually when the vendored ESM is refreshed.
globalThis.vaultaiOpaqueVendorVersion = "@serenity-kit/opaque@1.1.0";

globalThis.vaultaiOpaqueReady = (async () => {
  await opaque.ready;
  globalThis.vaultaiOpaqueClient = opaque.client;
  return true;
})();

globalThis.vaultaiOpaqueReady.catch((err) => {
  console.error("[vaultai-opaque-init] failed to initialize WASM:", err);
});
