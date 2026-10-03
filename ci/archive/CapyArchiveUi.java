// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;
import java.text.DateFormat;
import java.util.Date;
import java.util.List;

/** Read-only native archive pages; never inserts or sends a stored message. */
public final class CapyArchiveUi {
    private static AlertDialog current;
    private static BaseFragment owner;
    private CapyArchiveUi() {}
    public interface Current { boolean matches(); }
    private static String text(int id) { return LocaleController.getString(id); }

    public static void closeAll() {
        AlertDialog previous=current; current=null; owner=null;
        if (previous != null) previous.dismiss();
    }
    public static void closeFor(BaseFragment fragment) { if (fragment == owner) closeAll(); }
    private static void display(BaseFragment fragment, AlertDialog dialog) {
        closeAll(); current=dialog; owner=fragment;
        android.content.DialogInterface.OnDismissListener listener=ignored -> {
            if (current == dialog) { current=null; owner=null; }
        };
        if (fragment.showDialog(dialog, listener) == null && current == dialog) { current=null; owner=null; }
    }

    private static boolean available(BaseFragment fragment, Current location,
            AndroidArchiveCoordinator coordinator, AndroidArchiveCoordinator.Token token) {
        return fragment.getParentActivity() != null && location.matches()
                && !AndroidUtilities.needShowPasscode() && coordinator.isCurrent(token);
    }

    public static void show(BaseFragment fragment, int account, long dialog, String name, Current location) {
        AndroidArchiveCoordinator coordinator=CapyMessageArchive.get();
        AndroidArchiveCoordinator.Token token=coordinator.capture(account);
        if (!available(fragment,location,coordinator,token)) return;
        boolean enabled=CapyMessageArchive.enabled(account);
        AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
        b.setTitle(text(R.string.CapyArchive));
        b.setMessage(text(R.string.CapyArchiveDescription));
        b.setNegativeButton(text(R.string.Cancel), null);
        b.setPositiveButton(text(enabled ? R.string.CapyArchiveDisable : R.string.CapyArchiveEnable), (d,w) -> {
            if (!available(fragment,location,coordinator,token)) return;
            if (!CapyMessageArchive.setEnabled(account,token.owner,!enabled)) {
                AlertDialog.Builder error=new AlertDialog.Builder(fragment.getParentActivity());
                error.setTitle(text(R.string.CapyArchive)); error.setMessage(text(R.string.CapyArchiveFailure));
                error.setNegativeButton(text(R.string.Close),null);
                display(fragment,error.create());
            }
        });
        b.setNeutralButton(text(R.string.CapyArchiveOpen), (d,w) -> page(fragment,account,dialog,name,location,0));
        display(fragment,b.create());
    }

    private static void page(BaseFragment fragment, int account, long dialog, String name, Current location, long before) {
        AndroidArchiveCoordinator coordinator=CapyMessageArchive.get();
        AndroidArchiveCoordinator.Token token=coordinator.capture(account);
        if (!available(fragment,location,coordinator,token)) return;
        AlertDialog.Builder loading=new AlertDialog.Builder(fragment.getParentActivity());
        loading.setTitle(text(R.string.CapyArchive)); loading.setMessage(text(R.string.CapyArchiveLoading));
        loading.setNegativeButton(text(R.string.Cancel), null);
        AlertDialog waiting=loading.create(); display(fragment,waiting);
        coordinator.submit(token, store -> store.list(dialog,before), (entries,failed) -> {
            if (!available(fragment,location,coordinator,token) || current != waiting) return;
            AlertDialog.Builder b=new AlertDialog.Builder(fragment.getParentActivity());
            b.setTitle(text(R.string.CapyArchive)+" · "+name);
            StringBuilder body=new StringBuilder();
            long next=0;
            if (failed || entries == null) body.append(text(R.string.CapyArchiveFailure));
            else if (entries.isEmpty()) body.append(text(R.string.CapyArchiveEmpty));
            else for (AndroidArchiveStore.Entry entry : entries) {
                next=entry.id;
                body.append(DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(new Date(entry.savedAt))).append(" · ");
                body.append(text(entry.reason == CapyMessageArchive.DELETED ? R.string.CapyArchiveDeleted
                        : entry.reason == CapyMessageArchive.EXPIRED_MEDIA ? R.string.CapyArchiveExpired : R.string.CapyArchiveEdited));
                body.append("\n").append(entry.text.isEmpty() ? text(R.string.CapyArchiveNoText)
                        : entry.text);
                if (entry.media) body.append("\n").append(text(R.string.CapyArchiveOriginalMissing));
                body.append("\n\n");
            }
            b.setMessage(body.toString());
            b.setNegativeButton(text(R.string.Close),null);
            if (!failed && entries != null && entries.size() == AndroidArchiveStore.PAGE_SIZE) {
                final long cursor=next;
                b.setPositiveButton(text(R.string.CapyArchiveOlder),(d,w) -> {
                    if (available(fragment,location,coordinator,token)) page(fragment,account,dialog,name,location,cursor);
                });
            }
            b.setNeutralButton(text(R.string.CapyArchiveClear),(d,w) -> {
                if (!available(fragment,location,coordinator,token)) return;
                AlertDialog.Builder confirm=new AlertDialog.Builder(fragment.getParentActivity());
                confirm.setTitle(text(R.string.CapyArchiveClear)); confirm.setMessage(text(R.string.CapyArchiveClearConfirm));
                confirm.setNegativeButton(text(R.string.Cancel),null);
                confirm.setPositiveButton(text(R.string.CapyArchiveClear),(accepted,which) -> {
                    if (available(fragment,location,coordinator,token)) coordinator.clearArchive(account);
                });
                display(fragment,confirm.create());
            });
            display(fragment,b.create());
        });
    }
}
