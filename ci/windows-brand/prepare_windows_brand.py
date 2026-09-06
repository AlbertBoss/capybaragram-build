# SPDX-License-Identifier: MIT
"""Apply original CapybaraGram resources and native intro to a pinned Desktop tree."""
import argparse, hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = 'Telegram/SourceFiles/intro/'
FILES = [PREFIX+'intro_start.cpp',PREFIX+'intro_step.cpp',PREFIX+'intro_step.h','Telegram/Resources/winrc/Telegram.rc']
TITLE_FILES = [
    'Telegram/SourceFiles/window/main_window.cpp',
    'Telegram/SourceFiles/window/window_restore_shell.cpp',
    'Telegram/SourceFiles/window/window_saved_windows.cpp',
    'Telegram/SourceFiles/boxes/about_box.cpp',
]
FILES += TITLE_FILES
ASSETS = {'Telegram/Resources/art/icon256.ico':'capy-icon.ico',
    'Telegram/Resources/art/logo_256.png':'capy-logo.png',
    'Telegram/Resources/art/logo_256_no_margin.png':'capy-logo.png'}

def replace(text,old,new,count=1):
    if text.count(old) != count: raise ValueError('Windows brand anchor differs')
    return text.replace(old,new)

def transform(name,text):
    if name == FILES[0]:
        text = replace(text,'setTitleText(rpl::single(u"Telegram Desktop"_q));','setTitleText(rpl::single(u"CapybaraGram"_q));')
        return replace(text,'setDescriptionText(tr::lng_intro_about());','''setDescriptionText(rpl::merge(
		rpl::single(rpl::empty), Lang::Updated()
	) | rpl::map([] {
		return Lang::Id().startsWith(u"ru"_q)
			? u"Неофициальный клиент Telegram.\\nОбщение в своём ритме."_q
			: u"An unofficial Telegram client.\\nChat at your own pace."_q;
	}));''')
    if name == FILES[1]:
        text = replace(text,'void Step::prepareCoverMask() {\n','''void Step::prepareCoverMask() {
	if (_capyCoverIcon.isNull()) {
		_capyCoverIcon = QPixmap(u":/gui/art/logo_256.png"_q);
	}
''')
        text = replace(text,'anim::color(st::introCoverTopBg, st::introCoverBottomBg, y / realHeight)',
            'anim::color(QColor(54, 92, 69), QColor(65, 105, 78), y / realHeight)')
        start = text.index('\tauto left = 0;',text.index('void Step::paintCover('))
        end = text.index('\n}\n\nint Step::contentLeft()',start)
        return text[:start]+'''	const auto capySize = st::introCoverTitleTop - st::introCoverIconTop;
	const auto capyTop = top + (st::introCoverTitleTop - capySize) / 2;
	p.save();
	p.setRenderHint(QPainter::SmoothPixmapTransform);
	p.drawPixmap(QRect((width() - capySize) / 2, capyTop, capySize, capySize), _capyCoverIcon);
	p.restore();'''+text[end:]
    if name == FILES[2]:
        return replace(text,'\tQPixmap _coverMask;','\tQPixmap _coverMask;\n\tQPixmap _capyCoverIcon;')
    if name == FILES[3]:
        text = replace(text,'VALUE "CompanyName", "Telegram FZ-LLC"','VALUE "CompanyName", "CapybaraGram"')
        text = replace(text,'VALUE "FileDescription", "Telegram Desktop"','VALUE "FileDescription", "CapybaraGram - unofficial Telegram client"')
        return replace(text,'VALUE "ProductName", "Telegram Desktop"','VALUE "ProductName", "CapybaraGram"')
    if name in TITLE_FILES[:3]:
        return replace(text, 'u"Telegram"_q', 'u"CapybaraGram"_q')
    if name == TITLE_FILES[3]:
        return replace(text, 'box->setTitle(u"Telegram Desktop"_q);',
            'box->setTitle(u"CapybaraGram"_q);')
    raise ValueError('Unexpected brand source')

def digest(raw,text=False):
    return hashlib.sha256(raw.replace(b'\r\n',b'\n') if text else raw).hexdigest()

def plan(source,check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((ROOT/'input-hashes.json').read_text())
    if set(manifest['pre']) != set(FILES)|set(ASSETS) or set(manifest['post']) != set(manifest['pre']):
        raise ValueError('Windows brand allowlist differs')
    result = {}
    for name in FILES+list(ASSETS):
        path = source/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError('Brand source path escapes checkout')
        raw = path.read_bytes()
        if digest(raw,name in FILES) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Pinned Windows brand input differs: '+name)
        if check: result[name] = raw; continue
        output = transform(name,raw.decode('utf-8').replace('\r\n','\n')).encode('utf-8') if name in FILES else (ROOT/ASSETS[name]).read_bytes()
        if digest(output,name in FILES) != manifest['post'][name]:
            raise ValueError('Windows brand output differs: '+name)
        result[name] = output
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source',type=Path)
    p.add_argument('--check',action='store_true')
    args = p.parse_args()
    head = subprocess.run(['git','-C',str(args.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
    if head != '80158983dba09d3bf5d96701f21473d6c34bf5f5': raise ValueError('Desktop revision differs')
    result = plan(args.source,args.check)
    if not args.check:
        for name,raw in result.items(): (args.source/name).write_bytes(raw)
    print('PASS:',len(result),'Windows brand files','verified' if args.check else 'prepared')
