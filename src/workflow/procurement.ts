import {supplierEmailError,normalizeSupplierEmails} from './supplierEmail';
import type {RemoteWorkspace} from '../connected/connection';
import {validate} from '../erp/store';
import {addDays,type Production,type Vendor} from '../erp/model';
import {approveInquiry,startInquiries,inquiryApprovalValid,intentStamp,editData,risk,CASE,type Workflow} from './engine';
export function approveQuoteRequests(s:Workflow,approve=true){if(approve&&inquiryApprovalValid(s)&&s.inquiries.length&&s.inquiries.every(q=>q.status==='요청중'||q.status==='대상 제외'))return s;const old=s.inquiries;let approved:Workflow;if(s.orders.length){approved=structuredClone(s);approved.deferred=!approve;approved.approvals.unshift({id:'RFQ-APR-'+Date.now().toString(36),kind:1,at:s.now,actor:'구매 담당자',decision:approve?'승인':'보류',fingerprint:intentStamp(s.data),reason:'기존 PO 보존 · 추가 부족에 대한 견적 요청만 검토'});approved.audit.unshift({id:'RFQ-APR-LOG-'+Date.now().toString(36),at:s.now,actor:'구매 담당자',action:approve?'추가 견적 요청 승인':'추가 견적 요청 보류',entity:CASE,detail:'실제 추가 PO 생성·기존 PO 변경은 별도 승인 필요',revision:s.data.revision})}else approved=approveInquiry(s,approve);if(!approve)return approved;const n=startInquiries({...approved,inquiries:[]});for(const q of n.inquiries){const previous=old.find(x=>x.vendor===q.vendor);if(previous)q.history=[...previous.history,{at:n.now,status:'견적 요청 승인 갱신',note:'현재 생산 수요·일정에 대한 새 견적 요청'},...q.history]}return n;}

export function addProduction(s:Workflow,p:Production){if(s.data.productions.some(x=>x.id===p.id))throw Error('같은 생산번호가 이미 등록되어 있습니다.');const data=structuredClone(s.data);data.productions.push(p);return editData(s,data,p.id,'추가 생산계획 등록');}
export function quoteDraft(s:Workflow,vendorId:string){
 if(!inquiryApprovalValid(s))throw Error('견적 요청 1차 승인이 필요하거나 현재 원본과 승인 범위가 다릅니다.');
 const vendor=s.data.vendors.find(v=>v.id===vendorId),q=s.inquiries.find(x=>x.vendor===vendorId);
 if(!vendor?.approved||!vendor.productApproved||!q||q.status==='대상 제외')throw Error('승인된 공급업체 확인 요청이 필요합니다.');
 if(q.status!=='요청중'&&!(q.status==='미회신'&&q.history.some(h=>h.status==='실제 메일 발송 · 회신 대기')))throw Error('이미 처리된 회신입니다. 새 견적 요청은 승인 범위를 갱신하세요.');
 const r=risk(s),p=s.data.products[0];if(!r.required)throw Error('현재 부족량과 안전재고 기준 신규 확보 수량이 없습니다.');
 const schedule=s.data.productions.filter(p=>!s.produced.includes(p.id)).map(p=>({production_id:p.id,needed_date:p.date,quantity:p.il7}));
 const body=`${vendor.name} 담당자님께,\n\nBioFlow 구매 담당자입니다. 다음 원료의 견적과 공급 가능 조건을 요청드립니다.\n\n구매요청: ${CASE} / ERP 원본 R${s.data.revision}\n원료: ${p.name} (${p.id})\n확보 필요 수량: ${r.required}${p.unit}\n생산 부족 ${r.shortage} + 안전재고 보충 ${r.safetyGap} = ${r.required}${p.unit}\n최초 필요일: ${r.firstDate}\n발주 검토 기한: ${r.reviewBy}\n\n${schedule.map(x=>`${x.production_id}: 투입 ${x.needed_date}, 필요 ${x.quantity}${p.unit}, 희망 입고 ${addDays(x.needed_date,-s.data.config.qcDays-s.data.config.qaDays)} 이전`).join('\n')}\n\n단가, MOQ, 주문배수, 확약 수량, 회차별 입고일, 운송비, 견적 유효기간과 CoA/유효기간을 회신해 주세요.\nQC ${s.data.config.qcDays}일 + QA ${s.data.config.qaDays}일이 필요합니다. 입고 자체는 품질 사용 승인을 의미하지 않습니다.\n\n감사합니다.\nBioFlow 구매팀\n※ 합성 ERP 데이터에 기반한 견적 요청입니다. 실제 거래 확정·발주 승인은 별도입니다.`;
 return {case_id:CASE,vendor_id:vendor.id,vendor_name:vendor.name,recipient_email:vendor.email||'',subject:`[견적 요청] ${CASE} · ${p.id} · ${vendor.id} · R${s.data.revision}`,body,material_code:p.id,material_name:p.name,unit:p.unit,required_quantity:r.required,safety_stock:p.safety,schedule};
}
export function confirmSupplierReply(s:Workflow,vendorId:string,terms:Vendor,original:string,reference:string){
 if(!inquiryApprovalValid(s))throw Error('수요가 변경되어 견적 요청 승인을 다시 받아야 합니다.');
 const q=s.inquiries.find(x=>x.vendor===vendorId);if(!q||terms.id!==vendorId||!reference||!original.trim())throw Error('업체·회신 근거가 필요합니다.');
 const check=structuredClone(s.data);check.vendors=check.vendors.map(v=>v.id===vendorId?terms:v);const errors=validate(check);if(errors.length)throw Error(errors.join(' '));
 const n=structuredClone(s);const target=n.inquiries.find(x=>x.vendor===vendorId)!;const approved=n.data.vendors.find(x=>x.id===vendorId)!;
 if(!approved.approved||!approved.productApproved)throw Error('미승인 공급업체의 회신은 확약으로 등록할 수 없습니다.');
 target.terms={...structuredClone(terms),approved:approved.approved,productApproved:approved.productApproved,confirmed:true};target.status='공급 확인';target.original=original;target.repliedAt=n.now;target.validUntil=terms.quoteExpiry+'T18:00:00+09:00';target.missing=[];target.history.push({at:n.now,status:'담당자 회신 확인',note:reference});n.findings=[];n.integration=null;n.extraRequests=[];n.audit.unshift({id:'REPLY-'+reference,at:n.now,actor:'구매 담당자',action:'근거 확인 후 공급 회신 등록',entity:q.id,detail:reference,revision:n.data.revision});return n;
}

export function updateSupplierEmail(s:Workflow,vendorId:string,address:string){
 const email=address.trim().toLowerCase();if(email&&supplierEmailError(email))throw Error(supplierEmailError(email));
 const data=normalizeSupplierEmails(structuredClone(s.data)),vendor=data.vendors.find(v=>v.id===vendorId);if(!vendor)throw Error('공급업체를 찾을 수 없습니다.');
 vendor.email=email;return editData(s,data,vendorId,'견적 담당자 이메일 변경');
}
export async function saveQuoteReview(s:Workflow,approve:boolean,persist:(next:Workflow)=>Promise<RemoteWorkspace>,saved:(next:Workflow)=>void,open:()=>void){
 const result=await persist(approveQuoteRequests(s,approve));if(!result.workflow)throw Error('승인 저장 결과를 확인할 수 없습니다.');saved(result.workflow);if(approve)open();return result;
}
