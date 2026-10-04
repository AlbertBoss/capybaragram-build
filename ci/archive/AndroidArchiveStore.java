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
import java.io.InputStream;
import java.io.OutputStream;
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
    public static final long MAX_ORIGINAL_BYTES = 32L * 1024 * 1024;
    public static final long MAX_ORIGINALS_BYTES = 128L * 1024 * 1024;
    private static final int CHUNK_BYTES = 65536;
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

    private static void createOriginals(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE originals (snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE, "
                + "metadata BLOB NOT NULL, stored_bytes INTEGER NOT NULL, CHECK(length(metadata)>=32 AND length(metadata)<=4096), "
                + "CHECK(stored_bytes>=32 AND stored_bytes<=33574912))");
        db.execSQL("CREATE TABLE original_parts (snapshot_id INTEGER NOT NULL REFERENCES originals(snapshot_id) ON DELETE CASCADE, "
                + "part INTEGER NOT NULL, payload BLOB NOT NULL, CHECK(part>=2 AND part<=513), "
                + "CHECK(length(payload)>=33 AND length(payload)<=65568), PRIMARY KEY(snapshot_id,part))");
    }

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
                createOriginals(db);
                db.setVersion(2);
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
        try {
            if (db.getVersion() == 1) {
                db.beginTransaction();
                try { createOriginals(db); db.setVersion(2); db.setTransactionSuccessful(); }
                finally { db.endTransaction(); }
            }
            if (db.getVersion() != 2) throw new IOException("Unsupported archive version.");
            return new AndroidArchiveStore(db, generation, key);
        } catch (Exception error) { db.close(); throw error; }
    }

    private static SQLiteDatabase database(File file) {
        SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getAbsolutePath(), null,
                SQLiteDatabase.OPEN_READWRITE | SQLiteDatabase.NO_LOCALIZED_COLLATORS, broken -> {});
        try { db.execSQL("PRAGMA synchronous=FULL"); db.setForeignKeyConstraintsEnabled(true); return db; }
        catch (RuntimeException error) { db.close(); throw error; }
    }

    private static void background() {
        if (Looper.myLooper() == Looper.getMainLooper()) throw new IllegalStateException("Archive needs worker.");
    }

    private void ready() {
        if (Thread.currentThread() != worker || key == null || !db.isOpen()) throw new IllegalStateException("Archive closed.");
    }

    public long save(long dialog, int message, int reason, byte[] tl, String text, boolean media) throws Exception {
        ready();
        if (dialog == 0 || message == 0 || reason < 1 || reason > 3 || tl == null
                || tl.length > MAX_TL_BYTES || text == null) throw new IllegalArgumentException("Invalid snapshot.");
        byte[] fingerprint = MessageDigest.getInstance("SHA-256").digest(tl);
        String[] args = {Long.toString(dialog), Integer.toString(message), Integer.toString(reason),
                hex(fingerprint)};
        try (Cursor c = db.rawQuery("SELECT id FROM snapshots WHERE dialog_id=? AND message_id=? "
                + "AND reason=? AND hex(fingerprint)=?", args)) { if (c.moveToFirst()) return c.getLong(0); }
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
            return id;
        } finally { Arrays.fill(plain, (byte) 0); db.endTransaction(); }
    }

    /** All chunks and their authenticated descriptor commit together, or none do. */
    public void saveOriginal(long id, InputStream input, long expectedSize, String mime) throws Exception {
        ready();
        if (input == null || expectedSize <= 0 || expectedSize > MAX_ORIGINAL_BYTES || mime == null
                || mime.length() > 127 || !mime.matches("[a-zA-Z][a-zA-Z0-9.+-]*/[a-zA-Z0-9][a-zA-Z0-9.+-]*"))
            throw new IllegalArgumentException("Invalid original.");
        authenticateSnapshot(id);
        if (originalInfo(id) != null) return;
        byte[] buffer = new byte[CHUNK_BYTES];
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        db.beginTransaction();
        try {
            ContentValues header = new ContentValues(); header.put("snapshot_id", id);
            header.put("metadata", new byte[32]); header.put("stored_bytes", 32);
            db.insertOrThrow("originals", null, header);
            long copied = 0, stored = 0; int part = 2;
            while (copied < expectedSize) {
                if (Thread.currentThread().isInterrupted()) throw new IOException("Original interrupted.");
                int wanted = (int)Math.min(buffer.length, expectedSize-copied), read = 0;
                while (read < wanted) {
                    int n = input.read(buffer, read, wanted-read);
                    if (n <= 0) throw new IOException("Original incomplete.");
                    read += n;
                }
                digest.update(buffer,0,read);
                byte[] plain = Arrays.copyOf(buffer, read);
                byte[] encrypted;
                try { encrypted = PayloadCipher.encrypt(key, PayloadCipher.Context.archive(generation,id,part),plain); }
                finally { Arrays.fill(plain,(byte)0); Arrays.fill(buffer,(byte)0); }
                ContentValues values = new ContentValues(); values.put("snapshot_id",id); values.put("part",part++);
                values.put("payload",encrypted); db.insertOrThrow("original_parts",null,values);
                copied += read; stored += encrypted.length;
            }
            if (input.read() != -1) throw new IOException("Original size mismatch.");
            JSONObject body = new JSONObject(); body.put("version",1); body.put("size",copied);
            body.put("chunks",part-2); body.put("mime",mime); body.put("sha256",hex(digest.digest()));
            byte[] plain = body.toString().getBytes(StandardCharsets.UTF_8);
            byte[] encrypted;
            try { encrypted = PayloadCipher.encrypt(key,PayloadCipher.Context.archive(generation,id,1),plain); }
            finally { Arrays.fill(plain,(byte)0); }
            header.clear(); header.put("metadata",encrypted); header.put("stored_bytes",stored+encrypted.length);
            if (db.update("originals",header,"snapshot_id=?",new String[]{Long.toString(id)}) != 1)
                throw new IOException("Original update failed.");
            while (originalBytes() > MAX_ORIGINALS_BYTES) {
                db.execSQL("DELETE FROM originals WHERE snapshot_id=(SELECT snapshot_id FROM originals ORDER BY snapshot_id LIMIT 1)");
            }
            db.setTransactionSuccessful();
        } finally { Arrays.fill(buffer,(byte)0); db.endTransaction(); }
    }

    private long originalBytes() throws IOException {
        try (Cursor c = db.rawQuery("SELECT coalesce(sum(length(payload)),0)+(SELECT coalesce(sum(length(metadata)),0) FROM originals) FROM original_parts",null)) {
            if (!c.moveToFirst()) throw new IOException("Original quota unavailable.");
            return c.getLong(0);
        }
    }

    private void authenticateSnapshot(long id) throws Exception {
        if (id <= 0) throw new IllegalArgumentException("Invalid snapshot id.");
        try (Cursor c = db.query("snapshots",new String[]{"id","dialog_id","message_id","reason","created_at","payload"},
                "id=?",new String[]{Long.toString(id)},null,null,null)) {
            if (!c.moveToFirst()) throw new IOException("Snapshot unavailable.");
            decodeEntry(c);
        }
    }

    public Original originalInfo(long id) throws Exception {
        ready();
        try (Cursor c = db.query("originals",new String[]{"metadata"},"snapshot_id=?",new String[]{Long.toString(id)},null,null,null)) {
            if (!c.moveToFirst()) return null;
            byte[] plain = PayloadCipher.decrypt(key,PayloadCipher.Context.archive(generation,id,1),c.getBlob(0));
            try {
                JSONObject b = new JSONObject(new String(plain,StandardCharsets.UTF_8));
                long size = b.getLong("size"); int chunks = b.getInt("chunks");
                String mime = b.getString("mime"), sha = b.getString("sha256");
                if (b.getInt("version") != 1 || size <= 0 || size > MAX_ORIGINAL_BYTES
                        || chunks != (size+CHUNK_BYTES-1)/CHUNK_BYTES || !sha.matches("[0-9A-F]{64}")
                        || mime.length()>127 || !mime.matches("[a-zA-Z][a-zA-Z0-9.+-]*/[a-zA-Z0-9][a-zA-Z0-9.+-]*"))
                    throw new IOException("Original descriptor invalid.");
                return new Original(size,mime,sha,chunks);
            } finally { Arrays.fill(plain,(byte)0); }
        }
    }

    /** Caller must keep output private and publish only after this method returns. */
    public Original writeOriginal(long id, OutputStream output) throws Exception {
        ready(); authenticateSnapshot(id);
        Original original = originalInfo(id);
        if (original == null || output == null) throw new IOException("Original unavailable.");
        MessageDigest digest = MessageDigest.getInstance("SHA-256"); long size = 0; int part = 2;
        try (Cursor c = db.query("original_parts",new String[]{"part","payload"},"snapshot_id=?",new String[]{Long.toString(id)},null,null,"part")) {
            while(c.moveToNext()) {
                if (Thread.currentThread().isInterrupted() || part >= original.chunks+2 || c.getInt(0) != part)
                    throw new IOException("Original parts invalid.");
                byte[] plain = PayloadCipher.decrypt(key,PayloadCipher.Context.archive(generation,id,part),c.getBlob(1));
                try {
                    int expected = (int)Math.min(CHUNK_BYTES,original.size-size);
                    if (plain.length != expected) throw new IOException("Original chunk invalid.");
                    digest.update(plain); output.write(plain); size += plain.length; part++;
                } finally { Arrays.fill(plain,(byte)0); }
            }
        }
        if (size != original.size || part != original.chunks+2 || !original.sha256.equals(hex(digest.digest())))
            throw new IOException("Original incomplete.");
        return original;
    }

    private Entry decodeEntry(Cursor c) throws Exception {
        long id = c.getLong(0);
        byte[] plain = PayloadCipher.decrypt(key,PayloadCipher.Context.archive(generation,id,0),c.getBlob(5));
        try {
            JSONObject body = new JSONObject(new String(plain,StandardCharsets.UTF_8));
            if (body.getInt("version") != 1 || body.getLong("dialog") != c.getLong(1)
                    || body.getInt("message") != c.getInt(2) || body.getInt("reason") != c.getInt(3)
                    || body.getLong("saved_at") != c.getLong(4)) throw new IOException("Archive identity invalid.");
            return new Entry(id,c.getInt(2),c.getInt(3),c.getLong(4),body.getString("text"),body.getBoolean("has_media"));
        } finally { Arrays.fill(plain,(byte)0); }
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
                Entry entry = decodeEntry(c); entry.original = originalInfo(entry.id); result.add(entry);
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
        public Original original;
        Entry(long id, int message, int reason, long savedAt, String text, boolean media) {
            this.id=id; this.message=message; this.reason=reason; this.savedAt=savedAt; this.text=text; this.media=media;
        }
    }

    public static final class Original {
        public final long size;
        public final String mime, sha256;
        public final int chunks;
        Original(long size,String mime,String sha256,int chunks) {
            this.size=size; this.mime=mime; this.sha256=sha256; this.chunks=chunks;
        }
    }
}
