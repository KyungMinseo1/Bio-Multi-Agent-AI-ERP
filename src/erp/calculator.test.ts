import {describe,expect,it} from 'vitest';
import {createSeed,applyScenario} from './model';
import {analyze,approvalErrors,createOrder,executeStage,fingerprint,stages} from './calculator';
import {revise,reviewOrders,validate} from './store';
const report=(d= createSeed())=>({id:'TEST-R'+d.revision,revision:d.revision,fingerprint:fingerprint(d),createdAt:new Date().toISOString(),analysis:analyze(d),events:stages.map((_,i)=>executeStage(d,i)),data:structuredClone(d)});
describe('scenario_1.pdf 기준 데이터',()=>{
 it('장부 6개, 생산 가용 2개, 총 수요 12개, 신규 12개',()=>{const a=analyze(createSeed());expect(a.need).toEqual({ledger:6,stock:2,total:12,safety:2,required:12});expect(a.il15.ok).toBe(true)});
 it('품질 보류와 생산 전 만료는 서로 다른 원인으로 제외한다',()=>{const d=createSeed(),ev1=executeStage(d,1),ev2=executeStage(d,2);expect(ev1.rows).toEqual(['IL7-LOT-02']);expect(ev2.rows).toEqual(['IL7-LOT-03']);expect(d.lots[1].qa).toBe('미승인')});
 it('A MOQ20, B12 · 구매운송 1610만/1230만 · 차이380만',()=>{const [A,B,C]=analyze(createSeed()).options;expect(A.quantity).toBe(20);expect(B.quantity).toBe(12);expect(A.subtotal).toBe(16100000);expect(B.subtotal).toBe(12300000);expect(A.subtotal-B.subtotal).toBe(3800000);expect(C.supplied).toBe(0)});
 it('A 잔여10개는 11월30일 만료 위험, 장부가800만원은 총비용 중복가산 안함',()=>{const a=analyze(createSeed()).options[0];expect(a.remaining).toBe(10);expect(a.waste).toBe(10);expect(a.wasteValue).toBe(8000000);expect(a.total).toBe(a.subtotal+a.testing+a.storage+a.disposal)});
 it('B 가용일은 11.02/11.09/11.16, 각 생산후2개를 유지',()=>{const b=analyze(createSeed()).options[1];expect(b.deliveries.map(s=>s.available)).toEqual(['2026-11-02','2026-11-09','2026-11-16']);expect(b.checks.map(p=>p.after)).toEqual([2,2,2]);expect(b.points.map(p=>p.stock)).toEqual([2,6,2,6,2,6,2]);expect(b.eligible).toBe(true);expect(analyze(createSeed()).selected).toBe('B')});
 it('기존 보류·만료 Lot와 QC 대기분도 물리 보관비에 포함',()=>{const d=createSeed(),base=analyze(d).options[1].storage;d.lots[1].quantity+=3;expect(analyze(d).options[1].storage).toBeGreaterThan(base)});
});
describe('독립 변형과 가용성',()=>{
 it('2회차 QC +3일 →11.12 → PROD-02 2개 부족 및 추천보류',()=>{const a=analyze(applyScenario('qc-delay'));const b=a.options[1];expect(b.deliveries[1].available).toBe('2026-11-12');expect(b.checks.find(p=>p.id==='PROD-02')!.shortage).toBe(2);expect(a.selected).toBeNull();expect(a.actions.join(' ')).toContain('2026-11-05')});
 it('온도 이탈은 해당 회차만 보류하고 AI가 품질해제하지 않음',()=>{const d=applyScenario('temperature'),b=analyze(d).options[1];expect(b.deliveries.map(s=>s.included)).toEqual([true,false,true]);expect(b.shortage).toBe(2);expect(d.vendors[1].shipments[1].qaHold).toBe(true)});
 it('특정 Lot 품질 이슈는 업체 전체를 차단하지 않음',()=>{const d=applyScenario('quality-scope'),b=analyze(d).options[1];expect(d.vendors[1].approved).toBe(true);expect(b.deliveries[0].included).toBe(true);expect(b.deliveries[1].included).toBe(false)});
 it('관련성 미확인 공지는 감점·차단 없이 B안을 유지',()=>{const a=analyze(applyScenario('unrelated'));expect(a.selected).toBe('B');expect(a.warnings[0]).toContain('자동 감점')});
 it('C 공급 미확약과 제품 미승인을 독립 사유로 표시',()=>{const base=analyze(createSeed()).options[2],variant=analyze(applyScenario('c-quality')).options[2];expect(base.qualityApproved).toBe(true);expect(base.constraints).toContain('출하 수량·일정 미확약');expect(variant.constraints).toContain('업체/제품 품질 미승인');expect(variant.constraints).toContain('출하 수량·일정 미확약')});
 it('현금 부족은 예산 초과와 구분',()=>{const a=analyze(applyScenario('cash')),b=a.options[1];expect(b.total).toBeLessThan(a.need.required*1000000+1000000);expect(b.constraints).toContain('지급일 현금 한도 부족');expect(b.constraints).not.toContain('구매·운송 예산 초과');expect(a.selected).toBeNull()});
 it('생산 연기 시 A는 12월 투입 불가, B는 미출하 변경 확인',()=>{const a=analyze(applyScenario('production-delay'));expect(a.options[0].checks[2].shortage).toBe(4);expect(a.options[0].waste).toBe(14);expect(a.actions.join(' ')).toContain('서면 확인');expect(applyScenario('production-delay').vendors[1].shipments[1].qcDelay).toBe(0)});
});
describe('사용자 편집·추적·승인 경계',()=>{
 it('가격 변경은 소계·총비용·적격성에 반영',()=>{const d=createSeed();d.vendors[1].unitPrice=1500000;const a=analyze(d);expect(a.options[1].subtotal).toBe(18300000);expect(a.selected).toBeNull()});
 it('MOQ를 올려도 미확약 추가 공급을 만들어내지 않는다',()=>{const d=createSeed();d.vendors[1].moq=20;const b=analyze(d).options[1];expect(b.quantity).toBe(20);expect(b.supplied).toBe(12);expect(b.eligible).toBe(false)});
 it('수량/일정이 변경되면 이전 추천으로 PO를 생성하지 못함',()=>{const d=createSeed(),r=report(d),next=structuredClone(d);next.productions[1].il7=5;const changed=revise(d,next,'PROD-02','il7','4','5');expect(approvalErrors(changed,r).join()).toContain('stale');expect(()=>createOrder(changed,r,[])).toThrow();expect(r.data.productions[1].il7).toBe(4)});
 it('revision을 조작해도 원본 fingerprint 변화로 승인 차단',()=>{const d=createSeed(),r=report(d);d.lots[0].quantity=3;expect(approvalErrors(d,r).join()).toContain('stale')});
 it('PO 승인 후 재고·QC/QA 불변, 중복 PO 금지',()=>{const d=createSeed(),r=report(d),before=structuredClone(d);const po=createOrder(d,r,[]);expect(po.quantity).toBe(12);expect(po.shipments).toHaveLength(3);expect(d).toEqual(before);expect(()=>createOrder(d,r,[po])).toThrow('이미 존재')});
 it('부족 시나리오는 승인 차단, 생략실행도 실제 계산 근거 생성',()=>{const d=applyScenario('qc-delay'),r=report(d);expect(()=>createOrder(d,r,[])).toThrow('적격');expect(r.events).toHaveLength(12);expect(r.events[9].formula).toContain('2026-11-12');expect(r.events[9].snapshot).toHaveLength(3)});
 it('기록된 이벤트 스냅샷은 원본 변경과 독립',()=>{const d=createSeed(),ev=executeStage(d,0);d.lots[0].quantity=90;expect(ev.snapshot[0].quantity).toBe(2)});
 it('잘못된 수량·날짜·QC 일수 입력은 저장 거부',()=>{const d=createSeed();d.lots[0].quantity=-1;d.config.qcDays=1.5;d.vendors[1].shipments[0].arrival='2026-02-30';expect(validate(d).length).toBeGreaterThanOrEqual(3)});
 it('동일 지급일 여러 회차는 현금 한도를 공유한다',()=>{const d=createSeed();d.vendors[1].shipments.forEach(s=>{s.payment='2026-10-30';s.cashLimit=5000000});expect(analyze(d).options[1].cash.filter(c=>c.date==='2026-10-30').every(c=>!c.ok)).toBe(true)});
 it('다른 revision의 작업 로그로 현재 추천을 승인하지 못한다',()=>{const d=createSeed(),r=report(d);r.events[0].revision=99;expect(approvalErrors(d,r).join()).toContain('작업 로그');expect(()=>createOrder(d,r,[])).toThrow()});
 it('동일 내용으로 복원해도 revision이 다르면 기존 PO 재검토, 중복 PO 생성은 차단',()=>{const d=createSeed(),r=report(d),po=createOrder(d,r,[]),next={...d,revision:2};const orders=reviewOrders([po],next);expect(orders[0].status).toBe('재검토 필요');expect(()=>createOrder(next,report(next),orders)).toThrow('이미 존재')});
 it('B 단가가 더 낮아지면 최초 제안·전략 유지 판단도 실제 견적에 따라 변경',()=>{const d=createSeed();d.vendors[1].unitPrice=700000;expect(executeStage(d,4).result).toContain('최초 검토: B');expect(executeStage(d,10).title).toContain('전략 유지');expect(analyze(d).selected).toBe('B')});
 it('가용 재고가 충분하면 0개 PO 대신 신규 발주 불필요로 판정',()=>{const d=createSeed();d.lots[0].quantity=20;const a=analyze(d);expect(a.need.required).toBe(0);expect(a.selected).toBeNull();expect(a.actions.join(' ')).toContain('신규 발주가 필요하지');expect(()=>createOrder(d,report(d),[])).toThrow()});
 it('물리 보관구역 용량은 보류·만료 재고도 포함해 검증',()=>{const d=createSeed();d.products[0].capacity=10;expect(analyze(d).options[1].constraints).toContain('보관구역 합성 용량 초과')});
});
