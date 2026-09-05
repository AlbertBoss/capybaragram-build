# SPDX-License-Identifier: MIT
"""Integrate reviewed native notes after the pinned Android account patch."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
JAVA = 'TMessagesProj/src/main/java/'
FILES = [JAVA + 'org/telegram/' + name for name in (
    'messenger/UserConfig.java', 'ui/LaunchActivity.java', 'ui/ChatActivity.java')]
ADDED = {JAVA + 'org/capybaragram/local/' + name: ROOT.parent / 'vault' / name for name in (
    'PayloadCipher.java', 'AndroidVaultKeys.java', 'AndroidVaultStore.java',
    'VaultSchema.java', 'AndroidVaultCoordinator.java')}
ADDED.update({JAVA + 'org/capybaragram/telegram/' + name: ROOT / name for name in (
    'CapyVault.java', 'CapyNotesUi.java')})
ADDED.update({'TMessagesProj/src/main/res/values/capybaragram.xml': ROOT / 'strings.xml',
              'TMessagesProj/src/main/res/values-ru/capybaragram.xml': ROOT / 'strings-ru.xml'})

def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Android notes source anchor differs.')
    return text.replace(old, new)

def transform(name, text):
    if name == FILES[0]:
        text = replace(text, '    public void clearConfig() {\n',
            '    public void clearConfig() {\n        org.capybaragram.telegram.CapyVault.beforeLogout(currentAccount);\n')
        return replace(text, '            clientUserId = user.id;\n            checkPremiumSelf(oldUser, user);',
            '            clientUserId = user.id;\n'
            '            org.capybaragram.telegram.CapyVault.ownerChanged(currentAccount, oldUser == null ? 0 : oldUser.id, user.id);\n'
            '            checkPremiumSelf(oldUser, user);')
    if name == FILES[1]:
        return replace(text, '        SharedConfig.appLocked = true;\n',
            '        SharedConfig.appLocked = true;\n        org.capybaragram.telegram.CapyVault.locked();\n')
    if name == FILES[2]:
        for method in ['onPause', 'onFragmentDestroy']:
            anchor = '    public void ' + method + '() {\n'
            text = replace(text, anchor, anchor + '        org.capybaragram.telegram.CapyNotesUi.closeFor(this);\n')
        text = replace(text, '            public void onItemClick(final int id) {\n',
            '            public void onItemClick(final int id) {\n'
            '                if (id == 9001 || id == 9002) {\n'
            '                    showCapyVault(id == 9002);\n                    return;\n                }\n')
        anchor = '            headerItem.setContentDescription(LocaleController.getString(R.string.AccDescrMoreOptions));\n\n            if (currentUser != null && currentUser.self && chatMode != MODE_SAVED) {'
        text = replace(text, anchor, '''            headerItem.setContentDescription(LocaleController.getString(R.string.AccDescrMoreOptions));
            if (Build.VERSION.SDK_INT >= 23 && currentEncryptedChat == null && !inPreviewMode) {
                if (getTopicId() == 0 || (currentChat != null && ChatObject.isChannel(currentChat))) {
                    headerItem.addSubItem(9001, R.drawable.msg_edit, LocaleController.getString(R.string.CapyNote));
                }
                headerItem.addSubItem(9002, R.drawable.msg_copy, LocaleController.getString(R.string.CapyTemplates));
            }

            if (currentUser != null && currentUser.self && chatMode != MODE_SAVED) {''')
        anchor = '    @Override\n    public View createView(Context context) {'
        method = '''    private void showCapyVault(boolean templates) {
        if (Build.VERSION.SDK_INT < 23 || currentEncryptedChat != null || chatActivityEnterView == null
                || (currentChat == null && currentUser == null) || dialog_id == 0 || dialog_id == Long.MIN_VALUE) return;
        final long expectedDialog = dialog_id;
        final long expectedTopic = getTopicId();
        final int expectedAccount = currentAccount;
        final int peerType = dialog_id > 0 ? 1 : (ChatObject.isChannel(currentChat) ? 3 : 2);
        if (!templates && expectedTopic > 0 && peerType != 3) return;
        final String recipient = currentChat != null ? currentChat.title : UserObject.getUserName(currentUser);
        org.capybaragram.telegram.CapyNotesUi.show(this, expectedAccount, peerType,
                Math.abs(expectedDialog), expectedTopic, recipient, templates,
                () -> isLastFragment() && !paused && currentAccount == expectedAccount
                        && dialog_id == expectedDialog && getTopicId() == expectedTopic,
                value -> {
                    if (chatActivityEnterView == null) return;
                    CharSequence old = chatActivityEnterView.getFieldText();
                    SpannableStringBuilder combined = new SpannableStringBuilder();
                    if (old != null && old.length() > 0) combined.append(old).append('\\n');
                    combined.append(value);
                    chatActivityEnterView.setFieldText(combined);
                });
    }

'''
        return replace(text, anchor, method + anchor)
    raise ValueError('Unexpected Android notes patch target.')

def digest(raw): return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()

def plan(source, check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((ROOT / 'notes-input-hashes.json').read_text())
    if set(manifest['pre']) != set(FILES) or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED):
        raise ValueError('Android notes allowlist differs.')
    result = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError('Android notes source path escapes checkout.')
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(raw) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Android notes preparation state differs: ' + name)
        if not check:
            raw = transform(name, raw.decode('utf-8')).encode('utf-8')
            if digest(raw) != manifest['post'][name]:
                raise ValueError('Android notes transform differs from reviewed output.')
        result[name] = raw
    for name, origin in ADDED.items():
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Android notes added path escapes checkout.')
        raw = origin.read_bytes().replace(b'\r\n', b'\n')
        if digest(raw) != manifest['added'][name]:
            raise ValueError('Android notes bundled source differs.')
        if check:
            if not path.is_file() or digest(path.read_bytes()) != manifest['added'][name]:
                raise ValueError('Android notes installed source differs.')
        elif path.exists():
            raise ValueError('Android notes destination already exists.')
        result[name] = raw
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    head = subprocess.run(['git', '-C', str(args.source), 'rev-parse', 'HEAD'],
        check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if head != '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c':
        raise ValueError('Android source revision differs.')
    result = plan(args.source, args.check)
    if not args.check:
        for name, data in result.items():
            path = args.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    print('PASS:', len(result), 'Android native note files', 'verified' if args.check else 'prepared')
