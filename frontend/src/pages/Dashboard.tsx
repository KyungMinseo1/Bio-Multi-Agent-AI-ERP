import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, ArrowUpRight, Boxes, CalendarClock, CheckCircle2, Clock3, FlaskConical, MessagesSquare, RefreshCw, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react';
import { api, date, number, quantity, record, rows, send, text, type Row } from '../api';
import { Badge, Empty, ErrorBox, Evidence, InlineLink, Modal, PageHeading, Panel, ReadOnlyNotice, Timeline, useWorkspace } from '../components';
import CandidateComparison from '../CandidateComparison';
function AlertAcknowledgement({ alert, close, saved }: { alert: Row; close: () => void; saved: () => void }) {
  const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>();
  return <Modal title="발주 검토 알림 확인" close={close}><form onSubmit={async event => {
    event.preventDefault(); setBusy(true);
    try { await send(`/alerts/${text(alert.id)}/acknowledge`, { reason }); saved(); close(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }}><div className="form-description"><p>{text(alert.message)}</p><p>확인 기록은 재고 부족을 해결하거나 발주를 승인하지 않습니다.</p></div><div className="form-grid"><label className="span-two">검토 메모<textarea required value={reason} onChange={event => setReason(event.target.value)} placeholder="확인 내용과 후속 담당 업무를 기록하세요."/></label></div><ErrorBox error={error}/><footer className="modal-footer"><button className="button secondary" type="button" onClick={close}>취소</button><button className="button primary" disabled={busy}>{busy ? '저장 중…' : '확인 기록 저장'}</button></footer></form></Modal>;
}
export default function Dashboard() {
  const { scenarioId, scenario, planning, user, refresh } = useWorkspace(); const navigate = useNavigate();
  const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(); const [material, setMaterial] = useState('');
  const [acknowledging, setAcknowledging] = useState<Row | null>(null);
  const [showAllCandidates, setShowAllCandidates] = useState(false);
  const alertsQuery = useQuery({ queryKey: ['alerts', scenarioId], queryFn: () => api(`/scenarios/${scenarioId}/alerts`) });
  const materials = rows(planning.materials); const alerts = rows(alertsQuery.isSuccess ? alertsQuery.data : planning.alerts).filter(alert => alert.status !== 'resolved');
  const selected = material || text(alerts[0]?.material_id || materials[0]?.material_id); const current = materials.find(row => row.material_id === selected);
  const candidates = rows(planning.candidates).filter(row => row.material_id === selected).sort((a, b) => number(a.rank) - number(b.rank));
  const urgent = alerts.filter(alert => alert.status === 'urgent'); const plans = rows(scenario.production_plans);
  const start = async () => { setBusy(true); setError(undefined); try { const run = record(await send(`/scenarios/${scenarioId}/discussions`, { expected_revision: scenario.revision })); navigate(`/discussions/${text(run.id || run.run_id)}`); } catch (err) { setError(err); } finally { setBusy(false); } };
  return <>
    <PageHeading eyebrow="PROCUREMENT SITUATION" title="원료 상황부터, 함께 판단하기" description="재고·생산 수요를 확인하고, 실제 AI 협의를 거쳐 발주 여부와 시점을 결정하세요." action={<button className="button secondary" disabled={busy} onClick={async () => { setBusy(true); try { await send(`/scenarios/${scenarioId}/evaluate`, {}); await refresh(); } catch (err) { setError(err); } finally { setBusy(false); } }}><RefreshCw size={16} className={busy ? 'spin' : ''}/>재계산</button>}/>
    <ReadOnlyNotice/>
    <ErrorBox error={error || alertsQuery.error} retry={() => { refresh(); setError(undefined); }}/>
    <div className="decision-steps" aria-label="원료 의사결정 순서"><strong>1. 상황 파악</strong><ArrowRight size={15}/><span>2. 부서별 AI 협의</span><ArrowRight size={15}/><span>3. 추천·이견 확인</span><ArrowRight size={15}/><span>4. 담당자 선택·승인</span></div>
    <Panel title="먼저, 어떤 상황인가요?" subtitle={`계산 기준일 ${date(planning.as_of)} · 현재 데이터가 유지될 때의 수요와 재고입니다.`} action={<select aria-label="상황을 확인할 원료" value={selected} onChange={event => setMaterial(event.target.value)}>{materials.map(item => <option key={text(item.material_id)} value={text(item.material_id)}>{text(item.name)}</option>)}</select>}>
      {current ? <div className="situation-summary" id="material-situation">
        <h3>{text(current.name)} · {text(current.code)}</h3>
        <div className="comparison-context"><span>장부 재고 <strong>{quantity(current.book_quantity)}</strong></span><span>투입일 기준 기존 가용 재고 <strong>{quantity(current.usable_for_production)}</strong></span><span>예정 생산 수요 <strong>{quantity(current.required_quantity)}</strong></span><span>안전재고 목표 <strong>{quantity(current.safety_stock)} {text(current.base_unit)}</strong></span></div>
        {number(current.new_order_quantity) > 0 ? <p>현재 생산계획과 재고·기존 입고 조건이 유지된다면 추가 조달을 검토해야 합니다. 생산 수요와 안전재고를 반영한 <strong>추가 필요량은 계산상 {quantity(current.new_order_quantity)} {text(current.base_unit)}</strong>입니다. 구매 수량·공급 경로·분할 여부는 아직 선택하지 않았습니다.</p> : <p>현재 등록된 생산 수요와 안전재고 목표에서는 추가 조달 필요량이 계산되지 않았습니다. 수요·품질 상태·일정이 바뀌면 다시 검토해야 합니다.</p>}
        <div className="comparison-context"><span>추가 조달 없을 때 첫 부족 예상 <strong>{current.first_shortage_date ? date(current.first_shortage_date) : '현재 계산에서 없음'}</strong></span><span>역산한 검토 기한 추정 <strong>{current.latest_order_date ? date(current.latest_order_date) : '근거 부족 · 산정 안 됨'}</strong></span><span>이번 추가 발주일 <strong>미정 · 협의와 담당자 결정 필요</strong></span></div>
        <p className="projection-note">검토 기한은 첫 부족 예상일에서 유효 견적 중 가장 짧은 등록 조달기간을 뺀 참고값이며 실제 발주일이 아닙니다. 선택 공급안, QC/QA 슬롯, 공급 확약과 일정 변경에 따라 달라집니다. 보류·투입 전 만료 재고는 생산 가용량에서 제외하며 미래 QC/QA 완료는 확정 재고가 아닙니다.</p>
        <Evidence refs={current.evidence_refs}/>
      </div> : <Empty title="등록된 원료 상황이 없습니다">생산 수요와 원료·재고 데이터를 등록하세요.</Empty>}
    </Panel>
    <div className="metric-grid">
      <article className="metric-card"><div><span>검토 신호</span><span className="metric-icon amber"><CalendarClock size={19}/></span></div><strong>{alerts.length}<small>개 원료 알림</small></strong><p><span className="amber-text">{urgent.length}건 긴급 검토</span> · 발주 결정 아님</p></article>
      <article className="metric-card"><div><span>관리 중인 원료</span><span className="metric-icon teal"><FlaskConical size={19}/></span></div><strong>{materials.length}<small>개 품목</small></strong><p>품질 상태 · 투입일 · 유효일 기준 계산</p></article>
      <article className="metric-card"><div><span>연결된 생산계획</span><span className="metric-icon blue"><Boxes size={19}/></span></div><strong>{plans.length}<small>건</small></strong><p>입고일과 QC/QA 후 사용 가능 예상일 구분</p></article>
      <article className="metric-card"><div><span>저장된 내부 발주</span><span className="metric-icon violet"><ShieldCheck size={19}/></span></div><strong>{rows(scenario.purchase_orders).length}<small>건</small></strong><p>공급업체 전송 없는 내부 기록</p></article>
    </div>
    <Panel title="협의에서 확인할 검토 신호" subtitle="부족·검토 기한은 조건부 계산입니다. 발주 여부와 실제 주문일을 확정하지 않습니다." action={<span className="section-count">{alerts.length}개의 검토 항목</span>} className="action-panel">
      {alerts.length ? alerts.map(alert => {
        const item = materials.find(row => row.material_id === alert.material_id); const affected = rows(scenario.requirements).filter(row => row.material_id === alert.material_id);
        return <div className="alert-row" key={text(alert.id)}>
          <div className={`alert-symbol ${text(alert.status)}`}><TriangleAlert size={23}/></div>
          <div className="alert-main">
            <div className="alert-title"><h3>{text(item?.name) || '원료 확인 필요'}</h3><Badge value={alert.status}/><span className="subtle-code">{text(item?.code)}</span></div>
            <p>{text(alert.message)} · 발주 적합성은 부서별 협의에서 검토합니다.</p>
            <div className="alert-meta"><span><Clock3 size={13}/>역산 검토 기한 추정 {alert.latest_order_date || item?.latest_order_date ? date(alert.latest_order_date || item?.latest_order_date) : '산정 근거 부족'}</span><span>첫 부족 예상 {date(alert.first_shortage_date || item?.first_shortage_date)}</span><span>연결된 투입 수요 {affected.length}건</span></div>
            <details className="alert-calculation"><summary>감지 근거 · 조달기간 · 영향 생산 보기</summary><div className="alert-calculation-content">
              <p>현재 계획의 생산 가용량 {quantity(item?.free_available_quantity)} {text(item?.base_unit)}</p>
              <p>첫 안전재고 미달 예상 {date(item?.first_safety_breach_date)} · 첫 수요 부족 예상 {date(item?.expected_stockout_date)}</p>
              <p>역산에 사용한 등록 최단 조달기간 {item?.lead_time_days == null ? '유효 견적 정보 부족' : `${text(item?.lead_time_days)}일`} · 선택한 공급안의 실제 납기는 미정입니다.</p>
              <p>연결 생산 {Array.from(new Set(affected.map(requirement => text(plans.find(plan => plan.id === requirement.production_plan_id)?.code)))).filter(Boolean).join(' · ') || '연결 없음'}</p>
              {rows(item?.lead_time_breakdown).map((lead, index) => <p key={index}>{text(rows(scenario.offers).find(offer => offer.id === lead.offer_id)?.code)}: 준비 {text(lead.preparation_days)} + 운송 {text(lead.transport_days)} + 입고 {text(lead.receiving_days)} + QC {text(lead.qc_days)} + QA {text(lead.qa_days)}일</p>)}
              {rows(item?.existing_receipts).length > 0 && <details><summary>기존 입고 근거</summary><pre>{JSON.stringify(item?.existing_receipts, null, 2)}</pre></details>}
              <Evidence refs={alert.evidence_refs}/>
            </div></details>
            {alert.acknowledgement != null && <p className="alert-acknowledged">검토 확인: {text(record(alert.acknowledgement).actor)} · {text(record(alert.acknowledgement).reason)}</p>}
          </div>
          <div className="alert-actions"><button className="text-button" disabled={!user.id} onClick={() => setAcknowledging(alert)}>{alert.acknowledgement ? '확인 기록 추가' : '검토 확인'}</button><button className="button secondary small" onClick={() => { setMaterial(text(alert.material_id)); document.getElementById('material-situation')?.scrollIntoView({ behavior: 'smooth' }); }}>상황 확인<ArrowRight size={15}/></button>{acknowledging?.id === alert.id && <AlertAcknowledgement alert={alert} close={() => setAcknowledging(null)} saved={() => { alertsQuery.refetch(); }}/>}</div>
        </div>;
      }) : <div className="all-clear"><CheckCircle2 size={27}/><div><strong>현재 계산에서 검토 알림이 없습니다</strong><p>새 수요나 견적이 입력되면 재고와 검토 기한을 다시 계산합니다.</p></div></div>}
    </Panel>
    <div className="dashboard-columns">
      <Panel title="원료별 가용 재고" subtitle="장부 수량과 이번 생산에 사용할 수 있는 수량은 다릅니다." action={<InlineLink to="/erp/inventory">재고 관리</InlineLink>}>
        <div className="inventory-summary">{materials.map(item => {
          const book = number(item.book_quantity); const available = number(item.usable_for_production); const width = book ? Math.min(100, Math.max(0, available / book * 100)) : 0;
          return <button className={`material-summary ${selected === item.material_id ? 'selected' : ''}`} key={text(item.material_id)} onClick={() => setMaterial(text(item.material_id))}><div className="material-summary-top"><span><strong>{text(item.name)}</strong><small>{text(item.code)}</small></span><Badge value={item.alert_status}/></div><div className="inventory-bar"><span style={{ width: `${width}%` }}/></div><div className="inventory-numbers"><span><i className="legend-dot teal-bg"/>생산 가용 <strong>{quantity(item.usable_for_production)}</strong></span><span><i className="legend-dot gray-bg"/>장부 <strong>{quantity(item.book_quantity)}</strong> {text(item.base_unit)}</span></div></button>;
        })}</div><div className="panel-footnote">현재 승인 재고만 확정 가용량입니다. 미래 QC/QA 완료는 예측으로 구분합니다.</div>
      </Panel>
      <section className="discussion-invite">
        <div className="invite-decoration"><MessagesSquare size={110}/></div><span className="eyebrow">NEXT · REAL AI DISCUSSION</span><div className="invite-icon"><Sparkles size={25}/></div>
        <h2>발주가 필요한지,<br/>언제·어떻게 할지 함께 검토해요.</h2>
        <p>계산만으로 적합한 안을 확정하지 않습니다. 실제 AI가 부서별 근거와 이견을 검토한 뒤 추천하며, 최종 선택과 승인은 담당자가 합니다.</p>
        <div className="role-chips">{['구매', '재고·물류', '생산관리', '생산', 'QC', 'QA', '재무', 'Admin'].map(role => <span key={role}>{role}</span>)}</div>
        <button className="button white" onClick={start} disabled={busy || !user.id}>{busy ? '협의 요청 중…' : '현재 상황으로 AI 협의 시작'}<ArrowUpRight size={17}/></button>
        <small>현재 시나리오 전체를 검토합니다. 실제 LLM을 호출하며 미설정·호출 실패 시 오류를 표시하고 추천을 꾸미지 않습니다.</small>
      </section>
    </div>
    <section id="comparison" className="comparison-section">
      <div className="section-heading"><div><span className="eyebrow">OPTIONAL · PROVISIONAL CALCULATIONS</span><h2>참고용 잠정 계산</h2><p>협의에 쓰일 수치 자료입니다. 계산 순서는 AI 추천 순위나 발주 적합성 판단이 아닙니다.</p></div></div>
      <details className="provisional-candidates" key={selected}>
        <summary>{text(current?.name) || '선택 원료'} · 협의 전 계산 후보 펼치기 ({candidates.length}개)</summary>
        <div className="notice"><ShieldCheck size={17}/>등록 조건의 수치 검증과 여러 부서가 판단하는 적합성은 다릅니다. 실제 협의 결과에서 추천·남은 이견을 확인한 뒤 담당자가 결정합니다.</div>
        <CandidateComparison candidates={showAllCandidates ? candidates : candidates.slice(0, 3)} compact/>
        {candidates.length > 3 && <div className="show-all-candidates"><button className="button secondary small" onClick={() => setShowAllCandidates(!showAllCandidates)}>{showAllCandidates ? '앞의 세 계산만 보기' : `전체 ${candidates.length}개 잠정 계산 보기`}</button></div>}
      </details>
    </section>
    <Panel title="추가 조달 전 날짜별 재고 투영" subtitle="원본 계획 기준 · 미래 입고·QC/QA 완료는 예측이며 실제 사용 승인이 아닙니다." action={<InlineLink to="/erp/production">생산계획 수정</InlineLink>}>{rows(record(planning.timelines)[selected]).length ? <Timeline items={record(planning.timelines)[selected]}/> : <Empty title="선택 원료의 날짜별 내역이 없습니다">원료 수요와 기존 입고 일정을 등록해 주세요.</Empty>}</Panel>
  </>;
}
