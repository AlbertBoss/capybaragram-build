// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Looper;
import android.util.Base64;
import org.capybaragram.local.PayloadCipher;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import javax.crypto.SecretKey;

/** Encrypted message snapshots, separate from the notes database. No network. */
public final class AndroidArchiveStore implements AutoCloseable {
    public static final int MAX_ROWS = 2000;
    public static final int PAGE_SIZE = 20;
    public static final int MAX_TL_BYTES = 60000;
    private static final String CREATE = "CREATE TABLE snapshots (id INTEGER PRIMARY KEY, "
            + "dialog_id INTEGER NOT NULL, message_id INTEGER NOT NULL, reason INTEGER NOT NULL, "
            + "created_at INTEGER NOT NULL, fingerprint BLOB NOT NULL, payload BLOB NOT NULL, "
            + "CHECK(dialog_id!=0), CHECK(message_id!=0), CHECK(reason IN(1,2,3)), "
            + "CHECK(length(fingerprint)=32), CHECK(length(payload)>=32 AND length(payload)<=131072), "
            + "UNIQUE(dialog_id,message_id,reason,fingerprint))";
    private final UUID generation;
    private final Thread worker = Thread.currentThread();
    private final SQLiteDatabase db;
    private SecretKey key;

    private AndroidArchiveStore(SQLiteDatabase db, UUID generation, SecretKey key) {
        this.db = db; this.generation = generation; this.key = key;
    }

    public static File file(Context context, UUID generation) {
        PayloadCipher.Context.archive(generation, 1, 0);
        return new File(new File(context.getNoBackupFilesDir(), "capybaragram-archive"), generation + ".db");
    }

    public static AndroidArchiveStore create(Context context, UUID generation, SecretKey key) throws Exception {
        background();
        File file = file(context, generation), parent = file.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs()) || !file.createNewFile()) {
            throw new IOException("New archive unavailable.");
        }
        SQLiteDatabase db = database(file);
        try {
            db.beginTransaction();
            try {
                try (Cursor cursor = db.rawQuery("SELECT count(*) FROM sqlite_master", null)) {
                    if (!cursor.moveToFirst() || cursor.getLong(0) != 0 || db.getVersion() != 0) {
                        throw new IOException("Expected empty archive.");
                    }
                }
                db.execSQL(CREATE);
                db.execSQL("CREATE INDEX snapshots_chat_idx ON snapshots(dialog_id,id)");
                db.setVersion(1);
                db.setTransactionSuccessful();
            } finally { db.endTransaction(); }
            return new AndroidArchiveStore(db, generation, key);
        } catch (Exception error) { db.close(); throw error; }
    }

    public static AndroidArchiveStore open(Context context, UUID generation, SecretKey key) throws Exception {
        background();
        File file = file(context, generation);
        if (!file.isFile()) throw new IOException("Archive unavailable; original preserved.");
        SQLiteDatabase db = database(file);
        if (db.getVersion() != 1) { db.close(); throw new IOException("Unsupported archive version."); }
        return new AndroidArchiveStore(db, generation, key);
    }

    private static SQLiteDatabase database(File file) {
        SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getAbsolutePath(), null,
                SQLiteDatabase.OPEN_READWRITE | SQLiteDatabase.NO_LOCALIZED_COLLATORS, broken -> {});
        try { db.execSQL("PRAGMA synchronous=FULL"); return db; }
        catch (RuntimeException error) { db.close(); throw error; }
    }

    private static void background() {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Archive needs worker.");
    }

    private void ready() {
        if (Thread.currentThread() != worker || key == null || !db.isOpen()) throw new IllegalStateException("Archive closed.");
    }

    public void save(long dialog, int message, int reason, byte[] tl, String text, boolean media) throws Exception {
        ready();
        if (dialog == 0 || message == 0 || reason < 1 || reason > 3 || tl == null
                || tl.length > MAX_TL_BYTES || text == null) throw new IllegalArgumentException("Invalid snapshot.");
        byte[] fingerprint = MessageDigest.getInstance("SHA-256").digest(tl);
        String[] args = {Long.toString(dialog), Integer.toString(message), Integer.toString(reason),
                hex(fingerprint)};
        try (Cursor c = db.rawQuery("SELECT id FROM snapshots WHERE dialog_id=? AND message_id=? "
                + "AND reason=? AND hex(fingerprint)=?", args)) { if (c.moveToFirst()) return; }
        long now = Math.max(0, System.currentTimeMillis());
        JSONObject body = new JSONObject();
        body.put("version", 1); body.put("dialog", dialog); body.put("message", message);
        body.put("reason", reason); body.put("saved_at", now); body.put("text", text);
        body.put("tl", Base64.encodeToString(tl, Base64.NO_WRAP));
        body.put("has_media", media); body.put("original_media_saved", false);
        byte[] plain = body.toString().getBytes(StandardCharsets.UTF_8);
        db.beginTransaction();
        try {
            ContentValues values = new ContentValues();
            values.put("dialog_id", dialog); values.put("message_id", message); values.put("reason", reason);
            values.put("created_at", now); values.put("fingerprint", fingerprint); values.put("payload", new byte[32]);
            long id = db.insertOrThrow("snapshots", null, values);
            values.clear();
            values.put("payload", PayloadCipher.encrypt(key, PayloadCipher.Context.archive(generation, id, 0), plain));
            if (db.update("snapshots", values, "id=?", new String[]{Long.toString(id)}) != 1) throw new IOException("Snapshot update failed.");
            db.execSQL("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT " + MAX_ROWS + ")");
            db.setTransactionSuccessful();
        } finally { Arrays.fill(plain, (byte) 0); db.endTransaction(); }
    }

    public List<Entry> list(long dialog, long before) throws Exception {
        ready();
        if (dialog == 0 || before < 0) throw new IllegalArgumentException("Invalid archive page.");
        List<Entry> result = new ArrayList<>();
        String where = before == 0 ? "dialog_id=?" : "dialog_id=? AND id<?";
        String[] args = before == 0 ? new String[]{Long.toString(dialog)} : new String[]{Long.toString(dialog), Long.toString(before)};
        try (Cursor c = db.query("snapshots", new String[]{"id","dialog_id","message_id","reason","created_at","payload"},
                where, args, null, null, "id DESC", Integer.toString(PAGE_SIZE))) {
            while (c.moveToNext()) {
                long id = c.getLong(0);
                byte[] plain = PayloadCipher.decrypt(key, PayloadCipher.Context.archive(generation, id, 0), c.getBlob(5));
                try {
                    JSONObject body = new JSONObject(new String(plain, StandardCharsets.UTF_8));
                    if (body.getInt("version") != 1 || body.getLong("dialog") != c.getLong(1)
                            || body.getInt("message") != c.getInt(2) || body.getInt("reason") != c.getInt(3)
                            || body.getLong("saved_at") != c.getLong(4)) throw new IOException("Archive identity invalid.");
                    result.add(new Entry(id, c.getInt(2), c.getInt(3), c.getLong(4), body.getString("text"), body.getBoolean("has_media")));
                } finally { Arrays.fill(plain, (byte) 0); }
            }
        }
        return result;
    }

    private static String hex(byte[] bytes) {
        char[] chars = new char[bytes.length * 2];
        char[] alphabet = "0123456789ABCDEF".toCharArray();
        for (int i = 0; i < bytes.length; i++) { chars[i*2] = alphabet[(bytes[i]&255)>>>4]; chars[i*2+1] = alphabet[bytes[i]&15]; }
        return new String(chars);
    }

    @Override public void close() {
        if (Thread.currentThread() != worker) throw new IllegalStateException("Close on archive worker.");
        if (key == null) return;
        key = null; db.close();
    }

    public static final class Entry {
        public final long id, savedAt;
        public final int message, reason;
        public final String text;
        public final boolean media;
        Entry(long id, int message, int reason, long savedAt, String text, boolean media) {
            this.id=id; this.message=message; this.reason=reason; this.savedAt=savedAt; this.text=text; this.media=media;
        }
    }
}
