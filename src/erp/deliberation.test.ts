import {describe,it,expect} from 'vitest';
import {applyScenario,createSeed} from './model';
import {analyze} from './calculator';
import {departmentVerdicts,stagePlaybackMs} from './deliberation';
import {spreadsheetColumn} from './DataGrid';
describe('4개 부서 판단과 Admin 조정',()=>{
 it('기준안에서 구매/생산은 A, 재고/재무는 B를 선호하지만 최종은 B',()=>{const d=createSeed(),a=analyze(d),v=departmentVerdicts(d,a);expect(v).toHaveLength(4);expect(v.map(x=>x.vendor)).toEqual(['A','B','A','B']);expect(new Set(v.map(x=>x.agent)).size).toBe(4);expect(a.selected).toBe('B');expect(v[0].reason).toContain('800,000원');expect(v[2].tradeoff).toContain('16,100,000원')});
 it('수정 단가와 QC 지연이 부서 판단 및 최종안에 실제 반영',()=>{const d=createSeed();d.vendors[1].unitPrice=700000;expect(departmentVerdicts(d)[0].vendor).toBe('B');const delayed=applyScenario('qc-delay');expect(departmentVerdicts(delayed)[2].vendor).toBe('A');expect(analyze(delayed).selected).toBeNull()});
 it('필요량0이면 4개 부서도 추가 주문을 추천하지 않음',()=>{const d=createSeed();d.lots[0].quantity=20;expect(departmentVerdicts(d).every(v=>v.vendor===null)).toBe(true)});
});
describe('작업별 재생 속도와 스프레드시트 주소',()=>{
 it('조회는 짧고 재무·생산·Admin 조정은 길다',()=>{const d=createSeed();expect(stagePlaybackMs(d,0,1800)).toBeLessThan(500);expect(stagePlaybackMs(d,11,1800)).toBeGreaterThan(4000);expect(stagePlaybackMs(d,8,1800)).toBeGreaterThan(stagePlaybackMs(d,4,1800)*5)});
 it('실제 일정 제약이 생기면 검토 단계를 더 오래 보여준다',()=>{expect(stagePlaybackMs(applyScenario('qc-delay'),8,1800)).toBeGreaterThan(stagePlaybackMs(createSeed(),8,1800));expect(stagePlaybackMs(createSeed(),11,4000)).toBeLessThanOrEqual(14000)});
 it('Excel 열 주소는 A..Z, AA..AZ, BA로 표시',()=>{expect([0,25,26,51,52].map(spreadsheetColumn)).toEqual(['A','Z','AA','AZ','BA'])});
});
