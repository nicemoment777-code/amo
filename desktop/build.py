"""Сборка личного установщика и архива виджета без секретов и данных заказов."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import zipfile
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent.parent
RUNTIME=Path(os.environ['USERPROFILE'])/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
sys.path.insert(0,str(ROOT/'data'/'build-tools'))
sys.path.insert(0,str(ROOT/'data'/'printing'/'vendor'))
import PyInstaller.__main__

def assets():
    dest=ROOT/'widget'/'images'; dest.mkdir(parents=True,exist_ok=True)
    sizes={'logo_main':(400,272),'logo_small':(108,108),'logo':(130,100),'logo_medium':(240,84),'logo_min':(84,84),'tour_ru':(1188,616)}
    for name,(width,height) in sizes.items():
        image=Image.new('RGB',(width,height),'#153d30'); draw=ImageDraw.Draw(image)
        unit=min(width,height); x=int(width*.14); y=int(height*.18); w=int(unit*.56); h=int(unit*.6)
        draw.rounded_rectangle((x,y,x+w,y+h),radius=max(2,int(unit*.03)),fill='#f5f7ee')
        for i in range(11):
            bx=x+int(w*.12)+int(i*w*.065)
            draw.rectangle((bx,y+int(h*.4),bx+max(1,int(w*.025)),y+int(h*.76)),fill='#153d30')
        if name=='tour_ru':
            font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',34)
            draw.multiline_text((width*.53,height*.24),'Печать СДЭК\n\nАртикулы сверху\nЭтикетка 1:1\nКаждые 5 минут',font=font,fill='white',spacing=16)
        image.save(dest/(name+'.png'),optimize=True)

def build():
    if not (ROOT/'widget'/'images'/'logo.png').exists(): assets()
    (ROOT/'dist').mkdir(exist_ok=True)
    separator=os.pathsep
    args=[str(ROOT/'desktop'/'app.py'),'--name','SnowbrickPrinter','--onedir','--windowed','--noconfirm','--clean',
          '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'), '--specpath',str(ROOT/'build'),
          '--paths',str(ROOT/'ops'),'--paths',str(ROOT/'data'/'printing'/'vendor'),
          '--hidden-import','pypdf','--hidden-import','reportlab.pdfbase.ttfonts','--hidden-import','PIL.Image','--hidden-import','zxingcpp',
          '--collect-all','reportlab','--collect-all','pypdf']
    for name in ['print-agent.py','label_pdf.py','print_order.py','printer_routing.py','auto_print.py','pdf_archive.py','print_journal.py','print-image.ps1']:
        args+=['--add-data',str(ROOT/'ops'/name)+separator+'ops']
    for file in (RUNTIME/'native'/'poppler'/'Library'/'bin').iterdir():
        if file.suffix.lower()=='.dll' or file.name=='pdftoppm.exe':
            args+=['--add-binary',str(file)+separator+'poppler']
    PyInstaller.__main__.run(args)
    target=ROOT/'dist'/'SnowbrickPrinter'
    # Preserve bundled vendor licensing alongside the private installation.
    license_root=RUNTIME/'native'/'poppler'/'info'/'licenses'
    if license_root.exists(): shutil.copytree(license_root,target/'licenses'/'poppler',dirs_exist_ok=True)
    shutil.copy2(ROOT/'docs'/'WINDOWS-APP.md',target/'Инструкция.md')
    payload=ROOT/'build'/'payload.zip'
    with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for file in target.rglob('*'):
            if file.is_file(): archive.write(file,file.relative_to(target))
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/reference:System.Windows.Forms.dll','/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll','/reference:Microsoft.CSharp.dll','/resource:'+str(payload)+',payload.zip','/out:'+str(ROOT/'dist'/'SnowbrickSetup.exe'),str(ROOT/'desktop'/'Setup.cs')],check=True)
    with zipfile.ZipFile(ROOT/'dist'/'snowbrick-amocrm-widget.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for file in (ROOT/'widget').rglob('*'):
            if file.is_file(): archive.write(file,file.relative_to(ROOT/'widget'))

if __name__=='__main__': build()
