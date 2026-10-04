// SPDX-License-Identifier: MIT
package org.capybaragram.capture;

/** A revoked registration cannot report a queued callback into a newer chat. */
public final class CaptureGate {
    public static final long MIN_INTERVAL_MS = 2000L;
    public static final class Ticket {
        private Ticket() { }
    }
    private Ticket current;
    private long previous = -1;
    public Ticket arm() {
        current = new Ticket();
        previous = -1;
        return current;
    }
    public void revoke() { current = null; previous = -1; }
    public boolean claim(Ticket ticket, long elapsedMillis, boolean locationAllowed) {
        if (ticket == null || ticket != current || !locationAllowed || elapsedMillis < 0) return false;
        if (previous >= 0 && (elapsedMillis < previous || elapsedMillis - previous < MIN_INTERVAL_MS)) return false;
        previous = elapsedMillis;
        return true;
    }
}
