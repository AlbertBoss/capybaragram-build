// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;

/** Worker-owned, one-use job. Host must gate callbacks by account/session/lock. */
public final class OfflineSpeech implements AutoCloseable {
    static { System.loadLibrary("capy_voice_jni"); }
    private final AtomicBoolean cancelled=new AtomicBoolean();
    private long handle;
    private boolean used;
    public boolean cancelled(){ return cancelled.get(); }
    public synchronized void cancel(){ cancelled.set(true); if(handle!=0)nativeCancel(handle); }
    public synchronized int progress(){ return handle==0?0:nativeProgress(handle); }
    public String run(File verifiedModel,float[] mono16k,String language) {
        synchronized(this){ if(used)throw new IllegalStateException("Speech job already used.");used=true; }
        if(cancelled())throw new IllegalStateException("Speech job cancelled.");
        long opened=nativeOpen(verifiedModel.getAbsolutePath());
        synchronized(this){handle=opened;if(cancelled() && handle!=0)nativeCancel(handle);}
        byte[] result=null;
        try {
            if(opened==0 || cancelled())throw new IllegalStateException("Speech job unavailable.");
            result=nativeRun(opened,mono16k,language,Math.max(1,Math.min(2,Runtime.getRuntime().availableProcessors())));
            if(result==null || cancelled())throw new IllegalStateException("Speech job cancelled.");
            return new String(result,StandardCharsets.UTF_8).trim();
        } finally {
            if(result!=null)Arrays.fill(result,(byte)0);
            synchronized(this){if(handle!=0){nativeClose(handle);handle=0;}}
        }
    }
    /** Caller must close only after the worker returns; cancel() is the UI operation. */
    @Override public synchronized void close(){ if(handle!=0)throw new IllegalStateException("Speech worker still running."); }
    private static native long nativeOpen(String verifiedModelPath);
    private static native byte[] nativeRun(long handle,float[] pcm,String language,int threads);
    private static native void nativeCancel(long handle);
    private static native int nativeProgress(long handle);
    private static native void nativeClose(long handle);
}
