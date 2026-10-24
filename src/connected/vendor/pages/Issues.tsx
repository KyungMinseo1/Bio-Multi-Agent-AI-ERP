import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, FileCheck2, Link2, Plus, Radar, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { api, date, display, label, record, rows, send, text, time, type Row } from '../api';
import { Badge, Empty, ErrorBox, Modal, PageHeading, Panel, ReadOnlyNotice, RecordDetails, Success, useWorkspace } from '../components';
function VerifyIssue({ issue, close, saved }: { issue: Row; close: () => void; saved: () => void }) {
  const { scenarioId, scenario, user, refresh } = useWorkspace();
  const [status, setStatus] = useState('relevance_unconfirmed'); const [reason, setReason] = useState(''); const [evidence, setEvidence] = useState(''); const [delay, setDelay] = useState(''); const [demo, setDemo] = useState(false);
  const [target, setTarget] = useState<Record<string, string>>({ supplier_id: '', material_id: '', lot_id: '', purchase_order_id: '' }); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>();
  const issueQuery = useQuery({ queryKey: ['issue-evidence', scenarioId, issue.id], queryFn: () => api(`/issues/${text(issue.id)}?scenario_id=${scenarioId}`) });
  const evidenceChoices = [...rows(record(issueQuery.data).evidence_versions), ...(issue.source_kind === 'synthetic' ? [{ id: issue.id, name: '합성 이슈 원본' }] : [])];
  const real = issue.source_kind !== 'synthetic' && issue.is_synthetic !== true;
  return <Modal title="외부 이슈 관련성 확인" close={close}><form onSubmit={async event => { event.preventDefault(); setBusy(true); setError(undefined); try { if (!Object.values(target).some(Boolean)) throw new Error('영향을 확인할 ERP 대상을 하나 이상 선택하세요.'); if (real && !demo) throw new Error('실제 공지와 가상 ERP의 시연 연결 여부를 명시해 주세요.'); await send(`/scenarios/${scenarioId}/issues/${text(issue.id)}/links`, { ...Object.fromEntries(Object.entries(target).map(([key, value]) => [key, value || null])), verification_status: status, reason, evidence_refs: evidence.split(/[\n,]/).map(value => value.trim()).filter(Boolean), delay_days: delay ? Number(delay) : null, demo_association: real ? demo : false }); await refresh(); saved(); close(); } catch (err) { setError(err); } finally { setBusy(false); } }}><div className="form-description"><strong>{text(issue.title || issue.name || issue.summary)}</strong><p>원료명 유사성만으로 거래를 막지 않습니다. 실제 제품·Lot·납품분과의 관련성을 근거로 확인하세요.</p></div><div className="form-grid"><label className="span-two">확인 상태<select value={status} onChange={event => setStatus(event.target.value)}>{['relevance_unconfirmed', 'supply_impact_confirmed', ...(user.role === 'approver' ? ['quality_impact_confirmed', 'cleared'] : [])].map(value => <option key={value} value={value}>{label(value)}</option>)}</select><small>품질 영향 확정과 해제는 승인 담당자만 가능합니다.</small></label>{[['supplier_id', '공급업체', 'suppliers'], ['material_id', '원료', 'materials'], ['lot_id', 'Lot', 'lots'], ['purchase_order_id', '내부 발주', 'purchase_orders']].map(([key, name, source]) => <label key={key}>{name}<select value={target[key]} onChange={event => setTarget({ ...target, [key]: event.target.value })}><option value="">연결 안 함</option>{rows(scenario[source]).map(row => <option key={text(row.id)} value={text(row.id)}>{text(row.code)} {text(row.name)}</option>)}</select></label>)}<label className="span-two">확인 사유 · 범위<textarea value={reason} required onChange={event => setReason(event.target.value)} placeholder="제품, Lot, 납품분과의 일치 여부 및 확인 범위를 기록하세요."/></label><label className="span-two">근거 ID (줄바꿈 또는 쉼표 구분)<><textarea value={evidence} required onChange={event => setEvidence(event.target.value)} placeholder="원본 이슈 / Evidence / ERP 레코드 ID"/><span className="evidence-choices">{evidenceChoices.map((item, index) => <button type="button" className="text-button" key={text(item.id)} onClick={() => setEvidence(previous => [...new Set([...previous.split(/[\n,]/).map(value => value.trim()).filter(Boolean), text(item.id)])].join('\n'))}>+ {text(item.name) || `근거 버전 ${index + 1}`} <code>{text(item.id).slice(0, 8)}</code></button>)}</span></><small>임의 설명이 아니라 실제 저장된 근거의 ID를 입력합니다.</small></label>{status === 'supply_impact_confirmed' && <label>확인된 공급 지연일 (선택)<input type="number" min="0" step="1" value={delay} onChange={event => setDelay(event.target.value)}/><small>모르는 지연일을 임의로 추정하지 마세요.</small></label>}{real && <label className="checkbox-label span-two"><input type="checkbox" checked={demo} required onChange={event => setDemo(event.target.checked)}/><span>실제 공지와 가상 ERP의 <strong>시연 목적 연결</strong>임을 확인합니다. 실제 업체 피해를 확인한 것이 아닙니다.</span></label>}</div><ErrorBox error={error}/><footer className="modal-footer"><button className="button secondary" type="button" disabled={busy} onClick={close}>취소</button><button className="button primary" disabled={busy}><FileCheck2 size={16}/>{busy ? '기록 중…' : '확인 결과 저장'}</button></footer></form></Modal>;
}
function NewIssue({ close, saved }: { close: () => void; saved: () => void }) {
  const { scenarioId, refresh } = useWorkspace(); const [title, setTitle] = useState(''); const [summary, setSummary] = useState(''); const [error, setError] = useState<unknown>(); const [busy, setBusy] = useState(false);
  return <Modal title="합성 이슈 직접 등록" close={close}><form onSubmit={async event => { event.preventDefault(); setBusy(true); try { await send(`/scenarios/${scenarioId}/issues`, { title, name: title, summary, source_kind: 'synthetic', is_synthetic: true, verification_status: 'relevance_unconfirmed', severity: 'information', publisher: '사용자 등록 합성 자료' }); await refresh(); saved(); close(); } catch (err) { setError(err); } finally { setBusy(false); } }}><div className="notice">직접 등록 항목은 합성 자료로 표시합니다. 실제 공지는 공식 소스 동기화를 사용하세요.</div><div className="form-grid"><label className="span-two">이슈 제목<input value={title} onChange={event => setTitle(event.target.value)} required/></label><label className="span-two">내용 · 출처 설명<textarea value={summary} onChange={event => setSummary(event.target.value)} rows={6} required/></label></div><ErrorBox error={error}/><footer className="modal-footer"><button className="button secondary" type="button" onClick={close}>취소</button><button className="button primary" disabled={busy}>{busy ? '저장 중…' : '이슈 등록'}</button></footer></form></Modal>;
}
function IssueDetails({ issue, close }: { issue: Row; close: () => void }) {
  const { scenarioId } = useWorkspace();
  const query = useQuery({ queryKey: ['issue-evidence', scenarioId, issue.id], queryFn: () => api(`/issues/${text(issue.id)}?scenario_id=${scenarioId}`) });
  return <Modal title="이슈 원본 · 근거 버전" close={close}><ErrorBox error={query.error}/>{query.isPending ? <p className="form-description">원본과 근거 버전을 불러오고 있습니다…</p> : <RecordDetails row={{ ...record(query.data), scenario_association: issue }}/>}<footer className="modal-footer"><button className="button secondary" onClick={close}>닫기</button></footer></Modal>;
}
export default function Issues() {
  const { scenario, user, refresh } = useWorkspace(); const [search, setSearch] = useState(''); const [filter, setFilter] = useState('all'); const [verify, setVerify] = useState<Row | null>(null); const [detail, setDetail] = useState<Row | null>(null); const [create, setCreate] = useState(false); const [busy, setBusy] = useState(''); const [error, setError] = useState<unknown>(); const [success, setSuccess] = useState('');
  const sourcesQuery = useQuery({ queryKey: ['external-sources'], queryFn: () => api('/external-sources') });
  const issues = rows(scenario.issues).filter(issue => `${text(issue.title || issue.name)} ${text(issue.summary)} ${text(issue.publisher)}`.toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || filter === 'synthetic' ? filter === 'all' || issue.source_kind === 'synthetic' : filter === 'real' ? issue.source_kind !== 'synthetic' : ['unverified', 'relevance_unconfirmed'].includes(text(issue.verification_status))));
  return <>
    <PageHeading eyebrow="EXTERNAL SIGNALS & VERIFICATION" title="외부 이슈 모니터" description="공식 공지와 우리 ERP의 관련성을 구분하고, 확인된 영향만 의사결정에 반영합니다." action={<button className="button primary" disabled={!user.id} onClick={() => setCreate(true)}><Plus size={17}/>합성 이슈 등록</button>}/>
    <ReadOnlyNotice/><ErrorBox error={error || sourcesQuery.error}/>
    {success && <Success>{success}</Success>}
    <div className="notice"><ShieldAlert size={18}/>공식 공지도 관련성 확인 전에는 공급 차질로 확정하지 않습니다. 공개 소스가 공급망 전체를 포착하는 것은 아닙니다.</div>
    <Panel title="공식 소스 동기화" subtitle="실제 외부 수집과 합성 시나리오 자료는 명확히 구분됩니다.">
      <div className="source-status-grid">{rows(sourcesQuery.data).map(source => <article className="source-status" key={text(source.id)}>
        <div><span className="source-icon"><Radar size={21}/></span><div><h3>{text(source.display_name || source.name)}</h3><Badge value={source.enabled ? 'normal' : 'pending'}>{source.enabled ? '수집 활성' : '수집 비활성'}</Badge></div></div>
        <p>최근 성공 <strong>{time(source.last_success)}</strong></p>
        {source.last_error != null && <p className="danger-text">{display(source.last_error)}</p>}
        <button className="button secondary small" disabled={user.role !== 'approver' || !!busy} onClick={async () => {
          setBusy(text(source.id)); setError(undefined); setSuccess('');
          try {
            const result = record(await send(`/external-sources/${text(source.id)}/sync`, {}));
            await Promise.all([refresh(), sourcesQuery.refetch()]);
            if (result.status === 'failed') throw new Error(text(result.error) || '수집이 실패했습니다. 이전 데이터는 보존됩니다.');
            setSuccess(`공식 소스 동기화 결과: ${label(result.status || 'completed')}. 수집 이력과 현재 시나리오 관련성을 확인하세요.`);
          } catch (err) { setError(err); } finally { setBusy(''); }
        }}><RefreshCw size={14} className={busy === source.id ? 'spin' : ''}/>{busy === source.id ? '수집 중…' : '지금 동기화'}</button>
      </article>)}</div>
      {!rows(sourcesQuery.data).length && <Empty title="등록된 공식 수집 소스가 없습니다">환경 · 연동 설정에서 승인 담당자가 소스를 등록할 수 있습니다.</Empty>}
    </Panel>
    <Panel>
      <div className="table-toolbar">
        <div><h2>이슈 목록 <span>{issues.length}</span></h2><p>원문과 근거 버전, 확인 시각 및 ERP 연결을 검토하세요.</p></div>
        <div className="search-input"><Search size={16}/><input aria-label="이슈 검색" value={search} placeholder="제목, 내용, 발행기관 검색" onChange={event => setSearch(event.target.value)}/></div>
      </div>
      <div className="tabs inside">
        <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>전체</button>
        <button className={filter === 'unverified' ? 'active' : ''} onClick={() => setFilter('unverified')}>확인 필요</button>
        <button className={filter === 'real' ? 'active' : ''} onClick={() => setFilter('real')}>실제 수집</button>
        <button className={filter === 'synthetic' ? 'active' : ''} onClick={() => setFilter('synthetic')}>합성 자료</button>
      </div>
      <div className="issue-list">{issues.map(issue => {
        const synthetic = issue.source_kind === 'synthetic' || issue.is_synthetic === true;
        const url = text(issue.source_url || issue.url);
        return <article className="issue-card" key={text(issue.id)}>
          <div className="issue-card-top"><div className="issue-badges"><Badge value={synthetic ? 'synthetic' : 'normal'}>{synthetic ? '합성 자료' : '실제 공식 수집'}</Badge><Badge value={issue.verification_status}/>{issue.demo_association === true && <Badge>가상 ERP 시연 연결</Badge>}</div><small>{text(issue.publisher)}</small></div>
          <h3>{text(issue.title || issue.name) || '외부 이슈'}</h3>
          <p>{text(issue.summary)}</p>
          <div className="issue-dates"><span>발행 {date(issue.published_at)}</span><span>발생 {date(issue.occurred_at)}</span><span>수집 {time(issue.fetched_at)}</span><span>확인 {time(issue.verified_at || rows(issue.links).at(-1)?.confirmed_at)}</span></div>
          {rows(issue.links).length > 0 && <details className="issue-links">
            <summary><Link2 size={14}/>ERP 연결 · 확인 이력 {rows(issue.links).length}건</summary>
            {rows(issue.links).map((link, index) => <div key={text(link.id) || index}>
              <Badge value={link.verification_status}/>{link.demo_association === true && <Badge>시연 연결</Badge>}
              <p>{text(link.reason)}</p>
              <small>확인자 {text(link.confirmed_by)} · {time(link.confirmed_at)}</small>
              <pre>{JSON.stringify(link, null, 2)}</pre>
            </div>)}
          </details>}
          <div className="issue-actions">
            <button className="text-button" onClick={() => setDetail(issue)}>근거 · 원본 상세</button>
            {/^https?:\/\//i.test(url) && <a className="text-button" href={url} target="_blank" rel="noopener noreferrer">공식 원문<ExternalLink size={14}/></a>}
            <button className="button secondary small" disabled={!user.id} onClick={() => setVerify(issue)}><FileCheck2 size={15}/>관련성 확인</button>
          </div>
        </article>;
      })}{!issues.length && <Empty title="조건에 맞는 이슈가 없습니다">공식 소스를 동기화하거나 필터를 변경해 보세요. 수집 공지가 없다고 공급 위험이 없는 것은 아닙니다.</Empty>}</div>
    </Panel>
    {verify && <VerifyIssue issue={verify} close={() => setVerify(null)} saved={() => setSuccess('관련성 확인을 저장했습니다. 현재 시나리오 계산과 변경된 추천 상태를 확인하세요.')}/>}
    {detail && <IssueDetails issue={detail} close={() => setDetail(null)}/>}
    {create && <NewIssue close={() => setCreate(false)} saved={() => setSuccess('합성 이슈를 등록했습니다. 관련성은 별도로 확인해야 합니다.')}/>}
  </>;
}
