#include "AuditTokenSupport.h"
#include <bsm/libbsm.h>
#include <mach/mach.h>
#include <string.h>

size_t vps_audit_token_size(void) {
    return sizeof(audit_token_t);
}

bool vps_audit_token_euid(const void *bytes, size_t length, uid_t *uid) {
    if (bytes == NULL || uid == NULL || length != sizeof(audit_token_t)) {
        return false;
    }
    audit_token_t token;
    // NSData storage need not have audit_token_t's alignment.
    memcpy(&token, bytes, sizeof(token));
    *uid = audit_token_to_euid(token);
    return true;
}

bool vps_copy_own_audit_token(void *bytes, size_t length) {
    if (bytes == NULL || length != sizeof(audit_token_t)) {
        return false;
    }
    audit_token_t token;
    mach_msg_type_number_t count = TASK_AUDIT_TOKEN_COUNT;
    kern_return_t result = task_info(mach_task_self(), TASK_AUDIT_TOKEN,
                                    (task_info_t)&token, &count);
    if (result != KERN_SUCCESS || count != TASK_AUDIT_TOKEN_COUNT) {
        return false;
    }
    memcpy(bytes, &token, sizeof(token));
    return true;
}
