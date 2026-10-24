import { CheckCircle2, CircleAlert, Truck } from 'lucide-react';
import { date, display, label, money, quantity, record, rows, text, type Row } from './api';
import { Badge, Evidence, KeyValue, Timeline } from './components';
export default function CandidateComparison({ candidates, compact = false, action, evidence }: { candidates: Row[]; compact?: boolean; action?: (candidate: Row) => React.ReactNode; evidence?: Row[] }) {
  if (!candidates.length) return <div className="empty"><Truck size={28}/><h3>계산 가능한 발주 대안이 없습니다</h3><p>부족 수요, 유효 견적, 공급업체 승인 및 필수 입력을 확인하세요.</p></div>;
  return <div className={`candidate-grid ${compact ? 'compact' : ''}`}>{candidates.map((candidate, index) => {
    const validation = record(candidate.validation); const costs = record(candidate.costs); const valid = validation.hard_constraints_passed === true; const reasons = rows(validation.reasons); const warnings = rows(validation.warnings);
    return <article className={`candidate-card ${index === 0 && valid ? 'recommended' : ''}`} key={text(candidate.id)}>
      <div className="candidate-top"><span className="candidate-number">{String(index + 1).padStart(2, '0')}</span><Badge value={!valid ? 'infeasible' : validation.requires_budget_approval ? 'requires_budget_approval' : 'feasible'}/></div>
      <h3>{text(candidate.name)}</h3>
      <p className="candidate-quantity">주문 수량 <strong>{quantity(candidate.quantity)}</strong></p>
      <div className="candidate-cost"><span>예상 총비용</span><strong>{money(costs.total)}</strong><small>구매 + 운송 + 보관 + 시험 + 예상 폐기</small></div>
      <div className="candidate-checks">
        <div>{valid ? <CheckCircle2 size={16}/> : <CircleAlert size={16}/>}필수조건 {valid ? '충족' : '미충족'}</div>
        <div>{validation.target_delivery_met ? <CheckCircle2 size={16}/> : <CircleAlert size={16}/>}목표 투입일 {validation.target_delivery_met ? '충족 예상' : '미충족 / 확인 필요'}</div>
        <div><Truck size={16}/>{label(validation.supply_evidence_level)}</div>
        <div>{validation.cash_feasible ? <CheckCircle2 size={16}/> : <CircleAlert size={16}/>}지급일 현금 한도 {validation.cash_feasible ? '충족' : '미충족 / 확인 필요'}</div>
      </div>
      <div className="candidate-residuals">
        <KeyValue label="최종 투입 후 예상 가용 잔량" value={quantity(candidate.remaining_quantity)}/>
        <KeyValue label="기한 내 미소진 · 예상 폐기" value={quantity(candidate.expected_disposal_quantity)}/>
      </div>
      <details className="cost-details">
        <summary>비용 · 회차별 입고 상세</summary>
        <div className="cost-breakdown">
          {[['purchase', '구매'], ['transport', '운송'], ['storage', '보관'], ['testing', '시험'], ['disposal', '예상 폐기']].map(([key, name]) => <KeyValue key={key} label={name} value={money(costs[key])}/>)}
          <KeyValue label="구매 + 운송 소계" value={money(costs.subtotal)}/>
        </div>
        <div className="delivery-list">{rows(candidate.deliveries).map((delivery, i) => <div key={text(delivery.id) || i}>
          <strong>{i + 1}회차 · {quantity(delivery.quantity)}</strong>
          <span>입고 {date(delivery.arrival_date)}</span>
          <span>QC 시작 예상 {date(delivery.qc_start_date)}</span>
          <span>사용 가능 예상 {date(delivery.available_date)}</span>
          <span>유효일 {date(delivery.expiry_date)}</span>
          <span>지급일 {date(delivery.payment_date)}</span>
          <Badge value={delivery.confirmed ? 'confirmed' : 'unconfirmed'}/>
        </div>)}</div>
      </details>
      {rows(candidate.timeline).length > 0 && <details className="cost-details">
        <summary>이 안의 날짜별 가용 재고</summary>
        <p className="projection-note">미확약 입고는 제외합니다. 미래 QC/QA 완료는 실제 승인 전 예측치입니다.</p>
        <Timeline items={candidate.timeline} evidence={evidence}/>
      </details>}
      {reasons.length > 0 && <div className="candidate-reasons">{reasons.map((reason, i) => <div key={i}><p><CircleAlert size={14}/>{text(reason.message || reason.code)}</p><Evidence refs={reason.evidence_refs} extra={evidence}/></div>)}</div>}
      {warnings.length > 0 && <details className="risk-details"><summary>잔여 위험 · 확인사항 {warnings.length}건</summary>{warnings.map((warning, i) => <div key={i}><p>{display(warning.message || warning.code)}</p><Evidence refs={warning.evidence_refs} extra={evidence}/></div>)}</details>}
      <Evidence refs={candidate.evidence_refs} extra={evidence}/>
      {action && <div className="candidate-action">{action(candidate)}</div>}
    </article>;
  })}</div>;
}
