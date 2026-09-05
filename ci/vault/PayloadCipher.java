// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Written by Codex: the Fable response ended before its class declaration.
 * AES-GCM payload format, independent of Android and storage.
 * The adapter must create/protect an AES-256 key and supply the expected account
 * generation and row identity. Opaque key length cannot be checked here.
 * Does not prevent rollback, hide SQLite metadata, or protect a compromised
 * process. Key lifecycle, native storage and UI integration remain separate work.
 */
public final class PayloadCipher {
    public static final int MAX_ENVELOPE = 131072;
    public static final int MAX_PLAINTEXT = MAX_ENVELOPE - 32;
    private static final byte[] MAGIC = {'C', 'P', 'G', '1'};
    private static final byte[] DOMAIN = "CapybaraGram.payload.v1".getBytes(StandardCharsets.US_ASCII);
    private PayloadCipher() {}

    public static byte[] encrypt(SecretKey key, Context context, byte[] plaintext)
            throws GeneralSecurityException {
        validate(key, context, plaintext);
        if (plaintext.length > MAX_PLAINTEXT) throw invalid();
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key);
            byte[] iv = cipher.getIV();
            if (iv == null || iv.length != 12) throw new GeneralSecurityException();
            cipher.updateAAD(context.aad());
            byte[] encrypted = cipher.doFinal(plaintext);
            if (encrypted.length != plaintext.length + 16) throw new GeneralSecurityException();
            return ByteBuffer.allocate(16 + encrypted.length).put(MAGIC).put(iv).put(encrypted).array();
        } catch (GeneralSecurityException failure) {
            throw new GeneralSecurityException("Payload encryption failed.");
        }
    }

    public static byte[] decrypt(SecretKey key, Context context, byte[] envelope)
            throws GeneralSecurityException {
        validate(key, context, envelope);
        if (envelope.length < 32 || envelope.length > MAX_ENVELOPE) throw invalid();
        for (int i = 0; i < MAGIC.length; i++) if (envelope[i] != MAGIC[i]) throw invalid();
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key,
                    new GCMParameterSpec(128, Arrays.copyOfRange(envelope, 4, 16)));
            cipher.updateAAD(context.aad());
            return cipher.doFinal(envelope, 16, envelope.length - 16);
        } catch (GeneralSecurityException failure) {
            throw new GeneralSecurityException("Payload authentication failed.");
        }
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("Invalid payload arguments or format.");
    }

    private static void validate(SecretKey key, Context context, byte[] data) {
        if (key == null || context == null || data == null || !"AES".equals(key.getAlgorithm())) throw invalid();
    }

    public static final class Context {
        private final UUID generation;
        private final byte kind, peerType;
        private final long peerId, topicId, templateId;

        private Context(UUID generation, byte kind, byte peerType, long peerId, long topicId, long templateId) {
            if (generation == null || (generation.getMostSignificantBits() == 0 && generation.getLeastSignificantBits() == 0)) throw invalid();
            this.generation = generation;
            this.kind = kind;
            this.peerType = peerType;
            this.peerId = peerId;
            this.topicId = topicId;
            this.templateId = templateId;
        }

        public static Context note(UUID generation, int peerType, long peerId, long topicId) {
            if (peerType < 1 || peerType > 3 || peerId <= 0 || topicId < 0 || (topicId > 0 && peerType != 3)) throw invalid();
            return new Context(generation, (byte) 1, (byte) peerType, peerId, topicId, 0);
        }

        public static Context template(UUID generation, long templateId) {
            if (templateId <= 0) throw invalid();
            return new Context(generation, (byte) 2, (byte) 0, 0, 0, templateId);
        }

        // Fresh buffer on every call; big endian is ByteBuffer's defined default.
        byte[] aad() {
            return ByteBuffer.allocate(DOMAIN.length + 1 + 16 + 2 + 24)
                    .put(DOMAIN).put((byte) 0)
                    .putLong(generation.getMostSignificantBits()).putLong(generation.getLeastSignificantBits())
                    .put(kind).put(peerType).putLong(peerId).putLong(topicId).putLong(templateId).array();
        }
    }
}
