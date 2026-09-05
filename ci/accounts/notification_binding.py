# SPDX-License-Identifier: MIT
"""New Java source used by the reviewed notification account transformation."""

BINDING_SOURCE = '''// SPDX-License-Identifier: GPL-2.0-or-later
package org.telegram.messenger;

import android.content.Intent;
import android.net.Uri;

public final class NotificationAccountBinding {
    public static final String USER_ID_EXTRA = "capy_notification_user_id";

    private NotificationAccountBinding() {
    }

    public static Intent bind(Intent intent, int account) {
        final long userId = UserConfig.getInstance(account).getClientUserId();
        intent.putExtra("currentAccount", account);
        intent.putExtra(USER_ID_EXTRA, userId);
        final long dialogId = intent.getLongExtra("dialog_id",
            intent.getLongExtra("dialogId", intent.getLongExtra("did", 0)));
        final long topicId = intent.getLongExtra("topic_id", intent.getLongExtra("topicId", 0));
        intent.setData(new Uri.Builder().scheme("capybaragram").authority("notification")
            .appendPath(Integer.toString(account)).appendPath(Long.toString(userId))
            .appendPath(Long.toString(dialogId)).appendPath(Long.toString(topicId))
            .appendPath(Long.toString(intent.getLongExtra("userId", 0)))
            .appendPath(Long.toString(intent.getLongExtra("chatId", 0)))
            .appendPath(Integer.toString(intent.getIntExtra("encId", 0)))
            .appendPath(Boolean.toString(intent.getBooleanExtra("story", false)))
            .appendPath(Boolean.toString(intent.getBooleanExtra("storyReaction", false)))
            .build());
        return intent;
    }

    public static long userId(Intent intent) {
        return intent == null ? 0 : intent.getLongExtra(USER_ID_EXTRA, 0);
    }

    public static boolean isCurrent(Intent intent, int account) {
        return intent != null && intent.getIntExtra("currentAccount", -1) == account
            && isCurrent(account, userId(intent));
    }

    public static boolean isCurrent(int account, long expectedUserId) {
        return expectedUserId > 0 && UserConfig.isValidAccount(account)
            && UserConfig.getInstance(account).getClientUserId() == expectedUserId;
    }
}
'''

def receivers_transform(name, text, replace):
    if name.endswith('NotificationRepeat.java'):
        text = replace(text, '        final int currentAccount = intent.getIntExtra("currentAccount", UserConfig.selectedAccount);',
                       '        ApplicationLoader.postInitApplication();\n        final int currentAccount = intent.getIntExtra("currentAccount", -1);')
        text = replace(text, '!UserConfig.isValidAccount(currentAccount)', '!NotificationAccountBinding.isCurrent(intent, currentAccount)')
        return replace(text, '        AndroidUtilities.runOnUIThread(() -> NotificationsController.getInstance(currentAccount).repeatNotificationMaybe());',
            '        final long expectedUserId = NotificationAccountBinding.userId(intent);\n        AndroidUtilities.runOnUIThread(() -> {\n            if (NotificationAccountBinding.isCurrent(currentAccount, expectedUserId)) {\n                NotificationsController.getInstance(currentAccount).repeatNotificationMaybe();\n            }\n        });')
    if name.endswith('WearReplyReceiver.java') or name.endswith('AutoMessageHeardReceiver.java'):
        text = replace(text, '        ApplicationLoader.postInitApplication();',
            '        if (intent == null) {\n            return;\n        }\n        ApplicationLoader.postInitApplication();')
        text = replace(text, 'intent.getIntExtra("currentAccount", 0)', 'intent.getIntExtra("currentAccount", -1)')
        text = replace(text, '!UserConfig.isValidAccount(currentAccount)', '!NotificationAccountBinding.isCurrent(intent, currentAccount)')
        text = replace(text, '        AccountInstance accountInstance = AccountInstance.getInstance(currentAccount);',
            '        final long expectedUserId = NotificationAccountBinding.userId(intent);\n        AccountInstance accountInstance = AccountInstance.getInstance(currentAccount);')
        for anchor in ['                Utilities.globalQueue.postRunnable(() -> {', '                    AndroidUtilities.runOnUIThread(() -> {']:
            indent = anchor[:len(anchor)-len(anchor.lstrip())]+'    '
            text = replace(text, anchor, anchor+'\n'+indent+'if (!NotificationAccountBinding.isCurrent(currentAccount, expectedUserId)) {\n'+indent+'    return;\n'+indent+'}', 2)
        if name.endswith('WearReplyReceiver.java'):
            text = replace(text, 'sendMessage(accountInstance, text, dialogId, topicId, maxId, voiceMsgIds);',
                           'sendMessage(accountInstance, expectedUserId, text, dialogId, topicId, maxId, voiceMsgIds);', 3)
            text = replace(text, 'private void sendMessage(AccountInstance accountInstance, CharSequence text,',
                           'private void sendMessage(AccountInstance accountInstance, long expectedUserId, CharSequence text,')
            text = replace(text, '        MessageObject replyToMsgId = null;',
                '        if (!NotificationAccountBinding.isCurrent(accountInstance.getCurrentAccount(), expectedUserId)) {\n            return;\n        }\n        MessageObject replyToMsgId = null;')
        return text
    if name.endswith(('NotificationCallbackReceiver.java', 'PopupReplyReceiver.java', 'NotificationDismissReceiver.java')):
        text = replace(text, 'intent.getIntExtra("currentAccount", UserConfig.selectedAccount)', 'intent.getIntExtra("currentAccount", -1)')
        text = replace(text, '!UserConfig.isValidAccount(currentAccount)', '!NotificationAccountBinding.isCurrent(intent, currentAccount)')
        if name.endswith('NotificationDismissReceiver.java'):
            text = replace(text, '        int currentAccount = intent.getIntExtra',
                           '        ApplicationLoader.postInitApplication();\n        int currentAccount = intent.getIntExtra')
        return text
    if name.endswith('CopyCodeReceiver.java'):
        return replace(text, '        String text = intent.getStringExtra("text");',
            '        ApplicationLoader.postInitApplication();\n        if (intent == null || !NotificationAccountBinding.isCurrent(intent, intent.getIntExtra("currentAccount", -1))) {\n            return;\n        }\n        String text = intent.getStringExtra("text");')
    if name.endswith('SendMessagesHelper.java'):
        text = replace(text, '    public void sendNotificationCallback(long dialogId, int msgId, byte[] data) {\n        AndroidUtilities.runOnUIThread(() -> {',
            '    public void sendNotificationCallback(long dialogId, int msgId, byte[] data) {\n        final long expectedUserId = getUserConfig().getClientUserId();\n        AndroidUtilities.runOnUIThread(() -> {\n            if (!NotificationAccountBinding.isCurrent(currentAccount, expectedUserId)) {\n                return;\n            }')
        start = text.index('    public void sendNotificationCallback(')
        end = text.index('\n    public ', start+10)
        block = text[start:end]
        anchor = 'getConnectionsManager().sendRequest(req, (response, error) -> AndroidUtilities.runOnUIThread(() -> {'
        block = replace(block, anchor, anchor+'\n                if (!NotificationAccountBinding.isCurrent(currentAccount, expectedUserId)) {\n                    return;\n                }')
        return text[:start]+block+text[end:]
    if name.endswith('LaunchActivity.java'):
        # Ordinary links/launches remain unchanged; only stamped notifications are guarded.
        anchor = '    private boolean handleIntent(Intent intent, boolean isNew, boolean restore, boolean fromPassword, Browser.Progress progress, boolean rebuildFragments, boolean openedTelegram) {'
        return replace(text, anchor, anchor+'\n        if (intent != null && intent.hasExtra(org.telegram.messenger.NotificationAccountBinding.USER_ID_EXTRA)\n            && !org.telegram.messenger.NotificationAccountBinding.isCurrent(intent, intent.getIntExtra("currentAccount", -1))) {\n            return false;\n        }')
    raise ValueError('Unknown notification receiver file.')
