import {addDays,BASE,type ErpData} from '../erp/model';
export interface PlannedReceipt {id:string;material:string;vendor:string;lot:string;quantity:number;arrival:string;expiry:string;confirmed:boolean;qaHold:boolean;qcDelay:number;}
interface Order {lines:{id:string;lot:string;quantity:number;expiry:string;available:string;stage:string;blocked:boolean;confirmed:boolean;qaAt:string;}[];}
export function calculateRisks(data:ErpData,now:string,orders:Order[]=[],produced:string[]=[]){
 return data.products.map(product=>{
  const quantity=(p:ErpData['productions'][number])=>product.id==='MAT-IL7'?p.il7:product.id==='MAT-IL15'?p.il15:0;
  const plans=data.productions.filter(p=>!produced.includes(p.id)&&quantity(p)>0).sort((a,b)=>a.date.localeCompare(b.date));
  const firstDate=plans[0]?.date||now.slice(0,10);
  const lots=data.lots.filter(l=>l.material===product.id);
  const reviewed=lots.map(l=>({...l,usable:l.qc==='합격'&&l.qa==='승인'&&l.temperature==='적합'&&l.expiry>=firstDate,reason:l.qc!=='합격'||l.qa!=='승인'?'QC/QA 미승인':l.temperature!=='적합'?'온도 이탈':l.expiry<firstDate?'투입 전 만료':'승인 재고'}));
  const bins=reviewed.filter(l=>l.usable).map(l=>({qty:l.quantity,expiry:l.expiry,available:orders.flatMap(o=>o.lines).find(x=>x.lot===l.id)?.qaAt||l.received}));
  const registered=orders.flatMap(o=>o.lines);
  const releases=[...(product.id==='MAT-IL7'?registered.filter(l=>l.stage!=='QA 승인'&&!l.blocked&&l.confirmed).map(l=>({id:l.id,date:l.available,qty:l.quantity,expiry:l.expiry})):[]),...(data.plannedReceipts||[]).filter(l=>l.material===product.id&&l.confirmed&&!l.qaHold&&!registered.some(x=>x.id===l.id||x.lot===l.lot)&&!lots.some(x=>x.id===l.lot)&&data.vendors.some(v=>v.id===l.vendor&&v.approved&&v.productApproved)).map(l=>({id:l.id,date:addDays(l.arrival,data.config.qcDays+data.config.qaDays+l.qcDelay),qty:l.quantity,expiry:l.expiry}))].sort((a,b)=>a.date.localeCompare(b.date));
  let cursor=0;
  const rows=plans.map(p=>{while(cursor<releases.length&&releases[cursor].date<=p.date){const l=releases[cursor++];bins.push({qty:l.qty,expiry:l.expiry,available:l.date})}for(const l of bins)if(l.expiry<p.date)l.qty=0;const before=bins.filter(l=>l.available<=p.date).reduce((n,l)=>n+l.qty,0);let wanted=quantity(p);for(const l of bins.filter(l=>l.available<=p.date)){const used=Math.min(l.qty,wanted);l.qty-=used;wanted-=used}return {id:p.id,date:p.date,customer:p.delivery,need:quantity(p),before,shortage:wanted,after:bins.filter(l=>l.available<=p.date).reduce((n,l)=>n+l.qty,0)}});
  const shortage=rows.reduce((n,p)=>n+p.shortage,0),safetyGap=rows.length?Math.max(0,product.safety-rows.at(-1)!.after):0;
  const first=rows.find(p=>p.shortage>0)||rows.find(p=>p.after<product.safety);
  const leadTimes=data.vendors.filter(v=>v.approved&&v.productApproved).map(v=>({id:v.id,days:v.leadDays??Math.max(0,Math.round((Date.parse(v.shipments[0]?.arrival||BASE)-Date.parse(BASE))/86400000))}));
  const lead=leadTimes.length?Math.min(...leadTimes.map(v=>v.days)):0;
  const earliest=addDays(now.slice(0,10),lead+data.config.qcDays+data.config.qaDays);
  const level=shortage?(first&&earliest>first.date?'긴급':'위험'):safetyGap?'주의':'정상';
  return {material:product.id,name:product.name,unit:product.unit,level,shortage,safetyGap,required:shortage+safetyGap,firstDate:first?.date||'—',reviewBy:first?addDays(first.date,-(lead+data.config.qcDays+data.config.qaDays+1)):now.slice(0,10),rows,earliest,lead,leadTimes,qcDays:data.config.qcDays,qaDays:data.config.qaDays,reviewed,releases,stock:reviewed.filter(l=>l.usable&&l.received<=now.slice(0,10)).reduce((n,l)=>n+l.quantity,0),ledger:lots.reduce((n,l)=>n+l.quantity,0),safety:product.safety};
 });
}
