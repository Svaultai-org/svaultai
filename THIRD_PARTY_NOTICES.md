# Third-party notices

ATTORNEY_REVIEW_REQUIRED=true

SVaultAI includes or depends on third-party software. That software is not
relicensed under the proprietary terms in the root `LICENSE`; it remains
subject to the terms supplied by its respective copyright holders.

## Vendored distribution

The web client vendors `@serenity-kit/opaque` and its `opaque-ke` WebAssembly
core. Its MIT license and copyright notice are preserved verbatim at:

`vault_ai_frontend/web/assets/opaque/LICENSE-serenity-kit-opaque`

The native and server OPAQUE wrappers depend on the Rust `opaque-ke` ecosystem.
Cargo resolves the applicable upstream package licenses; those licenses apply
to those packages, not the SVaultAI-owned wrapper and application code.

## Package-managed dependencies

Dependency manifests and lockfiles are the authoritative version inventories:

- Flutter/Dart: `vault_ai_frontend/pubspec.yaml` and `pubspec.lock`
- Python: `vault_ai_backend/requirements.txt` and
  `vault_ai_backend/requirements-dev.txt`
- Node.js: `vault_ai_backend/package.json` and `package-lock.json`
- Rust OPAQUE server: `vault_ai_backend/opaque_server_crate/Cargo.toml` and
  `Cargo.lock`
- Rust OPAQUE client: `vault_ai_frontend/native/opaque_client/Cargo.toml` and
  `Cargo.lock`
- Apple platform packages: the tracked Podfiles and Podfile.lock files

Package-manager metadata and the license files installed with each package
control the use and redistribution of those dependencies. Builds and binary
distributions must retain notices and reproduce license text whenever the
upstream license requires it. Copyleft, attribution, patent-notice, source
offer, and trademark obligations must be reviewed for each distribution
target before release.

This notice is a compliance map, not a complete legal opinion. Automated
dependency-license inventory and qualified legal review should be part of
every release process.
