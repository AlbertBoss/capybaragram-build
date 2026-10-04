// SPDX-License-Identifier: MIT
package org.capybaragram.capture;

import org.capybaragram.readmode.CapyReadReceipts;
import org.telegram.messenger.UserConfig;
import org.telegram.tgnet.TLRPC;

/** Keeps the originating authorization lease through the native request queue. */
public final class CapyScreenshotRequest extends TLRPC.TL_messages_sendScreenshotNotification {
    private final int originAccount;
    private final long originOwner;
    private final CapyReadReceipts.SessionIdentity identity;
    public CapyScreenshotRequest(int account) {
        originAccount = account;
        originOwner = UserConfig.getInstance(account).getClientUserId();
        identity = CapyReadReceipts.captureSession(account);
    }
    public boolean ownedCurrent(int account) {
        return account == originAccount && originOwner != 0
                && CapyReadReceipts.isCurrent(identity);
    }
    public boolean allowed(int account) {
        return ownedCurrent(account) && CapyCapture.enabled(originAccount, originOwner);
    }
}
