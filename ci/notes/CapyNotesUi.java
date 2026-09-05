// SPDX-License-Identifier: MIT
package org.capybaragram.telegram;

import android.content.DialogInterface;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.capybaragram.local.AndroidVaultCoordinator;
import org.capybaragram.local.AndroidVaultStore;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.R;
import org.telegram.ui.ActionBar.AlertDialog;
import org.telegram.ui.ActionBar.BaseFragment;
import org.telegram.ui.ActionBar.Theme;
import org.telegram.ui.Components.EditTextBoldCursor;

/** Notes and templates use the client's theme and never send a message. */
public final class CapyNotesUi {
    private static AlertDialog current;
    private static BaseFragment owner;
    private static EditTextBoldCursor currentEditor;
    private CapyNotesUi() {}
    public interface Current { boolean matches(); }
    public interface Draft { void insert(String text); }

    public static void closeAll() {
        AlertDialog dialog = current;
        if (currentEditor != null) currentEditor.setText("");
        currentEditor = null;
        current = null;
        owner = null;
        if (dialog != null) dialog.dismiss();
    }

    public static void closeFor(BaseFragment fragment) {
        if (owner == fragment) closeAll();
    }

    private static String text(int id) { return LocaleController.getString(id); }

    public static void show(BaseFragment fragment, int account, int peerType, long peer,
            long topic, String recipient, boolean templates, Current location, Draft draft) {
        if (fragment.getParentActivity() == null || !location.matches()
                || AndroidUtilities.needShowPasscode()) return;
        AndroidVaultCoordinator vault = CapyVault.get();
        AndroidVaultCoordinator.Token token = vault.capture(account);
        if (token == null) return;
        Scope scope = new Scope(fragment, vault, token, peerType, peer, topic, recipient, location, draft);
        if (templates) list(scope, 0); else editor(scope, 0, null);
    }

    private static boolean valid(Scope scope, AlertDialog dialog) {
        if (current != dialog || !dialog.isShowing() || owner != scope.fragment) return false;
        if (!scope.location.matches() || !scope.vault.isCurrent(scope.token)) {
            closeAll();
            return false;
        }
        return true;
    }

    private static boolean display(Scope scope, AlertDialog dialog, EditTextBoldCursor input) {
        if (!scope.location.matches() || !scope.vault.isCurrent(scope.token)
                || scope.fragment.getParentActivity() == null) return false;
        closeAll();
        current = dialog;
        owner = scope.fragment;
        currentEditor = input;
        DialogInterface.OnDismissListener dismissed = ignored -> {
            if (input != null) input.setText("");
            if (current == dialog) {
                current = null;
                owner = null;
                currentEditor = null;
            }
        };
        dialog.setOnDismissListener(dismissed);
        if (dialog.getWindow() != null) {
            dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        }
        if (scope.fragment.showDialog(dialog, dismissed) == null || !dialog.isShowing()) {
            closeAll();
            return false;
        }
        dialog.setCanceledOnTouchOutside(false);
        return true;
    }

    private static void editor(Scope scope, long templateId, String initial) {
        // null initial means load a chat note. An empty initial creates a template.
        boolean note = initial == null;
        LinearLayout layout = new LinearLayout(scope.fragment.getParentActivity());
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = AndroidUtilities.dp(24);
        layout.setPadding(padding, AndroidUtilities.dp(8), padding, AndroidUtilities.dp(12));
        TextView helper = new TextView(scope.fragment.getParentActivity());
        helper.setTextSize(14);
        helper.setTextColor(Theme.getColor(Theme.key_dialogTextGray, scope.fragment.getResourceProvider()));
        helper.setText(text(note ? R.string.CapyNotePrivacy : R.string.CapyTemplatePrivacy));
        layout.addView(helper);
        EditTextBoldCursor input = new EditTextBoldCursor(scope.fragment.getParentActivity());
        input.setTextSize(18);
        input.setTextColor(Theme.getColor(Theme.key_dialogTextBlack, scope.fragment.getResourceProvider()));
        input.setHintTextColor(Theme.getColor(Theme.key_dialogTextHint, scope.fragment.getResourceProvider()));
        input.setHint(text(note ? R.string.CapyNoteHint : R.string.CapyTemplateHint));
        input.setGravity(Gravity.TOP | Gravity.START);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI | EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING);
        input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(note ? 16000 : 4096)});
        input.setMinLines(4);
        input.setMaxLines(10);
        layout.addView(input, new LinearLayout.LayoutParams(-1, -2));
        AlertDialog.Builder builder = new AlertDialog.Builder(scope.fragment.getParentActivity(),
                scope.fragment.getResourceProvider());
        builder.setTitle(text(note ? R.string.CapyNote : R.string.CapyTemplate));
        builder.setView(layout);
        builder.setPositiveButton(text(R.string.Save), null);
        builder.setNegativeButton(text(R.string.Cancel), null);
        builder.setNeutralButton(text(note ? R.string.CapyRetry : R.string.Delete), null);
        AlertDialog dialog = builder.create();
        if (!display(scope, dialog, input)) return;
        View save = dialog.getButton(DialogInterface.BUTTON_POSITIVE);
        View extra = dialog.getButton(DialogInterface.BUTTON_NEUTRAL);
        save.setEnabled(!note);
        input.setEnabled(!note);
        extra.setVisibility(note || templateId == 0 ? View.GONE : View.VISIBLE);
        if (!note) input.setText(initial);
        Runnable load = () -> {
            input.setEnabled(false);
            save.setEnabled(false);
            extra.setVisibility(View.GONE);
            helper.setText(text(R.string.CapyLoading));
            scope.vault.submit(scope.token, store -> store.getNote(scope.peerType, scope.peer, scope.topic),
                (value, failed) -> {
                    if (!valid(scope, dialog)) return;
                    helper.setText(text(failed ? R.string.CapyOpenFailed : R.string.CapyNotePrivacy));
                    extra.setVisibility(failed ? View.VISIBLE : View.GONE);
                    input.setEnabled(!failed);
                    save.setEnabled(!failed);
                    if (!failed) input.setText(value);
                });
        };
        if (note) {
            extra.setOnClickListener(view -> load.run());
            load.run();
        } else if (templateId > 0) {
            extra.setOnClickListener(view -> {
                if (!valid(scope, dialog)) return;
                save.setEnabled(false);
                extra.setEnabled(false);
                scope.vault.submit(scope.token, store -> { store.deleteTemplate(templateId); return true; },
                    (value, failed) -> {
                        if (!valid(scope, dialog)) return;
                        if (!failed) list(scope, 0);
                        else { helper.setText(text(R.string.CapySaveFailed)); save.setEnabled(true); extra.setEnabled(true); }
                    });
            });
        }
        save.setOnClickListener(view -> {
            if (!valid(scope, dialog)) return;
            String value = input.getText().toString();
            if (!note && value.trim().isEmpty()) { input.setError(text(R.string.CapyTemplateHint)); return; }
            input.setEnabled(false);
            save.setEnabled(false);
            extra.setEnabled(false);
            scope.vault.submit(scope.token, store -> {
                if (note) store.saveNote(scope.peerType, scope.peer, scope.topic, value);
                else if (templateId == 0) store.addTemplate(value);
                else store.updateTemplate(templateId, value);
                return true;
            }, (saved, failed) -> {
                if (!valid(scope, dialog)) return;
                if (!failed) { if (note) closeAll(); else list(scope, 0); }
                else {
                    helper.setText(text(R.string.CapySaveFailed));
                    input.setEnabled(true); save.setEnabled(true); extra.setEnabled(true);
                }
            });
        });
    }

    private static void list(Scope scope, int offset) {
        AlertDialog loading = new AlertDialog.Builder(scope.fragment.getParentActivity(),
                scope.fragment.getResourceProvider()).setTitle(text(R.string.CapyTemplates))
                .setMessage(text(R.string.CapyLoading)).setNegativeButton(text(R.string.Cancel), null).create();
        if (!display(scope, loading, null)) return;
        scope.vault.submit(scope.token, store -> store.listTemplates(offset), (rows, failed) -> {
            if (!valid(scope, loading)) return;
            AlertDialog.Builder builder = new AlertDialog.Builder(scope.fragment.getParentActivity(),
                    scope.fragment.getResourceProvider()).setTitle(text(R.string.CapyTemplates));
            if (failed) {
                builder.setMessage(text(R.string.CapyOpenFailed));
                builder.setPositiveButton(text(R.string.CapyRetry), (d, w) -> list(scope, offset));
            } else {
                if (rows.isEmpty()) builder.setMessage(text(R.string.CapyNoTemplates));
                else {
                    String[] labels = new String[rows.size() + (rows.size() == 100 ? 1 : 0)];
                    for (int i = 0; i < rows.size(); i++) {
                        String label = rows.get(i).text.replace('\n', ' ');
                        labels[i] = label.length() > 70 ? label.substring(0, 70) + "…" : label;
                    }
                    if (rows.size() == 100) labels[rows.size()] = text(R.string.CapyMoreTemplates);
                    builder.setItems(labels, (d, which) -> {
                        if (!scope.location.matches() || !scope.vault.isCurrent(scope.token)) return;
                        if (which == rows.size()) list(scope, offset + 100);
                        else preview(scope, rows.get(which));
                    });
                }
                builder.setPositiveButton(text(R.string.CapyNewTemplate), (d, w) -> editor(scope, 0, ""));
            }
            builder.setNegativeButton(text(R.string.Close), null);
            display(scope, builder.create(), null);
        });
    }

    private static void preview(Scope scope, AndroidVaultStore.Template template) {
        AlertDialog dialog = new AlertDialog.Builder(scope.fragment.getParentActivity(),
                scope.fragment.getResourceProvider()).setTitle(text(R.string.CapyPreview))
                .setMessage(scope.recipient + "\n\n" + template.text)
                .setPositiveButton(text(R.string.CapyInsertDraft), (d, w) -> {
                    if (scope.location.matches() && scope.vault.isCurrent(scope.token)) scope.draft.insert(template.text);
                }).setNeutralButton(text(R.string.Edit), (d, w) -> editor(scope, template.id, template.text))
                .setNegativeButton(text(R.string.Cancel), null).create();
        display(scope, dialog, null);
    }

    private static final class Scope {
        final BaseFragment fragment;
        final AndroidVaultCoordinator vault;
        final AndroidVaultCoordinator.Token token;
        final int peerType;
        final long peer, topic;
        final String recipient;
        final Current location;
        final Draft draft;
        Scope(BaseFragment fragment, AndroidVaultCoordinator vault, AndroidVaultCoordinator.Token token,
                int peerType, long peer, long topic, String recipient, Current location, Draft draft) {
            this.fragment = fragment; this.vault = vault; this.token = token; this.peerType = peerType;
            this.peer = peer; this.topic = topic; this.recipient = recipient;
            this.location = location; this.draft = draft;
        }
    }
}
