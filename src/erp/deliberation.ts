import {analyze,type Analysis,type Option,won} from './calculator';
import type {ErpData} from './model';
export interface DepartmentVerdict {agent:number;department:string;priority:string;vendor:string|null;headline:string;reason:string;tradeoff:string;readyAfter:number;}
/** Each department ranks real offers by its own objective. Admin still enforces all constraints. */
export function departmentVerdicts(data:ErpData,a:Analysis=analyze(data)):DepartmentVerdict[]{
 const confirmed=a.options.filter(o=>o.confirmed&&o.qualityApproved&&o.deliveries.every(s=>s.confirmed));
 const byId=(id:string)=>data.vendors.find(v=>v.id===id)!;
 const purchase=[...confirmed].sort((x,y)=>byId(x.id).unitPrice-byId(y.id).unitPrice)[0];
 const inventory=[...confirmed].sort((x,y)=>x.shortage-y.shortage||x.waste-y.waste||x.quantity-y.quantity||x.total-y.total)[0];
 const leadScore=(o:Option)=>o.checks.reduce((n,p)=>{const dates=o.deliveries.filter(s=>s.included&&s.available<=p.date).map(s=>s.available).sort();return n+(dates.length?(Date.parse(p.date)-Date.parse(dates[dates.length-1]))/86400000:0)},0);
 const production=[...confirmed].sort((x,y)=>x.shortage-y.shortage||leadScore(y)-leadScore(x)||x.total-y.total)[0];
 const finance=[...confirmed].sort((x,y)=>x.total-y.total)[0];
 const name=(o:Option|undefined)=>o?`${o.id}업체 ${o.quantity}바이알`:'확약 후보 없음';
 const unavailable=a.need.required===0;
 return [
 {agent:0,department:'구매',priority:'낮은 단가 · 공급 확약',vendor:unavailable?null:purchase?.id||null,headline:unavailable?'신규 발주 불필요':name(purchase),reason:purchase?`단가 ${won(byId(purchase.id).unitPrice)}. 공급이 확약된 승인 경로 중 단가가 가장 낮습니다.`:'공급 확약을 먼저 확보해야 합니다.',tradeoff:purchase?`MOQ 반영 ${purchase.quantity}개 · 구매·운송 ${won(purchase.subtotal)}. 총비용과 예산은 다른 부서와 조정해야 합니다.`:'미확약 견적은 확정안으로 제안하지 않습니다.',readyAfter:5},
 {agent:1,department:'재고·물류',priority:'폐기 최소화 · 안전재고 유지',vendor:unavailable?null:inventory?.id||null,headline:unavailable?'기존 승인 재고 사용':name(inventory),reason:inventory?`예상 폐기 ${inventory.waste}개. 생산별 부족 ${inventory.shortage}개를 먼저 줄인 뒤 잔여 폐기와 과잉 구매를 비교했습니다.`:'유효한 공급 경로가 없습니다.',tradeoff:inventory?`생산 후 재고 ${inventory.checks.map(p=>p.after).join(' → ')}개. ${inventory.shortage?'일부 생산은 부족하여 일정 조치가 필요합니다.':'분할 납품의 품질 승인 시점을 지켜야 합니다.'}`:'보류 Lot의 임의 사용은 허용하지 않습니다.',readyAfter:7},
 {agent:2,department:'생산관리',priority:'투입일 준수 · 조기 확보 여유',vendor:unavailable?null:production?.id||null,headline:unavailable?'기존 재고로 생산 검토':name(production),reason:production?`생산 투입 부족 ${production.shortage}개. 동일한 부족 조건에서는 원료를 더 일찍 확보해 일정 여유가 큰 안을 우선합니다.`:'투입 가능한 공급안이 없습니다.',tradeoff:production?`구매·운송 ${won(production.subtotal)}, 예상 폐기 ${production.waste}개. 일정 우선 판단이므로 예산·폐기와 조정이 필요합니다.`:'고객 납기를 확정하지 않습니다.',readyAfter:9},
 {agent:4,department:'재무',priority:'최종 총비용 · 예산 · 현금',vendor:unavailable?null:finance?.id||null,headline:unavailable?'추가 구매 지출 없음':name(finance),reason:finance?`시험·보관·폐기처리 포함 총비용 ${won(finance.total)}로, 확약·승인 후보 중 가장 낮습니다.`:'재무 검토 가능한 확약안이 없습니다.',tradeoff:finance?`예산 ${won(data.config.budget)}. ${finance.cash.some(c=>!c.ok)?'지급일 현금 한도 부족으로 승인할 수 없습니다.':finance.total>data.config.budget?'예산을 초과하므로 조건 변경이 필요합니다.':'지급일별 현금과 생산 적합성도 최종 확인해야 합니다.'}`:'단가만으로 절감액을 판단하지 않습니다.',readyAfter:8}
 ];
}
const weights=[.18,.32,.44,.7,.24,1.15,1.75,2.25,2.6,1.85,2.35,2.8];
export function stagePlaybackMs(data:ErpData,index:number,baseMs:number){const a=analyze(data);const reasoning=index>=6;const complication=reasoning&&(a.options.some(o=>o.confirmed&&o.qualityApproved&&o.shortage>0)||data.config.scenario!=='base')?1.2:1;return Math.max(180,Math.min(14000,Math.round(baseMs*(weights[index]??1)*complication)));}
