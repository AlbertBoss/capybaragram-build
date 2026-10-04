// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/** Test-only APK: actual Android Opus/AAC decoding and JNI CPU recognition; no Internet permission. */
public final class AndroidSpeechDeviceInstrumentation extends Instrumentation {
    private int checks;
    private Bundle arguments;
    private interface Operation {void run() throws Exception;}
    private void require(boolean value){if(!value)throw new AssertionError("Speech check "+(checks+1)+" failed");checks++;}
    private void rejects(Class<? extends Exception> type,Operation action) throws Exception {
        try{action.run();}catch(Exception error){if(type.isInstance(error)){checks++;return;}throw error;}
        throw new AssertionError("Expected "+type.getSimpleName());
    }
    @Override public void onCreate(Bundle args){arguments=args;super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle report=new Bundle();
        try{exercise();report.putString("stream","CAPY_ANDROID_SPEECH=PASS checks="+checks+"\n");finish(Activity.RESULT_OK,report);}
        catch(Throwable failure){report.putString("stream","CAPY_ANDROID_SPEECH=FAIL\n"+android.util.Log.getStackTraceString(failure));finish(Activity.RESULT_CANCELED,report);}
    }
    private File asset(String name,String expected,long expectedSize) throws Exception {
        if(expected==null || !expected.matches("[a-f0-9]{64}"))throw new IOException("Expected asset digest unavailable.");
        File file=new File(getTargetContext().getFilesDir(),name);MessageDigest sha=MessageDigest.getInstance("SHA-256");long count=0;
        try(InputStream source=getTargetContext().getAssets().open(name);FileOutputStream out=new FileOutputStream(file)) {
            byte[] bytes=new byte[65536];int n;
            while((n=source.read(bytes))!=-1){count+=n;if(count>expectedSize)throw new IOException("Asset too large.");sha.update(bytes,0,n);out.write(bytes,0,n);}
            Arrays.fill(bytes,(byte)0);out.getFD().sync();
        }
        StringBuilder actual=new StringBuilder();for(byte b:sha.digest())actual.append(String.format(Locale.ROOT,"%02x",b&255));
        require(count==expectedSize && expected.contentEquals(actual));return file;
    }
    private void exercise() throws Exception {
        File model=null,opus=null,aac=null,bad=new File(getTargetContext().getFilesDir(),"bad-audio.bin");
        float[] pcm=null,stereo=null;
        try {
            model=asset("tiny.bin",arguments.getString("model_sha"),77691713L);
            opus=asset("speech.ogg",arguments.getString("opus_sha"),Long.parseLong(arguments.getString("opus_size")));
            aac=asset("speech.m4a",arguments.getString("aac_sha"),Long.parseLong(arguments.getString("aac_size")));
            pcm=AndroidPcmDecoder.decode(opus,()->false);
            require(pcm.length>16000*5 && pcm.length<16000*15);
            boolean signal=false,finite=true;for(float sample:pcm){finite&=!Float.isNaN(sample) && !Float.isInfinite(sample) && Math.abs(sample)<=1;signal|=Math.abs(sample)>.01f;}
            require(signal && finite);
            try(OfflineSpeech speech=new OfflineSpeech()) {
                String text=speech.run(model,pcm,"en").toLowerCase(Locale.ROOT);
                require(text.contains("country") && text.contains("ask"));
                File captured=model;float[] samples=pcm;
                rejects(IllegalStateException.class,()->speech.run(captured,samples,"en"));
            }
            stereo=AndroidPcmDecoder.decode(aac,()->false);
            require(stereo.length>16000*5 && stereo.length<16000*15);
            require(Math.abs(stereo.length-pcm.length)<16000);
            File capturedOpus=opus;
            rejects(IOException.class,()->AndroidPcmDecoder.decode(capturedOpus,()->true));
            AtomicBoolean rejectedMain=new AtomicBoolean();
            runOnMainSync(()->{try{AndroidPcmDecoder.decode(capturedOpus,()->false);}catch(IllegalStateException expected){rejectedMain.set(true);}catch(Exception other){throw new AssertionError(other);}});
            require(rejectedMain.get());
            try(FileOutputStream out=new FileOutputStream(bad)){out.write(new byte[]{1,2,3,4});}
            rejects(IOException.class,()->AndroidPcmDecoder.decode(bad,()->false));
            try(OfflineSpeech cancelled=new OfflineSpeech()) {
                cancelled.cancel();require(cancelled.cancelled());File captured=model;float[] samples=pcm;
                rejects(IllegalStateException.class,()->cancelled.run(captured,samples,"en"));
            }
        }finally{
            if(pcm!=null)Arrays.fill(pcm,0);if(stereo!=null)Arrays.fill(stereo,0);
            if(model!=null)model.delete();if(opus!=null)opus.delete();if(aac!=null)aac.delete();bad.delete();
        }
    }
}
