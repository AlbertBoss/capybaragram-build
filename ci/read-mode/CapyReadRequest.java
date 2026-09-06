// SPDX-License-Identifier: MIT
package org.capybaragram.readmode;

import org.telegram.messenger.MessagesController;
import org.telegram.messenger.DialogObject;
import org.telegram.tgnet.TLObject;
import org.telegram.tgnet.TLRPC;

/** Builds one explicit read request for a snapshot of the opened chat, never a global override. */
public final class CapyReadRequest {
    private CapyReadRequest() {}
    public static TLObject create(MessagesController controller, long dialogId, long threadId,
            boolean monoForum, TLRPC.EncryptedChat secret, int latestId, int latestDate) {
        if (dialogId==0 || dialogId==Long.MIN_VALUE) return null;
        if (DialogObject.isEncryptedDialog(dialogId) && secret==null) return null;
        if (secret!=null && (!DialogObject.isEncryptedDialog(dialogId)
                || DialogObject.getEncryptedChatId(dialogId)!=secret.id)) return null;
        if (secret!=null) {
            if (!(secret instanceof TLRPC.TL_encryptedChat) || secret.auth_key==null || secret.auth_key.length<=1
                    || latestDate<=0 || latestDate==Integer.MAX_VALUE) return null;
            TLRPC.TL_messages_readEncryptedHistory request=new TLRPC.TL_messages_readEncryptedHistory();
            request.peer=new TLRPC.TL_inputEncryptedChat();
            request.peer.chat_id=secret.id;
            request.peer.access_hash=secret.access_hash;
            request.max_date=latestDate;
            return request;
        }
        if (latestId<=0 || latestId==Integer.MAX_VALUE) return null;
        TLRPC.InputPeer peer=controller.getInputPeer(dialogId);
        if (peer==null || peer instanceof TLRPC.TL_inputPeerEmpty) return null;
        if (monoForum && threadId!=0) {
            TLRPC.InputPeer topicPeer=controller.getInputPeer(threadId);
            if (topicPeer==null || topicPeer instanceof TLRPC.TL_inputPeerEmpty) return null;
            TLRPC.TL_messages_readSavedHistory request=new TLRPC.TL_messages_readSavedHistory();
            request.parent_peer=peer; request.peer=topicPeer; request.max_id=latestId;
            return request;
        }
        if (threadId!=0) {
            if (threadId<0 || threadId>Integer.MAX_VALUE) return null;
            TLRPC.TL_messages_readDiscussion request=new TLRPC.TL_messages_readDiscussion();
            request.peer=peer; request.msg_id=(int)threadId; request.read_max_id=latestId;
            return request;
        }
        if (peer instanceof TLRPC.TL_inputPeerChannel) {
            TLRPC.InputChannel channel=MessagesController.getInputChannel(peer);
            if (channel==null) return null;
            TLRPC.TL_channels_readHistory request=new TLRPC.TL_channels_readHistory();
            request.channel=channel; request.max_id=latestId;
            return request;
        }
        TLRPC.TL_messages_readHistory request=new TLRPC.TL_messages_readHistory();
        request.peer=peer; request.max_id=latestId;
        return request;
    }

    public static boolean accepted(TLObject request, TLObject response, TLRPC.TL_error error) {
        if (error!=null) return false;
        if (request instanceof TLRPC.TL_messages_readHistory) return response instanceof TLRPC.TL_messages_affectedMessages;
        return (request instanceof TLRPC.TL_channels_readHistory
                || request instanceof TLRPC.TL_messages_readDiscussion
                || request instanceof TLRPC.TL_messages_readEncryptedHistory
                || request instanceof TLRPC.TL_messages_readSavedHistory)
                && response instanceof TLRPC.TL_boolTrue;
    }
}
