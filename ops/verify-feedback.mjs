import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {createAmoCrm}=await import(pathToFileURL('/opt/amo/current/amocrm.mjs'));
const amo=await createAmoCrm(pathToFileURL('/var/lib/amo/amocrm.json'),'https://snowbrick.ru');
const catalog=await amo.printCandidates(0);
const stored=JSON.parse(await readFile('/var/lib/amo/amocrm.json','utf8'));
async function get(path){const response=await fetch('https://snegostroy.amocrm.ru'+path,{headers:{Authorization:'Bearer '+stored.accessToken}});if(!response.ok)throw Error('CRM HTTP '+response.status);return response.json();}
const pipeline=await get('/api/v4/leads/pipelines/8604134');
const stages=(pipeline._embedded?.statuses||[]).filter(v=>v.name?.trim().toLowerCase().replace(/\s+/g,' ')==='форма обратной связи');
const stageIds=new Set(stages.map(v=>v.id)),ids=new Set();
for(let page=1;page<=40;page++){const data=await get('/api/v4/leads?limit=250&filter[pipeline_id]=8604134&page='+page);for(const lead of data._embedded?.leads||[])if(stageIds.has(lead.status_id))ids.add(String(lead.id));if(!data._links?.next)break;}
let directBlocked=null;
if(ids.size){try{await amo.printLabel([...ids][0]);directBlocked=false;}catch(error){directBlocked=error.status===409;}}
console.log(JSON.stringify({feedbackStageFound:stages.length===1,feedbackCount:ids.size,visibleFeedback:catalog.items.filter(v=>ids.has(String(v.id))).length,directPrintingBlocked:directBlocked}));
