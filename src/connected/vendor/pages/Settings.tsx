import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Edit3, KeyRound, Link2, Plus, RefreshCw, Save, ShieldCheck } from 'lucide-react';
import { api, discussionRoles, display, label, record, rows, send, text, time, type Row } from '../api';
import { Badge, Empty, ErrorBox, Loading, Modal, PageHeading, Panel, ReadOnlyNotice, RecordDetails, Success, useWorkspace } from '../components';
function SourceForm({ source, close, saved }: { source: Row; close: () => void; saved: () => void }) {
  const { scenario } = useWorkspace(); const [values, setValues] = useState<Row>({ kind: 'rss', enabled: true, ownership_verified: false, poll_interval_minutes: 720, ...source }); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>();
  return <Modal title={`공식 수집 소스 ${source.id ? '수정' : '등록'}`} close={close}><form onSubmit={async event => { event.preventDefault(); setBusy(true); setError(undefined); try { const payload = { ...Object.fromEntries(['revision', 'kind', 'display_name', 'url', 'enabled', 'official_domain', 'ownership_verified'].filter(key => values[key] !== undefined).map(key => [key, values[key]])), supplier_id: values.supplier_id || null, poll_interval_minutes: Number(values.poll_interval_minutes) }; await send(`/external-sources${source.id ? `/${text(source.id)}` : ''}`, payload, source.id ? 'PATCH' : 'POST'); saved(); close(); } catch (err) { setError(err); } finally { setBusy(false); } }}><div className="notice"><ShieldCheck size={17}/>공개 HTTPS 공식 소스만 허용됩니다. 사설망·로컬 주소 및 검증되지 않은 리다이렉트는 서버에서 거부합니다.</div><div className="form-grid"><label>표시 이름<input required value={text(values.display_name)} onChange={event => setValues({ ...values, display_name: event.target.value })}/></label><label>소스 종류<select value={text(values.kind)} onChange={event => setValues({ ...values, kind: event.target.value })}><option value="rss">RSS / Atom</option><option value="openfda">openFDA Enforcement</option></select></label><label className="span-two">공식 HTTPS URL<input type="url" required value={text(values.url)} placeholder="https://" onChange={event => setValues({ ...values, url: event.target.value })}/></label><label>공식 도메인<input required value={text(values.official_domain)} placeholder="www.fda.gov" onChange={event => setValues({ ...values, official_domain: event.target.value })}/></label><label>수집 주기 (분)<input type="number" min="1" step="1" required value={text(values.poll_interval_minutes)} onChange={event => setValues({ ...values, poll_interval_minutes: event.target.value })}/></label><label className="span-two">연결 업체 (공식 소유 관계가 확인된 경우만)<select value={text(values.supplier_id)} onChange={event => setValues({ ...values, supplier_id: event.target.value || null })}><option value="">업체 연결 없음</option>{rows(scenario.suppliers).map(supplier => <option key={text(supplier.id)} value={text(supplier.id)}>{text(supplier.name)}</option>)}</select><small>실제 수집 공지를 가상 업체의 사고로 자동 연결하지 마세요.</small></label><label className="checkbox-label"><input type="checkbox" checked={values.enabled === true} onChange={event => setValues({ ...values, enabled: event.target.checked })}/>자동 수집 활성</label><label className="checkbox-label"><input type="checkbox" checked={values.ownership_verified === true} onChange={event => setValues({ ...values, ownership_verified: event.target.checked })}/>공식 소유 도메인 확인</label></div><ErrorBox error={error}/><footer className="modal-footer"><button className="button secondary" type="button" onClick={close} disabled={busy}>취소</button><button className="button primary" disabled={busy}><Save size={16}/>{busy ? '저장 중…' : '소스 저장'}</button></footer></form></Modal>;
}
function SourceRuns({ source, close }: { source: Row; close: () => void }) {
  const query = useQuery({ queryKey: ['source-runs', source.id], queryFn: () => api(`/external-sources/${text(source.id)}/runs`) });
  return <Modal title={`${text(source.display_name)} · 수집 이력`} close={close}>{query.isPending ? <Loading/> : <><ErrorBox error={query.error}/>{rows(query.data).length ? <div className="source-run-list">{rows(query.data).map(run => <details key={text(run.id)}><summary><Badge value={run.status}/><span>{time(run.started_at || run.created_at)}</span><span>수집 {display(run.fetched_count || run.count || run.items_count)}</span></summary><RecordDetails row={run}/></details>)}</div> : <Empty title="아직 수집 이력이 없습니다"/>}</>}<footer className="modal-footer"><button className="button secondary" onClick={close}>닫기</button></footer></Modal>;
}
export default function Settings({ settings }: { settings: Row }) {
  const { user } = useWorkspace(); const [editing, setEditing] = useState<Row | null>(null); const [runs, setRuns] = useState<Row | null>(null); const [success, setSuccess] = useState(''); const [error, setError] = useState<unknown>(); const [testing, setTesting] = useState(false);
  const sourcesQuery = useQuery({ queryKey: ['external-sources'], queryFn: () => api('/external-sources') }); const llm = record(settings.llm); const providers = record(llm.providers); const roles = record(llm.roles); const allowed = user.role === 'approver';
  return <>
    <PageHeading eyebrow="WORKSPACE SETTINGS" title="환경 · 연동 설정" description="실제 연결 상태와 역할별 모델 구성을 확인하고 공식 수집 소스를 관리합니다."/>
    <ReadOnlyNotice/>
    <ErrorBox error={error || sourcesQuery.error}/>
    {success && <Success>{success}</Success>}
    <div className="settings-grid">
      <Panel title="계정 · 접근 권한" subtitle="단일 조직의 로컬 계정과 서버 세션을 사용합니다.">
        <div className="setting-item"><span>초기 계정 설정</span><Badge value={settings.auth_configured ? 'completed' : 'pending'}>{settings.auth_configured ? '설정됨' : '서버 설정 필요'}</Badge></div>
        <div className="setting-item"><span>현재 사용자</span><strong>{text(user.email) || '읽기 전용 방문자'}</strong></div>
        <div className="setting-item"><span>역할</span><Badge>{user.role ? label(user.role) : '미인증'}</Badge></div>
        <div className="security-note"><KeyRound size={19}/><p>비밀번호·API 키는 서버 환경변수로만 설정합니다. 브라우저 응답에는 비밀값을 포함하지 않습니다.</p></div>
        {settings.setup_required === true && <div className="setup-instructions"><code>INITIAL_APPROVER_EMAIL</code><code>INITIAL_APPROVER_PASSWORD</code><code>SESSION_SECRET</code><p>서버 환경변수를 설정하고 API를 재시작하세요. 기본 로그인 비밀번호는 없습니다.</p></div>}
      </Panel>
      <Panel title="의사결정 안전 원칙" subtitle="계산·AI 검토·사람의 권한은 서로 대체하지 않습니다.">
        <div className="principle-list">
          <div><ShieldCheck size={19}/><span><strong>필수 품질 조건은 가격과 상쇄하지 않음</strong><small>QC/QA 승인과 발주 승인은 별도입니다.</small></span></div>
          <div><Link2 size={19}/><span><strong>미확인 이슈는 미확인으로 유지</strong><small>공식 공지도 ERP 관련성을 별도로 확인합니다.</small></span></div>
          <div><CheckCircle2 size={19}/><span><strong>최종 승인으로만 내부 PO 등록</strong><small>외부 공급업체에 이메일·API 주문을 보내지 않습니다.</small></span></div>
        </div>
      </Panel>
    </div>
    <Panel title="LLM 공급자 연결" subtitle="등록된 실제 모델만 호출합니다. 미설정·호출 오류를 합성 응답으로 대체하지 않습니다." action={
      <div className="provider-actions">
        <Badge value={llm.configured ? 'completed' : 'configuration_error'}>{llm.configured ? `선택 공급자: ${text(llm.provider)}` : '실제 토론을 위한 설정 필요'}</Badge>
        <button className="button secondary small" disabled={!allowed || testing} onClick={async () => {
          setTesting(true); setError(undefined); setSuccess('');
          try {
            const result = record(await send('/settings/test-provider', { role: 'purchasing' }));
            if (result.status !== 'connected') throw new Error('실제 모델 연결이 확인되지 않았습니다.');
            setSuccess('실제 구조화 모델 호출에 성공했습니다. 연결 확인은 전체 협의 완료를 의미하지 않습니다.');
          } catch (err) { setError(err); } finally { setTesting(false); }
        }}><RefreshCw size={13} className={testing ? 'spin' : ''}/>{testing ? '실제 호출 중…' : '실제 연결 확인'}</button>
      </div>
    }>
      <div className="provider-grid">{['openai', 'gemini', 'openrouter', 'vllm', 'openai_compatible'].map(name => {
        const provider = record(providers[name]);
        return <article className={`provider-card ${llm.provider === name ? 'selected' : ''}`} key={name}>
          <div><span className="provider-logo">{name === 'openai' ? 'O' : name === 'gemini' ? 'G' : name === 'openrouter' ? '↗' : name === 'vllm' ? 'V' : 'API'}</span><Badge value={provider.configured ? 'completed' : 'pending'}>{provider.configured ? '구성됨' : '미설정'}</Badge></div>
          <h3>{({ openai: 'OpenAI Responses', gemini: 'Google Gemini', openrouter: 'OpenRouter', vllm: 'vLLM', openai_compatible: 'OpenAI 호환 API' } as Record<string, string>)[name]}</h3>
          <span className="provider-model">{text(provider.model) || '모델 ID 필요'}</span><small>{llm.provider === name ? '현재 선택된 공급자' : '자동 공급자 전환 없음'}</small>
        </article>;
      })}</div>
      <div className="panel-footnote">설정됨은 자격증명·모델 구성 여부이며 연결 성공을 보장하지 않습니다. 실제 호출 결과는 협의 실행에 기록됩니다.</div>
      <div className="setting-item"><span>4개 검토 AI 병렬 라운드</span><strong>{text(llm.review_rounds ?? 1)}회 · 완료 후 Orchestrator 통합</strong></div>
      <p className="projection-note">구매·재고 및 생산계획·품질·재무가 매 라운드 동시에 검토합니다. 2회 이상이면 다음 라운드는 직전 전체 의견을 참고하며, 설정한 모든 라운드를 마친 후 Orchestrator가 전체 맥락을 통합합니다. 실행 도중 설정을 바꿔도 이미 시작한 협의의 라운드 수는 바뀌지 않습니다.</p>
      <details className="settings-environment">
        <summary>서버 환경변수 설정 안내</summary>
        <div className="environment-grid">
          <div><strong>공통 · 통합 검토</strong><code>LLM_PROVIDER</code><code>LLM_TIMEOUT_SECONDS=60</code><code>LLM_ORCHESTRATOR_TIMEOUT_SECONDS=180</code><code>LLM_REASONING_EFFORT=low</code><code>LLM_REVIEW_ROUNDS=1</code><small>기본 1회 · 2로 설정하면 4개 AI 병렬 검토를 두 번 실행</small></div>
          <div><strong>OpenAI Responses</strong><code>OPENAI_API_KEY</code><code>OPENAI_MODEL</code><code>OPENAI_BASE_URL (선택)</code></div>
          <div><strong>Gemini</strong><code>GEMINI_API_KEY</code><code>GEMINI_MODEL</code></div>
          <div><strong>OpenRouter</strong><code>OPENROUTER_API_KEY</code><code>OPENROUTER_MODEL</code></div>
          <div><strong>vLLM</strong><code>VLLM_BASE_URL</code><code>VLLM_MODEL</code><code>VLLM_API_KEY (선택)</code></div>
          <div><strong>OpenAI 호환 Chat Completions</strong><code>LLM_PROVIDER=openai_compatible</code><code>OPENAI_COMPATIBLE_BASE_URL</code><code>OPENAI_COMPATIBLE_MODEL</code><code>OPENAI_COMPATIBLE_API_KEY (선택)</code></div>
        </div>
        <p>vLLM·호환 API는 접근 가능한 /v1 기본 URL과 서버에서 제공하는 정확한 모델 ID가 모두 필요합니다. URL만으로는 연결할 수 없으며 strict JSON Schema 구조화 출력을 지원해야 합니다. vLLM은 별도 서버에서 실행하고 GPU 병렬화는 서버의 <code>vllm serve … --tensor-parallel-size …</code>로 설정합니다.</p>
        <p>역할별 LLM_ROLE_MAPPING의 timeout(초)이 최우선이며, 없으면 Orchestrator는 전용 제한 시간(기본 180초), 나머지 역할은 공통 제한 시간(기본 60초)을 사용합니다. 변경 후 API와 worker를 모두 재시작해야 합니다. 비동기 LLM 요청 시간초과는 서버 전체 중단을 의미하지 않습니다. 시간초과는 자동 재시도하지 않으며 원본 오류와 전체 검토 근거를 보존합니다.</p>
        <p>추론 강도는 auto·low·medium·high를 지원합니다. 빠른 판단에는 <code>LLM_REASONING_EFFORT=low</code>를 사용하며, 역할별 <code>LLM_ROLE_MAPPING</code>의 <code>reasoning_effort</code>가 공통 설정보다 우선합니다. 환경변수가 없으면 auto이며, auto는 추론 제어값을 보내지 않고 모델 기본값을 사용한다는 뜻이지 생각을 끈다는 뜻은 아닙니다.</p>
        <p>low·medium·high는 선택한 모델과 API 서버가 해당 추론 제어를 지원해야 합니다. 미지원 오류 시 auto로 바꾸거나 자동 재시도하지 않습니다. 네이티브 Gemini는 모델별 thinking_level·thinking_budget 차이 때문에 이 연동에서 auto만 허용합니다. 공통 low와 함께 사용하려면 해당 Gemini 역할의 reasoning_effort를 auto로 명시하세요.</p>
      </details>
      {Object.keys(roles).length > 0 && <div className="role-models"><h3>4개 검토 AI + Orchestrator 모델 매핑</h3>{discussionRoles.map(role => <div key={role}><strong>{label(role)}</strong><code>{typeof roles[role] === 'string' ? text(roles[role]) : `${text(record(roles[role]).provider)} / ${text(record(roles[role]).model)}`}</code><small>요청 제한 시간 {text(record(roles[role]).timeout)}초 · 추론 강도 {text(record(roles[role]).reasoning_effort)}</small>{record(roles[role]).configuration_error != null && <small className="danger-text">{text(record(roles[role]).configuration_error)}</small>}</div>)}</div>}
    </Panel>
    <Panel title="공식 외부 수집 소스" subtitle="승인 담당자가 공식 도메인과 소유 관계를 확인한 후 등록합니다." action={<button className="button primary small" disabled={!allowed} onClick={() => setEditing({})}><Plus size={15}/>소스 추가</button>}>
      <div className="table-scroll"><table>
        <thead><tr><th>소스</th><th>종류 / 상태</th><th>최근 성공 (KST)</th><th>공식 확인</th><th>관리</th></tr></thead>
        <tbody>{rows(sourcesQuery.data).map(source => <tr key={text(source.id)}>
          <td><strong>{text(source.display_name || source.name)}</strong><small className="source-url">{text(source.url)}</small>{source.last_error != null && <small className="danger-text">{display(source.last_error)}</small>}</td>
          <td><Badge value={source.enabled ? 'normal' : 'pending'}>{label(source.kind)} · {source.enabled ? '활성' : '비활성'}</Badge></td>
          <td>{time(source.last_success)}</td>
          <td><Badge value={source.ownership_verified ? 'completed' : 'pending'}>{source.ownership_verified ? '소유 관계 확인' : '확인 필요'}</Badge></td>
          <td><div className="table-actions"><button className="text-button" onClick={() => setRuns(source)}>수집 이력</button><button className="icon-button" disabled={!allowed} onClick={() => setEditing(source)} aria-label={`${text(source.display_name)} 수정`}><Edit3 size={16}/></button></div></td>
        </tr>)}</tbody>
      </table></div>
      {!rows(sourcesQuery.data).length && <Empty title="등록된 소스가 없습니다"/>}
      <div className="panel-footnote">실제 수집과 동기화는 외부 이슈 모니터에서 실행합니다. 수집 실패 시 이전 데이터는 보존되며 승인 전 최신성 확인이 필요합니다.</div>
    </Panel>
    {editing && <SourceForm source={editing} close={() => setEditing(null)} saved={() => { sourcesQuery.refetch(); setSuccess('공식 수집 소스 설정을 저장했습니다.'); }}/>}
    {runs && <SourceRuns source={runs} close={() => setRuns(null)}/>}
  </>;
}
