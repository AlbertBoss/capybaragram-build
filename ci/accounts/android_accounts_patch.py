# SPDX-License-Identifier: MIT
"""Draft account-capacity transformation. Not yet connected to release/preview CI."""
from pathlib import Path
import hashlib
import json

CAPACITY = 10
JAVA = 'TMessagesProj/src/main/java/org/telegram/'
CONFIG = JAVA+'messenger/UserConfig.java'
DEFINES = 'TMessagesProj/jni/tgnet/Defines.h'
CONNECTIONS = 'TMessagesProj/jni/tgnet/ConnectionsManager.cpp'
NOTIFICATIONS = JAVA+'messenger/NotificationsController.java'
INFO = JAVA+'ui/UserInfoActivity.java'
FILES = [CONFIG, DEFINES, CONNECTIONS, NOTIFICATIONS, INFO]

def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Source anchor differs from reviewed account patch.')
    return text.replace(old, new)

def native_selector():
    lines = ['ConnectionsManager& ConnectionsManager::getInstance(int32_t instanceNum) {',
             f'    static_assert(MAX_ACCOUNT_COUNT == {CAPACITY}, "Account selector and capacity must agree");',
             '    switch (instanceNum) {']
    for slot in range(CAPACITY):
        lines.extend([f'        case {slot}:', f'            static ConnectionsManager instance{slot}({slot});',
                      f'            return instance{slot};'])
    lines.extend(['        default:', '            std::abort();', '    }', '}'])
    return '\n'.join(lines)

def transform(name, text):
    if name == CONFIG:
        text = replace(text, 'MAX_ACCOUNT_DEFAULT_COUNT = 3;', f'MAX_ACCOUNT_DEFAULT_COUNT = {CAPACITY};')
        text = replace(text, 'MAX_ACCOUNT_COUNT = 4;', f'MAX_ACCOUNT_COUNT = {CAPACITY};')
        return replace(text, 'return hasPremiumOnAccounts() ? 5 : 3;', 'return MAX_ACCOUNT_COUNT;')
    if name == DEFINES:
        return replace(text, '#define MAX_ACCOUNT_COUNT 5', f'#define MAX_ACCOUNT_COUNT {CAPACITY}')
    if name == CONNECTIONS:
        start = text.index('ConnectionsManager& ConnectionsManager::getInstance(int32_t instanceNum) {')
        end = text.index('\nint ConnectionsManager::callEvents(', start)
        return text[:start]+native_selector()+'\n'+text[end:]
    if name == NOTIFICATIONS:
        # Notification IDs 4, 5 and 6 are already used by foreground services.
        # Android identifies notifications by (tag, id), separating every account.
        count_notify = text.count('notificationManager.notify(')
        count_cancel = text.count('notificationManager.cancel(')
        if (count_notify, count_cancel) != (4, 7):
            raise ValueError('Notification call inventory changed.')
        text = text.replace('notificationManager.notify(', 'notificationManager.notify("capybaragram.account." + currentAccount, ')
        return text.replace('notificationManager.cancel(', 'notificationManager.cancel("capybaragram.account." + currentAccount, ')
    if name == INFO:
        start = text.index('            if (!UserConfig.hasPremiumOnAccounts()) {\n                final int moreAccounts')
        end = text.index('\n        }\n        logoutRow', start)
        return text[:start]+'            items.add(UItem.asShadow(null));'+text[end:]
    raise ValueError('File outside account patch allowlist.')

def plan(source):
    root = Path(source).resolve(strict=True)
    manifest = json.loads(Path(__file__).with_name('android-input-hashes.json').read_text())
    if set(manifest) != set(FILES):
        raise ValueError('Input manifest differs.')
    result = {}
    for name in FILES:
        path = root/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Source path outside checkout.')
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != manifest[name]:
            raise ValueError('Source bytes differ from pinned revision.')
        result[name] = transform(name, raw.decode('utf-8')).encode('utf-8')
    return result
