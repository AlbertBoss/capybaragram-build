# SPDX-License-Identifier: MIT
"""OS-observed opt-in capture reporting, after the native connection stage."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SHA = '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'
JAVA = 'TMessagesProj/src/main/java/'
CHAT = JAVA + 'org/telegram/ui/ChatActivity.java'
VAULT = JAVA + 'org/capybaragram/telegram/CapyVault.java'
CONNECTIONS = JAVA + 'org/telegram/tgnet/ConnectionsManager.java'
SEND = JAVA + 'org/telegram/messenger/SendMessagesHelper.java'
MANIFEST = 'TMessagesProj/src/main/AndroidManifest.xml'
FILES = [CHAT, VAULT, CONNECTIONS, SEND, MANIFEST]
ADDED = {JAVA + 'org/capybaragram/capture/' + name: HERE / name for name in
         ('CaptureGate.java', 'CapyCapture.java', 'CapyCaptureUi.java', 'CapyScreenshotRequest.java')}
ADDED.update({'TMessagesProj/src/main/res/values/capy_capture.xml': HERE / 'strings.xml',
              'TMessagesProj/src/main/res/values-ru/capy_capture.xml': HERE / 'strings-ru.xml'})


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Screenshot preparation anchor differs: ' + before[:80])
    return text.replace(before, after)


def transform(name, text):
    if name == MANIFEST:
        if 'android.permission.DETECT_SCREEN_CAPTURE' in text:
            raise ValueError('Screenshot permission already present')
        before = '    <uses-permission android:name="android.permission.INTERNET" />'
        return once(text, before, before + '\n    <uses-permission android:name="android.permission.DETECT_SCREEN_CAPTURE" />')
    if name == VAULT:
        old = '        org.capybaragram.connection.CapyConnectionUi.closeAll();\n'
        text = once(text, old, old + '        org.capybaragram.capture.CapyCapture.closeAll();\n')
        old = '        AndroidUtilities.runOnUIThread(org.capybaragram.connection.CapyConnectionUi::closeAll);\n'
        if text.count(old) != 2:
            raise ValueError('Screenshot owner lifecycle inventory differs')
        return text.replace(old, old + '        AndroidUtilities.runOnUIThread(org.capybaragram.capture.CapyCapture::closeAll);\n')
    if name == CHAT:
        for method in ('onPause', 'onFragmentDestroy'):
            old = '    public void ' + method + '() {\n'
            text = once(text, old, old + '        org.capybaragram.capture.CapyCapture.closeFor(this);\n')
        old = '                if (id == 9006) { showCapyConnection(); return; }\n'
        text = once(text, old, '                if (id == 9007) { showCapyCapture(); return; }\n' + old)
        old = '                headerItem.addSubItem(9006, R.drawable.msg_settings, LocaleController.getString(R.string.CapyConnection));\n'
        text = once(text, old, old + '''                if (currentUser != null && currentEncryptedChat == null && !currentUser.bot && !currentUser.deleted
                        && currentUser.id != getUserConfig().getClientUserId() && currentUser.id != 777000L) {
                    headerItem.addSubItem(9007, R.drawable.msg_camera, LocaleController.getString(R.string.CapyCapture));
                }
''')
        start = text.index('    public void onResume() {\n')
        end = text.index('\n    @Override', start + 30)
        body = once(text[start:end], '        paused = false;\n',
                    '        paused = false;\n        bindCapyCapture();\n')
        text = text[:start] + body + text[end:]
        old = '    private void showCapyConnection() {\n'
        helper = '''    private boolean capyCaptureLocation(int account, long owner, long peer) {
        return !inPreviewMode && chatMode == MODE_DEFAULT && !paused && isLastFragment()
                && currentAccount == account && getUserConfig().getClientUserId() == owner
                && currentEncryptedChat == null && currentChat == null && currentUser != null
                && currentUser.id == peer && peer > 0 && peer != owner && peer != 777000L
                && !currentUser.bot && !currentUser.deleted;
    }

    private boolean bindCapyCapture() {
        final int account = currentAccount;
        final long owner = getUserConfig().getClientUserId();
        final long peer = currentUser == null ? 0 : currentUser.id;
        return org.capybaragram.capture.CapyCapture.bind(this, account,
                () -> capyCaptureLocation(account, owner, peer)
                        && !(PhotoViewer.hasInstance() && PhotoViewer.getInstance().isVisible())
                        && !(SecretMediaViewer.hasInstance() && SecretMediaViewer.getInstance().isVisible()),
                () -> {
                    if (capyCaptureLocation(account, owner, peer)) {
                        // The OS reports an activity, never a specific message or region.
                        org.capybaragram.capture.CapyCapture.report(account, owner, currentUser);
                    }
                });
    }

    private void showCapyCapture() {
        final int account = currentAccount;
        final long owner = getUserConfig().getClientUserId();
        final long peer = currentUser == null ? 0 : currentUser.id;
        org.capybaragram.capture.CapyCaptureUi.show(this, account,
                () -> capyCaptureLocation(account, owner, peer), this::bindCapyCapture);
    }

'''
        return once(text, old, helper + old)
    if name == SEND:
        old = '        TLRPC.TL_messages_sendScreenshotNotification req = new TLRPC.TL_messages_sendScreenshotNotification();\n'
        return once(text, old, old + '''        // reply_to is mandatory in the pinned layer, including the initial send.
        TLRPC.TL_inputReplyToMessage capyCaptureReply = new TLRPC.TL_inputReplyToMessage();
        capyCaptureReply.reply_to_msg_id = messageId;
        req.reply_to = capyCaptureReply;
''')
    if name == CONNECTIONS:
        old = '        if (capyRead != null && !org.capybaragram.readmode.CapyReadReceipts.consume(currentAccount, object, capyRead)) {\n'
        return once(text, old, '''        if (object instanceof org.capybaragram.capture.CapyScreenshotRequest
                && !((org.capybaragram.capture.CapyScreenshotRequest) object).allowed(currentAccount)) {
            TLRPC.TL_error error = new TLRPC.TL_error();
            error.code = -2000;
            error.text = "CAPY_SCREENSHOT_REPORT_REVOKED";
            object.freeResources();
            Utilities.stageQueue.postRunnable(() -> {
                try {
                    if (onComplete != null) onComplete.run(null, error);
                    else if (onCompleteTimestamp != null) onCompleteTimestamp.run(null, error, 0);
                } catch (Exception ignored) {
                    FileLog.e("CapybaraGram revoked screenshot callback failed; private data omitted.");
                }
            });
            return;
        }
''' + old)
    raise ValueError('Unexpected screenshot host')


def safe(root, name, existing=False):
    path = root / name
    current = path
    while current != root:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Screenshot path contains a link/junction')
        current = current.parent
    if not path.resolve(strict=existing).is_relative_to(root):
        raise ValueError('Screenshot path escapes checkout')
    if existing and not path.is_file():
        raise ValueError('Screenshot path is not a file')
    return path


def plan(source, check=False):
    root = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'native-host-hashes.json').read_text())
    if manifest['source_sha'] != SHA or set(manifest['pre']) != set(FILES) or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED):
        raise ValueError('Screenshot source/allowlist differs')
    result = {}
    for name in FILES:
        data = safe(root, name, True).read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Screenshot input changed: ' + name)
        output = data if check else transform(name, data.decode('utf-8')).encode('utf-8')
        if digest(output) != manifest['post'][name]:
            raise ValueError('Screenshot output changed')
        if not check:
            result[name] = output
    for name, payload in ADDED.items():
        if payload.is_symlink() or not payload.resolve(strict=True).is_relative_to(HERE):
            raise ValueError('Screenshot payload escapes package')
        data = payload.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['added'][name]:
            raise ValueError('Screenshot payload changed')
        target = safe(root, name)
        if check:
            if not target.is_file() or digest(target.read_bytes()) != digest(data):
                raise ValueError('Installed screenshot payload changed')
        elif target.exists():
            raise ValueError('Screenshot payload already exists')
        else:
            result[name] = data
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    head = subprocess.run(['git', '-C', str(args.source), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if head != SHA:
        raise ValueError('Wrong Android revision')
    result = plan(args.source, args.check)
    if not args.check:
        for name, data in result.items():
            path = args.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    print('CAPY_ANDROID_CAPTURE_SOURCE=' + ('CHECKED' if args.check else 'PREPARED'))
