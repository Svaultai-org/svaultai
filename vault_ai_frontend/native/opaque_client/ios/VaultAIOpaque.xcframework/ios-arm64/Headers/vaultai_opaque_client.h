#ifndef VAULTAI_OPAQUE_CLIENT_H
#define VAULTAI_OPAQUE_CLIENT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint32_t vaultai_opaque_client_link_anchor(void);
char *vaultai_opaque_client_start_registration(const char *password);
char *vaultai_opaque_client_finish_registration(
    const char *password,
    const char *registration_response,
    const char *client_registration_state,
    const char *client_identifier,
    const char *server_identifier);
char *vaultai_opaque_client_start_login(const char *password);
char *vaultai_opaque_client_finish_login(
    const char *client_login_state,
    const char *login_response,
    const char *password,
    const char *client_identifier,
    const char *server_identifier);
char *vaultai_pbkdf2_hmac_sha256(
    const char *password,
    const char *salt_base64,
    uint32_t iterations);
void vaultai_opaque_client_free_string(char *value);

#ifdef __cplusplus
}
#endif

#endif
