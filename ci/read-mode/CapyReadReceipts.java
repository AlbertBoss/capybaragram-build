// SPDX-License-Identifier: MIT
package org.capybaragram.readmode;

import org.telegram.messenger.UserConfig;
import org.telegram.tgnet.TLObject;
import org.telegram.tgnet.TLRPC;

/** Android host adapter. Captures travel with requests; no global allowance is consumed. */
public final class CapyReadReceipts {
    private static final String KEY = "capy_silent_read_v1";
    private static final Session[] sessions = new Session[UserConfig.MAX_ACCOUNT_COUNT];
    private CapyReadReceipts() {}

    private static final class Session {
        final long owner;
        final ReadReceiptPolicy policy;
        boolean retired;
        Session(long owner, boolean silent) {
            this.owner = owner;
            policy = new ReadReceiptPolicy(silent);
        }
    }

    public static final class CapturedRead {
        private final int account;
        private final TLObject request;
        private final Session session;
        private final ReadReceiptPolicy.Ticket ticket;
        private CapturedRead(int account, TLObject request, Session session, boolean explicit) {
            this.account = account;
            this.request = request;
            this.session = session;
            ticket = session.policy.capture(explicit);
        }
    }

    public static final class SessionIdentity {
        private final int account;
        private final Session session;
        private SessionIdentity(int account, Session session) { this.account=account; this.session=session; }
    }

    public static synchronized SessionIdentity captureSession(int account) {
        Session value=session(account);
        return value.owner == 0 || value.retired ? null : new SessionIdentity(account,value);
    }

    public static synchronized boolean isCurrent(SessionIdentity identity) {
        if (identity == null) return false;
        Session value=session(identity.account);
        return value == identity.session && value.owner != 0 && !value.retired;
    }

    private static Session session(int account) {
        if (account < 0 || account >= sessions.length) throw new IllegalArgumentException("Account slot");
        UserConfig config = UserConfig.getInstance(account);
        // Host transform makes this field volatile. Do not acquire UserConfig.sync
        // here: ownerChanged is called while that lock is already held.
        long owner = config.clientUserId;
        Session value = sessions[account];
        if (value == null || value.owner != owner) {
            value = new Session(owner, config.getPreferences().getBoolean(KEY + ":" + owner, false));
            sessions[account] = value;
        }
        return value;
    }

    public static synchronized boolean isSilent(int account) {
        Session value = session(account);
        return value.owner == 0 || value.retired || value.policy.isSilent();
    }

    public static synchronized boolean setSilent(int account, long expectedOwner, boolean enabled) {
        Session value = session(account);
        if (value.retired || expectedOwner == 0 || expectedOwner != value.owner) return false;
        UserConfig.getInstance(account).getPreferences().edit().putBoolean(KEY + ":" + value.owner, enabled).apply();
        value.policy.setSilent(enabled);
        return true;
    }

    public static synchronized void beforeLogout(int account) {
        Session value = session(account);
        value.retired = true;
        value.policy.reset(true);
    }

    public static synchronized void ownerChanged(int account, long previous, long next) {
        if (previous == next) return;
        Session old = sessions[account];
        if (old != null) { old.retired = true; old.policy.reset(true); }
        // All captured old requests keep the retired object, even when the same owner logs in again.
        sessions[account] = null;
    }

    public static synchronized CapturedRead capture(int account, TLObject request, boolean explicit) {
        return isReadReceipt(request) ? new CapturedRead(account, request, session(account), explicit) : null;
    }

    public static synchronized boolean consume(int account, TLObject request, CapturedRead captured) {
        if (captured == null || captured.account != account || captured.request != request) return false;
        Session value = session(account);
        return value == captured.session && value.owner != 0 && !value.retired && value.policy.consume(captured.ticket);
    }

    public static boolean isReadReceipt(TLObject request) {
        return request instanceof TLRPC.TL_messages_readHistory
            || request instanceof TLRPC.TL_channels_readHistory
            || request instanceof TLRPC.TL_messages_readDiscussion
            || request instanceof TLRPC.TL_messages_readEncryptedHistory
            || request instanceof TLRPC.TL_messages_readMessageContents
            || request instanceof TLRPC.TL_channels_readMessageContents
            || request instanceof TLRPC.TL_messages_readSavedHistory
            || request instanceof TLRPC.TL_messages_readMentions;
    }
}
