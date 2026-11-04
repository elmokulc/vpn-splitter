#ifndef VPN_SPLITTER_AUDIT_TOKEN_SUPPORT_H
#define VPN_SPLITTER_AUDIT_TOKEN_SUPPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <sys/types.h>

size_t vps_audit_token_size(void);
bool vps_audit_token_euid(const void *bytes, size_t length, uid_t *uid);
bool vps_copy_own_audit_token(void *bytes, size_t length);

#endif
