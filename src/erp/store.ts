import {BASE,createSeed,type ErpData,type Scenario,applyScenario} from './model';
import {analyze,fingerprint,type PurchaseOrder,type Report} from './calculator';
const KEY='bioflow-erp-v2';
export interface Saved {data:ErpData;orders:PurchaseOrder[];reports:Report[];}
export function validate(d:ErpData):string[]{const errors:string[]=[];const validDate=(s:string)=>/^\d{4}-\d{2}-\d{2}$/.test(s)&&!Number.isNaN(Date.parse(s))&&new Date(s+'T00:00:00Z').toISOString().slice(0,10)===s;
 const number=(n:number,label:string,min=0,integer=false)=>{if(!Number.isFinite(n)||n<min||(integer&&!Number.isInteger(n)))errors.push(label+' 값이 유효하지 않습니다.');};
 for(const l of d.lots){number(l.quantity,l.id+' 수량',0,true);if(!validDate(l.expiry))errors.push(l.id+' 유효일 확인 필요');}
 for(const p of d.productions){number(p.il7,p.id+' IL-7 수요',0,true);number(p.il15,p.id+' IL-15 수요',0,true);if(!validDate(p.date)||!validDate(p.completion)||!validDate(p.delivery)||p.date<BASE||p.date>p.completion||p.completion>p.delivery)errors.push(p.id+' 투입·완료·납품 날짜 순서가 잘못되었습니다.');}
 for(const v of d.vendors){if(v.quoteEmail!==undefined&&(typeof v.quoteEmail!=='string'||v.quoteEmail.length>254))errors.push('견적 담당자 이메일은 254자 이내 문자열이어야 합니다.');number(v.unitPrice,'단가',0);number(v.moq,'MOQ',1,true);number(v.multiple,'주문배수',1,true);number(v.shipping,'운송비');if(!validDate(v.quoteExpiry))errors.push('견적 유효일 확인 필요');for(const s of v.shipments){number(s.quantity,'확약 수량',1,true);number(s.qcDelay,'QC 대기',0,true);number(s.cashLimit,'현금 한도',0);if(!validDate(s.arrival)||!validDate(s.expiry)||!validDate(s.payment)||s.arrival<BASE||s.arrival>s.expiry)errors.push(s.id+' 입고/유효/지급일 확인 필요');}}
 for(const p of d.products){number(p.safety,'안전재고',0,true);number(p.capacity,'보관용량',1,true);}
 for(const [key,v] of Object.entries(d.config))if(typeof v==='number')number(v,key,0);
 if(!Number.isInteger(d.config.qcDays)||!Number.isInteger(d.config.qaDays))errors.push('QC·QA 기간은 정수 일수입니다.');
 return errors;
}
export function load():Saved{try{const s=JSON.parse(localStorage.getItem(KEY)||'null');if(s?.data?.schema===2&&Array.isArray(s.orders)&&Array.isArray(s.reports)&&!validate(s.data).length){analyze(s.data);return s}}catch{/* Fall back only for unusable persisted data. */}return {data:createSeed(),orders:[],reports:[]};}
export function save(s:Saved){try{localStorage.setItem(KEY,JSON.stringify({...s,reports:s.reports.slice(0,10)}));return true}catch{return false}}
export function revise(d:ErpData,next:ErpData,entity:string,field:string,before:string,after:string):ErpData{const errors=validate(next);if(errors.length)throw Error(errors.join(' '));return {...next,revision:d.revision+1,changes:[{id:`CHG-${d.revision+1}`,at:new Date().toISOString(),entity,field,before,after},...d.changes].slice(0,100)};}
export function scenarioData(d:ErpData,id:Scenario){const next=applyScenario(id);return revise(d,next,'SCENARIO','독립 기준 데이터로 전환',d.config.scenario,id);}
export function reviewOrders(orders:PurchaseOrder[],d:ErpData){const fp=fingerprint(d);return orders.map(o=>({...o,status:o.fingerprint===fp&&o.revision===d.revision?'가상 발주 승인' as const:'재검토 필요' as const}));}
