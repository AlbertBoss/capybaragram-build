// SPDX-License-Identifier: MIT
package org.capybaragram.telegram;

import android.content.SharedPreferences;
import android.os.Build;
import org.capybaragram.local.AndroidVaultCoordinator;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.ApplicationLoader;
import org.telegram.messenger.FileLog;
import org.telegram.messenger.SharedConfig;
import org.telegram.messenger.UserConfig;

/** Thin main-process adapter; credentials and Telegram messages never enter the vault API. */
public final class CapyVault {
    private static volatile AndroidVaultCoordinator instance;
    private CapyVault() {}

    public static synchronized AndroidVaultCoordinator get() {
        if (Build.VERSION.SDK_INT < 23) throw new IllegalStateException("Android 6 required.");
        if (instance == null) {
            instance = new AndroidVaultCoordinator(ApplicationLoader.applicationContext,
                    new AndroidVaultCoordinator.Host() {
                @Override public long currentOwner(int account) {
                    return UserConfig.getInstance(account).getClientUserId();
                }
                @Override public boolean unlocked() {
                    return !SharedConfig.appLocked && !SharedConfig.isWaitingForPasscodeEnter;
                }
                @Override public SharedPreferences preferences(int account) {
                    return UserConfig.getInstance(account).getPreferences();
                }
                @Override public void storageProblem() {
                    FileLog.e("CapybaraGram local storage operation failed; private data omitted.");
                }
            }, UserConfig.MAX_ACCOUNT_COUNT);
        }
        return instance;
    }

    public static void beforeLogout(int account) {
        if (Build.VERSION.SDK_INT >= 23) get().onLogout(account);
        AndroidUtilities.runOnUIThread(CapyNotesUi::closeAll);
    }

    public static void ownerChanged(int account, long previous, long next) {
        if (previous == next) return;
        AndroidVaultCoordinator vault = instance;
        if (vault != null) vault.onOwnerChanged(account, previous, next);
        AndroidUtilities.runOnUIThread(CapyNotesUi::closeAll);
    }

    public static void locked() {
        AndroidVaultCoordinator vault = instance;
        if (vault != null) vault.onLock();
        CapyNotesUi.closeAll();
    }
}
