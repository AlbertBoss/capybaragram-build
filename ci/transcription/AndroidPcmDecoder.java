// SPDX-License-Identifier: MIT
package org.capybaragram.voice;

import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.Looper;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** Decodes downloaded local audio; never marks a Telegram message as listened. */
public final class AndroidPcmDecoder {
    private static final int RATE=16000,MAX_SAMPLES=RATE*180;
    private AndroidPcmDecoder(){}
    public interface Cancel { boolean cancelled(); }
    public static float[] decode(File audio,Cancel cancel) throws Exception {
        if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Audio needs worker.");
        if(!audio.isFile()||audio.length()<=0||audio.length()>32L*1048576)throw new IOException("Local audio unavailable or too large.");
        MediaExtractor extractor=new MediaExtractor();MediaCodec codec=null;
        float[] pcm=new float[MAX_SAMPLES];int count=0;
        try(FileInputStream input=new FileInputStream(audio)) {
            extractor.setDataSource(input.getFD());MediaFormat selected=null;
            for(int i=0;i<extractor.getTrackCount();i++) {
                MediaFormat f=extractor.getTrackFormat(i);String mime=f.getString(MediaFormat.KEY_MIME);
                if(mime!=null&&mime.startsWith("audio/")){extractor.selectTrack(i);selected=f;break;}
            }
            if(selected==null)throw new IOException("No supported audio track.");
            if(selected.containsKey(MediaFormat.KEY_DURATION)&&selected.getLong(MediaFormat.KEY_DURATION)>180000000L)
                throw new IOException("Audio exceeds three minutes.");
            codec=MediaCodec.createDecoderByType(selected.getString(MediaFormat.KEY_MIME));
            codec.configure(selected,null,null,0);codec.start();
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();boolean inputDone=false,outputDone=false;
            int rate=0,channels=0,encoding=AudioFormat.ENCODING_PCM_16BIT;
            long frames=0;double next=0;float previous=0;long deadline=System.nanoTime()+120000000000L;
            while(!outputDone) {
                if(cancel.cancelled()||System.nanoTime()>deadline)throw new IOException("Audio decode cancelled or timed out.");
                if(!inputDone) {
                    int index=codec.dequeueInputBuffer(10000);
                    if(index>=0){ByteBuffer b=codec.getInputBuffer(index);if(b==null)throw new IOException("Decoder input unavailable.");
                        int size=extractor.readSampleData(b,0);
                        if(size<0){codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);inputDone=true;}
                        else{codec.queueInputBuffer(index,0,size,extractor.getSampleTime(),0);extractor.advance();}
                    }
                }
                int index=codec.dequeueOutputBuffer(info,10000);
                if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat f=codec.getOutputFormat();int updatedRate=f.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    int updatedChannels=f.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    int updatedEncoding=f.containsKey("pcm-encoding")?f.getInteger("pcm-encoding"):AudioFormat.ENCODING_PCM_16BIT;
                    if(updatedRate<8000||updatedRate>48000||updatedChannels<1||updatedChannels>2
                            ||(updatedEncoding!=AudioFormat.ENCODING_PCM_16BIT&&updatedEncoding!=AudioFormat.ENCODING_PCM_FLOAT)
                            ||(frames>0&&(rate!=updatedRate||channels!=updatedChannels||encoding!=updatedEncoding)))
                        throw new IOException("Unsupported decoder format.");
                    rate=updatedRate;channels=updatedChannels;encoding=updatedEncoding;
                } else if(index>=0) {
                    try {
                        ByteBuffer b=codec.getOutputBuffer(index);
                        if(info.size>0) {
                            if(b==null||rate==0||channels==0||info.offset<0||info.size>b.capacity()-info.offset)
                                throw new IOException("Invalid decoded audio.");
                            b.position(info.offset);b.limit(info.offset+info.size);b.order(ByteOrder.LITTLE_ENDIAN);
                            int frameBytes=channels*(encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2);
                            if(info.size%frameBytes!=0)throw new IOException("Partial audio frame.");
                            while(b.remaining()>=frameBytes) {
                                float mono=0;
                                for(int c=0;c<channels;c++)mono+=encoding==AudioFormat.ENCODING_PCM_FLOAT?b.getFloat():b.getShort()/32768.0f;
                                mono/=channels;
                                if(Float.isNaN(mono)||Float.isInfinite(mono))throw new IOException("Invalid decoded sample.");
                                mono=Math.max(-1f,Math.min(1f,mono));if(frames==0)previous=mono;
                                while(next<=frames) {
                                    if(count==MAX_SAMPLES)throw new IOException("Audio exceeds three minutes.");
                                    pcm[count++]=frames==0?mono:previous+(mono-previous)*(float)(next-(frames-1));
                                    next+=(double)rate/RATE;
                                }
                                previous=mono;frames++;
                                if(frames>(long)rate*180)throw new IOException("Audio exceeds three minutes.");
                            }
                        }
                        outputDone=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    } finally {codec.releaseOutputBuffer(index,false);}
                }
            }
            if(count==0)throw new IOException("Empty audio.");
            return Arrays.copyOf(pcm,count);
        } finally {
            Arrays.fill(pcm,0f);extractor.release();
            if(codec!=null){try{codec.stop();}finally{codec.release();}}
        }
    }
}
