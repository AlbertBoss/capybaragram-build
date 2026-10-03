# SPDX-License-Identifier: MIT
"""Native archive hooks, composed after silent reading and appearance."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
JAVA = 'TMessagesProj/src/main/java/'
STORAGE = JAVA + 'org/telegram/messenger/MessagesStorage.java'
CHAT = JAVA + 'org/telegram/ui/ChatActivity.java'
CONFIG = JAVA + 'org/telegram/messenger/UserConfig.java'
VAULT = JAVA + 'org/capybaragram/telegram/CapyVault.java'
FILES = [STORAGE, CHAT, CONFIG, VAULT]
ARCHIVE = 'org.capybaragram.archive.CapyMessageArchive'
UI = 'org.capybaragram.archive.CapyArchiveUi'
ADDED = {JAVA + 'org/capybaragram/archive/' + n: HERE / n for n in (
    'AndroidArchiveStore.java', 'AndroidArchiveCoordinator.java', 'CapyMessageArchive.java', 'CapyArchiveUi.java')}
ADDED.update({'TMessagesProj/src/main/res/values/capy_archive.xml': HERE / 'strings.xml',
    'TMessagesProj/src/main/res/values-ru/capy_archive.xml': HERE / 'strings-ru.xml'})


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Archive anchor differs: ' + old[:90])
    return text.replace(old, new)


def transform(name, text):
    if name == STORAGE:
        old = '    private ArrayList<Long> markMessagesAsDeletedInternal(long dialogId, ArrayList<Integer> messages, boolean deleteFiles, int mode, int threadMessageId) {\n'
        text = once(text, old, old + '        if (mode == ChatActivity.MODE_DEFAULT) ' + ARCHIVE + '.captureDeleted(currentAccount, database, dialogId, messages);\n')
        old = '    private ArrayList<Long> markMessagesAsDeletedInternal(long channelId, int mid, boolean deleteFiles) {\n'
        text = once(text, old, old + '        ' + ARCHIVE + '.captureThreshold(currentAccount, database, channelId, mid);\n')
        old = '''    public void emptyMessagesMedia(long dialogId, ArrayList<Integer> mids) {
        storageQueue.postRunnable(() -> {
'''
        text = once(text, old, old + '            ' + ARCHIVE + '.captureExpired(currentAccount, database, dialogId, mids);\n')
        old = '    private void putMessagesInternal(ArrayList<TLRPC.Message> messages, boolean withTransaction, boolean doNotUpdateDialogDate, int downloadMask, boolean ifNoLastMessage, int mode, long threadMessageId) {\n'
        return once(text, old, old + '        if (mode == ChatActivity.MODE_DEFAULT) ' + ARCHIVE + '.captureEdits(currentAccount, database, messages);\n')
    if name == CONFIG:
        old = '        org.capybaragram.readmode.CapyReadReceipts.beforeLogout(currentAccount);\n'
        text = once(text, old, old + '        ' + ARCHIVE + '.beforeLogout(currentAccount);\n')
        old = '            org.capybaragram.readmode.CapyReadReceipts.ownerChanged(currentAccount, oldUser == null ? 0 : oldUser.id, user.id);\n'
        return once(text, old, old + '            ' + ARCHIVE + '.ownerChanged(currentAccount, oldUser == null ? 0 : oldUser.id, user.id);\n')
    if name == VAULT:
        old = '        org.capybaragram.readmode.CapyReadModeUi.closeAll();\n'
        # Two lifecycle calls use runOnUIThread; only locked() calls directly.
        return once(text, old, old + '        ' + ARCHIVE + '.locked();\n')
    if name == CHAT:
        for method in ('onPause', 'onFragmentDestroy'):
            old = '    public void ' + method + '() {\n'
            text = once(text, old, old + '        ' + UI + '.closeFor(this);\n')
        old = '            public void onItemClick(final int id) {\n'
        text = once(text, old, old + '                if (id == 9004) { showCapyArchive(); return; }\n')
        old = '                headerItem.addSubItem(9003, R.drawable.msg_edit, LocaleController.getString(R.string.CapyReadMode));\n'
        text = once(text, old, old + '                headerItem.addSubItem(9004, R.drawable.msg_copy, LocaleController.getString(R.string.CapyArchive));\n')
        old = '    private void showCapyReadMode() {\n'
        method = '''    private void showCapyArchive() {
        if (inPreviewMode || chatMode != 0 || dialog_id == 0 || (currentUser == null && currentChat == null)) return;
        final int expectedAccount = currentAccount;
        final long expectedDialog = dialog_id;
        final long expectedThread = threadMessageId;
        final String recipient = currentChat != null ? currentChat.title : UserObject.getUserName(currentUser);
        org.capybaragram.archive.CapyArchiveUi.show(this, expectedAccount, expectedDialog, recipient,
                () -> isLastFragment() && !paused && currentAccount == expectedAccount
                        && dialog_id == expectedDialog && threadMessageId == expectedThread && chatMode == 0);
    }

'''
        return once(text, old, method + old)
    raise ValueError('Unexpected archive target')


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def plan(source, check=False):
    root = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'android-archive-hashes.json').read_text())
    if set(manifest['pre']) != set(FILES) or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED):
        raise ValueError('Wrong archive manifest allowlist')
    output = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Archive source path escapes checkout')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Archive input differs: ' + name)
        data = data if check else transform(name, data.decode('utf-8')).encode('utf-8')
        if digest(data) != manifest['post'][name]:
            raise ValueError('Archive output differs')
        output[name] = data
    for name, source_path in ADDED.items():
        data = source_path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['added'][name]:
            raise ValueError('Archive payload changed')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Archive added path escapes checkout')
        if check:
            if not path.is_file() or digest(path.read_bytes()) != digest(data):
                raise ValueError('Installed archive payload differs')
        elif path.exists():
            raise ValueError('Archive destination already exists')
        output[name] = data
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
    outputs = plan(a.source, a.check)
    if not a.check:
        for name, data in outputs.items():
            path = a.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    print('PASS: native archive hooks', 'verified' if a.check else 'prepared')
