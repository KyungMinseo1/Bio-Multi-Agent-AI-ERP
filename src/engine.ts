import {addDays,BASE,suppliers} from './data';
export const REQUIRED='2026-11-01';
export const QUANTITY=60;
export const BUDGET=9000000;
export function quotes(outage=false){return suppliers.map(s=>{const delay=outage&&s.id==='B'?10:0;const arrival=addDays(BASE,s.lead+delay);const available=addDays(arrival,s.qc);return {...s,delay,arrival,available,total:s.price*QUANTITY,onTime:available<=REQUIRED,eligible:s.quality&&available<=REQUIRED}})}
export function recommendation(outage=false){return quotes(outage).filter(s=>s.eligible).sort((a,b)=>a.total-b.total)[0]}
export interface Step {agent:number;title:string;body:string;tag:string;type:'info'|'conflict'|'success';proposal:string;}
export function meetingSteps(outage=false):Step[]{return outage?[
{agent:1,title:'변경된 공급망 데이터 수신',body:'바이오넥스 생산시설 정전으로 조달기간이 4일에서 14일로 늘어났습니다. 기존 재고는 10.30 소진 예정으로, 안전재고로 흡수할 수 없습니다.',tag:'가상 위험 이벤트',type:'conflict',proposal:'기존 B안 · 사용 가능일 재계산'},
{agent:0,title:'기존 추천안의 납기 재검토',body:'B 업체의 QC 완료일이 10.30 → 11.09로 변경됩니다. 승인된 C 업체는 10.31부터 사용 가능하며, FGF-2 60 mg 공급이 가능합니다.',tag:'B안 납기 +10일',type:'conflict',proposal:'B안 보류 → C안 검토'},
{agent:2,title:'생산 시작 전 대체 원료 확보 가능',body:'11.02 Batch 024 생산 시작 전, 11.01 원료 확보 마감은 유지합니다. C 업체 원료는 10.31 QC 완료로 마감을 1일 앞섭니다.',tag:'생산 일정 충족',type:'success',proposal:'C안 · 60 mg · 10.31 사용 가능'},
{agent:3,title:'대체 공급업체 승인 상태 확인',body:'노바셀 사이언스는 승인된 공급업체입니다. FGF-2 규격 및 가상 CoA 검토 이력이 유효하며, 입고 후 2일간 QC를 거칩니다.',tag:'품질 승인 유효',type:'success',proposal:'C안 · 품질 적합'},
{agent:4,title:'전환 비용과 예산 영향 분석',body:'C안 총액은 744만원으로 기존 B안 대비 36만원 증가합니다. 900만원의 시나리오 예산 내이며, 생산 지연 가정 비용 1,800만원보다 작습니다.',tag:'예산 내 · +36만원',type:'info',proposal:'C안 · ₩7,440,000'},
{agent:5,title:'공급업체 변경 및 기존 발주 검증',body:'C 업체 60 mg으로 전환을 추천합니다. 기존 B 발주가 있으면 담당자 승인 시 가상 취소 처리하고, 대체 발주 1건을 생성합니다. 실제 거래는 발생하지 않습니다.',tag:'수정 발주안 확정',type:'success',proposal:'최종 C안 · 60 mg · ₩7,440,000'}
]:[
{agent:1,title:'FGF-2 재고 소진 위험 감지',body:'가용 재고 18 mg, 일평균 사용량 3 mg 기준 잔여 6일입니다. 10.30 소진이 예상되며, 11.02 Batch 024 생산을 위해 11.01까지 신규 원료 확보가 필요합니다.',tag:'재고 커버리지 6일',type:'conflict',proposal:'발주 필요 · FGF-2 60 mg'},
{agent:0,title:'최저가 공급업체 A안 제안',body:'셀리온 바이오의 단가는 mg당 98,000원으로 가장 낮습니다. 60 mg 발주 시 588만원이며, 공급업체 품질 승인도 유효합니다. 납기 검토를 요청합니다.',tag:'최저가 우선 제안',type:'info',proposal:'A안 · 60 mg · ₩5,880,000'},
{agent:2,title:'A안은 생산 마감일을 넘깁니다',body:'A 업체는 조달 12일 + QC 2일로 11.07부터 사용 가능합니다. 원료 확보 마감보다 6일 늦습니다. B 업체는 10.30 사용 가능해 생산 일정을 충족합니다.',tag:'의견 충돌 · 비용 vs 납기',type:'conflict',proposal:'A안 제외 → B안으로 수정'},
{agent:3,title:'B·C 업체 품질 승인 검증',body:'바이오넥스와 노바셀 사이언스는 승인된 공급업체입니다. B 업체는 10.28 입고 후 QC 2일을 거쳐 10.30 사용 가능합니다. D 업체는 미승인으로 제외합니다.',tag:'B안 품질 승인 확인',type:'success',proposal:'B안 · 60 mg · 10.30 사용 가능'},
{agent:4,title:'120만원 추가 비용의 타당성 확인',body:'B안 708만원은 A안보다 120만원 높지만 900만원 예산 이내입니다. 생산 지연 시 1,800만원의 가정 손실을 피할 수 있어 추가 비용이 합리적입니다.',tag:'예산 소진율 78.7%',type:'info',proposal:'B안 · ₩7,080,000 · 예산 내'},
{agent:5,title:'가격·생산·품질을 종합한 최종 결정',body:'납기와 품질을 충족하는 후보 중 비용이 가장 낮은 바이오넥스 60 mg을 추천합니다. 10.30 사용 가능, 생산 전 3일의 여유가 있습니다. 담당자 승인을 요청합니다.',tag:'최종 추천 · B 업체',type:'success',proposal:'최종 B안 · 60 mg · ₩7,080,000'}
]}
/** A server implementation can satisfy this interface. Secrets must remain on that server. */
export interface AnalysisProvider {mode:'demo'|'live';ask(question:string,context:unknown):Promise<string>}
export class ServerAnalysisProvider implements AnalysisProvider {mode='live' as const;constructor(private endpoint='/api/analysis'){} async ask(question:string,context:unknown){const response=await fetch(this.endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,context})});if(!response.ok)throw new Error('분석 서버 연결에 실패했습니다.');const data=await response.json();if(typeof data.answer!=='string')throw new Error('잘못된 서버 응답입니다.');return data.answer;}}
