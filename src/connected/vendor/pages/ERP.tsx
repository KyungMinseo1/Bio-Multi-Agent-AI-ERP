import DecisionMemory from '../../../workflow/DecisionMemory';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { ChevronRight, Edit3, FileJson, Plus, Save, Search, SlidersHorizontal } from 'lucide-react';
import { date, display, label, money, quantity, rows, send, text, type Row } from '../api';
import { Badge, Empty, ErrorBox, Modal, PageHeading, Panel, ReadOnlyNotice, RecordDetails, Success, useWorkspace } from '../components';
import { collections, pageCollections, type Collection } from '../erpSchema';
function RecordForm({ collection, original, close, saved }: { collection: Collection; original: Row; close: () => void; saved: () => void }) {
  const { scenarioId, scenario, refresh } = useWorkspace();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(collection.fields.map(field => [
    field.key,
    field.type === 'json' ? original[field.key] == null ? '' : JSON.stringify(original[field.key], null, 2)
      : field.type === 'boolean' ? String(original[field.key] ?? (field.key === 'active'))
      : field.key === 'idempotency_key' ? text(original[field.key]) || crypto.randomUUID()
      : text(original[field.key]),
  ])));
  const [advanced, setAdvanced] = useState(false); const [raw, setRaw] = useState(JSON.stringify(original.id ? original : {}, null, 2));
  const [error, setError] = useState<unknown>(); const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError(undefined); setBusy(true);
    try {
      let payload: Row;
      if (advanced) { const parsed: unknown = JSON.parse(raw); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('레코드는 JSON 객체여야 합니다.'); payload = parsed as Row; }
      else { payload = { ...original }; for (const field of collection.fields) { const value = values[field.key]; if (value === '') { if (original[field.key] != null) payload[field.key] = null; else delete payload[field.key]; } else if (field.type === 'json') { try { payload[field.key] = JSON.parse(value); } catch { throw new Error(`${field.label}: 올바른 JSON 형식이 아닙니다.`); } } else if (field.type === 'boolean') payload[field.key] = value === 'true'; else payload[field.key] = value; } }
      delete payload.id; delete payload.created_at; delete payload.updated_at;
      if (original.id) payload.revision = original.revision;
      await send(`/scenarios/${scenarioId}/${collection.key}${original.id ? `/${text(original.id)}` : ''}`, payload, original.id ? 'PATCH' : 'POST');
      await refresh(); saved(); close();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  function switchMode() {
    if (!advanced) { const payload: Row = { ...original }; try { for (const field of collection.fields) if (values[field.key] !== '') payload[field.key] = field.type === 'json' ? JSON.parse(values[field.key]) : field.type === 'boolean' ? values[field.key] === 'true' : values[field.key]; setRaw(JSON.stringify(payload, null, 2)); } catch { setError(new Error('JSON 필드 형식을 먼저 수정하세요.')); return; } }
    else { try { const parsed: unknown = JSON.parse(raw); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('JSON 객체를 입력하세요.'); const data = parsed as Row; setValues(Object.fromEntries(collection.fields.map(field => [field.key, field.type === 'json' ? data[field.key] == null ? '' : JSON.stringify(data[field.key], null, 2) : text(data[field.key])]))); } catch (err) { setError(err); return; } }
    setAdvanced(!advanced); setError(undefined);
  }
  return <Modal title={`${collection.title} ${original.id ? '수정' : '등록'}`} close={close}><form onSubmit={submit}><div className="form-context"><span>현재 시나리오 <strong>{text(scenario.name)}</strong></span>{typeof original.id === 'string' && <Badge>레코드 v{text(original.revision)}</Badge>}<button className="text-button" type="button" onClick={switchMode}><FileJson size={15}/>{advanced ? '필드 양식으로' : '전체 JSON 편집'}</button></div><p className="form-description">{collection.description}</p>{advanced ? <label className="raw-editor">전체 레코드 JSON<textarea rows={22} value={raw} onChange={event => setRaw(event.target.value)} spellCheck={false}/><small>ID와 revision은 서버에서 보존합니다. 참조 ID는 현재 시나리오의 레코드를 사용하세요.</small></label> : <div className="form-grid">{collection.fields.map(field => { const options = field.ref ? rows(scenario[field.ref]) : []; const type = field.type; const value = values[field.key] || ''; return <label className={type === 'json' || type === 'textarea' ? 'span-two' : ''} key={field.key}>{field.label}{field.required && <span className="required"> *</span>}{type === 'select' || type === 'boolean' ? <select value={value} required={field.required} onChange={event => setValues({ ...values, [field.key]: event.target.value })}><option value="">선택 안 함</option>{type === 'boolean' ? <><option value="true">예</option><option value="false">아니오</option></> : field.ref ? options.map(row => <option value={text(row.id)} key={text(row.id)}>{text(row.code)} {text(row.name) || text(row.lot_code)}</option>) : (field.options || []).map(option => <option key={option} value={option}>{label(option)}</option>)}</select> : type === 'json' || type === 'textarea' ? <textarea rows={type === 'json' ? 5 : 3} className={type === 'json' ? 'code-input' : ''} value={value} required={field.required} onChange={event => setValues({ ...values, [field.key]: event.target.value })} spellCheck={type !== 'json'}/> : <input type={type === 'number' ? 'number' : type === 'date' ? 'date' : 'text'} step={type === 'number' ? 'any' : undefined} min={type === 'number' ? 0 : undefined} value={type === 'date' ? value.slice(0, 10) : value} required={field.required} onChange={event => setValues({ ...values, [field.key]: event.target.value })}/>}<small>{field.help || (field.ref && !options.length ? '먼저 참조 레코드를 등록해 주세요.' : '')}</small></label>; })}</div>}<ErrorBox error={error} retry={() => { refresh(); }}/><footer className="modal-footer"><span className="muted">저장 후 현재 시나리오만 재계산합니다.</span><button type="button" className="button secondary" disabled={busy} onClick={close}>취소</button><button className="button primary" disabled={busy}><Save size={16}/>{busy ? '저장 중…' : '저장'}</button></footer></form></Modal>;
}
export default function ERP() {
  const { page = 'materials' } = useParams(); const keys = pageCollections[page] || ['materials'];
  const [tab, setTab] = useState(''); const [search, setSearch] = useState(''); const [editing, setEditing] = useState<Row | null>(null); const [detail, setDetail] = useState<Row | null>(null); const [success, setSuccess] = useState(false);
  const { scenarioId,scenario, user } = useWorkspace();
  const collection = collections[keys.includes(tab) ? tab : keys[0]]; const source = rows(scenario[collection.key.replaceAll('-', '_')]);
  const list = source.filter(row => Object.values(row).some(value => display(value).toLowerCase().includes(search.toLowerCase())));
  function cell(row: Row, key: string) {
    const value = row[key]; const field = collection.fields.find(item => item.key === key);
    if (field?.ref) { const item = rows(scenario[field.ref]).find(item => item.id === value); return <span className="reference-cell">{text(item?.code || item?.name) || display(value)}</span>; }
    if (/_status$/.test(key) || ['status', 'confirmed', 'active', 'approved', 'product_approved'].includes(key)) return <Badge value={typeof value === 'boolean' ? value ? 'approved' : 'pending' : value}>{typeof value === 'boolean' ? key === 'approved' || key === 'product_approved' ? value ? '승인됨' : '미승인' : key === 'confirmed' ? value ? '공급 확약' : '미확약' : value ? '활성' : '비활성' : label(value)}</Badge>;
    if (/date$|_at$|valid_until/.test(key)) return date(value);
    if (/price|amount|cost/.test(key)) return money(value);
    if (field?.type === 'number') return quantity(value);
    return display(value);
  }
  return <>
    <PageHeading eyebrow="ERP DATA MANAGEMENT" title={collections[keys[0]].title} description={collections[keys[0]].description} action={<button className="button primary" onClick={() => { setEditing({}); setSuccess(false); }} disabled={!user.id || scenario.canonical_workspace === true}><Plus size={17}/>{collection.title} 등록</button>}/>
    <ReadOnlyNotice/>
    {page === 'purchase-orders' && <div className="notice"><SlidersHorizontal size={17}/>내부 PO는 공급업체에 이메일/API로 전송되지 않습니다. 발주 승인은 재고의 QC/QA 상태를 변경하지 않습니다.</div>}
    {success && <Success>저장되었습니다. 변경된 ERP 입력으로 계산 결과를 갱신했습니다.</Success>}
    {keys.length > 1 && <div className="tabs" role="tablist" aria-label="ERP 데이터 종류">{keys.map(key => <button role="tab" aria-selected={collection.key === key} key={key} className={collection.key === key ? 'active' : ''} onClick={() => { setTab(key); setSearch(''); setSuccess(false); }}>{collections[key].title}<span>{rows(scenario[key.replaceAll('-', '_')]).length}</span></button>)}</div>}
    <Panel>
      <div className="table-toolbar">
        <div><h2>{collection.title} 목록 <span>{source.length}</span></h2><p>{collection.description}</p></div>
        <div className="search-input"><Search size={16}/><input aria-label="레코드 검색" placeholder="코드, 이름, 상태 검색" value={search} onChange={event => setSearch(event.target.value)}/></div>
      </div>
      {list.length ? <div className="table-scroll"><table>
        <thead><tr>{collection.columns.map(key => <th key={key}>{collection.fields.find(field => field.key === key)?.label || ({ created_at: '등록일', revision: '버전' } as Record<string, string>)[key] || key}</th>)}<th>버전</th><th className="align-right">관리</th></tr></thead>
        <tbody>{list.map(row => <tr key={text(row.id)}>
          {collection.columns.map((key, index) => <td key={key}>{index === 0 ? <button className="table-primary" onClick={() => setDetail(row)}>{cell(row, key)}</button> : cell(row, key)}</td>)}
          <td className="muted">v{text(row.revision) || '1'}</td>
          <td><div className="table-actions"><button className="icon-button" aria-label={`${text(row.code || row.name)} 수정`} disabled={!user.id || scenario.canonical_workspace === true} onClick={() => setEditing(row)}><Edit3 size={16}/></button><button className="icon-button" aria-label={`${text(row.code || row.name)} 상세`} onClick={() => setDetail(row)}><ChevronRight size={17}/></button></div></td>
        </tr>)}</tbody>
      </table></div> : <Empty title={search ? '검색 결과가 없습니다' : '아직 등록된 데이터가 없습니다'}>{search ? '다른 검색어로 다시 검색해 보세요.' : `${collection.title} 등록 버튼에서 현재 시나리오에 필요한 정보를 입력하세요.`}</Empty>}
      <div className="table-footer"><span>{list.length} / {source.length}개 레코드</span><span>시나리오별 독립 저장 · 수정 이력 보존</span></div>
    </Panel>
    {collection.key==='purchase-orders'&&<DecisionMemory scenarioId={scenarioId} results/>}
    {editing && <RecordForm key={`${collection.key}-${text(editing.id)}`} collection={collection} original={editing} close={() => setEditing(null)} saved={() => setSuccess(true)}/>}
    {detail && <Modal title={text(detail.name || detail.code) || `${collection.title} 상세`} close={() => setDetail(null)}>
      <RecordDetails row={detail}/>
      <footer className="modal-footer"><button className="button secondary" onClick={() => setDetail(null)}>닫기</button><button className="button primary" disabled={!user.id || scenario.canonical_workspace === true} onClick={() => { setEditing(detail); setDetail(null); }}><Edit3 size={16}/>수정</button></footer>
    </Modal>}
  </>;
}
