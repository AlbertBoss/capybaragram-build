# SPDX-License-Identifier: MIT
"""Classify encrypted service read receipts before encryption and stage queue."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
HOST = 'TMessagesProj/src/main/java/org/telegram/messenger/SecretChatHelper.java'
BRIDGE = 'org.capybaragram.readmode.CapyReadReceipts'


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Secret read-mode anchor differs: ' + old[:90])
    return text.replace(old, new)


def transform(text):
    old = '    public void sendMessagesReadMessage(TLRPC.EncryptedChat encryptedChat, ArrayList<Long> random_ids, TLRPC.Message resendMessage) {\n'
    text = once(text, old, old + f'        if ({BRIDGE}.isSilent(currentAccount)) return;\n')
    old = '''    protected void performSendEncryptedRequest(TLRPC.DecryptedMessage req, TLRPC.Message newMsgObj, TLRPC.EncryptedChat chat, TLRPC.InputEncryptedFile encryptedFile, String originalPath, MessageObject newMsg) {
        if (req == null || chat.auth_key == null || chat instanceof TLRPC.TL_encryptedChatRequested || chat instanceof TLRPC.TL_encryptedChatWaiting) {
            return;
        }
        getSendMessagesHelper().putToSendingMessages(newMsgObj, false);
        Utilities.stageQueue.postRunnable(() -> {
            try {
                TLObject toEncryptObject;'''
    return once(text, old, '''    protected void performSendEncryptedRequest(TLRPC.DecryptedMessage req, TLRPC.Message newMsgObj, TLRPC.EncryptedChat chat, TLRPC.InputEncryptedFile encryptedFile, String originalPath, MessageObject newMsg) {
        if (req == null || chat.auth_key == null || chat instanceof TLRPC.TL_encryptedChatRequested || chat instanceof TLRPC.TL_encryptedChatWaiting) {
            return;
        }
        final ''' + BRIDGE + '''.CapturedRead capyRead = ''' + BRIDGE + '''.captureSecretRead(currentAccount, req);
        final ''' + BRIDGE + '''.SessionIdentity capyIdentity = capyRead == null ? null : ''' + BRIDGE + '''.captureSession(currentAccount);
        getSendMessagesHelper().putToSendingMessages(newMsgObj, false);
        Utilities.stageQueue.postRunnable(() -> {
            // Never allocate an encrypted sequence number, key-use count or
            // ciphertext for a suppressed receipt. Re-check the captured owner
            // and policy after queueing, including logout/re-login in one slot.
            if (capyRead != null && !''' + BRIDGE + '''.consume(currentAccount, req, capyRead)) {
                if (''' + BRIDGE + '''.isCurrent(capyIdentity)) {
                    getMessagesStorage().markMessageAsSendError(newMsgObj, 0);
                    AndroidUtilities.runOnUIThread(() -> {
                        if (!''' + BRIDGE + '''.isCurrent(capyIdentity)) return;
                        getSendMessagesHelper().processSentMessage(newMsgObj.id);
                        getSendMessagesHelper().removeFromSendingMessages(newMsgObj.id, false);
                    });
                }
                return;
            }
            try {
                TLObject toEncryptObject;''')


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def plan(source, check=False):
    root = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'android-secret-read-hashes.json').read_text())
    if manifest['source_sha'] != '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c' or manifest['host'] != HOST:
        raise ValueError('Wrong secret-read source manifest')
    path = root / HOST
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Unsafe secret-read source path')
    data = path.read_bytes().replace(b'\r\n', b'\n')
    if digest(data) != manifest['post' if check else 'pre']:
        raise ValueError('Wrong secret-read source bytes')
    output = data if check else transform(data.decode('utf-8')).encode('utf-8')
    if digest(output) != manifest['post']:
        raise ValueError('Wrong secret-read output bytes')
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('--check', action='store_true')
    a = p.parse_args()
    head = subprocess.run(['git', '-C', str(a.source), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    if head != '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c':
        raise ValueError('Wrong Android source revision')
    result = plan(a.source, a.check)
    if not a.check:
        (a.source / HOST).write_bytes(result)
    print('PASS: Android secret read-mode path', 'verified' if a.check else 'prepared')
