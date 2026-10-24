export type Row = Record<string, unknown>;
export function record(value: unknown): Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
}
export function rows(value: unknown): Row[] {
  const list = Array.isArray(value) ? value : record(value).items;
  if (!Array.isArray(list)) return [];
  return list.filter((item): item is Row => item !== null && typeof item === 'object' && !Array.isArray(item));
}
export const text = (value: unknown): string => value == null ? '' : String(value);
export const number = (value: unknown): number => Number(value || 0);
export const quantity = (value: unknown): string => value == null ? '—' : Number.isFinite(Number(value)) ? Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 3 }) : String(value);
export const money = (value: unknown): string => value == null ? '—' : `${quantity(value)}원`;
export const date = (value: unknown): string => value ? String(value).slice(0, 10).replaceAll('-', '.') : '미설정';
export const time = (value: unknown): string => value ? new Date(String(value)).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }) : '기록 없음';
export const display = (value: unknown): string => value == null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export class ApiError extends Error {
  status: number; detail: Row;
  constructor(status: number, detail: unknown) {
    const object = record(detail);
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? rows(detail).map(x => `${Array.isArray(x.loc) ? x.loc.slice(1).join('.') : ''}: ${text(x.msg)}`).join(' / ') : text(object.message || object.code) || '요청을 처리하지 못했습니다.';
    super(message); this.status = status; this.detail = object;
  }
}
export async function api(path: string, options: RequestInit = {}): Promise<unknown> {
  const response = await fetch(`/api/v1${path}`, { ...options, credentials: 'include', headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  const raw = await response.text(); let data: unknown;
  try { data = raw ? JSON.parse(raw) : null; } catch { throw new ApiError(response.status, 'API 응답 형식이 올바르지 않습니다. 서버 연결을 확인하세요.'); }
  if (!response.ok) throw new ApiError(response.status, record(data).detail || data);
  return data;
}
export const send = (path: string, body: unknown, method = 'POST', headers?: Record<string, string>) => api(path, { method, body: JSON.stringify(body), headers });
export const labels: Record<string, string> = {
  urgent: '긴급 검토', warning: '검토 필요', resolved: '정상', normal: '정상', data_missing: '정보 부족', confirmed: '확약 근거 있음', supported: '실적 근거 있음', unconfirmed: '공급 미확약',
  queued: '대기 중', running: '협의 진행 중', awaiting_review: '검토 · 승인 대기', completed: '완료', failed: '실패', stale: '입력 변경 · 재협의 필요', approved: '승인', pending: '대기', passed: '합격', rejected: '반려',
  unverified: '미확인', relevance_unconfirmed: '관련성 미확인', supply_impact_confirmed: '공급 영향 확인', quality_impact_confirmed: '품질 영향 확인', cleared: '해제 확인',
  accept: '동의', object: '이견', needs_information: '추가 확인', feasible: '계산상 제약 통과', infeasible: '계산상 제약 위반', requires_budget_approval: '별도 예산 승인 필요', configuration_error: '연결 설정 필요', synthetic: '합성 자료',
  purchasing: '구매 (사용자 Buyer AI)', inventory_planning: '재고·생산계획', quality: '품질 (QC·QA)', finance: '재무', admin: 'Admin',
  procurement: '구매', inventory: '재고·물류', inventory_logistics: '재고·물류', production_management: '생산관리', production_planning: '생산관리', production: '생산', qc: 'QC', qa: 'QA',
  operator: '운영 담당자', approver: '승인 담당자', openfda: 'openFDA', rss: 'RSS', cold: '냉장', frozen: '냉동', ambient: '상온', true: '예', false: '아니오',
  opening: '기준일 승인 재고', quality_release_forecast: 'QC/QA 완료 예상', expiry: '유효기간 경과', production_use: '생산 투입', demand: '예정 수요', refrigerated: '냉장', hold: '품질 보류', cancelled: '취소', selected: '내부 발주 등록 완료', proposed: '검토 대기', vial: '바이알',
};
export const reviewerRoles = ['purchasing', 'inventory_planning', 'quality', 'finance'] as const;
export const discussionRoles = [...reviewerRoles, 'admin'] as const;
export const label = (value: unknown): string => labels[String(value)] || display(value);
