// Source-level fallback for accidental plain `flutter build web`
// deployments. The release scripts overwrite build/web/vaultai-sw-
// bootstrap.js from vaultai-sw-bootstrap.template.js with a concrete
// release SHA; this file exists so /vaultai-sw-bootstrap.js is still a
// 200 response if the plain Flutter output is uploaded by mistake.
(function () {
  'use strict';

  window.__vaultaiSwBootstrapLoaded = true;

  var RELEASE = '__VAULTAI_APP_RELEASE__';
  if (RELEASE.charAt(0) === '_' && RELEASE.charAt(1) === '_') {
    console.warn(
      '[vaultai-sw-bootstrap] unresolved release token; ' +
      'run scripts/build-web-release before production upload.'
    );
    return;
  }

  var SW_URL = '/flutter_service_worker.js?v=' + RELEASE;
  var SW_SCOPE = '/';
  var RELOAD_KEY = 'vaultai_sw_migration_reloaded';
  var reloaded = false;

  if (!('serviceWorker' in navigator)) {
    return;
  }

  function readReloadedTarget() {
    try {
      return sessionStorage.getItem(RELOAD_KEY);
    } catch (_) {
      return null;
    }
  }

  function writeReloadedTarget(target) {
    try {
      sessionStorage.setItem(RELOAD_KEY, target);
    } catch (_) {}
  }

  function safeReload() {
    if (reloaded || readReloadedTarget() === RELEASE) {
      return;
    }
    reloaded = true;
    writeReloadedTarget(RELEASE);
    try {
      window.location.reload();
    } catch (_) {}
  }

  navigator.serviceWorker.addEventListener('controllerchange', safeReload);

  function registerNow() {
    try {
      navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
        .then(function (reg) {
          try {
            if (reg) reg.update();
          } catch (_) {}
        })
        .catch(function () {});
    } catch (_) {}
  }

  if (document.readyState === 'complete') {
    registerNow();
  } else {
    window.addEventListener('load', registerNow, { once: true });
  }
})();
