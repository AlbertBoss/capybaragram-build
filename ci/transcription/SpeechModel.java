// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import android.content.Context;
import android.os.Looper;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.UUID;

/** Only a hash-pinned multilingual model is accepted; no audio upload. */
public final class SpeechModel {
    private static final long SIZE=77691713L;
    private static final String SHA="be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21";
    private static final String URL_TEXT="https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.bin";
    private SpeechModel(){}
    public interface Status { boolean cancelled(); void progress(long received,long total); }
    private static void worker(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Model needs worker.");}
    private static String hex(byte[] bytes){
        StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
    public static boolean verified(File file) throws Exception {
        worker();if(!file.isFile()||file.length()!=SIZE)return false;
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[65536];
        try(InputStream input=new FileInputStream(file)){for(int n;(n=input.read(buffer))!=-1;)digest.update(buffer,0,n);}
        return SHA.equals(hex(digest.digest()));
    }
    public static File existing(Context context) throws Exception {
        worker();File model=new File(new File(context.getNoBackupFilesDir(),"capy-speech"),"tiny.bin");
        return verified(model)?model:null;
    }
    /** Explicit user-requested download. Single serialized speech worker only. */
    public static File download(Context context,Status status) throws Exception {
        worker();File dir=new File(context.getNoBackupFilesDir(),"capy-speech");
        if(!dir.isDirectory()&&!dir.mkdirs())throw new IOException("Model directory unavailable.");
        File target=new File(dir,"tiny.bin");if(verified(target))return target;
        File temp=new File(dir,UUID.randomUUID()+".part");
        HttpURLConnection connection=null;
        try {
            URL url=new URL(URL_TEXT);
            for(int i=0;;i++) {
                if(status.cancelled())throw new IOException("Model download cancelled.");
                if(!"https".equals(url.getProtocol())||url.getUserInfo()!=null||i>6)throw new IOException("Invalid model redirect.");
                connection=(HttpURLConnection)url.openConnection();connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(20000);connection.setReadTimeout(20000);connection.setUseCaches(false);
                int code=connection.getResponseCode();
                if(code==301||code==302||code==303||code==307||code==308) {
                    String next=connection.getHeaderField("Location");if(next==null)throw new IOException("Missing model redirect.");
                    URL nextUrl=new URL(url,next);connection.disconnect();connection=null;url=nextUrl;continue;
                }
                if(code!=200)throw new IOException("Model download unavailable.");break;
            }
            long count=0;byte[] buffer=new byte[65536];
            try(InputStream input=connection.getInputStream();FileOutputStream output=new FileOutputStream(temp)){
                for(int n;(n=input.read(buffer))!=-1;) {
                    if(status.cancelled()||count+n>SIZE)throw new IOException("Model download cancelled or exceeds limit.");
                    output.write(buffer,0,n);count+=n;status.progress(count,SIZE);
                }
                output.getFD().sync();
            }
            if(count!=SIZE||!verified(temp))throw new IOException("Model integrity check failed.");
            if(status.cancelled())throw new IOException("Model download cancelled.");
            // A failed replacement preserves the previous file; never return unverified data.
            if(!temp.renameTo(target))throw new IOException("Model could not be installed.");
            return target;
        } finally {if(connection!=null)connection.disconnect();if(temp.exists()&&!temp.delete())temp.deleteOnExit();}
    }
}
