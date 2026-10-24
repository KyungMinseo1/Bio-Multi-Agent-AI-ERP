import {describe,it,expect,vi} from 'vitest';
import {approveInquiry,startInquiries,seedWorkflow,recordExternalMailSent,receiveReplies} from './engine';
import {quoteForm,quotePayload,recipientError,runFirstReview} from './quoteMail';

const ready=()=>startInquiries(approveInquiry(seedWorkflow()));
describe('승인 후 견적 작성',()=>{
 it('저장이 완료된 서버 승인 데이터로만 작성 화면을 연다',async()=>{
  const s=ready(),events:string[]=[];
  await runFirstReview(true,async()=>{events.push('saved')},async()=>{events.push('approved');return {revision:2,workflow:s,scenario_id:'main-workspace'}},()=>events.push('applied'),async(state,revision)=>{events.push('composer');expect(state).toBe(s);expect(revision).toBe(2)});
  expect(events).toEqual(['saved','approved','applied','composer']);
 });
 it.each(['저장 실패','버전 충돌'])('%s 시 작성 화면으로 이동하지 않는다',async error=>{
  const open=vi.fn(),command=vi.fn(async()=>{throw Error(error)});
  await expect(runFirstReview(true,async()=>{if(error==='저장 실패')throw Error(error)},command,vi.fn(),open)).rejects.toThrow(error);
  expect(open).not.toHaveBeenCalled();if(error==='저장 실패')expect(command).not.toHaveBeenCalled();
 });
 it('승인 보류는 작성 화면을 열지 않는다',async()=>{
  const open=vi.fn();await runFirstReview(false,async()=>{},async()=>({revision:2,workflow:approveInquiry(seedWorkflow(),false),scenario_id:'main-workspace'}),vi.fn(),open);expect(open).not.toHaveBeenCalled();
 });
 it('업체별 주소와 승인된 규격·일정·회신 기한을 채운다',()=>{
  const s=ready(),a=quoteForm(s,'A'),b=quoteForm(s,'B');
  expect(a.recipient_email).toBe('supplier-a@example.com');expect(b.recipient_email).toBe('supplier-b@example.com');
  for(const expected of [s.data.products[0].content,s.data.products[0].unit,s.inquiries[0].deadline,'MOQ','CoA',s.data.productions[0].date])expect(a.body).toContain(expected);
  expect(quotePayload(s,a,3).inquiry_id).toBe(s.inquiries[0].id);
  expect(startInquiries(s).inquiries).toEqual(s.inquiries);
 });
 it('주소 누락·예시 주소를 차단하고 공통 수신자로 대체하지 않는다',()=>{
  const s=ready();delete s.data.vendors[0].quoteEmail;
  expect(quoteForm(s,'A','sender@company.co.kr').recipient_email).toBe('');
  expect(recipientError('','test')).not.toBe('');expect(recipientError('bad','preview')).not.toBe('');
  expect(recipientError('supplier-a@example.com','live')).not.toBe('');expect(recipientError('supplier-a@example.com','preview')).toBe('');
 });
 it('발송 이력은 별도 업체 목록이 없어도 가상 회신에서 제외한다',()=>{
  const sent=recordExternalMailSent(ready(),'A','<mock@bioflow.local>');const s=receiveReplies(sent);
  expect(s.inquiries[0].terms).toBeNull();expect(s.inquiries[0].status).toBe('미회신');
  expect(s.inquiries[1].terms).not.toBeNull();
 });
});
