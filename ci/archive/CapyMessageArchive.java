// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import android.content.SharedPreferences;
import org.telegram.SQLite.SQLiteCursor;
import org.telegram.SQLite.SQLiteDatabase;
import org.telegram.messenger.ApplicationLoader;
import org.telegram.messenger.AndroidUtilities;
import org.telegram.messenger.FileLog;
import org.telegram.messenger.SharedConfig;
import org.telegram.messenger.UserConfig;
import org.telegram.messenger.MessageObject;
import org.telegram.tgnet.NativeByteBuffer;
import org.telegram.tgnet.TLRPC;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;

/** Read Telegram's database only on its storage queue, before deletion/overwrite. */
public final class CapyMessageArchive {
    public static final int DELETED = 1, EXPIRED_MEDIA = 2, BEFORE_EDIT = 3;
    private static volatile AndroidArchiveCoordinator instance;
    private CapyMessageArchive() {}

    public static synchronized AndroidArchiveCoordinator get() {
        if (instance == null) instance = new AndroidArchiveCoordinator(ApplicationLoader.applicationContext,
                new AndroidArchiveCoordinator.Host() {
                    @Override public long currentOwner(int account) {
                        // Never take UserConfig's lock while holding archive metadata locks.
                        return UserConfig.getInstance(account).clientUserId;
                    }
                    @Override public boolean unlocked() {
                        return !SharedConfig.appLocked && !SharedConfig.isWaitingForPasscodeEnter;
                    }
                    @Override public SharedPreferences preferences(int account) {
                        return UserConfig.getInstance(account).getPreferences();
                    }
                    @Override public void storageProblem() { problem(); }
                }, UserConfig.MAX_ACCOUNT_COUNT);
        return instance;
    }

    private static String preference(long owner) { return "capy_archive_enabled:" + owner; }

    public static boolean enabled(int account) {
        UserConfig config = UserConfig.getInstance(account);
        long owner = config.clientUserId;
        return owner > 0 && config.getPreferences().getBoolean(preference(owner), false);
    }

    public static boolean setEnabled(int account, long expectedOwner, boolean enabled) {
        UserConfig config = UserConfig.getInstance(account);
        if (expectedOwner <= 0 || config.clientUserId != expectedOwner
                || SharedConfig.appLocked || SharedConfig.isWaitingForPasscodeEnter) return false;
        return config.getPreferences().edit().putBoolean(preference(expectedOwner), enabled).commit();
    }

    public static void beforeLogout(int account) { get().onLogout(account); AndroidUtilities.runOnUIThread(CapyArchiveUi::closeAll); }
    public static void ownerChanged(int account, long previous, long next) {
        if (previous == next) return;
        AndroidArchiveCoordinator coordinator = instance;
        if (coordinator != null) coordinator.onOwnerChanged(account, previous, next);
        AndroidUtilities.runOnUIThread(CapyArchiveUi::closeAll);
    }
    public static void locked() {
        AndroidArchiveCoordinator coordinator = instance;
        if (coordinator != null) coordinator.onLock();
        CapyArchiveUi.closeAll();
    }

    public static void captureDeleted(int account, SQLiteDatabase database, long dialog, ArrayList<Integer> ids) {
        if (!enabled(account) || ids == null || ids.isEmpty()) return;
        // Values are typed integers; no externally supplied SQL or file paths.
        StringBuilder list = new StringBuilder();
        for (int id : ids) { if (list.length() != 0) list.append(','); list.append(id); }
        rows(account, database, "SELECT uid,mid,data FROM messages_v2 WHERE mid IN(" + list + ") AND "
                + (dialog == 0 ? "is_channel=0" : "uid=" + dialog), DELETED);
    }

    public static void captureThreshold(int account, SQLiteDatabase database, long channel, int maximum) {
        if (!enabled(account) || channel <= 0) return;
        rows(account, database, "SELECT uid,mid,data FROM messages_v2 WHERE uid=" + (-channel) + " AND mid<=" + maximum, DELETED);
    }

    public static void captureExpired(int account, SQLiteDatabase database, long dialog, ArrayList<Integer> ids) {
        if (!enabled(account) || ids == null || ids.isEmpty()) return;
        StringBuilder list = new StringBuilder();
        for (int id : ids) { if (list.length() != 0) list.append(','); list.append(id); }
        rows(account, database, "SELECT uid,mid,data FROM messages_v2 WHERE uid=" + dialog + " AND mid IN(" + list + ")", EXPIRED_MEDIA);
    }

    public static void captureEdits(int account, SQLiteDatabase database, ArrayList<TLRPC.Message> incoming) {
        if (!enabled(account) || incoming == null) return;
        for (TLRPC.Message message : incoming) {
            if (message == null || message.id == 0 || message.edit_date == 0) continue;
            long dialog = MessageObject.getDialogId(message);
            if (dialog != 0) rows(account, database,
                    "SELECT uid,mid,data FROM messages_v2 WHERE uid=" + dialog + " AND mid=" + message.id,
                    BEFORE_EDIT, message);
        }
    }

    /** Hold the already downloaded original before a once/TTL viewer consumes it. */
    public static AndroidArchiveCoordinator.Token beginView(MessageObject object) {
        if (object == null || object.messageOwner == null || !object.isSecretMedia()) return null;
        final int account = object.currentAccount;
        if (!enabled(account) || SharedConfig.appLocked || SharedConfig.isWaitingForPasscodeEnter) return null;
        final AndroidArchiveCoordinator coordinator = get();
        final AndroidArchiveCoordinator.Token token = coordinator.captureBackground(account);
        captureViewed(token, object);
        return token;
    }

    /** Retries use the same viewer generation; slot reuse cannot adopt old media. */
    public static void captureViewed(AndroidArchiveCoordinator.Token token, MessageObject object) {
        if (token == null || object == null || object.messageOwner == null || !object.isSecretMedia()) return;
        final int account = object.currentAccount;
        final AndroidArchiveCoordinator coordinator = get();
        if (account != token.account || !coordinator.isCurrent(token) || !enabled(account)
                || SharedConfig.appLocked || SharedConfig.isWaitingForPasscodeEnter) return;
        final long dialog = object.getDialogId();
        final int messageId = object.getId();
        if (token == null || dialog == 0 || messageId == 0) return;
        NativeByteBuffer data = null;
        byte[] bytes = null;
        CapyArchiveMediaSource source = null;
        try {
            final TLRPC.Message message = object.messageOwner;
            final int size = message.getObjectSize();
            if (size <= 0 || size > AndroidArchiveStore.MAX_TL_BYTES) { problem(); return; }
            data = new NativeByteBuffer(size);
            message.serializeToStream(data);
            if (data.position() != size) { problem(); return; }
            bytes = new byte[size];
            ByteBuffer copy = data.buffer.asReadOnlyBuffer(); copy.position(0); copy.limit(size); copy.get(bytes);
            try { source = CapyArchiveMediaSource.open(account, message); }
            catch (Exception unavailable) { problem(); }
            final byte[] tl = bytes;
            final CapyArchiveMediaSource original = source;
            final String text = message.message == null ? "" : message.message;
            // Ownership transfers to the bounded FIFO before native onOpen/onClose.
            coordinator.persistViewed(token, store -> {
                long id = store.save(dialog, messageId, EXPIRED_MEDIA, tl, text, true);
                if (original != null && coordinator.isCurrent(token)) {
                    try { store.saveOriginal(id, original.input, original.size, original.mime); }
                    catch (Exception incomplete) { problem(); }
                }
                return null;
            }, () -> {
                try { if (original != null) original.close(); }
                catch (Exception closeFailure) { problem(); }
                finally { Arrays.fill(tl, (byte) 0); }
            });
            bytes = null; source = null;
        } catch (Exception failure) { problem(); }
        finally {
            try { if (source != null) source.close(); }
            catch (Exception closeFailure) { problem(); }
            if (bytes != null) Arrays.fill(bytes, (byte) 0);
            if (data != null) {
                // NativeByteBuffer's pool must not retain our serialized copy.
                try {
                    if (data.buffer != null) {
                        ByteBuffer wipe = data.buffer.duplicate(); wipe.position(0);
                        while (wipe.hasRemaining()) wipe.put((byte) 0);
                    }
                } finally { data.reuse(); }
            }
        }
    }

    private static void rows(int account, SQLiteDatabase database, String sql, int reason) {
        rows(account, database, sql, reason, null);
    }

    private static void rows(int account, SQLiteDatabase database, String sql, int reason, TLRPC.Message replacement) {
        AndroidArchiveCoordinator coordinator = get();
        AndroidArchiveCoordinator.Token token = coordinator.captureBackground(account);
        if (token == null) return;
        SQLiteCursor cursor = null;
        try {
            cursor = database.queryFinalized(sql);
            while (cursor.next()) {
                final long dialog = cursor.longValue(0);
                final int messageId = cursor.intValue(1);
                NativeByteBuffer data = cursor.byteBufferValue(2);
                if (data == null) continue;
                try {
                    if (data.limit() > AndroidArchiveStore.MAX_TL_BYTES) { problem(); continue; }
                    ByteBuffer copy = data.buffer.asReadOnlyBuffer(); copy.position(0);
                    final byte[] tl = new byte[copy.remaining()]; copy.get(tl);
                    try {
                    TLRPC.Message message = TLRPC.Message.TLdeserialize(data, data.readInt32(false), false);
                    if (message == null) { problem(); continue; }
                    message.readAttachPath(data, token.owner);
                    final String text = message.message == null ? "" : message.message;
                    final boolean media = message.media != null && !(message.media instanceof TLRPC.TL_messageMediaEmpty);
                    // Holding the source descriptor precedes upstream file deletion.
                    CapyArchiveMediaSource source=null;
                    if(media)try{source=CapyArchiveMediaSource.open(account,message);}catch(Exception unavailable){problem();}
                    final CapyArchiveMediaSource original=source;
                    try {
                        coordinator.persistBackground(token, store -> {
                            long id=store.save(dialog, messageId, reason, tl, text, media);
                            if(original!=null && coordinator.isCurrent(token)) {
                                try {store.saveOriginal(id,original.input,original.size,original.mime);}
                                catch(Exception incomplete){problem();}
                            }
                            return null;
                        });
                    } finally {if(original!=null)original.close();}
                    } finally { Arrays.fill(tl, (byte) 0); }
                } finally { data.reuse(); }
            }
        } catch (Exception failure) { problem(); }
        finally { if (cursor != null) cursor.dispose(); }
    }

    private static void problem() {
        FileLog.e("CapybaraGram: archive snapshot unavailable; private content omitted.");
    }
}
