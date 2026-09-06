# SPDX-License-Identifier: MIT
"""Draft native read-mode integration, applied after notes and folder callback patches."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
JAVA='TMessagesProj/src/main/java/'
CONNECTIONS=JAVA+'org/telegram/tgnet/ConnectionsManager.java'
CONTROLLER=JAVA+'org/telegram/messenger/MessagesController.java'
CONFIG=JAVA+'org/telegram/messenger/UserConfig.java'
CHAT=JAVA+'org/telegram/ui/ChatActivity.java'
VAULT=JAVA+'org/capybaragram/telegram/CapyVault.java'
FILES=[CONNECTIONS,CONTROLLER,CONFIG,CHAT,VAULT]
BRIDGE='org.capybaragram.readmode.CapyReadReceipts'
UI='org.capybaragram.readmode.CapyReadModeUi'
ADDED={JAVA+'org/capybaragram/readmode/'+n:ROOT/n for n in ['ReadReceiptPolicy.java','CapyReadReceipts.java','CapyReadModeUi.java','CapyReadRequest.java']}
ADDED.update({'TMessagesProj/src/main/res/values/capy_read_mode.xml':ROOT/'strings.xml',
              'TMessagesProj/src/main/res/values-ru/capy_read_mode.xml':ROOT/'strings-ru.xml'})

def replace(text,old,new,count=1):
    if text.count(old)!=count: raise ValueError('Read-mode anchor differs')
    return text.replace(old,new)

def transform(name,text):
    if name==CONNECTIONS:
        text=replace(text,'        final int requestToken = lastRequestToken.getAndIncrement();\n',
          '        final int requestToken = lastRequestToken.getAndIncrement();\n'
          f'        final {BRIDGE}.CapturedRead capyRead = {BRIDGE}.capture(currentAccount, object, false);\n',2)
        for callback in ['null','onCompleteTimestamp']:
            old=f'sendRequestInternal(object, onComplete, {callback}, onQuickAck, onWriteToSocket, flags, datacenterId, connectionType, immediate, requestToken);'
            text=replace(text,old,old[:-2]+', capyRead);')
        old='    private void sendRequestInternal(TLObject object, RequestDelegate onComplete, RequestDelegateTimestamp onCompleteTimestamp, QuickAckDelegate onQuickAck, WriteToSocketDelegate onWriteToSocket, int flags, int datacenterId, int connectionType, boolean immediate, int requestToken) {\n'
        new=f'''    public int sendRequestWithExplicitRead(TLObject object, RequestDelegate onComplete, long expectedOwner) {{
        final int requestToken = lastRequestToken.getAndIncrement();
        final {BRIDGE}.CapturedRead capyRead = {BRIDGE}.capture(currentAccount, object, true);
        Utilities.stageQueue.postRunnable(() -> {{
            if (expectedOwner == 0 || getUserConfig().getClientUserId() != expectedOwner) {{
                TLRPC.TL_error error = new TLRPC.TL_error();
                error.code = -2000;
                error.text = "CAPY_ACCOUNT_CHANGED";
                try {{ if (onComplete != null) onComplete.run(null, error); }} finally {{ object.freeResources(); }}
                return;
            }}
            sendRequestInternal(object, onComplete, null, null, null, 0, DEFAULT_DATACENTER_ID, ConnectionTypeGeneric, true, requestToken, capyRead);
        }});
        return requestToken;
    }}

    private void sendRequestInternal(TLObject object, RequestDelegate onComplete, RequestDelegateTimestamp onCompleteTimestamp, QuickAckDelegate onQuickAck, WriteToSocketDelegate onWriteToSocket, int flags, int datacenterId, int connectionType, boolean immediate, int requestToken, {BRIDGE}.CapturedRead capyRead) {{
        if (capyRead != null && !{BRIDGE}.consume(currentAccount, object, capyRead)) {{
            // Complete locally with an error, never forge a server success/pts update.
            TLRPC.TL_error error = new TLRPC.TL_error();
            error.code = -2000;
            error.text = "CAPY_READ_RECEIPT_SUPPRESSED";
            object.freeResources();
            Utilities.stageQueue.postRunnable(() -> {{
                try {{
                    if (onComplete != null) onComplete.run(null, error);
                    else if (onCompleteTimestamp != null) onCompleteTimestamp.run(null, error, 0);
                }} catch (Exception e) {{ FileLog.e(e); }}
            }});
            return;
        }}
'''
        return replace(text,old,new)
    if name==CONTROLLER:
        old='    public void markDialogAsRead(long dialogId, int maxPositiveId, int maxNegativeId, int maxDate, boolean popup, long threadId, int countDiff, boolean readNow, int scheduledCount) {\n'
        text=replace(text,old,old+f'        final boolean capySilentRead = {BRIDGE}.isSilent(currentAccount);\n')
        start=text.index(old);end=text.index('\n    public void fetchCommunityPendingJoinRequests',start)
        section=replace(text[start:end],'        if (createReadTask) {\n','        if (createReadTask && !capySilentRead) {\n')
        text=text[:start]+section+text[end:]
        old='        getSecretChatHelper().sendMessagesReadMessage(chat, randomIds, null);'
        return replace(text,old,f'        if (!{BRIDGE}.isSilent(currentAccount)) {{\n'+old+'\n        }')
    if name==CONFIG:
        text=replace(text,'    public long clientUserId;','    public volatile long clientUserId;')
        old='        org.capybaragram.telegram.CapyVault.beforeLogout(currentAccount);\n'
        text=replace(text,old,old+f'        {BRIDGE}.beforeLogout(currentAccount);\n')
        old='            org.capybaragram.telegram.CapyVault.ownerChanged(currentAccount, oldUser == null ? 0 : oldUser.id, user.id);\n'
        return replace(text,old,old+f'            {BRIDGE}.ownerChanged(currentAccount, oldUser == null ? 0 : oldUser.id, user.id);\n')
    if name==VAULT:
        old='        AndroidUtilities.runOnUIThread(CapyNotesUi::closeAll);\n'
        text=replace(text,old,old+f'        AndroidUtilities.runOnUIThread({UI}::closeAll);\n',2)
        old='        CapyNotesUi.closeAll();\n'
        return replace(text,old,old+f'        {UI}.closeAll();\n')
    if name==CHAT:
        for method in ['onPause','onFragmentDestroy']:
            old='    public void '+method+'() {\n'
            text=replace(text,old,old+f'        {UI}.closeFor(this);\n')
        old='            public void onItemClick(final int id) {\n'
        text=replace(text,old,old+'                if (id == 9003) { showCapyReadMode(); return; }\n')
        old='            if (Build.VERSION.SDK_INT >= 23 && currentEncryptedChat == null && !inPreviewMode) {\n'
        text=replace(text,old,'''            if (!inPreviewMode && chatMode == 0) {
                headerItem.addSubItem(9003, R.drawable.msg_edit, LocaleController.getString(R.string.CapyReadMode));
            }
'''+old)
        old='    @Override\n    public View createView(Context context) {'
        method='''    private void showCapyReadMode() {
        if (inPreviewMode || chatMode != 0 || dialog_id == 0 || (currentUser == null && currentChat == null)) return;
        final int expectedAccount = currentAccount;
        final long expectedDialog = dialog_id;
        final long expectedThread = threadMessageId;
        final long expectedOwner = getUserConfig().getClientUserId();
        final org.capybaragram.readmode.CapyReadReceipts.SessionIdentity identity =
                org.capybaragram.readmode.CapyReadReceipts.captureSession(expectedAccount);
        if (identity == null) return;
        final org.capybaragram.readmode.CapyReadModeUi.Current location =
                () -> isLastFragment() && !paused && currentAccount == expectedAccount
                        && dialog_id == expectedDialog && threadMessageId == expectedThread && chatMode == 0;
        final org.telegram.tgnet.TLObject request = org.capybaragram.readmode.CapyReadRequest.create(
                getMessagesController(), expectedDialog, expectedThread, getMessagesStorage().isMonoForum(expectedDialog),
                currentEncryptedChat, minMessageId[0], maxDate[0]);
        final org.capybaragram.readmode.CapyReadModeUi.ReadAction action = request == null ? null : completion -> {
            if (!location.matches() || !org.capybaragram.readmode.CapyReadReceipts.isCurrent(identity)) return;
            final int token = getConnectionsManager().sendRequestWithExplicitRead(request, (response, error) -> {
                if (!org.capybaragram.readmode.CapyReadReceipts.isCurrent(identity)) return;
                final boolean accepted = org.capybaragram.readmode.CapyReadRequest.accepted(request, response, error);
                if (accepted && response instanceof TLRPC.TL_messages_affectedMessages) {
                    TLRPC.TL_messages_affectedMessages affected = (TLRPC.TL_messages_affectedMessages) response;
                    MessagesController.getInstance(expectedAccount).processNewDifferenceParams(-1, affected.pts, -1, affected.pts_count);
                }
                completion.finish(accepted);
            }, expectedOwner);
            getConnectionsManager().bindRequestToGuid(token, classGuid);
        };
        final String recipient = currentChat != null ? currentChat.title : UserObject.getUserName(currentUser);
        org.capybaragram.readmode.CapyReadModeUi.show(this, expectedAccount, recipient, location, action);
    }

'''
        return replace(text,old,method+old)
    raise ValueError('Unexpected target')

def digest(data): return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
def plan(source,check=False):
    source=Path(source).resolve(strict=True)
    manifest=json.loads((ROOT/'android-read-mode-hashes.json').read_text())
    if set(manifest['pre'])!=set(FILES) or set(manifest['post'])!=set(FILES) or set(manifest['added'])!=set(ADDED): raise ValueError('Allowlist differs')
    result={}
    for name in FILES:
        path=source/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source): raise ValueError('Unsafe source path')
        data=path.read_bytes().replace(b'\r\n',b'\n')
        if digest(data)!=manifest['post' if check else 'pre'][name]: raise ValueError('Wrong input bytes: '+name)
        out=data if check else transform(name,data.decode('utf-8')).encode('utf-8')
        if digest(out)!=manifest['post'][name]: raise ValueError('Wrong output bytes')
        result[name]=out
    for name,path in ADDED.items():
        data=path.read_bytes()
        if digest(data)!=manifest['added'][name]: raise ValueError('Added source changed')
        target=source/name
        if target.is_symlink() or not target.resolve().is_relative_to(source): raise ValueError('Unsafe added path')
        if check:
            if not target.exists() or digest(target.read_bytes())!=digest(data): raise ValueError('Added source differs')
        elif target.exists(): raise ValueError('Added file already exists')
        result[name]=data
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    if head!='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c': raise ValueError('Wrong source revision')
    changes=plan(a.source,a.check)
    if not a.check:
        for name,data in changes.items():
            target=a.source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    print('PASS: Android read-mode integration', 'verified' if a.check else 'prepared')
