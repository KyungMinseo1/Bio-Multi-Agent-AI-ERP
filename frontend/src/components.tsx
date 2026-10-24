import { createContext, useContext, useEffect, useId, useRef, useState } from 'react';
import { AlertCircle, ArrowUpRight, Check, ChevronDown, Database, FileText, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ApiError, date, display, label, rows, text, type Row } from './api';
export interface Workspace { scenarioId: string; scenario: Row; planning: Row; user: Row; refresh: () => Promise<unknown>; }
export const WorkspaceContext = createContext<Workspace | null>(null);
export function useWorkspace() { const value = useContext(WorkspaceContext); if (!value) throw new Error('Workspace is unavailable'); return value; }
export function Badge({ value, children }: { value?: unknown; children?: React.ReactNode }) {
  const state = text(value); const tone = /urgent|failed|infeasible|rejected|quality_impact|object/.test(state) ? 'danger' : /warning|pending|unconfirmed|stale|needs_information|data_missing|requires_budget/.test(state) ? 'warning' : /approved|passed|completed|confirmed|accept|resolved|feasible/.test(state) ? 'success' : 'neutral';
  return <span className={`badge ${tone}`}><span className="badge-dot"/>{children || label(value)}</span>;
}
export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  if (!error) return null;
  return <div className="error-box" role="alert"><AlertCircle size={19}/><div><strong>{error instanceof ApiError && error.status === 409 ? '데이터가 변경되었습니다' : '요청을 완료하지 못했습니다'}</strong><p>{error instanceof Error ? error.message : display(error)}</p>{error instanceof ApiError && Object.keys(error.detail).length > 1 && <details><summary>서버 오류 상세</summary><pre>{JSON.stringify(error.detail, null, 2)}</pre></details>}{retry && <button className="text-button" onClick={retry}>최신 정보 다시 불러오기 →</button>}</div></div>;
}
export function Empty({ title = '등록된 항목이 없습니다', children }: { title?: string; children?: React.ReactNode }) { return <div className="empty"><Database size={30}/><h3>{title}</h3><p>{children || 'ERP에 필요한 정보를 등록하면 이곳에 표시됩니다.'}</p></div>; }
export function Loading({ message = '저장된 데이터를 불러오고 있습니다' }: { message?: string }) { return <div className="loading"><span className="spinner"/>{message}</div>; }
export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <header className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action && <div className="heading-action">{action}</div>}</header>; }
export function Panel({ title, subtitle, action, children, className = '' }: { title?: string; subtitle?: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) { return <section className={`panel ${className}`}>{title && <div className="panel-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>}{children}</section>; }
export function Modal({ title, children, close }: { title: string; children: React.ReactNode; close: () => void }) {
  const id = useId();
  const container = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const timer = window.setTimeout(() => container.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus(), 0);
    return () => { clearTimeout(timer); document.body.style.overflow = overflow; if (previous instanceof HTMLElement) previous.focus(); };
  }, []);
  return <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) close(); }}><section ref={container} className="modal" role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={event => {
    if (event.key === 'Escape') close();
    if (event.key === 'Tab') {
      const controls = container.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], summary');
      const first = controls?.[0]; const last = controls?.[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}><header><div><span className="eyebrow">ERP WORKSPACE</span><h2 id={id}>{title}</h2></div><button className="icon-button" aria-label="닫기" onClick={close}><X size={21}/></button></header>{children}</section></div>;
}
export function Evidence({ refs, extra }: { refs: unknown; extra?: Row[] }) {
  const { scenario, planning } = useWorkspace(); const [open, setOpen] = useState(false);
  const ids = Array.isArray(refs) ? refs.map(text) : [];
  const evidence = extra || [...rows(planning.evidence), ...Object.values(scenario).flatMap(value => rows(value))];
  return <div className="evidence"><button className="text-button" onClick={() => setOpen(!open)}><FileText size={14}/>{open ? '근거 접기' : `근거 보기${ids.length ? ` · ${ids.length}` : ''}`}<ChevronDown size={13}/></button>{open && <div className="evidence-content">{ids.length ? ids.map(id => { const item = evidence.find(row => row.id === id); return <details key={id}><summary>{text(item?.label || item?.name || item?.code || item?.role) || '근거 레코드'} <code>{id}</code></summary>{item ? <pre>{JSON.stringify(item, null, 2)}</pre> : <p>연결된 원본을 찾지 못했습니다. 참조 ID와 원본 스냅샷 상세를 확인하세요.</p>}</details>; }) : <p className="muted">연결된 근거가 제공되지 않았습니다.</p>}</div>}</div>;
}
export function KeyValue({ label: name, value }: { label: string; value: React.ReactNode }) { return <div className="key-value"><span>{name}</span><strong>{value}</strong></div>; }
export function ReadOnlyNotice() { const { user } = useWorkspace(); return !user.id ? <div className="notice"><AlertCircle size={17}/>읽기 전용으로 보고 있습니다. 등록·수정·토론·승인은 로그인 후 사용할 수 있습니다.</div> : null; }
export function RecordDetails({ row }: { row: Row }) { return <dl className="record-details">{Object.entries(row).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' && value !== null ? <pre>{JSON.stringify(value, null, 2)}</pre> : display(value)}</dd></div>)}</dl>; }
export function InlineLink({ to, children }: { to: string; children: React.ReactNode }) { return <Link className="inline-link" to={to}>{children}<ArrowUpRight size={15}/></Link>; }
export function Success({ children }: { children: React.ReactNode }) { return <div className="success-box" role="status"><Check size={18}/><div>{children}</div></div>; }
export function Timeline({ items, evidence }: { items: unknown; evidence?: Row[] }) {
  return <div className="timeline">{rows(items).map((item, index) => <div className="timeline-item" key={text(item.id) || `${text(item.date)}-${index}`}>
    <span className="timeline-dot"/><time>{date(item.date || item.arrival_date)}</time>
    <div><strong>{label(item.event || '입고 예정')}</strong>
      <p>{display(item.quantity)} · 가용 {display(item.available_quantity)}{item.available_date ? ` · 사용 가능 예상 ${date(item.available_date)}` : ''}</p>
      {Number(item.shortage_quantity || 0) > 0 && <Badge value="urgent">수요 미충족 {display(item.shortage_quantity)}</Badge>}
      <Evidence refs={item.evidence_refs} extra={evidence}/>
    </div>
  </div>)}</div>;
}
