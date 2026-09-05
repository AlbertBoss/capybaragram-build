// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteException;
import android.os.Looper;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import javax.crypto.SecretKey;

/**
 * Native SQLite storage on one background thread, one database per account
 * generation. Callers own account validation, key lifecycle and app-lock gating.
 * Notes/templates are local; no Telegram messages are sent by this class.
 */
public final class AndroidVaultStore implements AutoCloseable {
    private static final String NOTE_WHERE = "peer_type=? AND peer_id=? AND topic_id=?";
    private static final String[] PEER_TYPES = {"", "user", "chat", "channel"};
    private final UUID generation;
    private final Thread worker;
    private final SQLiteDatabase database;
    private SecretKey key;

    private AndroidVaultStore(SQLiteDatabase database, UUID generation, SecretKey key) {
        this.database = database;
        this.generation = generation;
        this.key = key;
        worker = Thread.currentThread();
    }

    // No user-provided filenames; this directory is excluded from Android backup.
    static File file(Context context, UUID generation) {
        PayloadCipher.Context.template(generation, 1);
        return new File(new File(context.getNoBackupFilesDir(), "capybaragram-vault"),
                generation + ".db");
    }

    private static void background() {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            throw new IllegalStateException("Vault storage requires a background worker.");
        }
    }

    private static void validateKey(SecretKey key) {
        if (key == null || !"AES".equals(key.getAlgorithm())) {
            throw new IllegalArgumentException("AES vault key required.");
        }
    }

    public static AndroidVaultStore create(Context context, UUID generation, SecretKey key)
            throws IOException {
        background();
        validateKey(key);
        File path = file(context, generation);
        File parent = path.getParentFile();
        if (parent == null || (!parent.isDirectory() && !parent.mkdirs())) {
            throw new IOException("Vault directory unavailable.");
        }
        if (!path.createNewFile()) throw new IOException("Vault already exists.");
        SQLiteDatabase db = openDatabase(path);
        try {
            db.beginTransaction();
            try {
                try (Cursor cursor = db.rawQuery("SELECT count(*) FROM sqlite_master", null)) {
                    if (!cursor.moveToFirst() || cursor.getLong(0) != 0 || db.getVersion() != 0) {
                        throw new SQLiteException("Expected an empty vault database.");
                    }
                }
                for (String statement : VaultSchema.STATEMENTS) db.execSQL(statement);
                db.setVersion(1);
                db.setTransactionSuccessful();
            } finally {
                db.endTransaction();
            }
            return new AndroidVaultStore(db, generation, key);
        } catch (RuntimeException failure) {
            db.close();
            // Preserve failed state for explicit recovery; never silently recreate it.
            throw failure;
        }
    }

    public static AndroidVaultStore open(Context context, UUID generation, SecretKey key)
            throws IOException {
        background();
        validateKey(key);
        File path = file(context, generation);
        if (!path.isFile()) throw new IOException("Vault database unavailable.");
        SQLiteDatabase db = openDatabase(path);
        try {
            if (db.getVersion() != 1) {
                throw new SQLiteException("Unsupported vault version; data preserved.");
            }
            return new AndroidVaultStore(db, generation, key);
        } catch (RuntimeException failure) {
            db.close();
            throw failure;
        }
    }

    private static SQLiteDatabase openDatabase(File file) {
        // The default Android corruption handler can delete the database. Preserve
        // it instead so recovery remains an explicit user decision.
        SQLiteDatabase db = SQLiteDatabase.openDatabase(file.getAbsolutePath(), null,
                // Payloads are encrypted and ordering uses integer ids, so locale
                // collators are unnecessary. This also prevents Android from
                // creating/updating android_metadata before schema validation.
                SQLiteDatabase.OPEN_READWRITE | SQLiteDatabase.NO_LOCALIZED_COLLATORS,
                corrupted -> { });
        try {
            db.execSQL("PRAGMA synchronous=FULL");
            return db;
        } catch (RuntimeException failure) {
            db.close();
            throw failure;
        }
    }

    private void ready() {
        if (Thread.currentThread() != worker || key == null || !database.isOpen()) {
            throw new IllegalStateException("Vault is closed or used on another thread.");
        }
    }

    private String[] noteArguments(int type, long peer, long topic) {
        PayloadCipher.Context.note(generation, type, peer, topic);
        return new String[]{PEER_TYPES[type], Long.toString(peer), Long.toString(topic)};
    }

    public String getNote(int type, long peer, long topic) throws GeneralSecurityException {
        ready();
        String[] arguments = noteArguments(type, peer, topic);
        try (Cursor cursor = database.query("notes", new String[]{"payload"}, NOTE_WHERE,
                arguments, null, null, null)) {
            return cursor.moveToFirst() ? decode(cursor.getBlob(0),
                    PayloadCipher.Context.note(generation, type, peer, topic)) : "";
        }
    }

    /** Empty text deletes the note; all nonempty text is encrypted before SQLite. */
    public void saveNote(int type, long peer, long topic, String text)
            throws GeneralSecurityException {
        ready();
        String[] arguments = noteArguments(type, peer, topic);
        if (text == null) throw new IllegalArgumentException("Note text required.");
        if (text.isEmpty()) {
            database.delete("notes", NOTE_WHERE, arguments);
            return;
        }
        byte[] payload = encode(text, PayloadCipher.Context.note(generation, type, peer, topic));
        long now = Math.max(0, System.currentTimeMillis());
        database.beginTransaction();
        try {
            ContentValues values = new ContentValues();
            values.put("peer_type", arguments[0]);
            values.put("peer_id", peer);
            values.put("topic_id", topic);
            values.put("payload", payload);
            values.put("created_at", now);
            values.put("updated_at", now);
            boolean exists;
            try (Cursor cursor = database.query("notes", new String[]{"id"}, NOTE_WHERE,
                    arguments, null, null, null)) {
                exists = cursor.moveToFirst();
            }
            if (exists) {
                database.execSQL("UPDATE notes SET payload=?, updated_at=MAX(updated_at,?) WHERE "
                        + NOTE_WHERE, new Object[]{payload, now, arguments[0], peer, topic});
            } else {
                database.insertOrThrow("notes", null, values);
            }
            database.setTransactionSuccessful();
        } finally {
            database.endTransaction();
        }
    }

    public long addTemplate(String text) throws GeneralSecurityException {
        ready();
        if (text == null || text.trim().isEmpty()) {
            throw new IllegalArgumentException("Template text required.");
        }
        database.beginTransaction();
        try {
            long now = Math.max(0, System.currentTimeMillis());
            ContentValues values = new ContentValues();
            // Placeholder never commits: AAD needs the newly allocated row id.
            values.put("payload", new byte[32]);
            values.put("created_at", now);
            values.put("updated_at", now);
            long id = database.insertOrThrow("templates", null, values);
            byte[] payload = encode(text, PayloadCipher.Context.template(generation, id));
            values.clear();
            values.put("payload", payload);
            if (database.update("templates", values, "id=?", new String[]{Long.toString(id)}) != 1) {
                throw new SQLiteException("Template insert failed.");
            }
            database.setTransactionSuccessful();
            return id;
        } finally {
            database.endTransaction();
        }
    }

    public List<Template> listTemplates(int offset) throws GeneralSecurityException {
        ready();
        if (offset < 0) throw new IllegalArgumentException("Invalid page offset.");
        List<Template> result = new ArrayList<>();
        try (Cursor cursor = database.query("templates", new String[]{"id", "payload"},
                null, null, null, null, "sort_order,id", offset + ",100")) {
            while (cursor.moveToNext()) {
                long id = cursor.getLong(0);
                result.add(new Template(id, decode(cursor.getBlob(1),
                        PayloadCipher.Context.template(generation, id))));
            }
        }
        return result;
    }

    public void deleteTemplate(long id) {
        ready();
        PayloadCipher.Context.template(generation, id);
        database.delete("templates", "id=?", new String[]{Long.toString(id)});
    }

    public void updateTemplate(long id, String text) throws GeneralSecurityException {
        ready();
        if (text == null || text.trim().isEmpty()) {
            throw new IllegalArgumentException("Template text required.");
        }
        byte[] payload = encode(text, PayloadCipher.Context.template(generation, id));
        database.beginTransaction();
        try {
            try (Cursor cursor = database.rawQuery("SELECT id FROM templates WHERE id=?",
                    new String[]{Long.toString(id)})) {
                if (!cursor.moveToFirst()) throw new IllegalArgumentException("Template unavailable.");
            }
            database.execSQL("UPDATE templates SET payload=?, updated_at=MAX(updated_at,?) WHERE id=?",
                    new Object[]{payload, Math.max(0, System.currentTimeMillis()), id});
            database.setTransactionSuccessful();
        } finally {
            database.endTransaction();
        }
    }

    private byte[] encode(String text, PayloadCipher.Context context)
            throws GeneralSecurityException {
        if (text.length() > PayloadCipher.MAX_PLAINTEXT) {
            throw new IllegalArgumentException("Text exceeds vault limit.");
        }
        byte[] plain = null;
        try {
            ByteBuffer buffer = StandardCharsets.UTF_8.newEncoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).encode(CharBuffer.wrap(text));
            plain = new byte[buffer.remaining()];
            buffer.get(plain);
            if (buffer.hasArray()) Arrays.fill(buffer.array(), (byte) 0);
            return PayloadCipher.encrypt(key, context, plain);
        } catch (CharacterCodingException failure) {
            throw new IllegalArgumentException("Invalid text encoding.");
        } finally {
            if (plain != null) Arrays.fill(plain, (byte) 0);
        }
    }

    private String decode(byte[] payload, PayloadCipher.Context context)
            throws GeneralSecurityException {
        byte[] plain = PayloadCipher.decrypt(key, context, payload);
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(plain)).toString();
        } catch (CharacterCodingException failure) {
            throw new GeneralSecurityException("Invalid vault text.");
        } finally {
            Arrays.fill(plain, (byte) 0);
        }
    }

    @Override public void close() {
        if (Thread.currentThread() != worker) {
            throw new IllegalStateException("Close vault on its worker.");
        }
        if (key == null) return;
        key = null;
        database.close();
    }

    public static final class Template {
        public final long id;
        public final String text;
        private Template(long id, String text) { this.id = id; this.text = text; }
    }
}
