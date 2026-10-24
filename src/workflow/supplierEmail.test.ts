import {afterEach,it,expect,vi} from 'vitest';
import {createSeed} from '../erp/model';
import {seedWorkflow,inquiryApprovalValid} from './engine';
import {approveQuoteRequests,quoteDraft,updateSupplierEmail,saveQuoteReview} from './procurement';
import {normalizeSupplierEmails,supplierEmailError} from './supplierEmail';
import {loadFlow,saveFlow} from './store';
afterEach(()=>vi.unstubAllGlobals());
const ready=()=>approveQuoteRequests(seedWorkflow());
it('선택한 업체별 주소를 표시하고 공통 주소를 추정하지 않는다',()=>{
 const s=ready();expect(quoteDraft(s,'A').recipient_email).toBe('supplier-a@example.com');expect(quoteDraft(s,'B').recipient_email).toBe('supplier-b@example.com');
 delete s.data.vendors[0].email;expect(quoteDraft(s,'A').recipient_email).toBe('');
});
it('이전 quoteEmail을 email로 이어받고 현재 email이 있으면 우선한다',()=>{
 const data=createSeed();delete data.vendors[0].email;Object.assign(data.vendors[0],{quoteEmail:'old@supplier.co.kr'});Object.assign(data.vendors[1],{quoteEmail:'old-b@supplier.co.kr'});
 const migrated=normalizeSupplierEmails(data);expect(migrated.vendors[0].email).toBe('old@supplier.co.kr');expect(migrated.vendors[1].email).toBe('supplier-b@example.com');expect(migrated.vendors[0]).not.toHaveProperty('quoteEmail');
});
it('업체 이메일 변경을 저장하고 새 화면 로드 후에도 복원한다',()=>{
 const values=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>values.set(key,value)});
 const before=ready(),next=updateSupplierEmail(before,'B','Buyer@Supplier.co.kr');expect(saveFlow(next)).toBe(true);
 const loaded=loadFlow();expect(quoteDraft(loaded,'B').recipient_email).toBe('buyer@supplier.co.kr');expect(quoteDraft(loaded,'A').recipient_email).toBe('supplier-a@example.com');expect(inquiryApprovalValid(loaded)).toBe(true);expect(loaded.inquiries[1].status).toBe('요청중');
});
it.each(['','invalid','a..b@supplier.co.kr','a@supplier..co.kr'])('잘못된 수신 주소 %s에 수정 안내를 표시한다',email=>expect(supplierEmailError(email)).toContain('수정'));
it('예시 주소는 실제 발송에서 차단하고 시뮬레이션에는 허용한다',()=>{expect(supplierEmailError('supplier-a@example.com',true)).toContain('실제 발송');expect(supplierEmailError('supplier-a@example.com')).toBe('')});
it('승인 저장이 성공한 다음에만 작성 화면을 연다',async()=>{
 const s=seedWorkflow(),events:string[]=[];await saveQuoteReview(s,true,async next=>{events.push('save');return {workflow:next,revision:2,scenario_id:'main-workspace'}},()=>events.push('apply'),()=>events.push('composer'));expect(events).toEqual(['save','apply','composer']);
});
it.each(['저장 실패','버전 충돌'])('%s이면 작성 화면을 열지 않는다',async message=>{
 const open=vi.fn(),apply=vi.fn();await expect(saveQuoteReview(seedWorkflow(),true,async()=>{throw Error(message)},apply,open)).rejects.toThrow(message);expect(open).not.toHaveBeenCalled();expect(apply).not.toHaveBeenCalled();
});
it('보류는 저장해도 화면을 열지 않고 진행 중 승인은 문의를 중복 생성하지 않는다',async()=>{
 const s=ready(),open=vi.fn();expect(approveQuoteRequests(s).inquiries).toEqual(s.inquiries);await saveQuoteReview(s,false,async next=>({workflow:next,revision:2,scenario_id:'main-workspace'}),vi.fn(),open);expect(open).not.toHaveBeenCalled();
});
