# SPDX-License-Identifier: MIT
"""Apply the CapybaraGram intro to the pinned, otherwise prepared Android tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
INTRO = 'TMessagesProj/src/main/java/org/telegram/ui/IntroActivity.java'
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
    for name, asset in ADDED.items():
        dest = source/name
        if dest.is_symlink() or not dest.resolve().is_relative_to(source):
            raise ValueError('Brand resource path escapes source')
        raw = (ROOT/asset).read_bytes()
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
