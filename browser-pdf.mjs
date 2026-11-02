import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const execute=promisify(execFile);
export async function browserPdf(items,contents){
  const dir=await mkdtemp(join(tmpdir(),'snowbrick-print-'));
  try{
    await writeFile(join(dir,'items.json'),JSON.stringify(items),{mode:0o600});
    for(let i=0;i<contents.length;i++)await writeFile(join(dir,i+'.pdf'),contents[i],{mode:0o600});
    await execute('/usr/bin/python3',[new URL('./ops/browser_pdf.py',import.meta.url).pathname,dir],{timeout:180000,maxBuffer:1024});
    return await readFile(join(dir,'batch.pdf'));
  }catch{throw new Error('Не удалось подготовить PDF или проверить все штрихкоды. Печать не выполнена.');}
  finally{await rm(dir,{recursive:true,force:true});}
}
