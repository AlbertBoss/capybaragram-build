// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import android.widget.Toast;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;

/** Native controls work both before authentication and in a chat. */
public final class CapyConnectionUi {
    public interface Current { boolean matches(); }
    private static AlertDialog current;
    private static BaseFragment owner;
    private CapyConnectionUi() { }
    private static String text(int resource) { return LocaleController.getString(resource); }
    public static void closeAll() {
        AlertDialog previous=current;current=null;owner=null;
        if (previous!=null) previous.dismiss();
    }
    public static void closeFor(BaseFragment fragment) { if (owner==fragment) closeAll(); }
    public static void show(BaseFragment fragment, Current location, Runnable proxySettings) {
        if (fragment.getParentActivity()==null || !location.matches() || AndroidUtilities.needShowPasscode()) return;
        final MemoryRoute.Snapshot snapshot=CapyConnectionService.snapshot();
        int status;
        switch (snapshot.phase) {
            case STARTING: status=R.string.CapyConnectionStarting;break;
            case LOCAL_READY: status=R.string.CapyConnectionLocalReady;break;
            case FAILED: status=R.string.CapyConnectionFailed;break;
            default: status=R.string.CapyConnectionDisabled;break;
        }
        AlertDialog.Builder builder=new AlertDialog.Builder(fragment.getParentActivity());
        builder.setTitle(text(R.string.CapyConnection));
        builder.setMessage(text(status)+"\n\n"+text(R.string.CapyConnectionDescription));
        builder.setPositiveButton(text(snapshot.requested ? R.string.CapyConnectionDisable : R.string.CapyConnectionEnable),
                (dialog,which) -> {
            if (fragment.getParentActivity()==null || !location.matches() || AndroidUtilities.needShowPasscode()) return;
            if (CapyConnectionService.snapshot().generation!=snapshot.generation) {
                Toast.makeText(fragment.getParentActivity(),text(R.string.CapyConnectionChanged),Toast.LENGTH_SHORT).show();return;
            }
            CapyConnectionService.setEnabled(!snapshot.requested);
            Toast.makeText(fragment.getParentActivity(),text(snapshot.requested
                    ? R.string.CapyConnectionDisabled : R.string.CapyConnectionStarting),Toast.LENGTH_SHORT).show();
        });
        builder.setNegativeButton(text(R.string.Cancel),null);
        if (proxySettings!=null) builder.setNeutralButton(text(R.string.CapyConnectionProxySettings),(dialog,which) -> {
            if (fragment.getParentActivity()!=null && location.matches() && !AndroidUtilities.needShowPasscode()) proxySettings.run();
        });
        closeAll();
        AlertDialog dialog=builder.create();current=dialog;owner=fragment;
        android.content.DialogInterface.OnDismissListener listener=ignored -> {
            if (current==dialog) { current=null;owner=null; }
        };
        if (fragment.showDialog(dialog,listener)==null && current==dialog) { current=null;owner=null; }
    }
}
