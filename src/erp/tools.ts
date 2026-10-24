/** Read-only tool boundary for a future server-side model. No API secret in client. */
import {analyze,lotReview,type Analysis} from './calculator';
import type {ErpData} from './model';
export const erpToolDefinitions=[
 {type:'function',name:'query_lots',description:'원료 코드로 Lot·품질·유효일·가용성 조회',strict:true,parameters:{type:'object',properties:{material:{type:'string',enum:['MAT-IL7','MAT-IL15']}},required:['material'],additionalProperties:false}},
 {type:'function',name:'evaluate_procurement',description:'MOQ·분할입고·QC/QA·생산·총비용·현금 계산',strict:true,parameters:{type:'object',properties:{vendor:{type:'string',enum:['A','B','C']}},required:['vendor'],additionalProperties:false}},
 {type:'function',name:'validate_recommendation',description:'모든 필수조건과 revision을 검증한 구조화 결과',strict:true,parameters:{type:'object',properties:{revision:{type:'integer'}},required:['revision'],additionalProperties:false}}
] as const;
export function callErpTool(data:ErpData,name:string,args:Record<string,unknown>){
 if(name==='query_lots'){if(!['MAT-IL7','MAT-IL15'].includes(String(args.material)))throw Error('허용하지 않는 원료 코드');return {revision:data.revision,rows:lotReview(data,String(args.material))};}
 if(name==='evaluate_procurement'){if(!['A','B','C'].includes(String(args.vendor)))throw Error('허용하지 않는 공급업체');return {revision:data.revision,result:analyze(data).options.find(o=>o.id===args.vendor)};}
 if(name==='validate_recommendation'){if(args.revision!==data.revision)throw Error('stale revision');return analyze(data);}
 throw Error('읽기 전용 도구 허용 목록에 없는 요청');
}
export const interpretationSchema={type:'object',properties:{revision:{type:'integer'},vendor:{type:['string','null'],enum:['A','B','C',null]},evidenceIds:{type:'array',items:{type:'string'}},summary:{type:'string'},actions:{type:'array',items:{type:'string'}}},required:['revision','vendor','evidenceIds','summary','actions'],additionalProperties:false} as const;
export function validateInterpretation(value:unknown,analysis:Analysis,validEvidenceIds:string[]){if(!value||typeof value!=='object')throw Error('구조화 결과 형식 오류');const v=value as Record<string,unknown>;if(v.revision!==analysis.revision||v.vendor!==analysis.selected)throw Error('계산 결과와 모델 판단 불일치');if(!Array.isArray(v.evidenceIds)||v.evidenceIds.length===0||v.evidenceIds.some(id=>!validEvidenceIds.includes(String(id))))throw Error('존재하지 않는 계산 근거');if(typeof v.summary!=='string'||!Array.isArray(v.actions)||v.actions.some(a=>typeof a!=='string'))throw Error('해석 필드 형식 오류');return v;}
