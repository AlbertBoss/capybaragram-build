// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

/** Process-local native transport. Start/stop must run on the controller worker. */
public final class NativeTunnel {
    static { System.loadLibrary("capy_connection_jni"); }
    private NativeTunnel() { }
    // Endpoint: two little-endian port bytes, then 34 ASCII secret bytes.
    // Keep it in memory and wipe it; never log or persist the endpoint.
    static native long start(byte[] endpoint);
    static native boolean status(long handle, int[] status);
    static native int stop(long handle);
}
