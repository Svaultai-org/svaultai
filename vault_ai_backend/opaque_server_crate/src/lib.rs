//! VaultAI pyo3 wrapper for Meta's audited opaque-ke (RFC 9807).
//!
//! This module contains **zero custom cryptography.** Every function
//! is a byte-in / byte-out shim over opaque-ke's typed API. The
//! ciphersuite matches @serenity-kit/opaque on the Web client so wire
//! interoperability is guaranteed against the same upstream Rust
//! crate.
//!
//! CipherSuite:
//!   * OPRF group:        Ristretto255
//!   * Key exchange:      Ristretto255 + Triple-DH
//!   * Hash:              SHA-512
//!   * Key-stretching:    Argon2id (default opaque-ke parameters)
//!
//! Public API (exposed to Python):
//!   * server_setup_new()                    -> ServerSetup bytes
//!   * server_registration_start(setup, ke1_msg, credential_id)
//!         -> RegistrationResponse bytes
//!   * server_registration_finish(ke3_msg)   -> RegistrationRecord bytes
//!   * server_login_start(setup, record, ke1_msg, credential_id)
//!         -> (LoginResponse bytes, ServerLoginState bytes)
//!   * server_login_finish(state_bytes, ke3_msg) -> session_key bytes
//!
//! State between rounds is serialized to bytes; the FastAPI handler
//! stores it in a short-lived Redis/DB slot keyed by request id. The
//! Rust crate is stateless.

use opaque_ke::{
    ciphersuite::CipherSuite,
    Ristretto255,
    ServerLogin,
    ServerLoginParameters,
    ServerLoginStartParameters,
    ServerLoginStartResult,
    ServerRegistration,
    ServerRegistrationStartResult,
    ServerSetup,
    RegistrationRequest,
    RegistrationResponse,
    RegistrationUpload,
    CredentialRequest,
    CredentialResponse,
    CredentialFinalization,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rand::rngs::OsRng;

/// Ristretto255-SHA512-Argon2id: matches @serenity-kit/opaque default.
#[derive(Default)]
struct VaultAiSuite;

impl CipherSuite for VaultAiSuite {
    type OprfCs = Ristretto255;
    type KeGroup = Ristretto255;
    type KeyExchange = opaque_ke::key_exchange::tripledh::TripleDh;
    type Ksf = argon2::Argon2<'static>;
}

fn py_err<E: std::fmt::Display>(e: E) -> PyErr {
    PyValueError::new_err(format!("opaque error: {}", e))
}

/// Generate a fresh long-term ServerSetup (server private key + OPRF
/// master key). Should be called ONCE per deployment and the returned
/// bytes stored as a secret (env var or KMS-wrapped in DB).
#[pyfunction]
fn server_setup_new(py: Python<'_>) -> PyResult<PyObject> {
    let mut rng = OsRng;
    let setup: ServerSetup<VaultAiSuite> = ServerSetup::new(&mut rng);
    let bytes = setup.serialize();
    Ok(PyBytes::new_bound(py, bytes.as_slice()).into())
}

/// Server-side registration step 1: consume client's RegistrationRequest,
/// produce RegistrationResponse.
///
/// `credential_id` is the vault_handle bytes — used by opaque-ke to
/// seed the per-record OPRF secret. Because the vault_handle is
/// high-entropy client-generated (see design report), it is not
/// dictionary-attackable.
#[pyfunction]
fn server_registration_start(
    py: Python<'_>,
    setup_bytes: &[u8],
    ke1_msg: &[u8],
    credential_id: &[u8],
) -> PyResult<PyObject> {
    let setup: ServerSetup<VaultAiSuite> =
        ServerSetup::deserialize(setup_bytes).map_err(py_err)?;
    let request: RegistrationRequest<VaultAiSuite> =
        RegistrationRequest::deserialize(ke1_msg).map_err(py_err)?;
    let result: ServerRegistrationStartResult<VaultAiSuite> =
        ServerRegistration::start(&setup, request, credential_id).map_err(py_err)?;
    let response_bytes = result.message.serialize();
    Ok(PyBytes::new_bound(py, response_bytes.as_slice()).into())
}

/// Server-side registration step 2: consume client's RegistrationUpload,
/// produce the registration record for storage in vault_zk_state.
#[pyfunction]
fn server_registration_finish(
    py: Python<'_>,
    ke3_msg: &[u8],
) -> PyResult<PyObject> {
    let upload: RegistrationUpload<VaultAiSuite> =
        RegistrationUpload::deserialize(ke3_msg).map_err(py_err)?;
    let record: ServerRegistration<VaultAiSuite> =
        ServerRegistration::finish(upload);
    let record_bytes = record.serialize();
    Ok(PyBytes::new_bound(py, record_bytes.as_slice()).into())
}

/// Server-side login step 1: consume client's CredentialRequest (KE1),
/// produce CredentialResponse (KE2) + ServerLogin state.
///
/// Returns a 2-tuple: (ke2_bytes, server_state_bytes). The FastAPI
/// handler MUST store server_state_bytes in a short-TTL request slot
/// keyed by the client's ephemeral session id and pass it back at the
/// finish step.
#[pyfunction]
fn server_login_start(
    py: Python<'_>,
    setup_bytes: &[u8],
    record_bytes: &[u8],
    ke1_msg: &[u8],
    credential_id: &[u8],
) -> PyResult<PyObject> {
    let setup: ServerSetup<VaultAiSuite> =
        ServerSetup::deserialize(setup_bytes).map_err(py_err)?;
    let record: ServerRegistration<VaultAiSuite> =
        ServerRegistration::deserialize(record_bytes).map_err(py_err)?;
    let request: CredentialRequest<VaultAiSuite> =
        CredentialRequest::deserialize(ke1_msg).map_err(py_err)?;

    let mut rng = OsRng;
    let start: ServerLoginStartResult<VaultAiSuite> = ServerLogin::start(
        &mut rng,
        &setup,
        Some(record),
        request,
        credential_id,
        ServerLoginStartParameters::default(),
    )
    .map_err(py_err)?;

    let ke2 = start.message.serialize();
    let state = start.state.serialize();
    let tuple = (
        PyBytes::new_bound(py, ke2.as_slice()),
        PyBytes::new_bound(py, state.as_slice()),
    );
    Ok(tuple.into_py(py))
}

/// Server-side login step 2: consume client's KE3 (CredentialFinalization)
/// plus the previously stored server state, produce session_key.
///
/// After this call the OPAQUE handshake is complete; the caller mints
/// an auth_sessions row keyed to the vault_id.
#[pyfunction]
fn server_login_finish(
    py: Python<'_>,
    server_state_bytes: &[u8],
    ke3_msg: &[u8],
) -> PyResult<PyObject> {
    let state: ServerLogin<VaultAiSuite> =
        ServerLogin::deserialize(server_state_bytes).map_err(py_err)?;
    let finalization: CredentialFinalization<VaultAiSuite> =
        CredentialFinalization::deserialize(ke3_msg).map_err(py_err)?;
    let result = state
        .finish(finalization, ServerLoginParameters::default())
        .map_err(py_err)?;
    Ok(PyBytes::new_bound(py, result.session_key.as_slice()).into())
}

#[pymodule]
fn vaultai_opaque_server(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(server_setup_new, m)?)?;
    m.add_function(wrap_pyfunction!(server_registration_start, m)?)?;
    m.add_function(wrap_pyfunction!(server_registration_finish, m)?)?;
    m.add_function(wrap_pyfunction!(server_login_start, m)?)?;
    m.add_function(wrap_pyfunction!(server_login_finish, m)?)?;
    Ok(())
}
