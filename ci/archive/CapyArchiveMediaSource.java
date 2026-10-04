// SPDX-License-Identifier: MIT
package org.capybaragram.archive;

import org.telegram.messenger.FileLoader;
import org.telegram.messenger.MessageObject;
import org.telegram.messenger.Utilities;
import org.telegram.tgnet.TLObject;
import org.telegram.tgnet.TLRPC;
import java.io.File;
import java.io.IOException;

/** Resolve a full attachment for this account, never choose a downloaded thumbnail. */
public final class CapyArchiveMediaSource implements AutoCloseable {
    public final VerifiedMediaInput input;
    public final long size;
    public final String mime;
    private CapyArchiveMediaSource(VerifiedMediaInput input,long size,String mime) {
        this.input=input;this.size=size;this.mime=mime;
    }
    public static CapyArchiveMediaSource open(int account,TLRPC.Message message) throws Exception {
        TLRPC.MessageMedia media=MessageObject.getMedia(message);
        if(media==null)return null;
        TLObject attachment; long size; String mime; int type,dc; long document;
        boolean cache=media.ttl_seconds!=0;
        if(media instanceof TLRPC.TL_messageMediaDocument && media.document!=null) {
            TLRPC.Document d=media.document;attachment=d;size=d.size;mime=d.mime_type;
            cache|=d.key!=null;document=d.id;dc=d.dc_id;
            type=MessageObject.isVoiceDocument(d)?FileLoader.MEDIA_DIR_AUDIO:
                    MessageObject.isVideoDocument(d)?FileLoader.MEDIA_DIR_VIDEO:FileLoader.MEDIA_DIR_DOCUMENT;
        } else if(media instanceof TLRPC.TL_messageMediaPhoto && media.photo!=null) {
            TLRPC.PhotoSize largest=null;
            for(TLRPC.PhotoSize p:media.photo.sizes) {
                if(p==null || p instanceof TLRPC.TL_photoSizeEmpty || p instanceof TLRPC.TL_photoStrippedSize
                        || p instanceof TLRPC.TL_photoPathSize || p instanceof TLRPC.TL_photoCachedSize
                        || p.location==null || p.size<=0 || p.w<=0 || p.h<=0)continue;
                if(largest==null || (long)p.w*p.h>(long)largest.w*largest.h
                        || ((long)p.w*p.h==(long)largest.w*largest.h && p.size>largest.size))largest=p;
            }
            if(largest==null)return null;
            attachment=largest;size=largest.size;mime="image/jpeg";type=FileLoader.MEDIA_DIR_IMAGE;
            cache|=largest.location.key!=null;document=largest.location.volume_id;
            dc=largest.location.dc_id+(largest.location.local_id<<16);
        } else return null;
        if(size<=0 || size>AndroidArchiveStore.MAX_ORIGINAL_BYTES)return null;
        if(mime==null || !mime.matches("[a-zA-Z][a-zA-Z0-9.+-]*/[a-zA-Z0-9][a-zA-Z0-9.+-]*"))mime="application/octet-stream";
        FileLoader loader=FileLoader.getInstance(account);
        // getPathToAttach(false) in this upstream consults selectedAccount. Resolve our own DB explicitly.
        if(!cache) {
            String path=loader.getFileDatabase().getPath(document,dc,type,true);
            if(path!=null) {
                CapyArchiveMediaSource result=at(new File(path),size,mime);
                if(result!=null)return result;
            }
            File directory=FileLoader.getDirectory(type);
            if(directory!=null) {
                CapyArchiveMediaSource result=at(new File(directory,FileLoader.getAttachFileName(attachment)),size,mime);
                if(result!=null)return result;
            }
        }
        return at(loader.getPathToAttach(attachment,null,true,true),size,mime);
    }
    private static boolean allowed(File file) throws IOException {
        File actual=file.getCanonicalFile();
        for(int type:new int[]{FileLoader.MEDIA_DIR_CACHE,FileLoader.MEDIA_DIR_IMAGE,FileLoader.MEDIA_DIR_AUDIO,
                FileLoader.MEDIA_DIR_VIDEO,FileLoader.MEDIA_DIR_DOCUMENT}) {
            File dir=FileLoader.getDirectory(type);
            if(dir!=null && actual.getPath().startsWith(dir.getCanonicalPath()+File.separator))return true;
        }
        return false;
    }
    private static CapyArchiveMediaSource at(File file,long size,String mime) throws IOException {
        if(file==null || !allowed(file))return null;
        if(file.isFile() && file.length()==size)
            return new CapyArchiveMediaSource(VerifiedMediaInput.open(file,size,null,null),size,mime);
        File encrypted=new File(file.getPath()+".enc");
        if(!encrypted.isFile() || encrypted.length()!=size || !allowed(encrypted))return null;
        File key=new File(FileLoader.getInternalCacheDir(),file.getName()+".enc.key");
        if(!key.isFile() || !key.getCanonicalPath().startsWith(FileLoader.getInternalCacheDir().getCanonicalPath()+File.separator))return null;
        return new CapyArchiveMediaSource(VerifiedMediaInput.open(encrypted,size,key,
                Utilities::aesCtrDecryptionByteArray),size,mime);
    }
    @Override public void close() throws IOException {input.close();}
}
