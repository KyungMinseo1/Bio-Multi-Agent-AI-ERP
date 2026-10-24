import {describe,it,expect} from 'vitest';
import {addDays,BASE,depletion,materials,risk,stockDays,suppliers} from './data';
import {BUDGET,meetingSteps,quotes,recommendation,REQUIRED} from './engine';
describe('가상 ERP 데이터의 정합성',()=>{
 it('FGF-2는 6일 커버리지로 10월 30일 소진된다',()=>{expect(stockDays(materials[0])).toBe(6);expect(depletion(materials[0])).toBe('2026-10-30');expect(risk(materials[0])).toBe('위험')});
 it('모든 Lot은 기준일에 유효하고 공급업체가 존재한다',()=>{for(const m of materials){expect(m.expiry>BASE).toBe(true);expect(suppliers.some(s=>s.name===m.supplier)).toBe(true);expect(m.stock).toBeGreaterThan(0)}});
 it('월 경계를 넘어 날짜를 올바르게 계산한다',()=>{expect(addDays(BASE,14)).toBe('2026-11-07')});
});
describe('납기·품질·비용을 고려한 발주 결정',()=>{
 it('최저가 A는 QC 완료일이 마감을 초과하여 제외된다',()=>{const a=quotes().find(s=>s.id==='A')!;expect(a.total).toBe(5880000);expect(a.available).toBe('2026-11-07');expect(a.eligible).toBe(false)});
 it('정상 시나리오에서 B가 승인 후보 중 최저가다',()=>{const s=recommendation();expect(s.id).toBe('B');expect(s.total).toBe(7080000);expect(s.available).toBe('2026-10-30');expect(s.total).toBeLessThan(BUDGET);expect(s.available<=REQUIRED&&s.quality).toBe(true)});
 it('정전 발생 시 B 사용일을 10일 연기하고 C로 전환한다',()=>{const b=quotes(true).find(s=>s.id==='B')!;expect(b.available).toBe('2026-11-09');expect(b.eligible).toBe(false);const c=recommendation(true);expect(c.id).toBe('C');expect(c.total-recommendation().total).toBe(360000);expect(c.available).toBe('2026-10-31')});
 it('품질 미승인 공급업체는 선택하지 않는다',()=>{for(const s of quotes()){if(!s.quality)expect(s.eligible).toBe(false)}});
 it('정상/사고 시나리오 모두 6개 Agent가 한번씩 기여한다',()=>{for(const outage of [false,true]){const steps=meetingSteps(outage);expect(steps).toHaveLength(6);expect(new Set(steps.map(s=>s.agent)).size).toBe(6);expect(steps.at(-1)?.agent).toBe(5)}});
 it('분할 대안은 72만원 절감하며 B 긴급 물량은 8일분이다',()=>{const split=24*118000+36*98000;expect(split).toBe(6360000);expect(recommendation().total-split).toBe(720000);expect(24/materials[0].daily).toBe(8)});
});
