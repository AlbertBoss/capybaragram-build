# SPDX-License-Identifier: MIT
"""Apply the CapybaraGram intro to the pinned, otherwise prepared Android tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import copy
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
INTRO = 'TMessagesProj/src/main/java/org/telegram/ui/IntroActivity.java'
LOGIN = 'TMessagesProj/src/main/java/org/telegram/ui/LoginActivity.java'
ICONS = 'TMessagesProj/src/main/java/org/telegram/ui/LauncherIconController.java'
ICON_VARIANTS = [
    ('DEFAULT','DefaultIcon','sand','#F2E9D9'),
    ('VINTAGE','VintageIcon','forest','#365C45'),
    ('AQUA','AquaIcon','water','#BBD9DC'),
    ('PREMIUM','PremiumIcon','clay','#CDA18A'),
    ('TURBO','TurboIcon','lilac','#CDC5DC'),
    ('NOX','NoxIcon','night','#272F32'),
]
ADDED = {
    'TMessagesProj/src/main/res/drawable/capy_intro.xml':'capy_intro.xml',
    'TMessagesProj/src/main/res/values/capy_brand.xml':'strings.xml',
    'TMessagesProj/src/main/res/values-ru/capy_brand.xml':'strings-ru.xml',
}

def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned intro anchor differs')
    return text.replace(old,new)

def transform(text):
    start = text.index('        titles = new CharSequence[]{')
    end = text.index('        return true;',start)
    titles = ',\n'.join('                LocaleController.getString(R.string.CapyIntroTitle'+str(i)+')' for i in range(1,7))
    messages = ',\n'.join('                LocaleController.getString(R.string.CapyIntroMessage'+str(i)+')' for i in range(1,7))
    text = text[:start]+'        titles = new CharSequence[]{\n'+titles+'\n        };\n        messages = new String[]{\n'+messages+'\n        };\n'+text[end:]
    start = text.index('        logoDrawable = context.getResources()')
    end = text.index('        actionBar.setAddToContainer(false);',start)
    text = text[:start]+text[end:]
    start = text.index('        TextureView textureView = new TextureView(context);')
    end = text.index('        viewPager = new ViewPager(context);',start)
    text = text[:start]+'''        android.widget.ImageView capyImage = new android.widget.ImageView(context);
        capyImage.setImageResource(R.drawable.capy_intro);
        capyImage.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        frameLayout2.addView(capyImage, LayoutHelper.createFrame(ICON_WIDTH_DP, ICON_HEIGHT_DP, Gravity.CENTER));

'''+text[end:]
    text = replace(text,'    private Drawable logoDrawable;\n','')
    text = replace(text,'                Intro.setScrollOffset(offset);\n','')
    text = replace(text,'            } else Intro.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundWhite));','            }') if '            } else Intro.setBackgroundColor' in text else replace(text,'        } else Intro.setBackgroundColor(Theme.getColor(Theme.key_windowBackgroundWhite));','        }')
    text = replace(text,'        logoDrawable.setColorFilter(Theme.multAlpha(getThemedColor(Theme.key_actionBarDefaultTitle), 0.9f), PorterDuff.Mode.MULTIPLY);\n','')
    text = replace(text,'        startMessagingButtonBackground.setColors(new int[]{getThemedColor(Theme.key_featuredStickers_addButton), getThemedColor(Theme.key_featuredStickers_addButton2)});',
        '        startMessagingButtonBackground.setColors(new int[]{0xff365c45, 0xff41694e});')
    text = replace(text,'        startMessagingButton.setTextColor(Theme.getColor(Theme.key_featuredStickers_buttonText));','        startMessagingButton.setTextColor(Color.WHITE);')
    text = replace(text,'''                if (size > dp(260)) {
                    super.onMeasure(MeasureSpec.makeMeasureSpec(dp(320), MeasureSpec.EXACTLY), heightMeasureSpec);
                } else {
                    super.onMeasure(widthMeasureSpec, heightMeasureSpec);
                }''','''                super.onMeasure(MeasureSpec.makeMeasureSpec(Math.min(size, dp(288)), MeasureSpec.EXACTLY), heightMeasureSpec);''')
    return text

def digest(data):
    return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()

def transform_identity(name,text):
    if name == LOGIN:
        return replace(text,
            'builder.setPositiveButton(getString("Continue", R.string.Continue), null);\n                                        builder.setMessage(getString("AllowFillNumber", R.string.AllowFillNumber));',
            'builder.setPositiveButton(getString(R.string.CapyPermissionContinue), null);\n                                        builder.setMessage(getString(R.string.CapyPhonePermission));')
    if name == ICONS:
        start = text.index('        DEFAULT("DefaultIcon",')
        end = text.index('\n\n',start)
        variants = [f'        {enum}("{alias}", R.drawable.capy_icon_bg_{key}, R.drawable.capy_icon_foreground, R.string.CapyIcon{key.title()})'
            for enum,alias,key,color in ICON_VARIANTS]
        # These are original client artwork, available to every account. No server entitlement is changed.
        return text[:start]+',\n'.join(variants)+';'+text[end:]
    raise ValueError('Unexpected identity source')

def generated_icons():
    ns = 'http://schemas.android.com/apk/res/android'
    ET.register_namespace('android',ns)
    a = '{'+ns+'}'
    def xml(doc): return b'<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(doc,encoding='utf-8')+b'\n'
    art = ET.parse(ROOT/'capy_intro.xml').getroot()
    foreground = ET.Element('vector',{a+'width':'108dp',a+'height':'108dp',a+'viewportWidth':'108',a+'viewportHeight':'108'})
    group = ET.SubElement(foreground,'group',{a+'scaleX':'0.42',a+'scaleY':'0.42',a+'translateX':'12',a+'translateY':'22.5'})
    # Original artwork spans x25..175/y4..146. At this scale it fits the central 66dp safe zone.
    for path in list(art)[1:]: group.append(copy.deepcopy(path))
    base = 'TMessagesProj/src/main/res/'
    result = {base+'drawable/capy_icon_foreground.xml':xml(foreground)}
    for enum,alias,key,color in ICON_VARIANTS:
        bg = ET.Element('shape',{a+'shape':'rectangle'})
        ET.SubElement(bg,'solid',{a+'color':color})
        result[base+f'drawable/capy_icon_bg_{key}.xml'] = xml(bg)
        legacy = copy.deepcopy(foreground)
        legacy.insert(0,ET.Element('path',{a+'fillColor':color,a+'pathData':'M0,0 H108 V108 H0 Z'}))
        result[base+f'drawable/capy_icon_{key}.xml'] = xml(legacy)
        adaptive = ET.Element('adaptive-icon')
        ET.SubElement(adaptive,'background',{a+'drawable':f'@drawable/capy_icon_bg_{key}'})
        ET.SubElement(adaptive,'foreground',{a+'drawable':'@drawable/capy_icon_foreground'})
        result[base+f'drawable-v26/capy_icon_{key}.xml'] = xml(adaptive)
    return result

def plan(source, check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((ROOT/'input-hashes.json').read_text())
    path = source/INTRO
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
        raise ValueError('Intro path escapes source')
    raw = path.read_bytes().replace(b'\r\n',b'\n')
    if digest(raw) != manifest['post' if check else 'pre']:
        raise ValueError('Intro source differs from pinned preparation')
    output = raw if check else transform(raw.decode('utf-8')).encode('utf-8')
    if digest(output) != manifest['post']:
        raise ValueError('Intro transform differs from reviewed output')
    result = {INTRO:output}
    for name in [LOGIN,ICONS]:
        dest = source/name
        if dest.is_symlink() or not dest.resolve(strict=True).is_relative_to(source):
            raise ValueError('Identity source path escapes source')
        raw = dest.read_bytes().replace(b'\r\n',b'\n')
        hashes = manifest['identity'][name]
        if digest(raw) != hashes['post' if check else 'pre']:
            raise ValueError('Identity input differs: '+name)
        output = raw if check else transform_identity(name,raw.decode('utf-8')).encode('utf-8')
        if digest(output) != hashes['post']: raise ValueError('Identity output differs')
        result[name] = output
    added = {name:(ROOT/asset).read_bytes() for name,asset in ADDED.items()}
    added.update(generated_icons())
    if set(added) != set(manifest['added']): raise ValueError('Brand resource inventory differs')
    for name, raw in added.items():
        dest = source/name
        if dest.is_symlink() or not dest.resolve().is_relative_to(source):
            raise ValueError('Brand resource path escapes source')
        if digest(raw) != manifest['added'][name]:
            raise ValueError('Brand resource differs')
        if check:
            if not dest.is_file() or digest(dest.read_bytes()) != digest(raw):
                raise ValueError('Installed brand resource differs')
        elif dest.exists():
            raise ValueError('Brand resource destination already exists')
        result[name] = raw
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    head = subprocess.run(['git','-C',str(args.source),'rev-parse','HEAD'],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    if head != '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c':
        raise ValueError('Android source revision differs')
    result = plan(args.source,args.check)
    if not args.check:
        for name, data in result.items():
            path = args.source/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
    print('PASS: native CapybaraGram intro', 'verified' if args.check else 'prepared')
