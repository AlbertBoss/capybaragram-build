// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.util.Arrays;

/** Size-checked source; decrypt only bytes actually read, never stale buffer tails. */
public final class VerifiedMediaInput extends InputStream {
    public interface Decryptor { void apply(byte[] data,byte[] key,byte[] iv,int start,int count,int offset); }
    private final FileInputStream input;
    private final byte[] key,iv;
    private final Decryptor decryptor;
    private final long size;
    private int offset;
    private boolean closed;
    private VerifiedMediaInput(FileInputStream input,long size,byte[] key,byte[] iv,Decryptor decryptor) {
        this.input=input; this.size=size; this.key=key; this.iv=iv; this.decryptor=decryptor;
    }
    public static VerifiedMediaInput open(File file,long expected,File keyFile,Decryptor decryptor) throws IOException {
        if(expected<=0 || expected>AndroidArchiveStore.MAX_ORIGINAL_BYTES) throw new IOException("Unsupported original size.");
        byte[] key=null,iv=null;
        FileInputStream input=null;
        try {
            if(keyFile!=null) {
                if(decryptor==null)throw new IOException("Cache decryption unavailable.");
                key=new byte[32];iv=new byte[16];
                try(RandomAccessFile secret=new RandomAccessFile(keyFile,"r")) {
                    if(secret.length()!=48)throw new IOException("Cache key invalid.");
                    secret.readFully(key);secret.readFully(iv);
                }
            }
            input=new FileInputStream(file);
            if(input.getChannel().size()!=expected)throw new IOException("Original incomplete.");
            return new VerifiedMediaInput(input,expected,key,iv,decryptor);
        } catch(IOException|RuntimeException error) {
            if(input!=null)input.close();
            if(key!=null)Arrays.fill(key,(byte)0);
            if(iv!=null)Arrays.fill(iv,(byte)0);
            throw error;
        }
    }
    @Override public int read(byte[] buffer,int start,int count) throws IOException {
        if(closed)throw new IOException("Original source closed.");
        if(buffer==null)throw new NullPointerException();
        if(start<0 || count<0 || count>buffer.length-start)throw new IndexOutOfBoundsException();
        if(count==0)return 0;
        if(offset==size) {
            if(input.read()!=-1)throw new IOException("Original source grew.");
            return -1;
        }
        int result=input.read(buffer,start,(int)Math.min(count,size-offset));
        if(result<=0)throw new IOException("Original source truncated.");
        if(key!=null)decryptor.apply(buffer,key,iv,start,result,offset);
        offset+=result;return result;
    }
    @Override public int read() throws IOException {
        byte[] one=new byte[1];
        try{return read(one,0,1)<0?-1:one[0]&255;}
        finally{Arrays.fill(one,(byte)0);}
    }
    @Override public void close() throws IOException {
        if(closed)return;closed=true;
        try{input.close();}finally{
            if(key!=null)Arrays.fill(key,(byte)0);
            if(iv!=null)Arrays.fill(iv,(byte)0);
        }
    }
}
