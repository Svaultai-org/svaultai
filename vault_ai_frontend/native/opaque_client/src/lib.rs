use std::ffi::{CStr, CString};
use std::os::raw::c_char;

use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine as _,
};
use pbkdf2::pbkdf2_hmac;
use opaque_ke::ciphersuite::CipherSuite;
use opaque_ke::{
    ClientLogin, ClientLoginFinishParameters, ClientRegistration,
    ClientRegistrationFinishParameters, CredentialResponse, Identifiers, RegistrationResponse,
    Ristretto255,
};
use rand::rngs::OsRng;
use serde_json::json;
use sha2::{Sha256, Sha512};
use zeroize::{Zeroize, Zeroizing};

#[derive(Default)]
struct VaultAiSuite;

impl CipherSuite for VaultAiSuite {
    type OprfCs = Ristretto255;
    type KeyExchange = opaque_ke::key_exchange::tripledh::TripleDh<Ristretto255, Sha512>;
    type Ksf = argon2::Argon2<'static>;
}

fn cstr(ptr: *const c_char) -> Result<Zeroizing<String>, ()> {
    if ptr.is_null() {
        return Ok(Zeroizing::new(String::new()));
    }
    unsafe { CStr::from_ptr(ptr) }
        .to_str()
        .map(|s| Zeroizing::new(s.to_owned()))
        .map_err(|_| ())
}

fn b64d(s: &str) -> Result<Zeroizing<Vec<u8>>, ()> {
    URL_SAFE_NO_PAD
        .decode(s.as_bytes())
        .map(Zeroizing::new)
        .map_err(|_| ())
}

fn b64e(raw: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(raw)
}

fn b64d_standard_or_url(s: &str) -> Result<Zeroizing<Vec<u8>>, ()> {
    STANDARD
        .decode(s.as_bytes())
        .or_else(|_| URL_SAFE_NO_PAD.decode(s.as_bytes()))
        .map(Zeroizing::new)
        .map_err(|_| ())
}

fn output(text: String) -> *mut c_char {
    CString::new(text)
        .unwrap_or_else(|_| CString::new("{\"ok\":false,\"error\":\"json_failed\"}").unwrap())
        .into_raw()
}

fn ok(value: serde_json::Value) -> *mut c_char {
    output(value.to_string())
}

fn err(code: &str) -> *mut c_char {
    ok(json!({"ok": false, "error": code}))
}

fn optional_identifier(value: &str) -> Option<&[u8]> {
    if value.is_empty() {
        None
    } else {
        Some(value.as_bytes())
    }
}

fn key_stretching() -> Result<argon2::Argon2<'static>, ()> {
    // Match @serenity-kit/opaque's default "memory-constrained" Argon2id
    // parameters used by the production web client.
    let params = argon2::Params::new(1 << 16, 3, 4, None).map_err(|_| ())?;
    Ok(argon2::Argon2::new(
        argon2::Algorithm::Argon2id,
        argon2::Version::V0x13,
        params,
    ))
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_opaque_client_start_registration(
    password: *const c_char,
) -> *mut c_char {
    let password = match cstr(password) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let mut rng = OsRng;
    match ClientRegistration::<VaultAiSuite>::start(&mut rng, password.as_bytes()) {
        Ok(result) => ok(json!({
            "ok": true,
            "clientRegistrationState": b64e(result.state.serialize().as_slice()),
            "registrationRequest": b64e(result.message.serialize().as_slice()),
        })),
        Err(_) => err("protocol_failed"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_opaque_client_finish_registration(
    password: *const c_char,
    registration_response: *const c_char,
    client_registration_state: *const c_char,
    client_identifier: *const c_char,
    server_identifier: *const c_char,
) -> *mut c_char {
    let password = match cstr(password) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let response_bytes = match cstr(registration_response).and_then(|s| b64d(&s)) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let state_bytes = match cstr(client_registration_state).and_then(|s| b64d(&s)) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let client_id = match cstr(client_identifier) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let server_id = match cstr(server_identifier) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let state = match ClientRegistration::<VaultAiSuite>::deserialize(state_bytes.as_slice()) {
        Ok(value) => value,
        Err(_) => return err("protocol_failed"),
    };
    let response =
        match RegistrationResponse::<VaultAiSuite>::deserialize(response_bytes.as_slice()) {
            Ok(value) => value,
            Err(_) => return err("protocol_failed"),
        };
    let ksf = match key_stretching() {
        Ok(value) => value,
        Err(_) => return err("protocol_failed"),
    };
    let params = ClientRegistrationFinishParameters::new(
        Identifiers {
            client: optional_identifier(&client_id),
            server: optional_identifier(&server_id),
        },
        Some(&ksf),
    );
    let mut rng = OsRng;
    match state.finish(&mut rng, password.as_bytes(), response, params) {
        Ok(result) => ok(json!({
            "ok": true,
            "registrationRecord": b64e(result.message.serialize().as_slice()),
            "exportKey": b64e(result.export_key.as_slice()),
            "serverStaticPublicKey": b64e(result.server_s_pk.serialize().as_slice()),
        })),
        Err(_) => err("protocol_failed"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_opaque_client_start_login(password: *const c_char) -> *mut c_char {
    let password = match cstr(password) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let mut rng = OsRng;
    match ClientLogin::<VaultAiSuite>::start(&mut rng, password.as_bytes()) {
        Ok(result) => ok(json!({
            "ok": true,
            "clientLoginState": b64e(result.state.serialize().as_slice()),
            "startLoginRequest": b64e(result.message.serialize().as_slice()),
        })),
        Err(_) => err("protocol_failed"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_opaque_client_finish_login(
    client_login_state: *const c_char,
    login_response: *const c_char,
    password: *const c_char,
    client_identifier: *const c_char,
    server_identifier: *const c_char,
) -> *mut c_char {
    let state_bytes = match cstr(client_login_state).and_then(|s| b64d(&s)) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let response_bytes = match cstr(login_response).and_then(|s| b64d(&s)) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let password = match cstr(password) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let client_id = match cstr(client_identifier) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let server_id = match cstr(server_identifier) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let state = match ClientLogin::<VaultAiSuite>::deserialize(state_bytes.as_slice()) {
        Ok(value) => value,
        Err(_) => return err("auth_failed"),
    };
    let response = match CredentialResponse::<VaultAiSuite>::deserialize(response_bytes.as_slice())
    {
        Ok(value) => value,
        Err(_) => return err("auth_failed"),
    };
    let ksf = match key_stretching() {
        Ok(value) => value,
        Err(_) => return err("protocol_failed"),
    };
    let params = ClientLoginFinishParameters::new(
        None,
        Identifiers {
            client: optional_identifier(&client_id),
            server: optional_identifier(&server_id),
        },
        Some(&ksf),
    );
    let mut rng = OsRng;
    match state.finish(&mut rng, password.as_bytes(), response, params) {
        Ok(result) => ok(json!({
            "ok": true,
            "finishLoginRequest": b64e(result.message.serialize().as_slice()),
            "sessionKey": b64e(result.session_key.as_slice()),
            "exportKey": b64e(result.export_key.as_slice()),
            "serverStaticPublicKey": b64e(result.server_s_pk.serialize().as_slice()),
        })),
        Err(_) => err("auth_failed"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_pbkdf2_hmac_sha256(
    password: *const c_char,
    salt_base64: *const c_char,
    iterations: u32,
) -> *mut c_char {
    if iterations == 0 {
        return err("bad_input");
    }
    let password = match cstr(password) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let salt = match cstr(salt_base64).and_then(|s| b64d_standard_or_url(&s)) {
        Ok(value) => value,
        Err(_) => return err("bad_input"),
    };
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2_hmac::<Sha256>(password.as_bytes(), salt.as_slice(), iterations, &mut key[..]);
    ok(json!({
        "ok": true,
        "key": STANDARD.encode(key.as_slice()),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn vaultai_opaque_client_free_string(value: *mut c_char) {
    if !value.is_null() {
        let mut bytes = CString::from_raw(value).into_bytes_with_nul();
        bytes.zeroize();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use opaque_ke::{ServerLogin, ServerLoginParameters, ServerRegistration, ServerSetup};

    fn hex_to_bytes(value: &str) -> Vec<u8> {
        assert_eq!(value.len() % 2, 0);
        (0..value.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&value[i..i + 2], 16).unwrap())
            .collect()
    }

    fn pbkdf2_sha256(password: &[u8], salt: &[u8], iterations: u32) -> [u8; 32] {
        let mut key = [0u8; 32];
        pbkdf2_hmac::<Sha256>(password, salt, iterations, &mut key);
        key
    }

    fn register_with_web_ksf(
        setup: &ServerSetup<VaultAiSuite>,
        password: &[u8],
        credential_id: &[u8],
    ) -> Vec<u8> {
        let mut rng = OsRng;
        let client_start = ClientRegistration::<VaultAiSuite>::start(&mut rng, password).unwrap();
        let server_start =
            ServerRegistration::start(setup, client_start.message, credential_id).unwrap();
        let ksf = key_stretching().unwrap();
        let client_finish = client_start
            .state
            .finish(
                &mut rng,
                password,
                server_start.message,
                ClientRegistrationFinishParameters::new(
                    Identifiers {
                        client: None,
                        server: None,
                    },
                    Some(&ksf),
                ),
            )
            .unwrap();
        ServerRegistration::<VaultAiSuite>::finish(client_finish.message)
            .serialize()
            .to_vec()
    }

    fn login_with_ksf(
        setup: &ServerSetup<VaultAiSuite>,
        record_bytes: &[u8],
        password: &[u8],
        credential_id: &[u8],
        ksf: Option<&argon2::Argon2<'static>>,
    ) -> bool {
        let mut rng = OsRng;
        let client_start = ClientLogin::<VaultAiSuite>::start(&mut rng, password).unwrap();
        let record = ServerRegistration::<VaultAiSuite>::deserialize(record_bytes).unwrap();
        let server_start = ServerLogin::start(
            &mut rng,
            setup,
            Some(record),
            client_start.message,
            credential_id,
            ServerLoginParameters::default(),
        )
        .unwrap();
        let client_finish = match client_start.state.finish(
            &mut rng,
            password,
            server_start.message,
            ClientLoginFinishParameters::new(
                None,
                Identifiers {
                    client: None,
                    server: None,
                },
                ksf,
            ),
        ) {
            Ok(value) => value,
            Err(_) => return false,
        };
        match server_start
            .state
            .finish(client_finish.message, ServerLoginParameters::default())
        {
            Ok(server_finish) => client_finish.session_key == server_finish.session_key,
            Err(_) => false,
        }
    }

    #[test]
    fn web_compatible_ksf_is_required_for_android_login() {
        let mut rng = OsRng;
        let setup = ServerSetup::<VaultAiSuite>::new(&mut rng);
        let credential_id = b"test-credential-id";
        let password = b"test-pin";
        let record = register_with_web_ksf(&setup, password, credential_id);

        assert!(!login_with_ksf(
            &setup,
            &record,
            password,
            credential_id,
            None,
        ));

        let ksf = key_stretching().unwrap();
        assert!(login_with_ksf(
            &setup,
            &record,
            password,
            credential_id,
            Some(&ksf),
        ));
    }

    #[test]
    fn pbkdf2_hmac_sha256_matches_fixed_vectors() {
        let cases = [
            (
                b"password".as_slice(),
                b"salt".as_slice(),
                1,
                "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b",
            ),
            (
                b"password".as_slice(),
                b"salt".as_slice(),
                2,
                "ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43",
            ),
            (
                b"password".as_slice(),
                b"salt".as_slice(),
                4096,
                "c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a",
            ),
        ];
        for (password, salt, iterations, expected_hex) in cases {
            assert_eq!(
                pbkdf2_sha256(password, salt, iterations).to_vec(),
                hex_to_bytes(expected_hex),
            );
        }
    }
}
