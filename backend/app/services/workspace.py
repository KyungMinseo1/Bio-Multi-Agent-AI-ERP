"""Integration boundary: browser ERP drafts and team API share the original TS engine.
Only the authenticated final command may create a new workspace purchase order.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from sqlalchemy import select, delete
from fastapi import HTTPException
from ..models import Scenario, ERPRecord, Recommendation, DiscussionRun, AuditEvent
from ..config import COLLECTIONS
from .erp import lock_revision, audit

WORKSPACE = 'main-workspace'
ROOT = Path(__file__).resolve().parents[3]


def execute(workflow=None, command='verify', args=None):
    path = ROOT / 'server-dist' / 'workflow.cjs'
    if not path.exists():
        raise HTTPException(503, '공유 계산 엔진을 먼저 빌드하세요: npm run build:engine')
    try:
        result = subprocess.run([os.environ.get('BIOFLOW_NODE', 'node'), str(path)], input=json.dumps({'workflow': workflow, 'command': command, 'args': args or {}}), text=True, capture_output=True, timeout=20, cwd=ROOT)
        value = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise HTTPException(503, '공유 ERP 계산 엔진 실행 실패') from None
    if result.returncode or 'error' in value:
        raise HTTPException(422, value.get('error', '업무 계산 실패'))
    return value


def view(row):
    return {'scenario_id': WORKSPACE, 'revision': row.revision, 'workflow': row.data['_workflow'], 'stamp': row.data['workspace_stamp'], 'data_revision': row.data['data_revision'], 'engine': 'shared-typescript-v2.1'}


def persist(db, value, expected, actor, action):
    row = db.get(Scenario, WORKSPACE)
    if row and row.revision != expected:
        raise HTTPException(409, detail={'code': 'workspace_conflict', 'message': '서버 업무가 변경됐습니다. 로컬 초안을 보존하고 서버 업무를 다시 확인하세요.', 'current_revision': row.revision})
    if not row and expected != 0:
        raise HTTPException(409, '서버 업무가 아직 없습니다. 새 등록을 선택하세요.')
    if row and row.data.get('_workflow') == value['workflow']:
        return view(row)
    previous = copy.deepcopy(row.data.get('_workflow')) if row else None
    if row:
        revision = lock_revision(db, WORKSPACE, expected)
    else:
        revision = 1
        row = Scenario(id=WORKSPACE, revision=revision, data={})
        db.add(row)
        db.flush()
    projection = copy.deepcopy(value['projection'])
    metadata = {k: v for k, v in projection.items() if k not in COLLECTIONS}
    metadata['_workflow'] = value['workflow']
    metadata['_canonical_calculation']['revision'] = revision
    row.data = metadata
    # Only our derived projection is replaced; other scenarios and immutable audit/run tables stay intact.
    db.execute(delete(ERPRecord).where(ERPRecord.scenario_id == WORKSPACE))
    for collection in COLLECTIONS:
        for record in projection.get(collection, []):
            db.add(ERPRecord(scenario_id=WORKSPACE, collection=collection, record_id=record['id'], revision=revision, data={**record, 'revision': revision}))
    audit(db, actor, action, WORKSPACE, before={'workflow': previous} if previous else None, after={'revision': revision, 'workflow': value['workflow'], 'stamp': value['stamp']})
    db.commit()
    return view(row)


def upload(db, workflow, expected, user, migration=False):
    old = db.get(Scenario, WORKSPACE)
    if user.role != 'approver' and (workflow.get('approvals') or workflow.get('orders')):
        raise HTTPException(403, '승인 이력이 포함된 업무 등록은 승인 담당자만 가능합니다.')
    if old:
        prior = {o['id']: o for o in old.data['_workflow']['orders']}
        current = {o['id']: o for o in workflow.get('orders', [])}
        if prior.keys() != current.keys():
            raise HTTPException(409, '발주 추가는 최종 승인 API를 사용하세요. 등록 PO는 초안 저장/초기화로 삭제할 수 없습니다.')
        immutable = ('id', 'caseId', 'sourceRevision', 'sourceStamp', 'createdAt', 'vendor', 'product', 'quantity', 'unitPrice', 'purchase', 'shipping', 'subtotal', 'estimatedTotal', 'approval', 'strategy', 'report')
        if any(any(prior[key].get(f) != current[key].get(f) for f in immutable) for key in prior):
            raise HTTPException(409, '기존 발주의 승인 당시 조건은 변경할 수 없습니다.')
    elif workflow.get('orders') and not migration:
        raise HTTPException(422, '기존 발주가 있는 로컬 업무는 명시적 이관 확인이 필요합니다.')
    value = execute(workflow)
    return persist(db, value, expected, user.email, 'workspace.import' if not old else 'workspace.save')


def command(db, name, args, expected, user):
    row = db.get(Scenario, WORKSPACE)
    if not row:
        raise HTTPException(404, '현재 업무를 먼저 서버에 등록하세요.')
    if row.revision != expected:
        raise HTTPException(409, '서버 업무 버전 변경: 다시 확인하세요.')
    if name in {'registerPO', 'approveInquiry'} and user.role != 'approver':
        raise HTTPException(403, '승인 담당자 권한이 필요합니다.')
    allowed = {'detect', 'approveInquiry', 'startInquiries', 'receiveReplies', 'analyze', 'registerPO', 'trackNext', 'trackingIssue', 'trackReview', 'finishProduction'}
    if name not in allowed:
        raise HTTPException(422, '허용되지 않은 업무 명령')
    workflow = row.data['_workflow']
    review = (workflow.get('integration') or {}).get('externalReview')
    if name == 'registerPO' and review:
        rec = db.get(Recommendation, review.get('recommendationId'))
        if not rec or rec.status != 'proposed' or review.get('stamp') != execute(workflow)['stamp']:
            raise HTTPException(409, '실제 AI 추천 원본/상태가 변경됐습니다.')
    value = execute(workflow, name, args)
    if name == 'registerPO' and review:
        rec.status = 'selected'
    return persist(db, value, expected, user.email, 'workspace.' + name)


def adopt(db, recommendation_id, expected, stamp, user):
    row = db.get(Scenario, WORKSPACE)
    rec = db.get(Recommendation, recommendation_id)
    if not row or row.revision != expected or not rec or rec.scenario_id != WORKSPACE:
        raise HTTPException(409, '업무 또는 실제 AI 추천 버전 불일치')
    run = db.get(DiscussionRun, rec.run_id)
    if rec.status != 'proposed' or run.status != 'awaiting_review' or rec.snapshot_revision != row.revision:
        raise HTTPException(409, '현재 버전에서 완료된 실제 AI 추천만 가져올 수 있습니다.')
    candidate = rec.data['candidate']
    summary = ' / '.join(x['claim'] for x in rec.data.get('rationale_items', []))
    value = execute(row.data['_workflow'], 'adoptReview', {'vendor': candidate.get('original_vendor_id'), 'stamp': stamp, 'runId': run.id, 'recommendationId': rec.id, 'summary': summary})
    return persist(db, value, expected, user.email, 'workspace.adopt_real_review')
