# SPDX-License-Identifier: MIT
"""Pinned, native CapybaraGram appearance; applied after existing feature patches."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SHAS = {'android': '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c',
        'windows': '80158983dba09d3bf5d96701f21473d6c34bf5f5'}

def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Appearance anchor differs: ' + old[:90])
    return text.replace(old, new)

def transform(name, text):
    if name.endswith('/Theme.java'):
        text = replace(text, '        String themesString = themeConfig.getString("themes2", null);', '''        // Separate bundled themes keep all existing custom themes and accents intact.
        ThemeInfo capyLight = new ThemeInfo();
        capyLight.name = "Capybara Light";
        capyLight.assetName = "capy-light.attheme";
        capyLight.isDark = ThemeInfo.LIGHT;
        capyLight.previewBackgroundColor = 0xffeee9e0;
        capyLight.previewInColor = 0xfffffdf9;
        capyLight.previewOutColor = 0xfff3dfb8;
        capyLight.sortIndex = -2;
        themes.add(capyLight);
        themesDict.put(capyLight.name, capyLight);
        currentDayTheme = capyLight;
        ThemeInfo capyDark = new ThemeInfo();
        capyDark.name = "Capybara Dark";
        capyDark.assetName = "capy-dark.attheme";
        capyDark.isDark = ThemeInfo.DARK;
        capyDark.previewBackgroundColor = 0xff101315;
        capyDark.previewInColor = 0xff222629;
        capyDark.previewOutColor = 0xff33302a;
        capyDark.sortIndex = -1;
        themes.add(capyDark);
        themesDict.put(capyDark.name, capyDark);
        currentNightTheme = capyDark;

        String themesString = themeConfig.getString("themes2", null);''')
        return replace(text, '        if (applyingTheme == null) {\n            applyingTheme = defaultTheme;',
                       '        if (applyingTheme == null) {\n            applyingTheme = capyLight;')
    if name.endswith('/IntroActivity.java'):
        text = replace(text, '        bottomPages = new BottomPagesView(context, viewPager, 6);',
                       '        bottomPages = new BottomPagesView(context, viewPager, 6);\n'
                       '        bottomPages.setColor(-1, Theme.key_featuredStickers_addButton);')
        text = replace(text, 'String dayThemeName = "Blue";', 'String dayThemeName = "Capybara Light";')
        text = replace(text, 'String nightThemeName = "Night";', 'String nightThemeName = "Capybara Dark";')
        text = replace(text, 'new int[]{0xff365c45, 0xff41694e}',
                       'new int[]{Theme.getColor(Theme.key_featuredStickers_addButton), Theme.getColor(Theme.key_featuredStickers_addButton)}')
        return replace(text, 'startMessagingButton.setTextColor(Color.WHITE);',
                       'startMessagingButton.setTextColor(Theme.getColor(Theme.key_featuredStickers_buttonText));')
    if name.endswith('/ChatActivity.java'):
        old = '                    headerItem.addSubItem(9001, R.drawable.msg_edit, LocaleController.getString(R.string.CapyNote));'
        new = '''                    headerItem.addSubItem(9001, R.drawable.msg_edit, LocaleController.getString(R.string.CapyNote));
                    // Direct, labelled action in the native chat header. Same guarded editor.
                    menu.addItem(9001, R.drawable.msg_edit).setContentDescription(LocaleController.getString(R.string.CapyNote));'''
        return replace(text, old, new)
    if name.endswith('/intro_step.cpp'):
        return replace(text, 'anim::color(QColor(54, 92, 69), QColor(65, 105, 78), y / realHeight)',
                       'anim::color(QColor(23, 27, 30), QColor(37, 39, 40), y / realHeight)')
    if name.endswith('/window_theme.cpp'):
        text = replace(text, '''\treturn Ui::ReadBackgroundImage(
\t\tu":/gui/art/background.tgv"_q,
\t\tQByteArray(),
\t\ttrue
\t).image;''', '''\t// Calm neutral background, shared with the bundled light theme.
\tauto image = QImage(32, 32, QImage::Format_ARGB32_Premultiplied);
\timage.fill(QColor(238, 233, 224));
\treturn image;''')
        text = replace(text, 'void ChatBackground::setPreparedAfterPaper(QImage image) {', '''void ChatBackground::setPreparedAfterPaper(QImage image) {
\t// Old default profiles still carry Telegram's green gradient parameters.
\t// Render our neutral default without changing a user's custom wallpaper.
\tif (!nightMode() && _themeObject.pathAbsolute.isEmpty()
\t\t&& (Data::IsDefaultWallPaper(_paper)
\t\t\t|| Data::details::IsTestingDefaultWallPaper(_paper))) {
\t\tconst auto neutral = ReadDefaultImage();
\t\tsetPrepared(neutral, neutral, QImage());
\t\treturn;
\t}
''')
        return replace(text, '''\tstyle::main_palette::reset(ColorizerForTheme(QString()));
\tsaveAdjustableColors();''', '''\tstyle::main_palette::reset(ColorizerForTheme(QString()));
\t// Only the default palette is changed. Imported themes keep their own colors.
\tLoadTheme(readThemeContent(u":/gui/day-blue.tdesktop-theme"_q),
\t\tstyle::colorizer(), std::nullopt);
\tsaveAdjustableColors();''')
    if name.endswith('/window_themes_embedded.cpp'):
        begin = text.index('\treturn {', text.index('std::vector<EmbeddedScheme> EmbeddedThemes()'))
        end = text.index('\n}\n',begin)
        block = text[begin:end]
        schemes = block.split('EmbeddedScheme{')
        palettes = [('eee9e0','f3dfb8','fffdf9','f3dfb8','fffdf9','8c570d'),
                    ('eee9e0','f3dfb8','fffdf9','f3dfb8','fffdf9','8c570d'),
                    ('101315','33302a','222629','222629','33302a','efb454'),
                    ('101315','33302a','222629','222629','33302a','efb454')]
        import re
        if len(schemes)!=5: raise ValueError('Embedded theme inventory changed')
        for i, palette in enumerate(palettes,1):
            values=iter(palette)
            if len(re.findall(r'qColor\("[0-9a-f]+"\)',schemes[i]))!=6: raise ValueError('Embedded preview colors changed')
            schemes[i]=re.sub(r'qColor\("[0-9a-f]+"\)',lambda _: 'qColor("'+next(values)+'")',schemes[i])
        return text[:begin]+'EmbeddedScheme{'.join(schemes)+text[end:]
    if name.endswith('/history_view_top_bar_widget.h'):
        text = replace(text, '\tobject_ptr<Ui::IconButton> _menuToggle;',
                       '\tobject_ptr<Ui::IconButton> _menuToggle;\n\tobject_ptr<Ui::IconButton> _capyTools;')
        return replace(text, '\tvoid showPeerMenu();', '\tvoid showPeerMenu();\n\tvoid showCapyTools();')
    if name.endswith('/history_view_top_bar_widget.cpp'):
        text = replace(text, '#include <QPointer>', '#include <QPointer>\n#include "styles/style_menu_icons.h"')
        text = replace(text, ', _menuToggle(this, st::topBarMenuToggle)',
                       ', _menuToggle(this, st::topBarMenuToggle)\n, _capyTools(this, st::topBarSearch)')
        text = replace(text, '\t_menuToggle->setAcceptBoth(true, true);', '''\t_menuToggle->setAcceptBoth(true, true);
\t_capyTools->setIconOverride(&st::menuIconEdit, &st::menuIconEdit);
\t_capyTools->setAccessibleName(u"CapybaraGram · Notes / Templates"_q);
\t_capyTools->setToolTip(u"CapybaraGram · Заметки / Шаблоны"_q);
\t_capyTools->setClickedCallback([=] { showCapyTools(); });''')
        text = replace(text, '\t_search->moveToRight(_rightTaken, otherButtonsTop);', '''\t_capyTools->moveToRight(_rightTaken, otherButtonsTop);
\tif (!_capyTools->isHidden()) _rightTaken += _capyTools->width();
\t_search->moveToRight(_rightTaken, otherButtonsTop);''')
        text = replace(text, '\t_menuToggle->setVisible(hasMenu\n', '''\t_capyTools->setVisible(hasMenu && !_chooseForReportReason
\t\t&& !_searchMode && !visible && (_narrowRatio < 1.)
\t\t&& _activeChat.key.peer() && !_activeChat.key.sublist());
\t_menuToggle->setVisible(hasMenu
''')
        method = '''void TopBarWidget::showCapyTools() {
\tif (!createMenu(_capyTools)) return;
\tconst auto addAction = Ui::Menu::CreateAddActionCallback(_menu);
\tCapy::AddNoteAction(_controller, _activeChat, addAction);
\tif (_capyDraftInserter) {
\t\tconst auto weak = QPointer<TopBarWidget>(this);
\t\tconst auto epoch = _capyContextEpoch;
\t\tCapy::AddTemplatesAction(_controller, _activeChat, [weak, epoch](QString text) {
\t\t\treturn weak && weak->_capyContextEpoch == epoch
\t\t\t\t&& weak->_capyDraftInserter && weak->_capyDraftInserter(std::move(text));
\t\t}, addAction);
\t}
\tif (_menu->empty()) { closeMenu(); return; }
\t_menu->setForcedOrigin(Ui::PanelAnimation::Origin::TopRight);
\t_menu->popup(mapToGlobal(QPoint(_capyTools->x() + _capyTools->width(), height())));
}

'''
        return replace(text, 'void TopBarWidget::showPeerMenu() {', method+'void TopBarWidget::showPeerMenu() {')
    raise ValueError('Unexpected appearance host: '+name)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def plan(source, platform, check=False):
    root = Path(source).resolve(strict=True)
    manifest = json.loads((HERE/(platform+'-hashes.json')).read_text())
    result = {}
    for name, info in manifest['files'].items():
        path = root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Appearance destination escapes checkout')
        if 'asset' in info:
            output = (HERE/info['asset']).read_bytes()
            if digest(output) != info['post']: raise ValueError('Changed appearance asset')
        if check:
            raw = path.read_bytes()
            if info.get('text'): raw = raw.replace(b'\r\n',b'\n')
            if digest(raw) != info['post']: raise ValueError('Appearance output differs: '+name)
            continue
        if info['pre'] is None:
            if path.exists(): raise ValueError('Will not overwrite added appearance file')
        else:
            raw = path.read_bytes()
            if info.get('text'): raw = raw.replace(b'\r\n',b'\n')
            if digest(raw) != info['pre']: raise ValueError('Appearance input differs: '+name)
        if 'asset' not in info:
            output = transform(name,raw.decode('utf-8')).encode('utf-8')
        if digest(output) != info['post']: raise ValueError('Appearance transformation differs')
        result[name] = output
    return result

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('platform',choices=SHAS);p.add_argument('source',type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    head=subprocess.run(['git','-C',str(a.source),'rev-parse','HEAD'],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    if head != SHAS[a.platform]: raise ValueError('Unexpected upstream revision')
    changes=plan(a.source,a.platform,a.check)
    for name,raw in changes.items():
        dest=a.source/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    print('PASS: native',a.platform,'appearance', 'verified' if a.check else 'applied')
