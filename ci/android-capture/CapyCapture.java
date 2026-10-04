// SPDX-License-Identifier: MIT
package org.capybaragram.capture;

import android.annotation.TargetApi;
import android.app.Activity;
import android.os.Build;
import android.os.SystemClock;
import android.widget.Toast;
import java.lang.ref.WeakReference;
import org.capybaragram.readmode.CapyReadReceipts;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.ApplicationLoader;
import org.telegram.messenger.FileLog;
import org.telegram.messenger.LocaleController;
import org.telegram.messenger.MessagesController;
import org.telegram.messenger.R;
import org.telegram.messenger.SharedConfig;
import org.telegram.messenger.UserConfig;
import org.telegram.messenger.Utilities;
import org.telegram.tgnet.ConnectionsManager;
import org.telegram.tgnet.TLRPC;
import org.telegram.ui.ActionBar.BaseFragment;

/** Cooperative OS-observed screenshot reporting; no pixels, gallery watcher or remote detector. */
public final class CapyCapture {
    public interface Current { boolean matches(); }
    private static final String KEY = "capy_capture_report_v1:";
    private static Registration active;
    private CapyCapture() { }
    public static boolean supported() { return Build.VERSION.SDK_INT >= 34; }
    public static boolean enabled(int account, long owner) {
        return owner != 0 && account >= 0 && account < UserConfig.MAX_ACCOUNT_COUNT
                && UserConfig.getInstance(account).getClientUserId() == owner
                && UserConfig.getInstance(account).getPreferences().getBoolean(KEY + owner, false);
    }
    public static boolean setEnabled(int account, long owner, boolean value,
            CapyReadReceipts.SessionIdentity identity) {
        if (!supported() || owner == 0 || !CapyReadReceipts.isCurrent(identity)
                || UserConfig.getInstance(account).getClientUserId() != owner) return false;
        UserConfig.getInstance(account).getPreferences().edit().putBoolean(KEY + owner, value).apply();
        return true;
    }
    public static void report(int account, long owner, TLRPC.User user) {
        if (!enabled(account, owner) || user == null || user.id <= 0 || user.id == owner
                || user.id == 777000L || user.bot || user.deleted) return;
        final CapyScreenshotRequest request = new CapyScreenshotRequest(account);
        TLRPC.TL_inputPeerUser peer = new TLRPC.TL_inputPeerUser();
        peer.user_id = user.id;
        peer.access_hash = user.access_hash;
        request.peer = peer;
        TLRPC.TL_inputReplyToMessage reply = new TLRPC.TL_inputReplyToMessage();
        reply.reply_to_msg_id = 0; // the OS never identifies a message or region
        request.reply_to = reply;
        request.random_id = Utilities.random.nextLong();
        if (request.random_id == 0) request.random_id = 1;
        if (!request.allowed(account)) return;
        ConnectionsManager.getInstance(account).sendRequest(request, (response, error) -> {
            if (!request.ownedCurrent(account)) return;
            if (error == null && response instanceof TLRPC.Updates) {
                // Show only the real server service event, never a local success placeholder.
                MessagesController.getInstance(account).processUpdates((TLRPC.Updates) response, false);
            } else if (error == null || !"CAPY_SCREENSHOT_REPORT_REVOKED".equals(error.text)) {
                AndroidUtilities.runOnUIThread(() -> {
                    if (request.ownedCurrent(account) && !SharedConfig.appLocked
                            && !SharedConfig.isWaitingForPasscodeEnter && !ApplicationLoader.mainInterfacePaused) {
                        Toast.makeText(ApplicationLoader.applicationContext,
                                LocaleController.getString(R.string.CapyCaptureReportFailed), Toast.LENGTH_LONG).show();
                    }
                });
            }
        });
    }
    public static void closeAll() {
        Registration old = active;
        active = null;
        if (old != null) old.stop();
        CapyCaptureUi.closeAll();
    }
    public static void closeFor(BaseFragment fragment) {
        if (active != null && active.fragment.get() == fragment) {
            Registration old = active;
            active = null;
            old.stop();
        }
        CapyCaptureUi.closeFor(fragment);
    }
    public static boolean bind(BaseFragment fragment, int account, Current location, Runnable report) {
        // Called on the UI thread after native onResume and after an explicit setting change.
        Registration old = active;
        active = null;
        if (old != null) old.stop();
        long owner = UserConfig.getInstance(account).getClientUserId();
        if (!supported() || !enabled(account, owner) || fragment.getParentActivity() == null
                || !location.matches() || AndroidUtilities.needShowPasscode()) return false;
        CapyReadReceipts.SessionIdentity identity = CapyReadReceipts.captureSession(account);
        if (identity == null) return false;
        Registration next = new Api34Registration(fragment, account, owner, identity, location, report);
        active = next;
        if (!next.start()) {
            active = null;
            next.stop();
            return false;
        }
        return true;
    }

    // This base has no references to API-34 types, so a disabled/pre-14 client
    // does not need to resolve Activity.ScreenCaptureCallback.
    private abstract static class Registration {
        final WeakReference<BaseFragment> fragment;
        final WeakReference<Activity> activity;
        final int account;
        final long owner;
        final CaptureGate gate = new CaptureGate();
        final CaptureGate.Ticket ticket = gate.arm();
        CapyReadReceipts.SessionIdentity identity;
        Current location;
        Runnable report;
        boolean registered;
        Registration(BaseFragment fragment, int account, long owner,
                CapyReadReceipts.SessionIdentity identity, Current location, Runnable report) {
            this.fragment = new WeakReference<>(fragment);
            this.activity = new WeakReference<>(fragment.getParentActivity());
            this.account = account;
            this.owner = owner;
            this.identity = identity;
            this.location = location;
            this.report = report;
        }
        abstract boolean start();
        abstract void unregister(Activity previous);
        void stop() {
            gate.revoke();
            boolean wasRegistered = registered;
            registered = false;
            Activity previous = activity.get();
            // Also release host lambdas if the OS refuses unregistering a callback.
            identity = null;
            location = null;
            report = null;
            fragment.clear();
            activity.clear();
            if (wasRegistered && previous != null) {
                try { unregister(previous); }
                catch (RuntimeException failure) {
                    FileLog.e("CapybaraGram OS screenshot unregistration failed; callback revoked.");
                }
            }
        }
        final void captured() {
            BaseFragment frame = fragment.get();
            Activity window = activity.get();
            boolean allowed = active == this && registered && frame != null && window != null
                    && frame.getParentActivity() == window && !window.isFinishing() && !window.isDestroyed()
                    && window.hasWindowFocus() && !ApplicationLoader.mainInterfacePaused
                    && !SharedConfig.appLocked && !SharedConfig.isWaitingForPasscodeEnter
                    && !AndroidUtilities.needShowPasscode() && frame.getVisibleDialog() == null
                    && enabled(account, owner) && CapyReadReceipts.isCurrent(identity)
                    && location != null && location.matches() && report != null;
            if (gate.claim(ticket, SystemClock.elapsedRealtime(), allowed)) report.run();
        }
    }

    // SDK-34 classes are resolved only after the version guard in bind().
    @TargetApi(34)
    private static final class Api34Registration extends Registration implements Activity.ScreenCaptureCallback {
        Api34Registration(BaseFragment fragment, int account, long owner,
                CapyReadReceipts.SessionIdentity identity, Current location, Runnable report) {
            super(fragment, account, owner, identity, location, report);
        }
        @Override boolean start() {
            Activity value = activity.get();
            if (value == null || value.isFinishing() || value.isDestroyed()) return false;
            try {
                value.registerScreenCaptureCallback(value.getMainExecutor(), this);
                registered = true;
                return true;
            } catch (RuntimeException failure) {
                FileLog.e("CapybaraGram OS screenshot registration failed; private context omitted.");
                return false;
            }
        }
        @Override void unregister(Activity previous) { previous.unregisterScreenCaptureCallback(this); }
        @Override public void onScreenCaptured() { captured(); }
    }
}
