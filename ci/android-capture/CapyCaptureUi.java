// SPDX-License-Identifier: MIT
package org.capybaragram.capture;

import android.widget.Toast;
import org.capybaragram.readmode.CapyReadReceipts;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.messenger.UserConfig;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;

public final class CapyCaptureUi {
    public interface Binding { boolean run(); }
    private static AlertDialog current;
    private static BaseFragment owner;
    private CapyCaptureUi() { }
    private static String text(int key) { return LocaleController.getString(key); }
    public static void closeAll() {
        AlertDialog old = current;
        current = null;
        owner = null;
        if (old != null) old.dismiss();
    }
    public static void closeFor(BaseFragment fragment) { if (owner == fragment) closeAll(); }
    public static void show(BaseFragment fragment, int account,
            CapyCapture.Current location, Binding refresh) {
        if (fragment.getParentActivity() == null || !location.matches() || AndroidUtilities.needShowPasscode()) return;
        final long user = UserConfig.getInstance(account).getClientUserId();
        final CapyReadReceipts.SessionIdentity identity = CapyReadReceipts.captureSession(account);
        if (identity == null) return;
        final boolean supported = CapyCapture.supported();
        final boolean wasEnabled = CapyCapture.enabled(account, user);
        AlertDialog.Builder builder = new AlertDialog.Builder(fragment.getParentActivity());
        builder.setTitle(text(R.string.CapyCapture));
        builder.setMessage((supported ? text(wasEnabled ? R.string.CapyCaptureOn : R.string.CapyCaptureOff)
                : text(R.string.CapyCaptureUnsupported)) + "\n\n" + text(R.string.CapyCaptureDescription));
        builder.setNegativeButton(text(R.string.Cancel), null);
        if (supported) builder.setPositiveButton(text(wasEnabled ? R.string.CapyCaptureDisable : R.string.CapyCaptureEnable), (dialog, which) -> {
            if (fragment.getParentActivity() == null || !location.matches()
                    || !CapyReadReceipts.isCurrent(identity) || AndroidUtilities.needShowPasscode()) return;
            boolean next = !wasEnabled;
            if (!CapyCapture.setEnabled(account, user, next, identity)) return;
            boolean registered = refresh.run();
            if (next && !registered) {
                CapyCapture.setEnabled(account, user, false, identity);
                Toast.makeText(fragment.getParentActivity(), text(R.string.CapyCaptureUnavailable), Toast.LENGTH_LONG).show();
            } else {
                Toast.makeText(fragment.getParentActivity(), text(next ? R.string.CapyCaptureOn : R.string.CapyCaptureOff), Toast.LENGTH_LONG).show();
            }
        });
        closeAll();
        AlertDialog dialog = builder.create();
        current = dialog;
        owner = fragment;
        android.content.DialogInterface.OnDismissListener listener = ignored -> {
            if (current == dialog) { current = null; owner = null; }
        };
        if (fragment.showDialog(dialog, listener) == null && current == dialog) { current = null; owner = null; }
    }
}
