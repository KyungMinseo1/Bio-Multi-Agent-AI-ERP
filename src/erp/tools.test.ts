import {describe,it,expect} from 'vitest';
import {createSeed} from './model';
import {analyze} from './calculator';
import {callErpTool,validateInterpretation} from './tools';
describe('LLM 확장용 읽기 전용 도구 및 구조화 검증',()=>{
 it('허용 도구는 현재 ERP 근거를 반환하고 원본을 바꾸지 않는다',()=>{const d=createSeed(),before=structuredClone(d);expect(callErpTool(d,'query_lots',{material:'MAT-IL7'})).toMatchObject({revision:1});expect(d).toEqual(before);expect(()=>callErpTool(d,'approve_quality',{})).toThrow()});
 it('stale revision·허용되지 않은 원료를 거부한다',()=>{expect(()=>callErpTool(createSeed(),'validate_recommendation',{revision:99})).toThrow('stale');expect(()=>callErpTool(createSeed(),'query_lots',{material:'OTHER'})).toThrow()});
 it('모델 판단은 계산 결과 및 실제 근거 ID와 일치해야 한다',()=>{const a=analyze(createSeed()),v={revision:1,vendor:'B',evidenceIds:['EV-R1-12'],summary:'계산 결과 해석',actions:[]};expect(validateInterpretation(v,a,['EV-R1-12'])).toEqual(v);expect(()=>validateInterpretation({...v,vendor:'C'},a,['EV-R1-12'])).toThrow();expect(()=>validateInterpretation({...v,evidenceIds:['FAKE']},a,['EV-R1-12'])).toThrow()});
});
