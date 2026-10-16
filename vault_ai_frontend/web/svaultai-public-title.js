// Preserve the public page title when Flutter sets its application title.
// Private routes retain their own titles and existing indexing restrictions.
(function () {
  'use strict';
  var title = 'SVaultAI — Encrypted Digital Vault';
  function syncPublicTitle() {
    if (window.location.pathname === '/' && document.title !== title) {
      document.title = title;
    }
  }
  syncPublicTitle();
  new MutationObserver(syncPublicTitle).observe(document.head, {
    childList: true, subtree: true, characterData: true
  });
  window.addEventListener('popstate', syncPublicTitle);
})();
