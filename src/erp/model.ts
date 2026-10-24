import {addDays,BASE} from '../data';
export {BASE,addDays};
export type Scenario='base'|'qc-delay'|'production-delay'|'temperature'|'quality-scope'|'unrelated'|'cash'|'c-quality';
export type TableKind='lots'|'quotes'|'production'|'shipments'|'costs';
export interface Product {id:string;name:string;manufacturer:string;sku:string;form:string;content:string;grade:string;unit:string;conversion:number;safety:number;process:string;approval:string;storage:string;capacity:number;}
export interface Lot {id:string;material:string;quantity:number;qc:'합격'|'품질 보류';qa:'승인'|'미승인';expiry:string;coa:string;temperature:'적합'|'이탈';hold:string;releaseCondition:string;received:string;}
export interface Production {id:string;name:string;date:string;il7:number;il15:number;completion:string;delivery:string;budget:number;}
export interface Shipment {id:string;lot:string;quantity:number;arrival:string;expiry:string;qcDelay:number;temperature:'적합'|'이탈';qaHold:boolean;confirmed:boolean;coa:string;commitment:string;payment:string;cashLimit:number;}
export interface Vendor {id:string;name:string;unitPrice:number;moq:number;multiple:number;shipping:number;approved:boolean;productApproved:boolean;confirmed:boolean;quoteExpiry:string;quoteRef:string;contractRef:string;changeTerms:string;shipments:Shipment[];}
export interface Config {budget:number;qcDays:number;qaDays:number;testingPerLot:number;storagePerVialDay:number;disposalPerVial:number;safetyBudget:number;horizon:string;scenario:Scenario;}
export interface QualityNotice {id:string;manufacturer:string;product:string;lot:string;relevanceConfirmed:boolean;note:string;}
export interface ErpData {schema:2;notices:QualityNotice[];revision:number;products:Product[];lots:Lot[];productions:Production[];vendors:Vendor[];config:Config;changes:Change[];}
export interface Change {id:string;at:string;entity:string;field:string;before:string;after:string;}
export interface ScenarioInfo {id:Scenario;name:string;description:string;source:string;}
export const scenarios:ScenarioInfo[]=[
{id:'base',name:'기준 시나리오',description:'IL-7 가용 2 + 신규 12 → 생산 12 + 안전재고 2',source:'PDF §3–5'},
{id:'qc-delay',name:'QC 병목 +3일',description:'B 2회차 QC 시작 3일 지연 → 11.12 사용 가능 → PROD-02 부족',source:'PDF §6'},
{id:'production-delay',name:'PROD-03 12월 연기',description:'마지막 투입 12.09로 연기 · 단기 유효 재고와 미출하 회차 변경 확인',source:'PDF §6 · 12.09는 확장 가정'},
{id:'temperature',name:'B 2회차 온도 이탈',description:'해당 Lot만 QA 보류 · 자동 해제 없이 부족 재계산',source:'PDF §6'},
{id:'quality-scope',name:'특정 Lot 품질 이슈',description:'제조사·제품·Lot가 일치하는 B 2회차만 보류',source:'PDF §6'},
{id:'unrelated',name:'공지 관련성 미확인',description:'원료명만 유사한 공지 · 자동 차단 없이 확인 요청',source:'PDF §6'},
{id:'cash',name:'지급일 현금 부족',description:'예산과 별개로 B 2회차 지급일 현금 한도 300만원',source:'PDF §6 · 금액은 확장 가정'},
{id:'c-quality',name:'C 제품 승인 미완료',description:'공급 미확약과 제품 미승인 사유를 분리',source:'PDF §4'}];
const shipment=(vendor:string,index:number,quantity:number,arrival:string,expiry:string,confirmed=true):Shipment=>({id:`RCPT-${vendor}-${String(index).padStart(2,'0')}`,lot:`IL7-${vendor}-LOT-${String(index).padStart(2,'0')}`,quantity,arrival,expiry,qcDelay:0,temperature:'적합',qaHold:false,confirmed,coa:`COA-${vendor}-IL7-${index}`,commitment:confirmed?`COMMIT-${vendor}-20261024-${index}`:'',payment:arrival,cashLimit:13000000});
export function createSeed():ErpData{return {
 schema:2,revision:1,notices:[],
 products:[{id:'MAT-IL7',name:'재조합 인간 IL-7',manufacturer:'합성 제조사 BIO-MFG-01',sku:'SYN-IL7-001',form:'미개봉 동결건조 · 합성 제품',content:'동일 함량 규격 U1 · 실물 함량 미지정',grade:'공정개발용 합성 규격',unit:'바이알',conversion:1,safety:2,process:'면역세포 배양 공정개발',approval:'APR-PROD-IL7-01',storage:'선택 제품 공식 규격 확인 필요 · 합성 보관구역 COLD-01',capacity:100},
 {id:'MAT-IL15',name:'재조합 인간 IL-15',manufacturer:'합성 제조사 BIO-MFG-02',sku:'SYN-IL15-001',form:'미개봉 동결건조 · 합성 제품',content:'동일 함량 규격 U2 · 실물 함량 미지정',grade:'공정개발용 합성 규격',unit:'바이알',conversion:1,safety:2,process:'동반 원료 · 대체 불가',approval:'APR-PROD-IL15-01',storage:'선택 제품 공식 규격 확인 필요 · 합성 보관구역 COLD-01',capacity:100}],
 lots:[{id:'IL7-LOT-01',material:'MAT-IL7',quantity:2,qc:'합격',qa:'승인',expiry:'2027-03-31',coa:'COA-IL7-01',temperature:'적합',hold:'',releaseCondition:'QC 적합 및 QA 서명 기록 유효',received:'2026-10-01'},
 {id:'IL7-LOT-02',material:'MAT-IL7',quantity:2,qc:'품질 보류',qa:'미승인',expiry:'2027-03-31',coa:'COA-IL7-02',temperature:'적합',hold:'CoA 문서 대조 미완료 (확장 합성 사유)',releaseCondition:'QC 문서 일치 확인 및 QA 담당자의 보류 해제 서명 필요',received:'2026-10-02'},
 {id:'IL7-LOT-03',material:'MAT-IL7',quantity:2,qc:'합격',qa:'승인',expiry:'2026-10-31',coa:'COA-IL7-03',temperature:'적합',hold:'최초 생산 투입일 이전 유효기간 만료',releaseCondition:'유효기간 연장 가정 금지 · 별도 폐기 절차 필요',received:'2026-09-01'},
 {id:'IL15-LOT-01',material:'MAT-IL15',quantity:20,qc:'합격',qa:'승인',expiry:'2027-03-31',coa:'COA-IL15-01',temperature:'적합',hold:'',releaseCondition:'QC 적합 및 QA 승인',received:'2026-10-01'}],
 productions:[{id:'PROD-01',name:'T 세포 배양 · Pilot 01',date:'2026-11-04',il7:4,il15:4,completion:'2026-11-09',delivery:'2026-11-12',budget:2400000},{id:'PROD-02',name:'T 세포 배양 · Pilot 02',date:'2026-11-11',il7:4,il15:4,completion:'2026-11-16',delivery:'2026-11-19',budget:4300000},{id:'PROD-03',name:'T 세포 배양 · Pilot 03',date:'2026-11-18',il7:4,il15:4,completion:'2026-11-23',delivery:'2026-11-26',budget:4300000}],
 vendors:[{id:'A',name:'A · 대량 할인',unitPrice:800000,moq:20,multiple:20,shipping:100000,approved:true,productApproved:true,confirmed:true,quoteExpiry:'2026-10-27',quoteRef:'QT-A-20261024',contractRef:'CTR-A-01',changeTerms:'일괄 발주 · 수량 감액/취소는 별도 합의 필요',shipments:[shipment('A',1,20,'2026-10-30','2026-11-30')]},
 {id:'B',name:'B · 분할 구매',unitPrice:1000000,moq:4,multiple:4,shipping:100000,approved:true,productApproved:true,confirmed:true,quoteExpiry:'2026-10-27',quoteRef:'QT-B-20261024',contractRef:'CTR-B-01',changeTerms:'회차별 4개 확약 · 미출하 일정 변경/취소는 공급업체 서면 동의 필요 (합성 계약)',shipments:[shipment('B',1,4,'2026-10-30','2027-03-31'),shipment('B',2,4,'2026-11-06','2027-03-31'),shipment('B',3,4,'2026-11-13','2027-03-31')]},
 {id:'C',name:'C · 저가 미확약',unitPrice:700000,moq:4,multiple:4,shipping:100000,approved:true,productApproved:true,confirmed:false,quoteExpiry:'2026-10-27',quoteRef:'QT-C-20261024',contractRef:'미체결',changeTerms:'출하 확약·납품실적 미확인 · 확정안 채택 불가',shipments:[shipment('C',1,12,'2026-10-30','2027-03-31',false)]}],
 config:{budget:13000000,qcDays:2,qaDays:1,testingPerLot:100000,storagePerVialDay:200,disposalPerVial:20000,safetyBudget:2000000,horizon:'2026-11-30',scenario:'base'},changes:[]
}}
export function applyScenario(id:Scenario):ErpData{const d=createSeed();d.config.scenario=id;const b=d.vendors[1];
 if(id==='qc-delay')b.shipments[1].qcDelay=3;
 if(id==='production-delay'){d.productions[2].date='2026-12-09';d.productions[2].completion='2026-12-14';d.productions[2].delivery='2026-12-17'}
 if(id==='temperature'){b.shipments[1].temperature='이탈';b.shipments[1].qaHold=true}
 if(id==='quality-scope')d.notices.push({id:'ISSUE-IL7-B-02',manufacturer:d.products[0].manufacturer,product:d.products[0].sku,lot:b.shipments[1].lot,relevanceConfirmed:true,note:'합성 품질 이슈: 제조사·제품·Lot와 우리 납품분 일치 확인'});
 if(id==='unrelated')d.notices.push({id:'NOTICE-UNVERIFIED-01',manufacturer:'관련성 미확인',product:'유사 원료명',lot:'미확인',relevanceConfirmed:false,note:'추가 확인 요청 · 자동 차단 없음'});
 if(id==='cash')b.shipments[1].cashLimit=3000000;
 if(id==='c-quality')d.vendors[2].productApproved=false;
 return d;
}
export const sourceNotes=[
 {field:'기준일·IL-7 3개 Lot·생산 수요·A/B/C 견적·B 입고일·QC/QA·예산',source:'scenario_1.pdf §2–4',status:'원문 반영'},
 {field:'제품 식별자·함량 기호 U1/U2·보관구역·CoA·확약·계약 ID·보류 사유',source:'PDF가 요구한 ERP 필드의 합성 확장',status:'추가 합성 설정'},
 {field:'IL-15 승인 20개·생산당 4개·안전재고 2개',source:'PDF의 충분한 승인 재고 조건을 충족하는 확장',status:'추가 합성 설정'},
 {field:'시험비 10만원/Lot·보관비 200원/바이알·일·폐기처리비 2만원/개',source:'PDF 미지정 추가 비용의 편집 가능한 가정',status:'추가 합성 설정'},
 {field:'C 운송비 10만원·예상일 10.30·유효일 2027.03.31',source:'미확약 참고 견적 · 확정 공급량 계산에서 제외',status:'추가 합성 설정'},
 {field:'생산 완료/고객 납품 일정·생산별 예산 배분·현금 한도·회차별 지급일',source:'업무 연결을 위한 합성 관리값 · 고객 납기 준수 확정 아님',status:'추가 합성 설정'}];
