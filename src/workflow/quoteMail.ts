import {addDays} from '../erp/model';
import {CASE, risk, type Workflow} from './engine';
import type {RemoteWorkspace} from '../connected/connection';

export async function runFirstReview(approve:boolean,save:()=>Promise<unknown>,command:()=>Promise<RemoteWorkspace>,stored:(s:Workflow)=>void,open:(s:Workflow,revision:number)=>Promise<void>){
 await save();
 const result=await command();
 if(!result.workflow)throw Error('승인 저장 결과를 확인할 수 없습니다.');
 stored(result.workflow);
 if(approve)await open(result.workflow,result.revision);
 return result;
}

export interface EmailForm {vendor_id:string;vendor_name:string;sender_email:string;recipient_email:string;subject:string;body:string;}
export function quoteForm(s:Workflow,id:string,sender=''):EmailForm {
 const v=s.data.vendors.find(v=>v.id===id)! ,p=s.data.products[0],q=s.inquiries.find(q=>q.vendor===id)!;
 const lines=s.data.productions.map(x=>`- ${x.id}: 투입 ${x.date} / ${x.il7}${p.unit} / 희망 입고 ${addDays(x.date,-s.data.config.qcDays-s.data.config.qaDays)}`).join('\n');
 return {vendor_id:v.id,vendor_name:v.name,sender_email:sender,recipient_email:v.quoteEmail||'',subject:`견적 요청: ${p.id} · ${CASE}`,body:`${v.name} 담당자님께,\n업체 담당자: ${v.quoteEmail||'주소 설정 필요'}\n\n아래 원료의 견적 및 공급 조건 회신을 요청드립니다.\n구매요청: ${CASE}\n원료: ${p.id} / ${p.sku} / ${p.name}\n규격: ${p.form} / ${p.content} / ${p.grade}\n단위: ${p.unit}\n요청 수량: ${risk(s).required}${p.unit}\n생산 투입 및 희망 입고 일정:\n${lines}\n회신 기한: ${q.deadline}\n\n확인 요청 사항:\n1. 단가, MOQ, 주문 배수, 운송비\n2. 분할 납품 가능 여부 및 회차별 수량·입고일 확약\n3. Lot별 유효기간, CoA 및 운송·품질 문서\n4. 지급 조건, 견적 유효기간, 변경·취소 조건\n\n본 문의는 공급 확인을 위한 요청이며 최종 구매 발주 승인이 아닙니다.\n감사합니다.\nBioFlow 구매팀`};
}
export function quotePayload(s:Workflow,form:EmailForm,revision:number){return {...form,case_id:CASE,inquiry_id:s.inquiries.find(q=>q.vendor===form.vendor_id)!.id,expected_revision:revision,material_code:s.data.products[0].id,material_name:s.data.products[0].name,unit:s.data.products[0].unit,required_quantity:risk(s).required,safety_stock:s.data.products[0].safety,schedule:s.data.productions.map(p=>({production_id:p.id,needed_date:p.date,quantity:p.il7}))};}
export function recipientError(address:string,mode:string){
 if(!/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(address))return '공급업체 담당자 이메일이 없거나 형식이 잘못됐습니다. 업체 정보에서 수정하세요.';
 if(mode==='live'&&/@(?:.*\.)?(?:example\.(?:com|net|org)|test|invalid|localhost)$/i.test(address))return '예시 업체 주소로 실제 발송할 수 없습니다. 업체 정보에서 수정하세요.';
 return '';
}
