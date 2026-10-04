// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Test-only helper, no Internet permission; the native library is copied from the exact release APK. */
public final class RussianModelComparisonInstrumentation extends Instrumentation {
    private Bundle arguments;
    @Override public void onCreate(Bundle args) { arguments = args; super.onCreate(args); start(); }
    private static String sha(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes))
            result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }
    private byte[] assetBytes(String name, int limit) throws Exception {
        if (!name.matches("[a-z0-9._-]{1,80}")) throw new IllegalArgumentException("Invalid fixture name.");
        try (InputStream in = getTargetContext().getAssets().open(name);
                ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = in.read(buffer)) != -1) {
                if (out.size() + count > limit) throw new IllegalStateException("Fixture exceeds its bound.");
                out.write(buffer, 0, count);
            }
            Arrays.fill(buffer, (byte)0); return out.toByteArray();
        }
    }
    private File assetFile(String name, int size, String expected) throws Exception {
        if (expected == null || !expected.matches("[a-f0-9]{64}") || size <= 0 || size > 80000000)
            throw new IllegalArgumentException("Missing fixture identity.");
        if (!name.matches("[a-z0-9._-]{1,80}")) throw new IllegalArgumentException("Invalid fixture name.");
        File file = new File(getTargetContext().getFilesDir(), name);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[65536]; long total = 0;
        try (InputStream in = getTargetContext().getAssets().open(name); FileOutputStream out = new FileOutputStream(file)) {
            int count;
            while ((count = in.read(buffer)) != -1) {
                total += count;
                if (total > size) throw new IllegalStateException("Fixture exceeds its bound.");
                digest.update(buffer, 0, count); out.write(buffer, 0, count);
            }
            out.getFD().sync();
            StringBuilder actual = new StringBuilder();
            for (byte b : digest.digest()) actual.append(String.format(Locale.ROOT, "%02x", b & 255));
            if (total != size || !expected.contentEquals(actual)) throw new IllegalStateException("Fixture identity differs.");
            return file;
        } finally { Arrays.fill(buffer, (byte)0); }
    }
    private static String[] words(String text) {
        String normalized = text.toLowerCase(Locale.ROOT).replace('ё', 'е')
            .replaceAll("[^\\p{L}\\p{Nd}]+", " ").trim();
        if (normalized.isEmpty()) return new String[0];
        String[] words = normalized.split(" +");
        if (words.length > 500) throw new IllegalStateException("Unexpectedly long transcript.");
        return words;
    }
    private static int distance(String[] ref, String[] actual) {
        int[] previous = new int[actual.length + 1], current = new int[actual.length + 1];
        for (int i = 0; i <= actual.length; i++) previous[i] = i;
        for (int r = 1; r <= ref.length; r++) {
            current[0] = r;
            for (int a = 1; a <= actual.length; a++)
                current[a] = Math.min(Math.min(previous[a] + 1, current[a - 1] + 1),
                    previous[a - 1] + (ref[r - 1].equals(actual[a - 1]) ? 0 : 1));
            int[] swap = previous; previous = current; current = swap;
        }
        return previous[actual.length];
    }
    private void phase(String modelId, int row, String codec, String language, String stage) {
        Bundle status = new Bundle();
        status.putString("stream", "CAPY_RUSSIAN_PHASE=" + modelId + ":" + row + ":" + codec + ":" + language + ":" + stage + "\n");
        sendStatus(0, status);
    }
    private void observation(JSONObject record) {
        Bundle status = new Bundle();
        status.putString("stream", "CAPY_RUSSIAN_OBSERVATION_JSON=" + record.toString() + "\n");
        sendStatus(0, status);
    }
    private JSONObject recognize(File model, String modelId, JSONObject sample, String codec, String language) throws Exception {
        JSONObject encoded = sample.getJSONObject(codec);
        File audio = assetFile(encoded.getString("file"), encoded.getInt("bytes"), encoded.getString("sha256"));
        float[] pcm = null;
        try {
            phase(modelId, sample.getInt("row_index"), codec, language, "decode-start");
            pcm = AndroidPcmDecoder.decode(audio, () -> false);
            double expected = sample.getDouble("source_duration_seconds");
            if (pcm.length < 16000 || Math.abs(pcm.length / 16000.0 - expected) > 0.5)
                throw new IllegalStateException("Decoded duration differs.");
            boolean signal = false;
            for (float p : pcm) {
                if (Float.isNaN(p) || Float.isInfinite(p) || Math.abs(p) > 1.0f)
                    throw new IllegalStateException("Invalid decoded PCM.");
                signal |= Math.abs(p) > 0.01f;
            }
            if (!signal) throw new IllegalStateException("No decoded speech signal.");
            phase(modelId, sample.getInt("row_index"), codec, language, "native-start");
            long started = android.os.SystemClock.elapsedRealtime();
            String text;
            try (OfflineSpeech speech = new OfflineSpeech()) { text = speech.run(model, pcm, language); }
            long elapsed = android.os.SystemClock.elapsedRealtime() - started;
            String reference = sample.getString("reference");
            String[] refWords = words(reference), actualWords = words(text);
            if (refWords.length == 0) throw new IllegalStateException("Empty reference.");
            int errors = distance(refWords, actualWords);
            JSONObject record = new JSONObject();
            record.put("model_id", modelId); record.put("row_index", sample.getInt("row_index")); record.put("codec", codec);
            record.put("language_argument", language); record.put("reference", reference); record.put("transcript", text);
            record.put("reference_words", refWords.length); record.put("hypothesis_words", actualWords.length);
            record.put("word_edits", errors); record.put("word_error_rate", errors / (double)refWords.length);
            record.put("decoded_samples", pcm.length); record.put("inference_milliseconds", elapsed);
            record.put("real_time_factor", elapsed / (pcm.length / 16.0));
            return record;
        } finally { if (pcm != null) Arrays.fill(pcm, 0.0f); audio.delete(); }
    }
    @Override public void onStart() {
        Bundle report = new Bundle(); File model = null;
        try {
            byte[] raw = assetBytes("fixture-manifest.json", 100000);
            if (!sha(raw).equals(arguments.getString("fixture_manifest_sha"))) throw new IllegalStateException("Fixture manifest differs.");
            JSONObject manifest = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            Arrays.fill(raw, (byte)0);
            JSONArray samples = manifest.getJSONArray("samples");
            if (samples.length() != 5) throw new IllegalStateException("Expected the first five dataset rows.");
            byte[] choicesRaw = assetBytes("model-choices.json", 20000);
            if (!sha(choicesRaw).equals(arguments.getString("model_choices_sha")))
                throw new IllegalStateException("Model choices differ.");
            JSONObject choices = new JSONObject(new String(choicesRaw, StandardCharsets.UTF_8));
            Arrays.fill(choicesRaw, (byte)0);
            JSONArray models = choices.getJSONArray("models");
            if (models.length() != 2 || !"ru".equals(choices.getString("language")))
                throw new IllegalStateException("Expected exactly two preselected Russian model cases.");
            JSONArray records = new JSONArray(); JSONObject summaries = new JSONObject();
            for (int m = 0; m < models.length(); m++) {
                JSONObject choice = models.getJSONObject(m);
                String modelId = choice.getString("id");
                if (!modelId.equals(m == 0 ? "tiny" : "base_q5_1"))
                    throw new IllegalStateException("Model sequence differs.");
                model = assetFile(choice.getString("file"), choice.getInt("bytes"), choice.getString("sha256"));
                int totalWords = 0, totalEdits = 0; long totalMillis = 0;
                for (int i = 0; i < samples.length(); i++) {
                    JSONObject sample = samples.getJSONObject(i);
                    if (sample.getInt("row_index") != i)
                        throw new IllegalStateException("Dataset selection differs.");
                    JSONObject record = recognize(model, modelId, sample, "opus", "ru");
                    observation(record); records.put(record);
                    totalWords += record.getInt("reference_words"); totalEdits += record.getInt("word_edits");
                    totalMillis += record.getLong("inference_milliseconds");
                }
                JSONObject summary = new JSONObject();
                summary.put("sample_count", 5); summary.put("reference_words", totalWords);
                summary.put("word_edits", totalEdits); summary.put("word_error_rate", totalEdits / (double)totalWords);
                summary.put("inference_milliseconds_sum", totalMillis);
                summaries.put(modelId, summary);
                model.delete(); model = null;
            }
            JSONObject result = new JSONObject();
            result.put("technical_execution", "PASS"); result.put("observations", records);
            result.put("model_summaries", summaries);
            result.put("normalization", "Lowercase Unicode letters/digits; punctuation ignored; ё=е; no stemming or numeric-word rewriting.");
            result.put("test_helper_has_internet_permission", false); result.put("telegram_chat_ui_tested", false);
            result.put("physical_arm64_device", false); result.put("production_model_changed", false);
            result.put("language_argument", "ru"); result.put("general_russian_accuracy_proven", false);
            report.putString("stream", "CAPY_RUSSIAN_MODELS_RESULT_JSON=" + result.toString()
                + "\nCAPY_ANDROID_RUSSIAN_MODELS=TECHNICAL_PASS\n");
            finish(Activity.RESULT_OK, report);
        } catch (Throwable failure) {
            report.putString("stream", "CAPY_ANDROID_RUSSIAN_MODELS=FAIL\n" + android.util.Log.getStackTraceString(failure));
            finish(Activity.RESULT_CANCELED, report);
        } finally { if (model != null) model.delete(); }
    }
}
