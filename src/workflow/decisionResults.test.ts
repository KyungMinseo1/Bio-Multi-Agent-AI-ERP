import {it,expect} from 'vitest';
import {displayResult,outcomePayload,costFields} from './decisionResults';
it('미입력과 명시적 0 및 false를 구분한다',()=>{
 expect(displayResult(null)).toBe('미확인');expect(displayResult(0)).toBe('0');expect(displayResult(false)).toBe('false');
 const p=outcomePayload({revision:2},{actual_purchase_cost:'0',used_quantity:'0',production_delayed:'false',change_reason:'확인'},[],'real');
 expect(p.actual_purchase_cost).toBe('0');expect(p.used_quantity).toBe(0);expect(p.production_delayed).toBe(false);expect(p.actual_transport_cost).toBeNull();expect(p.remaining_quantity).toBeNull();expect(p.production_delay_days).toBeNull();
});
it('통화 입력 정밀도를 보존하며 폐기 구매원가를 중복 합산하지 않는다',()=>{
 const p=outcomePayload({revision:0},{actual_purchase_cost:'100000000000.000001',actual_disposal_cost:'3.20',expired_quantity:'10'},[],'demo');
 expect(p.actual_purchase_cost).toBe('100000000000.000001');expect(p.actual_disposal_cost).toBe('3.20');expect(costFields).toHaveLength(5);expect(Object.keys(p)).not.toContain('expired_purchase_cost');expect(Object.keys(p)).not.toContain('savings');
});
it('실제 날짜의 빈 값은 null이고 근거는 줄 단위로 보존한다',()=>{
 const p=outcomePayload({revision:4},{evidence_refs:['GRN-1',' COA-2 ',''].join(String.fromCharCode(10)),change_reason:'회신 확인'},[{line_id:'L1',actual_arrival:'2026-11-01',usable_date:''}],'real');
 expect(p.receipts).toEqual([{line_id:'L1',actual_arrival:'2026-11-01',usable_date:null}]);expect(p.evidence_refs).toEqual(['GRN-1','COA-2']);expect(p.expected_revision).toBe(4);expect(p.production_delayed).toBeNull();
});
