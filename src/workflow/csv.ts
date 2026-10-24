import {type ErpData} from '../erp/model';
import {validate} from '../erp/store';
export const csvKinds=['materials','production','lots','suppliers','shipments','receipts'] as const;
export type CsvKind=typeof csvKinds[number];
export const csvLabels:Record<CsvKind,string>={materials:'원료·안전재고',production:'생산계획',lots:'Lot 재고·품질',suppliers:'공급업체·견적',shipments:'공급 회차',receipts:'기존 입고 예정'};
export function parseCSV(text:string):string[][]{
 if(text.length>2_000_000)throw Error('CSV는 2MB 이하로 등록하세요.');
 const rows:string[][]=[];let row:string[]=[],cell='',quoted=false,closed=false;const input=text.replace(/^\uFEFF/,'');
 for(let i=0;i<input.length;i++){const c=input[i];if(quoted){if(c==='"'){if(input[i+1]==='"'){cell+='"';i++}else{quoted=false;closed=true}}else cell+=c;continue}
 if(c==='"'){if(cell||closed)throw Error('CSV 따옴표 형식이 잘못되었습니다.');quoted=true}else if(c===','){row.push(cell);cell='';closed=false}else if(c==='\n'||c==='\r'){if(c==='\r'&&input[i+1]==='\n')i++;row.push(cell);if(row.some(x=>x!==''))rows.push(row);row=[];cell='';closed=false}else{if(closed)throw Error('따옴표 뒤에 구분자가 필요합니다.');cell+=c}}
 if(quoted)throw Error('CSV 따옴표가 닫히지 않았습니다.');row.push(cell);if(row.some(x=>x!==''))rows.push(row);
 if(!rows.length)throw Error('CSV 헤더가 필요합니다.');const headers=rows[0];if(new Set(headers).size!==headers.length||headers.some(x=>!x))throw Error('중복되거나 빈 CSV 열 이름이 있습니다.');if(rows.slice(1).some(r=>r.length!==headers.length))throw Error('CSV 행의 열 개수가 헤더와 다릅니다.');return rows;
}
const encode=(v:unknown)=>'"'+String(v??'').replace(/"/g,'""')+'"';
export function csvRecords(data:ErpData,kind:CsvKind):Record<string,unknown>[] {
 if(kind==='materials')return data.products.map(p=>({id:p.id,name:p.name,safety:p.safety,unit:p.unit}));
 if(kind==='production')return data.productions.map(p=>({...p}));
 if(kind==='lots')return data.lots.map(l=>({...l}));
 if(kind==='suppliers')return data.vendors.map(({shipments,...v})=>({...v,email:v.email||'',leadDays:v.leadDays??Math.max(0,Math.round((Date.parse(shipments[0]?.arrival||'2026-10-24')-Date.parse('2026-10-24'))/86400000))}));
 if(kind==='shipments')return data.vendors.flatMap(v=>v.shipments.map(l=>({vendor:v.id,...l})));
 return (data.plannedReceipts||[]).map(l=>({...l}));
}
const emptyReceipt=['id','material','vendor','lot','quantity','arrival','expiry','confirmed','qaHold','qcDelay'];
export function exportCSV(data:ErpData,kind:CsvKind){const rows=csvRecords(data,kind),headers=rows.length?Object.keys(rows[0]):kind==='receipts'?emptyReceipt:[];return '\uFEFF'+[headers.map(encode).join(','),...rows.map(r=>headers.map(k=>encode(r[k])).join(','))].join('\r\n')+'\r\n'}
export function importCSV(data:ErpData,kind:CsvKind,text:string):ErpData{
 const [headers,...values]=parseCSV(text);const expected=Object.keys(csvRecords(data,kind)[0]||Object.fromEntries(emptyReceipt.map(k=>[k,''])));
 if(expected.some(k=>!headers.includes(k))||headers.some(k=>!expected.includes(k)))throw Error('CSV 열이 맞지 않습니다. 이 화면에서 내려받은 원본 양식을 사용하세요.');
 const numeric=new Set(['safety','il7','il15','budget','quantity','unitPrice','moq','multiple','shipping','qcDelay','cashLimit','leadDays']);const boolean=new Set(['approved','productApproved','confirmed','qaHold']);
 const rows=values.map(cells=>Object.fromEntries(headers.map((k,i)=>{const raw=cells[i];if(numeric.has(k)){if(!/^\d+(\.\d+)?$/.test(raw)||!Number.isFinite(Number(raw)))throw Error(k+'에는 0 이상의 수를 입력하세요.');return [k,Number(raw)]}if(boolean.has(k)){if(raw!=='true'&&raw!=='false')throw Error(k+'는 true/false여야 합니다.');return [k,raw==='true']}return [k,raw]})));
 const ids=rows.map(r=>String(r.id));if(new Set(ids).size!==ids.length||ids.some(x=>!x.trim()))throw Error('CSV 행 ID는 비어 있거나 중복될 수 없습니다.');
 const d=structuredClone(data);
 if(kind==='materials'){if(rows.length!==d.products.length||rows.some(r=>!d.products.some(p=>p.id===r.id)))throw Error('기존 원료 코드는 유지해야 합니다.');d.products=d.products.map(p=>({...p,...rows.find(r=>r.id===p.id)})) as ErpData['products']}
 if(kind==='production')d.productions=rows as unknown as ErpData['productions'];
 if(kind==='lots'){for(const r of rows){if(!d.products.some(p=>p.id===r.material)||!['합격','품질 보류'].includes(String(r.qc))||!['승인','미승인'].includes(String(r.qa))||!['적합','이탈'].includes(String(r.temperature)))throw Error('Lot 원료·품질 상태가 유효하지 않습니다.')}d.lots=rows as unknown as ErpData['lots']}
 if(kind==='suppliers'){if(rows.length!==d.vendors.length||rows.some(r=>!d.vendors.some(v=>v.id===r.id)))throw Error('기존 공급업체 코드는 유지해야 합니다.');d.vendors=d.vendors.map(v=>({...v,...rows.find(r=>r.id===v.id)})) as ErpData['vendors']}
 if(kind==='shipments'){if(rows.some(r=>!d.vendors.some(v=>v.id===r.vendor)))throw Error('공급 회차의 공급업체 코드가 없습니다.');d.vendors=d.vendors.map(v=>({...v,shipments:rows.filter(r=>r.vendor===v.id).map(({vendor,...l})=>l)})) as ErpData['vendors'];if(d.vendors.some(v=>!v.shipments.length))throw Error('공급업체별 회차가 하나 이상 필요합니다.')}
 if(kind==='receipts'){if(rows.some(r=>!d.products.some(p=>p.id===r.material)||!d.vendors.some(v=>v.id===r.vendor)))throw Error('입고 예정의 원료·업체 코드가 없습니다.');d.plannedReceipts=rows as unknown as ErpData['plannedReceipts']}
 const errors=validate(d);if(errors.length)throw Error(errors.join(' '));return d;
}
