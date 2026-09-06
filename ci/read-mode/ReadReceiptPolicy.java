// SPDX-License-Identifier: MIT
package org.capybaragram.readmode;

/** One instance per account session. No global one-shot permission. */
public final class ReadReceiptPolicy {
    private boolean silent;
    private long generation;

    public static final class Ticket {
        private final ReadReceiptPolicy issuer;
        private final long generation;
        private final boolean explicit;
        private final boolean suppressedWhenCreated;
        private boolean consumed;

        private Ticket(ReadReceiptPolicy issuer, long generation, boolean explicit, boolean suppressed) {
            this.issuer = issuer;
            this.generation = generation;
            this.explicit = explicit;
            suppressedWhenCreated = suppressed;
        }
    }

    public ReadReceiptPolicy(boolean silent) { this.silent = silent; }
    public synchronized boolean isSilent() { return silent; }
    public synchronized void setSilent(boolean value) { silent = value; }

    /** Capture when the request is created, before posting to an asynchronous queue. */
    public synchronized Ticket capture(boolean explicitUserAction) {
        return new Ticket(this, generation, explicitUserAction, silent && !explicitUserAction);
    }

    /** The caller must carry this ticket alongside that exact request. */
    public synchronized boolean consume(Ticket ticket) {
        if (ticket == null || ticket.issuer != this || ticket.generation != generation || ticket.consumed) {
            return false;
        }
        ticket.consumed = true;
        return !ticket.suppressedWhenCreated && (ticket.explicit || !silent);
    }

    /** Retire pending permissions on logout/owner change, including re-login by the same owner. */
    public synchronized void reset(boolean initialSilent) {
        generation++;
        silent = initialSilent;
    }
}
