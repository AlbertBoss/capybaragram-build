# SPDX-License-Identifier: MIT
"""Compose native voice menus and lifecycle closure after the archive patch."""
import argparse,hashlib,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
JAVA='TMessagesProj/src/main/java/'
CHAT=JAVA+'org/telegram/ui/ChatActivity.java'
VAULT=JAVA+'org/capybaragram/telegram/CapyVault.java'
FILES=[CHAT,VAULT]
ADDED={JAVA+'org/capybaragram/voice/'+n:HERE/n for n in ('OfflineSpeech.java','SpeechModel.java','AndroidPcmDecoder.java','CapyVoiceUi.java')}
ADDED.update({'TMessagesProj/src/main/res/values/capy_voice.xml':HERE/'strings.xml',
              'TMessagesProj/src/main/res/values-ru/capy_voice.xml':HERE/'strings-ru.xml',
              'TMessagesProj/src/main/assets/capy_whisper_license.txt':HERE/'UPSTREAM-LICENSE.txt'})
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Voice anchor differs: '+old[:100])
    return text.replace(old,new)
def transform(name,text):
    if name==CHAT:
        for method in ('onPause','onFragmentDestroy'):
            old='    public void '+method+'() {\n'
            text=once(text,old,old+'        org.capybaragram.voice.CapyVoiceUi.closeFor(this);\n')
        old='            if (options.isEmpty() && optionsView == null) {\n'
        added='''            if (chatMode == MODE_DEFAULT && message.isVoice()) {
                items.add(LocaleController.getString(R.string.CapySpeech));
                options.add(9005);
                icons.add(R.drawable.msg_edit);
            }

'''
        text=once(text,old,added+old)
        old='        boolean preserveDim = false;\n        switch (option) {\n'
        added='''            case 9005: {
                final MessageObject target = selectedObject;
                AndroidUtilities.runOnUIThread(() -> showCapyVoice(target));
                break;
            }
'''
        text=once(text,old,old+added)
        old='    private void showCapyArchive() {\n'
        added='''    private void showCapyVoice(MessageObject message) {
        if (inPreviewMode || chatMode != MODE_DEFAULT || message == null || !message.isVoice()
                || message.getDialogId() != dialog_id) return;
        final int expectedAccount = currentAccount;
        final long expectedDialog = dialog_id;
        final long expectedThread = threadMessageId;
        org.capybaragram.voice.CapyVoiceUi.show(this, expectedAccount, message,
                () -> isLastFragment() && !paused && currentAccount == expectedAccount
                        && dialog_id == expectedDialog && threadMessageId == expectedThread && chatMode == MODE_DEFAULT);
    }

'''
        return once(text,old,added+old)
    if name==VAULT:
        old='        AndroidUtilities.runOnUIThread(CapyNotesUi::closeAll);\n'
        if text.count(old)!=2:raise ValueError('Expected both vault owner lifecycle hooks')
        text=text.replace(old,old+'        AndroidUtilities.runOnUIThread(org.capybaragram.voice.CapyVoiceUi::closeAll);\n')
        old='        org.capybaragram.archive.CapyMessageArchive.locked();\n'
        return once(text,old,old+'        org.capybaragram.voice.CapyVoiceUi.closeAll();\n')
    raise ValueError('Unexpected voice host')
def digest(data):return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
def plan(source,check=False):
    root=Path(source).resolve(strict=True);manifest=json.loads((HERE/'android-voice-hashes.json').read_text())
    if set(manifest['pre'])!=set(FILES) or set(manifest['post'])!=set(FILES) or set(manifest['added'])!=set(ADDED):raise ValueError('Voice allowlist differs')
    outputs={}
    for name in FILES:
        path=root/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):raise ValueError('Voice host escapes checkout')
        data=path.read_bytes().replace(b'\r\n',b'\n')
        if digest(data)!=manifest['post' if check else 'pre'][name]:raise ValueError('Voice host differs: '+name)
        result=data if check else transform(name,data.decode('utf-8')).encode('utf-8')
        if digest(result)!=manifest['post'][name]:raise ValueError('Voice output differs')
        outputs[name]=result
    for name,source in ADDED.items():
        data=source.read_bytes().replace(b'\r\n',b'\n');target=root/name
        if digest(data)!=manifest['added'][name] or target.is_symlink() or not target.resolve().is_relative_to(root):raise ValueError('Voice payload differs')
        if check:
            if not target.is_file() or digest(target.read_bytes())!=digest(data):raise ValueError('Installed voice payload differs')
        elif target.exists():raise ValueError('Voice destination exists')
        outputs[name]=data
    return outputs
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
    if head!='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c':raise ValueError('Wrong Android source revision')
    outputs=plan(a.source,a.check)
    if not a.check:
        for name,data in outputs.items():
            path=a.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print('PASS: native voice menus/lifecycle prepared' if not a.check else 'PASS: native voice menus/lifecycle verified')
