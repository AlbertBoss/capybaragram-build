// SPDX-License-Identifier: MIT
#include <jni.h>
#include <cstddef>
#include <cstdint>
#include <limits>
#include "native_api.h"

namespace {
void wipe(void *pointer, std::size_t size) {
    auto *bytes = static_cast<volatile unsigned char *>(pointer);
    while (size--) *bytes++ = 0;
}
bool valid(const CapyConnectionEndpoint &value) {
    if (value.abi_version != 1 || !value.port || value.reserved != 0
            || value.secret[0] != 'd' || value.secret[1] != 'd' || value.secret[34] != 0) return false;
    for (int index = 2; index < 34; ++index) {
        const auto byte = value.secret[index];
        if (!((byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f'))) return false;
    }
    return true;
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_org_capybaragram_connection_NativeTunnel_start(JNIEnv *env, jclass, jbyteArray output) {
    if (!output || env->GetArrayLength(output) != 36 || env->ExceptionCheck()) return 0;
    CapyConnectionEndpoint endpoint{};
    const auto handle = capy_connection_start(&endpoint);
    jbyte bytes[36]{};
    const bool accepted = handle && handle <= static_cast<std::uint64_t>(std::numeric_limits<jlong>::max())
        && valid(endpoint);
    if (accepted) {
        bytes[0] = static_cast<jbyte>(endpoint.port & 0xff);
        bytes[1] = static_cast<jbyte>(endpoint.port >> 8);
        for (int index = 0; index < 34; ++index) bytes[index + 2] = static_cast<jbyte>(endpoint.secret[index]);
    }
    env->SetByteArrayRegion(output, 0, 36, bytes);
    wipe(bytes, sizeof(bytes));
    wipe(&endpoint, sizeof(endpoint));
    if (!accepted || env->ExceptionCheck()) {
        if (handle) capy_connection_stop(handle);
        return 0;
    }
    return static_cast<jlong>(handle);
}

extern "C" JNIEXPORT jboolean JNICALL
Java_org_capybaragram_connection_NativeTunnel_status(JNIEnv *env, jclass, jlong handle, jintArray output) {
    if (!output || env->GetArrayLength(output) != 7 || env->ExceptionCheck()) return JNI_FALSE;
    CapyConnectionStatus status{};
    const bool accepted = handle > 0 && capy_connection_status(static_cast<std::uint64_t>(handle), &status) == 1
        && status.abi_version == 1 && status.running <= 1 && status.active <= 128
        && status.data_centre <= 65535 && status.route <= 4;
    jint values[7]{};
    if (accepted) {
        values[0] = 1;
        values[1] = static_cast<jint>(status.running);
        values[2] = static_cast<jint>(status.active);
        values[3] = static_cast<jint>(status.established);
        values[4] = static_cast<jint>(status.failed_tunnels);
        values[5] = static_cast<jint>(status.data_centre);
        values[6] = static_cast<jint>(status.route);
    }
    env->SetIntArrayRegion(output, 0, 7, values);
    return accepted && !env->ExceptionCheck() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jint JNICALL
Java_org_capybaragram_connection_NativeTunnel_stop(JNIEnv *, jclass, jlong handle) {
    return handle > 0 ? capy_connection_stop(static_cast<std::uint64_t>(handle)) : 0;
}
