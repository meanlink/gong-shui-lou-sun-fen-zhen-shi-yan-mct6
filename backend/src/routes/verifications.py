from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from src.config.database import get_db
from src.models import Job, Verification
from src.middlewares.auth import current_user, can_write
from src.services import verification as verify
from src.services import jobs as jobs_service
from src.services.audit import record
from src.utils.serialization import verification_dict
router = APIRouter(prefix='/verifications')


def _synthetic_unverifiable(job):
    """历史试验缺依据：明确合成不可验真视图，不生成任何新凭据。"""
    return {
        'id': None, 'job_id': job.id, 'status': 'unverifiable', 'progress': 0,
        'attempts': 0, 'rule_version': '', 'evidence_hash': '', 'has_evidence': False,
        'seal_intact': False, 'sealed_at': None, 'checked_at': None, 'updated_at': None,
        'differences': [{'type': 'missing_evidence',
                         'message': '历史试验完成时未封存计算依据，标记为不可验真，禁止用新版规则补算冒充'}],
    }


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = []
    for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100)):
        v = db.scalar(select(Verification).where(Verification.job_id == j.id))
        if v is None:
            if j.status == 'completed':
                rows.append(_synthetic_unverifiable(j))
            continue
        verify.get_verification(db, j.id)  # 触发封存篡改即时失效
        db.refresh(v)
        rows.append(verification_dict(v))
    return rows


@router.get('/{vid}/evidence')
def evidence(vid: int, db=Depends(get_db), u=Depends(current_user)):
    v = db.get(Verification, vid)
    if not v:
        raise HTTPException(404, '验真凭据不存在')
    if not verify.seal_intact(v):
        raise HTTPException(409, '封存凭据已被改动而失效')
    record(db, u.email, 'verification.evidence_download', {'id': vid})
    db.commit()
    return JSONResponse(verify.evidence_bundle(v))


@router.get('/job/{job_id}')
def detail(job_id: int, db=Depends(get_db), u=Depends(current_user)):
    v, job = verify.get_verification(db, job_id)
    if v is None:
        if job.status != 'completed':
            raise HTTPException(409, '试验尚未完成，暂无验真凭据')
        return _synthetic_unverifiable(job)
    return verification_dict(v)


@router.post('/job/{job_id}', status_code=202)
def start(job_id: int, db=Depends(get_db), u=Depends(can_write)):
    v = verify.request_verification(db, job_id)
    record(db, u.email, 'verification.start', {'id': v.id, 'job_id': job_id, 'run_key': v.run_key})
    db.commit()
    jobs_service.enqueue_verification(v.id)
    return verification_dict(v)
