// One coordinate unit is exactly 120 mm. Geometry is never shrunk to draw seams.
export const EPS=1e-6;
export const clone=x=>structuredClone(x);
export const uid=()=>globalThis.crypto?.randomUUID?.()||Math.random().toString(36).slice(2);
export function turn(x,z,a){const r=a*Math.PI/180;return [Math.cos(r)*x+Math.sin(r)*z,-Math.sin(r)*x+Math.cos(r)*z]}
export function worldBrick(g,b){const p=turn(b.c[0],b.c[2],g.angle);const a=(g.angle+(b.a||0))*Math.PI/180;return {id:b.id,c:[p[0]+g.x,b.c[1],p[1]+g.z],h:b.d.map(v=>v/2),u:[Math.cos(a),-Math.sin(a)],v:[Math.sin(a),Math.cos(a)]}}
const dot=(p,a)=>p[0]*a[0]+p[1]*a[1];
const radius=(b,a)=>Math.abs(dot(b.u,a))*b.h[0]+Math.abs(dot(b.v,a))*b.h[2];
export function separation(a,b,axis){return Math.abs(dot([b.c[0]-a.c[0],b.c[2]-a.c[2]],axis))-radius(a,axis)-radius(b,axis)}
export function overlap(a,b){if(a.h[1]+b.h[1]-Math.abs(a.c[1]-b.c[1])<=EPS)return false;return [a.u,a.v,b.u,b.v].every(axis=>separation(a,b,axis)<-EPS)}
export function contact(a,b){const vertical=Math.abs(a.c[1]-b.c[1])-a.h[1]-b.h[1];const axes=[a.u,a.v,b.u,b.v];if(Math.abs(vertical)<=EPS)return axes.every(axis=>separation(a,b,axis)<-EPS);if(vertical>=-EPS)return false;return [a.u,a.v].some(axis=>[b.u,b.v].some(other=>Math.abs(dot(axis,other))>1-EPS)&&Math.abs(separation(a,b,axis))<=EPS&&axes.filter(other=>Math.abs(dot(axis,other))<1-EPS).every(other=>separation(a,b,other)<-EPS))}
export function allBricks(groups){return groups.flatMap(g=>g.bricks.map(b=>({g,b,w:worldBrick(g,b)})))}
export function validateBrick(groups,g,b,ignoreId=null){const w=worldBrick(g,b);if(w.c[1]-w.h[1]<-EPS)return {ok:false,reason:'Деталь ниже поверхности поля'};const rest=allBricks(groups).filter(x=>x.b.id!==ignoreId);const collisions=rest.filter(x=>overlap(w,x.w));if(collisions.length)return {ok:false,reason:'Недостаточно места: детали пересекаются',collisions};if(w.c[1]-w.h[1]>EPS&&!rest.some(x=>contact(w,x.w)))return {ok:false,reason:'Нужно соприкосновение граней без зазора'};return {ok:true,reason:w.c[1]-w.h[1]<EPS?'На снежном поле':'Точная стыковка · зазор 0 мм'}}
export function validateGroup(groups,candidate,ignoreId=null){const ws=candidate.bricks.map(b=>worldBrick(candidate,b));const rest=allBricks(groups.filter(g=>g.id!==ignoreId));for(const w of ws){if(w.c[1]-w.h[1]<-EPS)return {ok:false,reason:'Постройка ниже поверхности поля'};if(rest.some(x=>overlap(w,x.w)))return {ok:false,reason:'Постройки пересекаются'}}return {ok:true,reason:'Можно установить'}}
export function snapGroup(groups,candidate,ignoreId=null){const rest=allBricks(groups.filter(g=>g.id!==ignoreId));let best=null;const moving=candidate.bricks.filter(b=>b.c[1]<1.1).map(b=>worldBrick(candidate,b));const near=rest.filter(x=>x.b.c[1]<1.1);for(const a of moving)for(const {w:b} of near){if(Math.hypot(a.c[0]-b.c[0],a.c[2]-b.c[2])>5)continue;if(![a.u,a.v].some(u=>Math.abs(dot(u,b.u))>1-EPS))continue;for(const axis of [b.u,b.v]){const tangent=[-axis[1],axis[0]];if(separation(a,b,tangent)>-0.15)continue;const delta=dot([a.c[0]-b.c[0],a.c[2]-b.c[2]],axis);const gap=Math.abs(delta)-radius(a,axis)-radius(b,axis);if(Math.abs(gap)>0.65)continue;const shift=-gap*(delta>=0?1:-1);if(best&&Math.abs(shift)>=best.dist)continue;const c={...candidate,x:candidate.x+axis[0]*shift,z:candidate.z+axis[1]*shift};if(validateGroup(groups,c,ignoreId).ok)best={group:c,dist:Math.abs(shift)}}}return best?{...best,snapped:true}:{group:candidate,snapped:false}}
export function rotateBrick(b,axis){const n=clone(b),d=n.d;if(axis==='y')[d[0],d[2]]=[d[2],d[0]];if(axis==='x')[d[1],d[2]]=[d[2],d[1]];if(axis==='z')[d[0],d[1]]=[d[1],d[0]];const delta=turn((d[0]-b.d[0])/2,(d[2]-b.d[2])/2,b.a||0);n.c=[b.c[0]+delta[0],b.c[1]+(d[1]-b.d[1])/2,b.c[2]+delta[1]]; // preserve the oriented minimum corner
return n}
export function counts(groups,settings){let full=0,half=0;for(const g of groups)for(const b of g.bricks)b.kind==='half'?half++:full++;const parts=full+half,make=full+Math.ceil(half/2),team=Math.max(1,Math.floor(settings.team)||1),cycle=Math.max(1,Number(settings.cycle)||30),lay=Math.max(0,Number(settings.lay)||0);const manufacture=Math.ceil(make/team)*cycle,assembly=Math.ceil(parts/team)*lay;return {full,half,parts,make,manufacture,assembly,seconds:manufacture+assembly}}
export function timeLabel(seconds){seconds=Math.ceil(seconds);const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;return [h?`${h} ч`:null,m?`${m} мин`:null,s||(!h&&!m)?`${s} сек`:null].filter(Boolean).join(' ')}
function brick(x,y,z,dx=2,dz=1){return {id:uid(),kind:dx*dz===1?'half':'full',c:[x+dx/2,y+0.5,z+dz/2],d:[dx,1,dz],a:0}}
export function wall(length=8,height=6){const bs=[];for(let y=0;y<height;y++){let x=0;if(y%2){bs.push(brick(x,y,0,1));x++}for(;x+2<=length;x+=2)bs.push(brick(x,y,0));if(x<length)bs.push(brick(x,y,0,1))}return bs}
export function corner(n=8,height=6){const bs=[];for(let y=0;y<height;y++){if(y%2===0){for(let x=0;x<n;x+=2)bs.push(brick(x,y,0));for(let z=1;z<n;){const len=Math.min(2,n-z);bs.push(brick(0,y,z,1,len));z+=len}}else{for(let z=0;z<n;z+=2)bs.push(brick(0,y,z,1,2));for(let x=1;x<n;){const len=Math.min(2,n-x);bs.push(brick(x,y,0,len));x+=len}}}return bs}
export function tower(n=8,height=7){
  const bs=[];
  for(let y=0;y<=height;y++){
    const row=[];
    if(y%2===0){
      for(let x=0;x<n;x+=2){row.push(brick(x,y,0));row.push(brick(x,y,n-1))}
      for(let z=1;z<n-1;z+=2){row.push(brick(0,y,z,1,2));row.push(brick(n-1,y,z,1,2))}
    }else{
      for(let z=0;z<n;z+=2){row.push(brick(0,y,z,1,2));row.push(brick(n-1,y,z,1,2))}
      for(let x=1;x<n-1;x+=2){row.push(brick(x,y,0));row.push(brick(x,y,n-1))}
    }
    // The crenels are a subset of the next bonded row, including its corner orientation.
    bs.push(...(y===height?row.filter(b=>{const start=b.d[0]===2?b.c[0]-1:b.c[2]-1;return y%2?b.d[2]===2?start%4===0:start%4===3:b.d[0]===2?start%4===0:start%4===3}):row));
  }
  return bs;
}
export function centered(bs){const xs=bs.flatMap(b=>[b.c[0]-b.d[0]/2,b.c[0]+b.d[0]/2]),zs=bs.flatMap(b=>[b.c[2]-b.d[2]/2,b.c[2]+b.d[2]/2]);const x=(Math.min(...xs)+Math.max(...xs))/2,z=(Math.min(...zs)+Math.max(...zs))/2;return bs.map(b=>({...b,c:[b.c[0]-x,b.c[1],b.c[2]-z]}))}
export function presets(){return [{id:'wall',name:'Прямая стена',note:'960 × 120 × 720 мм',bricks:centered(wall())},{id:'corner',name:'Угловая секция',note:'Связанные углы · 6 рядов',bricks:centered(corner())},{id:'tower',name:'Квадратная башня',note:'С зубцами · 960 × 960 мм',bricks:centered(tower())}]}
export function instantiate(template,x=0,z=0,angle=0){return {id:uid(),name:template.name,x,z,angle,bricks:template.bricks.map(b=>({...clone(b),id:uid()}))}}
export function demo(){const p=presets();return [instantiate(p[2],-8,-6),instantiate(p[2],8,-6),instantiate(p[0],0,-9.5),instantiate(p[0],-11.5,2,90),instantiate(p[0],11.5,2,90),instantiate(p[1],-8,9,180),instantiate(p[0],6,5.5)]}
