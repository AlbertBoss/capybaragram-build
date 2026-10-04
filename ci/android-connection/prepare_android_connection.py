# SPDX-License-Identifier: MIT
"""Guarded native Java integration after the archive and voice stages."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
SHA='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'
JAVA='TMessagesProj/src/main/java/'
CONNECTIONS=JAVA+'org/telegram/tgnet/ConnectionsManager.java'
CHAT=JAVA+'org/telegram/ui/ChatActivity.java'
LOGIN=JAVA+'org/telegram/ui/LoginActivity.java'
VAULT=JAVA+'org/capybaragram/telegram/CapyVault.java'
PROGUARD='TMessagesProj/proguard-rules.pro'
FILES=[CONNECTIONS,CHAT,LOGIN,VAULT,PROGUARD]
ADDED={JAVA+'org/capybaragram/connection/'+name:HERE/name for name in
       ('ConnectionController.java','MemoryRoute.java','NativeTunnel.java','CapyConnectionService.java','CapyConnectionUi.java')}
ADDED.update({'TMessagesProj/src/main/res/values/capy_connection.xml':HERE/'strings.xml',
              'TMessagesProj/src/main/res/values-ru/capy_connection.xml':HERE/'strings-ru.xml'})

def digest(data):return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()

def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Connection host anchor differs: '+old[:80])
    return text.replace(old,new)

def transform(name,text):
    if name==PROGUARD:
        if 'org.capybaragram.connection.NativeTunnel' in text:raise ValueError('Connection JNI keep rule already present')
        return text+'\n# Preserve the symbol-based production JNI entry points under R8.\n-keep class org.capybaragram.connection.NativeTunnel { *; }\n'
    if name==CONNECTIONS:
        old='    public static void setProxySettings(boolean enabled, String address, int port, String username, String password, String secret) {\n'
        begin=text.index(old)
        end=text.index('\n    public static native void native_switchBackend(',begin)
        new='''    private static final org.capybaragram.connection.MemoryRoute capyRoute =
            new org.capybaragram.connection.MemoryRoute(UserConfig.MAX_ACCOUNT_COUNT,
                (account, enabled, address, port, username, password, secret) ->
                    native_setProxySettings(account, enabled ? address : "", enabled ? port : 1080,
                                            enabled ? username : "", enabled ? password : "", enabled ? secret : ""));

    private static org.capybaragram.connection.MemoryRoute.Proxy capySavedProxy() {
        SharedPreferences preferences = ApplicationLoader.applicationContext.getSharedPreferences("mainconfig", Activity.MODE_PRIVATE);
        return new org.capybaragram.connection.MemoryRoute.Proxy(preferences.getBoolean("proxy_enabled", false),
                preferences.getString("proxy_ip", ""), preferences.getInt("proxy_port", 1080),
                preferences.getString("proxy_user", ""), preferences.getString("proxy_pass", ""),
                preferences.getString("proxy_secret", ""));
    }

    public static long capyBeginConnection(boolean enabled) {
        return capyRoute.begin(enabled, capySavedProxy());
    }

    public static boolean capyAcceptConnection(long generation, byte[] endpoint) {
        return capyRoute.ready(generation, endpoint);
    }

    public static boolean capyFailConnection(long generation) {
        return capyRoute.failed(generation);
    }

    public static org.capybaragram.connection.MemoryRoute.Snapshot capyConnectionSnapshot() {
        return capyRoute.snapshot();
    }

    public static void setProxySettings(boolean enabled, String address, int port, String username, String password, String secret) {
        final long revoked = capyRoute.manualSelected(new org.capybaragram.connection.MemoryRoute.Proxy(
                enabled, address, port, username, password, secret));
        // The route lock is released before acquiring or scheduling the controller lock.
        org.capybaragram.connection.CapyConnectionService.manualSelected(revoked);
        for (int a = 0; a < UserConfig.MAX_ACCOUNT_COUNT; a++) {
            if (UserConfig.getInstance(a).isClientActivated()) {
                AccountInstance.getInstance(a).getMessagesController().checkPromoInfo(true);
            }
        }
    }
'''
        if text.count(old)!=1:raise ValueError('Proxy setter inventory changed')
        text=text[:begin]+new+text[end:]
        old='''        if (preferences.getBoolean("proxy_enabled", false) && !TextUtils.isEmpty(proxyAddress)) {
            native_setProxySettings(currentAccount, proxyAddress, proxyPort, proxyUsername, proxyPassword, proxySecret);
        }
'''
        text=once(text,old,'''        capyRoute.beforeInitialize(currentAccount, new org.capybaragram.connection.MemoryRoute.Proxy(
                preferences.getBoolean("proxy_enabled", false), proxyAddress, proxyPort, proxyUsername, proxyPassword, proxySecret));
''')
        old='SharedConfig.measureDevicePerformanceClass());\n        checkConnection();\n'
        return once(text,old,'SharedConfig.measureDevicePerformanceClass());\n        capyRoute.afterInitialize(currentAccount);\n        checkConnection();\n')
    if name==CHAT:
        for method in ('onPause','onFragmentDestroy'):
            old='    public void '+method+'() {\n'
            text=once(text,old,old+'        org.capybaragram.connection.CapyConnectionUi.closeFor(this);\n')
        old='                if (id == 9004) { showCapyArchive(); return; }\n'
        text=once(text,old,'                if (id == 9006) { showCapyConnection(); return; }\n'+old)
        old='                headerItem.addSubItem(9004, R.drawable.msg_copy, LocaleController.getString(R.string.CapyArchive));\n'
        text=once(text,old,old+'                headerItem.addSubItem(9006, R.drawable.msg_settings, LocaleController.getString(R.string.CapyConnection));\n')
        old='    private void showCapyArchive() {\n'
        new='''    private void showCapyConnection() {
        if (inPreviewMode || chatMode != MODE_DEFAULT || paused) return;
        final int account = currentAccount;
        final long owner = getUserConfig().getClientUserId();
        org.capybaragram.connection.CapyConnectionUi.show(this,
                () -> isLastFragment() && !paused && currentAccount == account
                        && getUserConfig().getClientUserId() == owner,
                () -> presentFragment(new ProxyListActivity()));
    }

'''
        return once(text,old,new+old)
    if name==LOGIN:
        for method in ('onPause','onFragmentDestroy'):
            old='    public void '+method+'() {\n'
            text=once(text,old,old+'        org.capybaragram.connection.CapyConnectionUi.closeFor(this);\n')
        old='    private View cachedFragmentView;\n'
        text=once(text,old,'    private TextView capyConnectionButton;\n'+old)
        old='                marginLayoutParams = (MarginLayoutParams) proxyButtonView.getLayoutParams();\n'
        text=once(text,old,'''                marginLayoutParams = (MarginLayoutParams) capyConnectionButton.getLayoutParams();
                marginLayoutParams.topMargin = AndroidUtilities.dp(8) + statusBarHeight;

'''+old)
        old='        updateProxyButton(false, true);\n'
        text=once(text,old,old+'''
        capyConnectionButton = new TextView(context);
        capyConnectionButton.setText(getString(R.string.CapyConnectionLogin));
        capyConnectionButton.setTextSize(TypedValue.COMPLEX_UNIT_DIP, 14);
        capyConnectionButton.setTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteLinkText));
        capyConnectionButton.setGravity(Gravity.CENTER);
        capyConnectionButton.setSingleLine(true);
        capyConnectionButton.setEllipsize(TextUtils.TruncateAt.END);
        capyConnectionButton.setMaxWidth(AndroidUtilities.dp(180));
        capyConnectionButton.setPadding(AndroidUtilities.dp(8), 0, AndroidUtilities.dp(8), 0);
        capyConnectionButton.setContentDescription(getString(R.string.CapyConnection));
        capyConnectionButton.setOnClickListener(v -> org.capybaragram.connection.CapyConnectionUi.show(
                this, this::isLastFragment, () -> presentFragment(new ProxyListActivity())));
        sizeNotifierFrameLayout.addView(capyConnectionButton,
                LayoutHelper.createFrame(LayoutHelper.WRAP_CONTENT, 48, Gravity.TOP | Gravity.CENTER_HORIZONTAL, 48, 8, 48, 0));
''')
        return text
    if name==VAULT:
        old='        org.capybaragram.voice.CapyVoiceUi.closeAll();\n'
        text=once(text,old,old+'        org.capybaragram.connection.CapyConnectionUi.closeAll();\n')
        old='        AndroidUtilities.runOnUIThread(org.capybaragram.voice.CapyVoiceUi::closeAll);\n'
        if text.count(old)!=2:raise ValueError('Vault owner lifecycle inventory changed')
        return text.replace(old,old+'        AndroidUtilities.runOnUIThread(org.capybaragram.connection.CapyConnectionUi::closeAll);\n')
    raise ValueError('Unexpected connection host')

def plan(source,check=False):
    root=Path(source).resolve(strict=True)
    manifest=json.loads((HERE/'native-host-hashes.json').read_text())
    if manifest['source_sha']!=SHA or set(manifest['pre'])!=set(FILES) or set(manifest['post'])!=set(FILES) or set(manifest['added'])!=set(ADDED):
        raise ValueError('Connection source/allowlist differs')
    result={}
    for name in FILES:
        path=root/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):raise ValueError('Connection host escapes checkout')
        data=path.read_bytes().replace(b'\r\n',b'\n')
        if digest(data)!=manifest['post' if check else 'pre'][name]:raise ValueError('Connection host hash differs: '+name)
        output=data if check else transform(name,data.decode()).encode()
        if digest(output)!=manifest['post'][name]:raise ValueError('Connection output hash differs')
        result[name]=output
    for name,payload in ADDED.items():
        data=payload.read_bytes().replace(b'\r\n',b'\n');target=root/name
        if digest(data)!=manifest['added'][name] or target.is_symlink() or not target.resolve().is_relative_to(root):raise ValueError('Connection payload differs')
        if check:
            if not target.is_file() or digest(target.read_bytes())!=digest(data):raise ValueError('Installed connection payload differs')
        elif target.exists():raise ValueError('Added connection file already exists')
        result[name]=data
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    head=subprocess.run(['git','-C',str(args.source),'rev-parse','HEAD'],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Android source revision')
    result=plan(args.source,args.check)
    if not args.check:
        for name,data in result.items():
            path=args.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print('PASS: native connection hosts '+('verified' if args.check else 'prepared'))
