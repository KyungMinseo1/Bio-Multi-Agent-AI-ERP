import DecisionMemory from '../../../workflow/DecisionMemory';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, ChevronRight, CircleDot, GitBranch, Loader2, MessagesSquare, Plus, Radio, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api, discussionRoles, reviewerRoles, display, label, money, number, record, rows, send, text, time, type Row } from '../api';
import { Badge, Empty, ErrorBox, Evidence, Loading, Modal, PageHeading, Panel, ReadOnlyNotice, RecordDetails, Success, useWorkspace } from '../components';
import CandidateComparison from '../CandidateComparison';
function Approval({ recommendation, close, approved }: { recommendation: Row; close: () => void; approved: (po: Row) => void }) {
  const { scenarioId, scenario, user, refresh } = useWorkspace();
  const [decisionReason,setDecisionReason]=useState('');const [ack, setAck] = useState(false); const [reason, setReason] = useState(''); const [amount, setAmount] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(); const [key] = useState(() => crypto.randomUUID());
  const candidate = record(recommendation.candidate); const validation = record(candidate.validation); const needsBudget = validation.requires_budget_approval === true;
  return <Modal title="내부 발주 최종 승인" close={close}><div className="approval-body"><div className="approval-warning"><ShieldCheck size={24}/><div><strong>담당자의 결정으로 내부 PO를 등록합니다</strong><p>외부 업체에 주문을 전송하지 않으며 QC/QA 사용 승인도 변경하지 않습니다.</p></div></div><h3>{text(candidate.name)}</h3><div className="approval-total"><span>예상 총비용</span><strong>{money(record(candidate.costs).total)}</strong></div><p className="muted">승인 직전 공식 소스 동기화와 현재 데이터 재검증을 수행합니다. 변경 또는 확인 실패 시 발주를 생성하지 않습니다.</p><div className="approval-risks"><h4>남은 위험 · 확인사항</h4>{Array.isArray(recommendation.remaining_risks) && recommendation.remaining_risks.length ? recommendation.remaining_risks.map((risk, i) => <p key={i}>{display(risk)}</p>) : <p>추천 원본과 회차별 확약 근거를 다시 확인하세요. 예상 완료일은 실제 사용 승인이 아닙니다.</p>}</div><label>이 안을 선택한 이유<textarea required maxLength={2000} value={decisionReason} onChange={e=>setDecisionReason(e.target.value)}/></label><DecisionMemory scenarioId={scenarioId}/><label className="checkbox-label"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)}/><span>미확인 외부 이슈와 남은 위험을 확인했습니다. 미확인을 품질 문제 확정 또는 안전 확인으로 간주하지 않습니다.</span></label>{needsBudget && <div className="budget-approval"><h4>추가 예산 승인 필요</h4><label>추가 승인 금액 (원)<input type="number" min="0" step="1" value={amount} onChange={event => setAmount(event.target.value)} required/></label><label>추가 예산 승인 사유<textarea value={reason} onChange={event => setReason(event.target.value)} required/></label></div>}<ErrorBox error={error} retry={() => { refresh(); }}/></div><footer className="modal-footer"><span className="muted">{label(user.role)} · 데이터 v{text(scenario.revision)}</span><button className="button secondary" onClick={close} disabled={busy}>취소</button><button className="button primary" disabled={busy || !decisionReason.trim() || !ack || user.role !== 'approver' || (needsBudget && (!reason.trim() || !amount))} onClick={async () => { setBusy(true); setError(undefined); try { const result = record(await send(`/recommendations/${text(recommendation.id)}/approve`, { expected_revision: scenario.revision, acknowledge_unverified: ack, decision_reason:decisionReason.trim(), budget_approval_reason: needsBudget ? reason : null, budget_approval_amount: needsBudget ? amount : undefined }, 'POST', { 'Idempotency-Key': key })); await refresh(); approved(record(result.purchase_order || result)); close(); } catch (err) { setError(err); } finally { setBusy(false); } }}><ShieldCheck size={16}/>{busy ? '동기화 · 검증 중…' : '승인하고 내부 발주 등록'}</button></footer></Modal>;
}
export default function Discussions() {
  const { id } = useParams(); const { scenarioId, scenario, user, refresh, adoptRecommendation } = useWorkspace(); const navigate = useNavigate();
  const [error, setError] = useState<unknown>(); const [busy, setBusy] = useState(false); const [approval, setApproval] = useState<Row | null>(null); const [po, setPo] = useState<Row | null>(null); const [connected, setConnected] = useState(false); const [evidenceRun, setEvidenceRun] = useState(false);
  const listQuery = useQuery({ queryKey: ['discussions', scenarioId], queryFn: () => api(`/scenarios/${scenarioId}/discussions`) });
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: () => api('/settings') });
  const runQuery = useQuery({ queryKey: ['discussion', scenarioId, id], queryFn: () => api(`/discussions/${id}`), enabled: !!id, refetchInterval: query => ['queued', 'running'].includes(text(record(query.state.data).status)) ? 2500 : false });
  const run = record(runQuery.data); const belongs = !run.scenario_id || run.scenario_id === scenarioId; const status = text(run.status); const active = status === 'running' || status === 'queued';
  const stale = status === 'stale' || (run.snapshot_revision != null && number(run.snapshot_revision) !== number(scenario.revision));
  useEffect(() => {
    setConnected(false); if (!id || !belongs || !active) return;
    const source = new EventSource(`/api/v1/discussions/${id}/events`, { withCredentials: true });
    source.onopen = () => setConnected(true); source.onerror = () => setConnected(false);
    const update = () => { runQuery.refetch(); };
    source.onmessage = update; ['progress', 'message', 'strategy', 'recommendation', 'status', 'completed', 'failed', 'update'].forEach(name => source.addEventListener(name, update));
    return () => source.close();
  }, [id, belongs, active, scenarioId]);
  async function start() { setBusy(true); setError(undefined); try { const result = record(await send(`/scenarios/${scenarioId}/discussions`, { expected_revision: scenario.revision })); setPo(null); navigate(`/discussions/${text(result.id || result.run_id)}`); listQuery.refetch(); } catch (err) { setError(err); } finally { setBusy(false); } }
  if (id && runQuery.isPending) return <Loading message="저장된 협의와 근거를 불러오고 있습니다"/>;
  if (id && !belongs) return <><PageHeading eyebrow="SCENARIO ISOLATION" title="다른 시나리오의 협의입니다" description="시나리오 간 데이터가 섞이지 않도록 이 협의의 조회와 승인을 중단했습니다."/><button className="button primary" onClick={() => navigate('/discussions')}>현재 시나리오 협의로 이동</button></>;
  const recommendations = rows(run.recommendations).sort((a, b) => number(a.rank) - number(b.rank)); const messages = rows(run.messages); const strategies = rows(run.strategies); const progress = record(run.progress);
  const latestMessages = Array.from(new Map(messages.map(message => [text(message.role), message] as const)).values());
  const snapshot = record(run.snapshot); const snapshotEvidence = [...rows(record(run.calculation || snapshot.planning).evidence), ...messages, ...strategies, ...Object.values(record(snapshot.data || snapshot)).flatMap(value => rows(value))];
  const frozenRounds = number(record(run.calculation).review_rounds);
  const configuredRounds = number(record(record(settingsQuery.data).llm).review_rounds) || 1;
  const reviewRounds = frozenRounds || configuredRounds;
  const historicalRoles = Array.from(new Set([...messages.map(message => text(message.role)), ...Object.keys(progress)]))
    .filter(role => ['procurement', 'inventory', 'inventory_logistics', 'production_management', 'production_planning', 'production', 'qc', 'qa'].includes(role));
  const isHistorical = !frozenRounds && historicalRoles.length > 0;
  const hasLegacyAdmin = messages.some(message => message.role === 'admin') || typeof progress.admin === 'string';
  const visibleRoles: string[] = isHistorical || hasLegacyAdmin ? [...new Set([...messages.map(message => text(message.role)), ...Object.keys(progress).filter(role => typeof progress[role] === 'string')])] : [...discussionRoles];
  const currentRound = number(progress.round) || Math.max(0, ...messages.filter(message => reviewerRoles.some(role => role === message.role)).map(message => number(message.version)));
  return <>
    <PageHeading eyebrow="PARALLEL AI REVIEW" title={id ? 'AI 검토 결과 · Orchestrator 통합' : 'AI 병렬 검토'} description={id ? '실제 AI 검토, 계산 근거와 남은 이견을 확인하고 담당자가 최종 판단합니다.' : `4개 AI가 ${configuredRounds}회 병렬 검토한 뒤 Orchestrator가 검토 결과와 핵심 검증 자료를 통합해 최선의 안을 제안합니다.`} action={<button className="button primary" disabled={busy || !user.id} onClick={start}><Plus size={17}/>{busy ? '실행 요청 중…' : id ? '현재 데이터로 새 검토' : '현재 상황으로 AI 병렬 검토 시작'}</button>}/>
    <ReadOnlyNotice/>
    <ErrorBox error={error || listQuery.error || runQuery.error}/>
    <div className="decision-steps" aria-label="원료 의사결정 순서"><span>1. 부족·유효기간 확인</span><ChevronRight size={15}/><span>2. 기본안 A/B/C</span><ChevronRight size={15}/><strong>3. 4개 AI 병렬 검토</strong><ChevronRight size={15}/><span>4. Orchestrator 통합</span><ChevronRight size={15}/><span>5. 담당자 승인</span></div>
    <div className="notice"><MessagesSquare size={17}/>계산 후보는 검토 자료이며 추천이 아닙니다. 실제 협의가 발주 필요성과 공급안·시점을 검토합니다. 역산 기한과 미래 QC/QA 완료일은 추정이며, 실제 발주일은 담당자 결정 전 미정입니다.</div>
    {po && <Success><strong>내부 발주가 등록되었습니다 · {text(po.code || po.id)}</strong><p>외부 전송 없음 · 승인으로 QC/QA 상태는 변경되지 않습니다.</p><button className="text-button" onClick={() => navigate('/erp/purchase-orders')}>내부 발주 목록 보기 →</button></Success>}
    {!id ? <>
      <div className="notice"><MessagesSquare size={17}/>실제 LLM 설정이 필요합니다. 자격증명이 없거나 호출이 실패하면 가짜 협의나 추천을 만들지 않습니다.</div>
      <Panel title="협의 이력" subtitle="현재 시나리오의 불변 스냅샷과 실제 호출 기록입니다.">
        {listQuery.isPending ? <Loading/> : rows(listQuery.data).length ? <div className="discussion-list">{rows(listQuery.data).map(item => <button key={text(item.id)} onClick={() => navigate(`/discussions/${text(item.id)}`)}><span className="discussion-list-icon"><MessagesSquare size={21}/></span><div><strong>원료 조달 협의 <code>#{text(item.id).slice(0, 8)}</code></strong><p>스냅샷 v{text(item.snapshot_revision)} · {time(item.created_at)}</p></div><Badge value={item.status}/><ChevronRight size={18}/></button>)}</div> : <Empty title="아직 실행한 협의가 없습니다">재고·수요 상황을 확인하고 실제 AI 협의를 요청하세요. 협의가 완료되기 전에는 추천안을 표시하지 않습니다.</Empty>}
      </Panel>
    </> : <>
      <button className="text-button back-link" onClick={() => navigate('/discussions')}><ArrowLeft size={15}/>협의 목록</button>
      <div className="run-status-strip"><div><Badge value={run.status}/><code>#{text(run.id).slice(0, 8)}</code><span>스냅샷 v{text(run.snapshot_revision)}</span><span>{time(run.created_at)}</span></div>{active && <span className="stream-status"><Radio size={14}/>{connected ? '실시간 진행 수신 중' : '저장된 진행 상태 확인 중'}</span>}<button className="text-button" onClick={() => setEvidenceRun(!evidenceRun)}>당시 스냅샷 {evidenceRun ? '접기' : '보기'}</button></div>
      {evidenceRun && <Panel title="협의 원본 스냅샷" subtitle="현재 ERP가 아니라 협의 시작 당시 저장된 데이터입니다."><RecordDetails row={snapshot}/></Panel>}
      {stale && <div className="error-box"><TriangleAlert size={20}/><div><strong>협의 이후 ERP 입력이 변경되었습니다</strong><p>과거 근거는 보존되지만 이전 추천을 승인할 수 없습니다. 현재 데이터로 새 협의를 실행하세요.</p></div></div>}
      {run.error != null && <ErrorBox error={typeof run.error === 'string' ? new Error(run.error) : new Error(display(run.error))}/>}
      <Panel title={isHistorical ? '저장된 과거 역할별 진행 상태' : `4개 AI 병렬 검토 → Orchestrator 통합 · ${currentRound ? `${Math.min(currentRound, reviewRounds)} / ${reviewRounds}라운드` : `총 ${reviewRounds}라운드 대기`}`} subtitle={isHistorical ? '이 실행 당시의 역할과 실제 기록을 그대로 표시합니다.' : '각 라운드에서 구매·재고 및 생산계획·품질·재무가 동시에 검토합니다. 다음 라운드는 직전 전체 의견을 참고하고, 모든 라운드 후 Orchestrator가 통합 판단합니다.'}>
        <div className="role-progress" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>{visibleRoles.map(role => {
          const roleMessages = messages.filter(message => message.role === role); const state = text(progress[role]) || (roleMessages.length ? 'completed' : 'pending');
          return <div className={`role-state ${state}`} key={role}><span>{state === 'completed' ? <CheckCircle2 size={18}/> : state === 'running' ? <Loader2 size={18} className="spin"/> : <CircleDot size={18}/>}</span><strong>{label(role)}</strong><small>{label(state)}</small></div>;
        })}</div>
      </Panel>
      <section className="recommendation-section">
        <div className="section-heading"><div><span className="eyebrow">4 · ORCHESTRATOR OUTCOME</span><h2>Orchestrator 통합 추천 · 우선순위</h2><p>모든 회차의 실제 검토 의견과 핵심 검증 자료를 통합해 Orchestrator가 정한 추천 순서입니다. 기본 계산의 비용 순서가 아닙니다. 추천 이유·이견·조건부 일정을 확인한 뒤 담당자가 선택·승인하세요. 추천은 QC/QA 사용 승인이 아닙니다.</p></div></div>
        {recommendations.length ? <CandidateComparison stage="recommendation" candidates={recommendations.map(item => ({ ...record(item.candidate), recommendation_id: item.id }))} action={candidate => {
          const recommendation = recommendations.find(item => item.id === candidate.recommendation_id)!;
          return <>
            <div className="rationale-list">{rows(recommendation.rationale_items).map((rationale, index) => <div key={index}><strong>{text(rationale.claim)}</strong><Evidence refs={[...(Array.isArray(rationale.evidence_refs) ? rationale.evidence_refs : []), ...(Array.isArray(rationale.message_refs) ? rationale.message_refs : []), ...(Array.isArray(rationale.change_refs) ? rationale.change_refs : [])]} extra={snapshotEvidence}/></div>)}</div>
            {Array.isArray(recommendation.remaining_risks) && recommendation.remaining_risks.length > 0 && <div className="risk-note"><strong>남은 위험</strong>{recommendation.remaining_risks.map((risk, i) => <p key={i}>{display(risk)}</p>)}</div>}
            <button className="button primary full-width" disabled={stale || user.role !== 'approver' || recommendation.status === 'selected' || !record(candidate.validation).hard_constraints_passed} onClick={() => adoptRecommendation ? adoptRecommendation(recommendation) : setApproval(recommendation)}><ShieldCheck size={16}/>{recommendation.status === 'selected' ? '내부 발주 등록 완료' : stale ? '변경됨 · 재협의 필요' : user.role !== 'approver' ? '승인 담당자 권한 필요' : adoptRecommendation ? '주 업무의 2차 승인으로 가져오기' : '이 안 검토 후 최종 승인'}</button>
          </>;
        }} evidence={snapshotEvidence}/> : <Empty title={active ? '부서 검토가 진행 중입니다' : status === 'failed' ? '협의가 완료되지 않았습니다' : '협의에서 제안한 추천안이 없습니다'}>{active ? '실제 역할 검토와 Orchestrator 재검증을 마친 뒤에만 추천안을 표시합니다. 계산 후보를 추천으로 대신 표시하지 않습니다.' : '실패 원인·이견·후보 제외 사유를 확인하세요. 추천이 없다는 이유로 제약 검증을 우회하거나 발주를 자동 생성하지 않습니다.'}</Empty>}
      </section>
      <Panel title="협의 당시 참고 계산과 제약 위반 사유" subtitle="수치 검증은 부서별 적합성 판단이나 실제 품질 승인이 아닙니다. 과거 계산은 현재 ERP 데이터로 덮어쓰지 않습니다.">
        <details className="historical-candidates"><summary>당시 전체 계산 후보 보기 ({rows(record(run.calculation).candidates).length}개)</summary><CandidateComparison candidates={rows(record(run.calculation).candidates)} evidence={snapshotEvidence}/><details><summary>버전별 검증 원본</summary><pre>{JSON.stringify(run.validations || [], null, 2)}</pre></details></details>
      </Panel>
      <Panel title="AI별 검토 의견과 남은 이견" subtitle="의견은 계산 검증 근거와 구분합니다. 남은 반대·추가 확인 요청을 숨기지 않습니다.">
        {messages.length ? <div className="department-summary">{latestMessages.map(message => <article key={text(message.id)}>
          <div className="department-heading"><span className="department-avatar">{label(message.role).slice(0, 2)}</span><div><strong>{label(message.role)}</strong><small>{isHistorical ? `전략 v${text(message.version)}` : message.role === 'admin' ? '과거 Admin 통합 판단' : message.role === 'orchestrator' ? '전체 라운드 통합 판단' : `병렬 검토 ${text(message.version)} / ${reviewRounds}라운드`}</small></div><Badge value={message.position}>{!isHistorical && message.position === 'accept' ? '검토상 수용' : label(message.position)}</Badge></div>
          <h3>{typeof message.proposal === 'string' ? message.proposal : text(record(message.proposal).summary) || '전략 검토 의견'}</h3>
          {message.reasons != null && <div className="department-reasons">{Array.isArray(message.reasons) ? message.reasons.map((reason, index) => <p key={index}>{typeof reason === 'string' ? reason : display(record(reason).message || reason)}</p>) : <p>{display(message.reasons)}</p>}</div>}
          <details><summary>수치 영향 · 남은 조건과 요청 조치</summary><h4>검증된 수치 영향</h4><pre>{JSON.stringify(message.impacts, null, 2)}</pre><h4>남은 조건 · 확인/수정 요청</h4>{Array.isArray(message.change_requests) ? message.change_requests.map((request, index) => <p key={index}>{display(request)}</p>) : <pre>{JSON.stringify(message.change_requests, null, 2)}</pre>}</details><Evidence refs={message.evidence_refs} extra={snapshotEvidence}/>
        </article>)}</div> : <Empty title="아직 저장된 역할 의견이 없습니다"/>}
      </Panel>
      <Panel title={isHistorical ? '전략 버전과 변경 이력' : '라운드별 검토 전략과 변경 이력'} subtitle="원본 제안은 덮어쓰지 않고 버전별로 보존합니다.">
        {strategies.length ? <div className="strategy-list">{strategies.map((strategy, index) => {
          const previous = strategies[index - 1]; const keys = previous ? Object.keys(strategy).filter(key => !['id', 'created_at', 'version'].includes(key) && JSON.stringify(strategy[key]) !== JSON.stringify(previous[key])) : [];
          return <details key={text(strategy.id)}><summary><GitBranch size={17}/><strong>전략 v{text(strategy.version) || index + 1}</strong><span>{index === 0 ? '최초 제안' : `이전 버전 대비 ${keys.length}개 항목 변경`}</span></summary>{previous && keys.map(key => <div className="version-diff" key={key}><strong>{key}</strong><div><span>이전</span><pre>{JSON.stringify(previous[key], null, 2)}</pre></div><div><span>수정</span><pre>{JSON.stringify(strategy[key], null, 2)}</pre></div></div>)}<RecordDetails row={strategy}/></details>;
        })}</div> : <Empty title="저장된 전략 버전이 없습니다"/>}
      </Panel>
      <Panel><details className="full-log"><summary><MessagesSquare size={19}/><strong>전체 토론 원본 로그</strong><span>{messages.length}개 메시지</span></summary>{messages.map(message => <details key={text(message.id)}><summary>{label(message.role)} · v{text(message.version)} · <code>{text(message.id)}</code></summary><RecordDetails row={message}/></details>)}<details><summary>원본 실행 이벤트</summary><pre>{JSON.stringify(run.events || [], null, 2)}</pre></details></details></Panel>
    </>}
    {approval && <Approval recommendation={approval} close={() => setApproval(null)} approved={result => { setPo(result); runQuery.refetch(); }}/>}
  </>;
}
