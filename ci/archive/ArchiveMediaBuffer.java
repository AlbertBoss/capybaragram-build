// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import android.media.MediaDataSource;
import java.io.IOException;
import java.io.OutputStream;
import java.util.Arrays;

/** Exact bounded private memory; no plaintext media files or external intents. */
public final class ArchiveMediaBuffer extends OutputStream {
    private byte[] bytes;
    private int written;
    public final AndroidArchiveStore.Original original;
    public ArchiveMediaBuffer(AndroidArchiveStore.Original original) {
        if(original==null || original.size<=0 || original.size>AndroidArchiveStore.MAX_ORIGINAL_BYTES)
            throw new IllegalArgumentException("Invalid original buffer.");
        this.original=original;bytes=new byte[(int)original.size];
    }
    @Override public synchronized void write(int value) throws IOException {
        if(bytes==null || written==bytes.length)throw new IOException("Original buffer full.");
        bytes[written++]=(byte)value;
    }
    @Override public synchronized void write(byte[] data,int start,int count) throws IOException {
        if(bytes==null || start<0 || count<0 || count>data.length-start || count>bytes.length-written)
            throw new IOException("Original buffer full.");
        System.arraycopy(data,start,bytes,written,count);written+=count;
    }
    public synchronized android.graphics.Bitmap image() throws IOException {
        if(bytes==null || written!=bytes.length)throw new IOException("Original buffer incomplete.");
        android.graphics.BitmapFactory.Options opts=new android.graphics.BitmapFactory.Options();
        opts.inJustDecodeBounds=true;android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);
        if(opts.outWidth<=0 || opts.outHeight<=0)throw new IOException("Unsupported image.");
        opts.inJustDecodeBounds=false;opts.inSampleSize=1;
        while((long)(opts.outWidth/opts.inSampleSize)*(opts.outHeight/opts.inSampleSize)>2_000_000L)
            opts.inSampleSize*=2;
        android.graphics.Bitmap bitmap=android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);
        if(bitmap==null)throw new IOException("Unsupported image.");
        return bitmap;
    }
    public MediaDataSource source() {
        return new MediaDataSource() {
            @Override public int readAt(long position,byte[] out,int offset,int count) throws IOException {
                synchronized(ArchiveMediaBuffer.this) {
                    if(bytes==null || written!=bytes.length)throw new IOException("Original buffer closed.");
                    if(position<0 || offset<0 || count<0 || count>out.length-offset)throw new IOException("Invalid read.");
                    if(count==0)return 0;if(position>=bytes.length)return -1;
                    int n=(int)Math.min(count,bytes.length-position);System.arraycopy(bytes,(int)position,out,offset,n);return n;
                }
            }
            @Override public long getSize() throws IOException {
                synchronized(ArchiveMediaBuffer.this) {
                    if(bytes==null || written!=bytes.length)throw new IOException("Original buffer closed.");
                    return bytes.length;
                }
            }
            @Override public void close() {ArchiveMediaBuffer.this.close();}
        };
    }
    @Override public synchronized void close() {
        if(bytes!=null)Arrays.fill(bytes,(byte)0);bytes=null;written=0;
    }
}
