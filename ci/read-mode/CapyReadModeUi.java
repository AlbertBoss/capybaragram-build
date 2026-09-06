// SPDX-License-Identifier: MIT
package org.capybaragram.readmode;

import android.widget.Toast;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.messenger.UserConfig;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;

/** Native account-local controls; the caller supplies a snapshot of the intended chat. */
public final class CapyReadModeUi {
    private static AlertDialog current;
    private static BaseFragment owner;
    private CapyReadModeUi() {}
    public interface Current { boolean matches(); }
    public interface Completion { void finish(boolean accepted); }
    public interface ReadAction { void run(Completion completion); }
    private static String text(int id) { return LocaleController.getString(id); }

    public static void closeAll() {
        AlertDialog old=current;
        current=null; owner=null;
        if (old!=null) old.dismiss();
    }
    public static void closeFor(BaseFragment fragment) { if (owner==fragment) closeAll(); }
    private static void display(BaseFragment fragment, AlertDialog dialog) {
        closeAll(); current=dialog; owner=fragment;
        android.content.DialogInterface.OnDismissListener listener=ignored -> {
            if (current==dialog) { current=null; owner=null; }
        };
        if (fragment.showDialog(dialog,listener)==null && current==dialog) { current=null; owner=null; }
    }

    public static void show(BaseFragment fragment, int account, String recipient,
            Current location, ReadAction readAction) {
        if (fragment.getParentActivity()==null || !location.matches() || AndroidUtilities.needShowPasscode()) return;
        final long owner=UserConfig.getInstance(account).getClientUserId();
        final CapyReadReceipts.SessionIdentity identity=CapyReadReceipts.captureSession(account);
        if (identity==null) return;
        final boolean wasSilent=CapyReadReceipts.isSilent(account);
        AlertDialog.Builder builder=new AlertDialog.Builder(fragment.getParentActivity());
        builder.setTitle(text(wasSilent ? R.string.CapyReadModeOn : R.string.CapyReadModeOff));
        builder.setMessage(text(R.string.CapyReadModeDescription));
        builder.setPositiveButton(text(wasSilent ? R.string.CapyReadModeDisable : R.string.CapyReadModeEnable), (dialog, which) -> {
            if (!location.matches() || !CapyReadReceipts.isCurrent(identity) || AndroidUtilities.needShowPasscode()) return;
            if (CapyReadReceipts.setSilent(account,owner,!wasSilent)) {
                Toast.makeText(fragment.getParentActivity(),text(!wasSilent ? R.string.CapyReadModeOn : R.string.CapyReadModeOff),Toast.LENGTH_SHORT).show();
            }
        });
        builder.setNegativeButton(text(R.string.Cancel),null);
        if (readAction!=null) builder.setNeutralButton(text(R.string.CapyReadLoaded), (dialog,which) -> {
            if (!location.matches() || !CapyReadReceipts.isCurrent(identity) || AndroidUtilities.needShowPasscode()) return;
            AlertDialog.Builder confirm=new AlertDialog.Builder(fragment.getParentActivity());
            confirm.setTitle(text(R.string.CapyReadLoaded));
            confirm.setMessage(text(R.string.CapyReadLoadedConfirm)+"\n\n"+recipient);
            confirm.setNegativeButton(text(R.string.Cancel),null);
            confirm.setPositiveButton(text(R.string.CapyReadLoaded), (acceptedDialog,acceptedWhich) -> {
                if (!location.matches() || !CapyReadReceipts.isCurrent(identity) || AndroidUtilities.needShowPasscode()) return;
                readAction.run(accepted -> AndroidUtilities.runOnUIThread(() -> {
                    if (!location.matches() || !CapyReadReceipts.isCurrent(identity) || fragment.getParentActivity()==null || AndroidUtilities.needShowPasscode()) return;
                    Toast.makeText(fragment.getParentActivity(),text(accepted ? R.string.CapyReadAccepted : R.string.CapyReadFailed),Toast.LENGTH_SHORT).show();
                }));
            });
            display(fragment,confirm.create());
        });
        display(fragment,builder.create());
    }
}
