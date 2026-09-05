// SPDX-License-Identifier: MIT
package org.capybaragram.local;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.capybaragram.local.PayloadCipher.Context;

/** Synthetic fixture tests, not AndroidKeyStore or native adapter verification. */
public final class PayloadCipherTest {
    private static int checks;
    private static final UUID GENERATION = UUID.fromString("01020304-0506-0708-1112-131415161718");
    private interface Checked { void run() throws Exception; }
    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("Check " + (checks + 1) + " failed");
        checks++;
    }
    private static void invalid(Checked operation) throws Exception {
        try { operation.run(); } catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Invalid input accepted");
    }
    private static void authentication(Checked operation) throws Exception {
        try { operation.run(); } catch (GeneralSecurityException expected) { checks++; return; }
        throw new AssertionError("Invalid ciphertext authenticated");
    }
    private static SecretKey key() throws Exception {
        KeyGenerator generator = KeyGenerator.getInstance("AES");
        generator.init(256);
        return generator.generateKey();
    }
    private static byte[] independentAad(int kind, int peerType, long peerId, long topicId, long templateId) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        out.write("CapybaraGram.payload.v1".getBytes(StandardCharsets.US_ASCII));
        out.writeByte(0);
        // Literal UUID bytes instead of calling Context or UUID serialization.
        for (int value : new int[]{1,2,3,4,5,6,7,8,17,18,19,20,21,22,23,24}) out.writeByte(value);
        out.writeByte(kind); out.writeByte(peerType);
        out.writeLong(peerId); out.writeLong(topicId); out.writeLong(templateId);
        return bytes.toByteArray();
    }
    public static void main(String[] args) throws Exception {
        final SecretKey key = key(), wrongKey = key();
        final Context note = Context.note(GENERATION, 3, 0x0102030405060708L, 0x1112131415161718L);
        final Context template = Context.template(GENERATION, 0x2122232425262728L);
        final byte[] text = "Заметка: капибара 🦫".getBytes(StandardCharsets.UTF_8);
        for (byte[] plain : new byte[][]{new byte[0], text, new byte[PayloadCipher.MAX_PLAINTEXT]}) {
            byte[] blob = PayloadCipher.encrypt(key, note, plain);
            check(blob.length == plain.length + 32);
            check(Arrays.equals(plain, PayloadCipher.decrypt(key, note, blob)));
        }
        byte[] noteAad = independentAad(1, 3, 0x0102030405060708L, 0x1112131415161718L, 0);
        check(Arrays.equals(note.aad(), noteAad));
        check(Arrays.equals(template.aad(), independentAad(2, 0, 0, 0, 0x2122232425262728L)));
        byte[] changedAad = note.aad(); changedAad[0] ^= 1;
        check(Arrays.equals(note.aad(), noteAad));
        final byte[] blob = PayloadCipher.encrypt(key, note, text);
        check(Arrays.equals(Arrays.copyOf(blob, 4), new byte[]{'C','P','G','1'}));
        Cipher direct = Cipher.getInstance("AES/GCM/NoPadding");
        direct.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, Arrays.copyOfRange(blob, 4, 16)));
        direct.updateAAD(noteAad);
        check(Arrays.equals(text, direct.doFinal(blob, 16, blob.length - 16)));
        check(!Arrays.equals(blob, PayloadCipher.encrypt(key, note, text))); // smoke only
        authentication(() -> PayloadCipher.decrypt(wrongKey, note, blob));
        for (final Context other : new Context[]{
                Context.note(UUID.fromString("02020304-0506-0708-1112-131415161718"),3,0x0102030405060708L,0x1112131415161718L),
                Context.note(GENERATION,3,1,0x1112131415161718L),
                Context.note(GENERATION,3,0x0102030405060708L,1), template}) {
            authentication(() -> PayloadCipher.decrypt(key, other, blob));
        }
        final byte[] userBlob = PayloadCipher.encrypt(key, Context.note(GENERATION,1,1,0), text);
        authentication(() -> PayloadCipher.decrypt(key, Context.note(GENERATION,2,1,0), userBlob));
        final byte[] templateBlob = PayloadCipher.encrypt(key, template, text);
        check(Arrays.equals(text, PayloadCipher.decrypt(key, template, templateBlob)));
        authentication(() -> PayloadCipher.decrypt(key, Context.template(GENERATION,1), templateBlob));
        authentication(() -> PayloadCipher.decrypt(key, note, templateBlob));
        for (int index : new int[]{0,3,4,15,16,blob.length-1}) {
            final byte[] corrupt = blob.clone(); corrupt[index] ^= 1;
            if (index < 4) invalid(() -> PayloadCipher.decrypt(key, note, corrupt));
            else authentication(() -> PayloadCipher.decrypt(key, note, corrupt));
        }
        for (int length : new int[]{0,1,4,15,16,31}) {
            final byte[] truncated = Arrays.copyOf(blob, length);
            invalid(() -> PayloadCipher.decrypt(key,note,truncated));
        }
        authentication(() -> PayloadCipher.decrypt(key,note,Arrays.copyOf(blob,blob.length-1)));
        invalid(() -> PayloadCipher.encrypt(key,note,new byte[PayloadCipher.MAX_PLAINTEXT+1]));
        invalid(() -> PayloadCipher.decrypt(key,note,new byte[PayloadCipher.MAX_ENVELOPE+1]));
        invalid(() -> PayloadCipher.encrypt(null,note,text));
        invalid(() -> PayloadCipher.encrypt(key,null,text));
        invalid(() -> PayloadCipher.encrypt(key,note,null));
        invalid(() -> PayloadCipher.decrypt(null,note,blob));
        invalid(() -> PayloadCipher.decrypt(key,null,blob));
        invalid(() -> PayloadCipher.decrypt(key,note,null));
        invalid(() -> Context.note(null,1,1,0));
        invalid(() -> Context.template(new UUID(0,0),1));
        invalid(() -> Context.note(GENERATION,0,1,0));
        invalid(() -> Context.note(GENERATION,4,1,0));
        invalid(() -> Context.note(GENERATION,1,0,0));
        invalid(() -> Context.note(GENERATION,1,-1,0));
        invalid(() -> Context.note(GENERATION,3,1,-1));
        invalid(() -> Context.note(GENERATION,1,1,1));
        invalid(() -> Context.note(GENERATION,2,1,1));
        invalid(() -> Context.template(GENERATION,0));
        invalid(() -> Context.template(GENERATION,-1));
        System.out.println("PASS: " + checks + " checks; native key/storage/runtime integration not tested.");
    }
}
