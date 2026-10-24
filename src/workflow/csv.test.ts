import {describe,it,expect} from 'vitest';
import {createSeed} from '../erp/model';
import {csvKinds,exportCSV,importCSV,parseCSV} from './csv';
import {calculateRisks} from './rules';
import {seedWorkflow,detect,inquiryApprovalValid,editData,receiveReplies,runAgent,agents,integrate,extraAnalyze,registerPO} from './engine';
import {addProduction,approveQuoteRequests,quoteDraft} from './procurement';

describe('CSV 원본 검증과 관계 보존',()=>{
 it('6종 CSV를 BOM·CRLF·한글·숫자·품질 상태를 유지해 왕복한다',()=>{let d=createSeed();for(const k of csvKinds){const csv=exportCSV(d,k);d=importCSV(d,k,csv);expect(parseCSV(exportCSV(d,k))).toEqual(parseCSV(csv))}expect(calculateRisks(d,'2026-10-24')[0].required).toBe(12)});
 it('따옴표 안의 쉼표·개행·이스케이프를 보존한다',()=>{expect(parseCSV('id,name\r\nA,"한글, 본문\n두번째 ""인용"""\r\n')[1]).toEqual(['A','한글, 본문\n두번째 "인용"']);expect(()=>parseCSV('id,id\n1,2')).toThrow('중복');expect(()=>parseCSV('id,name\nA,"open')).toThrow('닫히지')});
 it('잘못된 날짜·원료 참조·중복 ID는 원본을 바꾸지 않는다',()=>{const d=createSeed();expect(()=>importCSV(d,'production',exportCSV(d,'production').replace('2026-11-04','2026-02-30'))).toThrow();const csv=exportCSV(d,'lots');expect(()=>importCSV(d,'lots',csv.replace('MAT-IL7','UNKNOWN'))).toThrow('원료');expect(()=>importCSV(d,'lots',csv.replace('IL7-LOT-02','IL7-LOT-01'))).toThrow('중복');expect(d.lots[0].material).toBe('MAT-IL7')});
});
describe('생산·QC·납기 변경과 자동 감지',()=>{
 it('추가 생산 수요를 재계산하고 기존 승인을 무효화한다',()=>{const base=approveQuoteRequests(detect(seedWorkflow()));const n=addProduction(base,{id:'PROD-04',name:'추가',date:'2026-11-25',completion:'2026-11-30',delivery:'2026-12-03',il7:4,il15:12,budget:0});const risks=calculateRisks(n.data,n.now);expect(risks[0].required).toBe(16);expect(risks[1].required).toBe(6);expect(inquiryApprovalValid(n)).toBe(false);expect(n.notifications.some(x=>x.title.includes('MAT-IL15'))).toBe(true);expect(()=>quoteDraft(n,'B')).toThrow('승인')});
 it('동일 위험의 반복 계산은 알림·로그를 중복 생성하지 않는다',()=>{const once=detect(seedWorkflow());const twice=detect(once);expect(twice).toBe(once);expect(twice.notifications).toHaveLength(1)});
 it('입고 예정은 QC/QA 완료일에만 배정하고 장부·현재 가용에 합산하지 않는다',()=>{const d=createSeed();d.plannedReceipts=[{id:'EXIST-1',material:'MAT-IL7',vendor:'B',lot:'EXIST-LOT',quantity:4,arrival:'2026-10-30',expiry:'2027-03-31',confirmed:true,qaHold:false,qcDelay:0}];const r=calculateRisks(d,'2026-10-24')[0];expect(r.stock).toBe(2);expect(r.ledger).toBe(6);expect(r.required).toBe(8);d.plannedReceipts[0].qcDelay=3;expect(calculateRisks(d,'2026-10-24')[0].rows[0].shortage).toBe(2);d.plannedReceipts[0].confirmed=false;expect(calculateRisks(d,'2026-10-24')[0].required).toBe(12)});
 it('업체 리드타임이 길어지면 검토 기한과 위험도가 바뀐다',()=>{const d=createSeed();for(const v of d.vendors)v.leadDays=20;const r=calculateRisks(d,'2026-10-24')[0];expect(r.level).toBe('긴급');expect(r.reviewBy).toBe('2026-10-11')});
 it('견적 승인 후 업체별 수량·QC 일정·생산별 필요일로 초안을 만든다',()=>{const s=approveQuoteRequests(seedWorkflow());const b=quoteDraft(s,'B');expect(b.required_quantity).toBe(12);expect(b.schedule).toHaveLength(3);expect(b.body).toContain('QC 2일 + QA 1일');expect(b.body).toContain('2026-11-04');expect(s.orders).toHaveLength(0)});
});

it('기존 PO를 보존한 상태로 추가 부족에 대한 견적 요청만 별도 승인한다',()=>{let s=receiveReplies(approveQuoteRequests(seedWorkflow()));for(const a of agents)s=runAgent(s,a.id);s=integrate(s);if(s.extraRequests.some(r=>!r.resolved))s=extraAnalyze(s);s=registerPO(s);const original=structuredClone(s.orders[0]);s=addProduction(s,{id:'PROD-04',name:'추가',date:'2026-11-25',completion:'2026-11-30',delivery:'2026-12-03',il7:4,il15:4,budget:0});s=approveQuoteRequests(s);expect(quoteDraft(s,'B').required_quantity).toBe(4);expect(s.orders[0]).toEqual(original)});

it('동일 CSV 재적용은 버전·승인을 변경하지 않아 중복 요청 우회가 되지 않는다',()=>{const s=approveQuoteRequests(detect(seedWorkflow()));const n=editData(s,importCSV(s.data,'production',exportCSV(s.data,'production')),'CSV:production','동일값');expect(n.data.revision).toBe(s.data.revision);expect(inquiryApprovalValid(n)).toBe(true)});

it('이미 가상 확약된 업체는 새 승인 없이 실제 견적 메일 대상으로 전환하지 않는다',()=>{const s=receiveReplies(approveQuoteRequests(seedWorkflow()));expect(()=>quoteDraft(s,'B')).toThrow('이미 처리');expect(quoteDraft(approveQuoteRequests(s),'B').required_quantity).toBe(12)});
