"""验真复算服务。

设计约束（对应业务需求）：
  1. 新试验完成时封存原输入、参数、规则版本与可独立执行的计算依据；
  2. 升级后仍按凭据中的原版规则包复算，绝不调用当前算法冒充；
  3. 逐段分诊与指标逐项比较，差异或缺件即判失败，且不修改原成绩；
  4. 验真通过且凭据对应当前成果（指纹一致、封存未被改动）才可批准/分发；
  5. 改动封存内容立即失效（每次读取/执行先校验封存指纹）；
  6. 中断后恢复同次核验（同一 run_key 与进度），并发重试不重复出凭据；
  7. 旧执行迟到不覆盖接管结论（worker_token 占用令牌 + CAS 写回）；
  8. 历史试验缺依据时标记 unverifiable，禁止用新版补算冒充。
"""
import time
import uuid
import hashlib
import inspect

from fastapi import HTTPException
from sqlalchemy import select

from src.models import Job, Dataset, Verification
from src.rule_versions import get_rule, CURRENT_RULE_VERSION
from src.utils.serialization import checksum, fingerprint, result_fingerprint

QUEUE_KEY = 'verification:queue'
MAX_DIFFS = 200


# ---------------------------------------------------------------- 封存
def _rule_source(rule_module):
    return inspect.getsource(rule_module)


def seal_job(db, job, rule_version=None):
    """任务完成时封存凭据。已存在凭据时原样返回（封存只做一次）。"""
    existing = db.scalar(select(Verification).where(Verification.job_id == job.id))
    if existing:
        return existing
    version = rule_version or CURRENT_RULE_VERSION
    try:
        rule_module = get_rule(version)
        rule_source = _rule_source(rule_module)
        rule_source_hash = hashlib.sha256(rule_source.encode('utf-8')).hexdigest()
    except (KeyError, OSError, TypeError):
        # 规则版本缺件或依据不可读也要留下凭据，复算时明确判失败，而不是静默换版。
        rule_source, rule_source_hash = '', ''
    dataset = db.get(Dataset, job.dataset_id)
    now = time.time()
    evidence = {
        'job_id': job.id,
        'job_name': job.name,
        'dataset_id': job.dataset_id,
        # 原输入快照与批次指纹；批次本身不可变，这里再留一份校验口径。
        'input_records': list(dataset.records) if dataset else [],
        'input_checksum': checksum(dataset.records) if dataset else '',
        'params': dict(job.params or {}),
        'params_checksum': checksum(job.params or {}),
        'rule_version': version,
        # 可独立执行的计算依据：冻结规则包源码 + 源码指纹 + 运行时口径。
        'rule_source': rule_source,
        'rule_source_hash': rule_source_hash,
        'rule_runtime': dict(getattr(rule_module, 'RUNTIME', {})),
        # 被封存的原成绩指纹；原成绩本身留在 jobs.result，验真绝不改写它。
        'result_fingerprint': result_fingerprint(job.result or {}),
        'sealed_at': now,
    }
    evidence['seal_hash'] = fingerprint({k: v for k, v in evidence.items() if k != 'seal_hash'})
    v = Verification(
        job_id=job.id, evidence=evidence, evidence_hash=evidence['seal_hash'],
        status='pending', progress=0, differences=[], attempts=0,
        sealed_at=now, created_at=now, updated_at=now,
    )
    db.add(v)
    db.flush()
    return v


def seal_intact(v):
    """封存内容是否保持原样：外层指纹与清单内指纹必须一致且清单完整。"""
    evidence = v.evidence or {}
    if not evidence or not v.evidence_hash:
        return False
    required = ('input_records', 'input_checksum', 'params', 'rule_version',
                'rule_source', 'rule_source_hash', 'result_fingerprint', 'seal_hash')
    if any(key not in evidence for key in required):
        return False
    body = {k: val for k, val in evidence.items() if k != 'seal_hash'}
    return fingerprint(body) == v.evidence_hash == evidence.get('seal_hash', '')


def get_verification(db, job_id):
    """读取复算状态；无凭据的历史试验返回合成的 unverifiable 视图。"""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, '分析任务不存在')
    v = db.scalar(select(Verification).where(Verification.job_id == job_id))
    if not v:
        return None, job
    # 改动封存内容立即失效：任何一次读取发现指纹不符即落失败。
    if v.status in ('pending', 'running', 'passed') and not seal_intact(v):
        v.status = 'failed'
        v.progress = 100
        v.differences = [{'type': 'seal_tampered', 'message': '封存内容与封存指纹不一致，凭据已失效，必须重新封存后才能验真。'}]
        v.checked_at = time.time()
        v.updated_at = time.time()
        db.commit()
    return v, job


# ------------------------------------------------- 发起 / 占用 / 恢复
def request_verification(db, job_id):
    """发起验真（写角色可发起）。并发重试复用同一 run_key，不重复出凭据。"""
    v, job = get_verification(db, job_id)
    if job.status != 'completed':
        raise HTTPException(409, '仅已完成的试验可以发起验真复算')
    if v is None:
        # 历史试验缺依据：明确标记不可验真，不用新版补算冒充。
        raise HTTPException(409, '该历史试验缺少封存依据，标记为不可验真，无法用新版规则补算')
    if not seal_intact(v):
        raise HTTPException(409, '封存凭据已被改动而失效，无法发起验真')
    if v.status == 'running':
        # 同次核验进行中：幂等返回既有 run_key，由 worker 断点恢复，不另立凭据。
        return v
    if v.status == 'passed':
        raise HTTPException(409, '验真已通过；凭据未改动无需重复核验')
    v.run_key = uuid.uuid4().hex
    v.worker_token = None
    v.status = 'running'
    v.progress = 5
    v.differences = []
    v.attempts += 1
    v.updated_at = time.time()
    db.commit()
    return v


def activate(db, v):
    """把已封存的凭据置为运行态并生成同次核验令牌（供 worker/seed 直接驱动）。"""
    v.run_key = uuid.uuid4().hex
    v.worker_token = None
    v.status = 'running'
    v.progress = 5
    v.differences = []
    v.attempts += 1
    v.updated_at = time.time()
    return v


def claim(db, verification_id, worker_token):
    """worker 占用一次核验。CAS 保证并发重试只有一个执行者；返回是否占用成功。"""
    v = db.get(Verification, verification_id)
    if not v or v.status != 'running':
        return False
    if v.worker_token and v.worker_token != worker_token:
        return False  # 已有执行者，并发重试不重复执行、不重复出凭据
    v.worker_token = worker_token
    v.updated_at = time.time()
    db.commit()
    return True


def recover_stale(db):
    """worker 启动/巡检时把失去占用者的 running 核验放回可认领状态，恢复同次核验。"""
    for v in db.scalars(select(Verification).where(Verification.status == 'running')):
        v.worker_token = None
        v.updated_at = time.time()
    db.commit()


# ---------------------------------------------------------------- 比较
def _metric_map(metrics):
    return {m['label']: {'value': m.get('value'), 'unit': m.get('unit', '')} for m in (metrics or [])}


def _segment_map(rows):
    return {r['segment_id']: r for r in (rows or [])}


def compare_results(expected, recomputed):
    """逐段分诊 + 指标 + 图表 + 结论逐项比较，返回差异清单（不改原成绩）。"""
    diffs = []
    exp_metrics, got_metrics = _metric_map(expected.get('metrics')), _metric_map(recomputed.get('metrics'))
    for label in sorted(set(exp_metrics) | set(got_metrics)):
        if label not in exp_metrics:
            diffs.append({'type': 'metric_extra', 'label': label, 'expected': None, 'actual': got_metrics[label]['value']})
        elif label not in got_metrics:
            diffs.append({'type': 'metric_missing', 'label': label, 'expected': exp_metrics[label]['value'], 'actual': None})
        elif exp_metrics[label]['value'] != got_metrics[label]['value']:
            diffs.append({'type': 'metric_mismatch', 'label': label,
                          'expected': exp_metrics[label]['value'], 'actual': got_metrics[label]['value']})
        if len(diffs) >= MAX_DIFFS:
            return diffs
    exp_rows, got_rows = _segment_map(expected.get('table', {}).get('rows', [])), _segment_map(recomputed.get('table', {}).get('rows', []))
    for segment_id in sorted(set(exp_rows) | set(got_rows)):
        old, new = exp_rows.get(segment_id), got_rows.get(segment_id)
        if old is None:
            diffs.append({'type': 'segment_extra', 'segment_id': segment_id, 'message': '复算结果出现原结论没有的管段'})
        elif new is None:
            diffs.append({'type': 'segment_missing', 'segment_id': segment_id, 'message': '复算结果缺少原结论中的管段'})
        else:
            for field in ('triage', 'risk_pct', 'actual'):
                if old.get(field) != new.get(field):
                    diffs.append({'type': 'segment_mismatch', 'segment_id': segment_id, 'field': field,
                                  'expected': old.get(field), 'actual': new.get(field)})
                    if len(diffs) >= MAX_DIFFS:
                        return diffs
    for key in ('summary', 'chart', 'findings', 'method'):
        if expected.get(key) != recomputed.get(key):
            diffs.append({'type': 'result_mismatch', 'field': key,
                          'expected': expected.get(key), 'actual': recomputed.get(key)})
            if len(diffs) >= MAX_DIFFS:
                return diffs
    return diffs


# ---------------------------------------------------------------- 执行
def run_verification(db, verification_id, worker_token):
    """按封存的原版规则独立复算并比较。任何阶段失败都只写复算区，不动原成绩。"""
    v = db.get(Verification, verification_id)
    if not v:
        return
    # 旧执行迟到：占用令牌已被新执行者接管时直接拒绝写回。
    if v.worker_token != worker_token or v.status != 'running':
        return

    def fail(reason, diffs=None):
        latest = db.get(Verification, verification_id)
        if not latest or latest.worker_token != worker_token:
            return  # 再次防迟到覆盖
        latest.status = 'failed'
        latest.progress = 100
        latest.differences = (diffs or []) + [{'type': 'failed_reason', 'message': reason}]
        latest.checked_at = time.time()
        latest.updated_at = time.time()
        db.commit()

    def progress(pct):
        latest = db.get(Verification, verification_id)
        if latest and latest.worker_token == worker_token and latest.status == 'running':
            latest.progress = pct
            latest.updated_at = time.time()
            db.commit()

    # 1) 封存完整性（改动封存内容立即失效）
    if not seal_intact(v):
        return fail('封存内容与封存指纹不一致，凭据已失效')
    evidence = v.evidence
    progress(20)
    # 2) 规则版本缺件 → 失败，绝不回退到当前版本
    try:
        rule_module = get_rule(evidence['rule_version'])
    except KeyError:
        return fail(f"规则版本 {evidence.get('rule_version')} 的独立计算依据缺件")
    # 3) 独立计算依据（冻结源码）指纹必须与封存一致，防止规则包被偷换
    source_hash = hashlib.sha256(_rule_source(rule_module).encode('utf-8')).hexdigest()
    if source_hash != evidence.get('rule_source_hash') or not evidence.get('rule_source'):
        return fail('冻结规则源码与封存指纹不一致，计算依据已被改动')
    progress(40)
    # 4) 原输入/参数缺件即失败，不用新版或其他数据补算
    if not evidence.get('input_records') or checksum(evidence['input_records']) != evidence.get('input_checksum'):
        return fail('封存的原输入缺失或自校验失败')
    if checksum(evidence.get('params', {})) != evidence.get('params_checksum'):
        return fail('封存参数自校验失败')
    progress(60)
    # 5) 按原版规则独立复算
    try:
        recomputed = rule_module.analyze(evidence['input_records'], evidence['params'])
    except Exception as exc:  # 复算中断/报错按失败留痕
        return fail('原版规则复算中断：%s' % str(exc)[:300])
    progress(85)
    # 6) 与被封存的原成绩逐段、逐指标比较
    job = db.get(Job, v.job_id)
    expected = job.result if job else {}
    diffs = compare_results(expected, recomputed)
    recomputed_fp = result_fingerprint(recomputed)
    current_fp = result_fingerprint(expected or {})
    fp_match = recomputed_fp == evidence.get('result_fingerprint') == current_fp
    if not fp_match:
        diffs.append({'type': 'fingerprint_mismatch',
                      'message': '复算成果指纹与封存原成绩或当前成果不一致',
                      'expected': evidence.get('result_fingerprint'), 'actual': recomputed_fp})
    if len(diffs) > MAX_DIFFS:
        diffs = diffs[:MAX_DIFFS] + [{'type': 'truncated', 'message': '差异超过 %d 条，仅保留前 %d 条' % (MAX_DIFFS, MAX_DIFFS)}]
    latest = db.get(Verification, verification_id)
    if not latest or latest.worker_token != worker_token:
        return  # 旧执行迟到，不覆盖接管结论
    latest.differences = diffs
    latest.progress = 100
    latest.checked_at = time.time()
    latest.updated_at = time.time()
    latest.status = 'passed' if not diffs and fp_match else 'failed'
    db.commit()


# ------------------------------------------------------------ 批准闸门
def ensure_approved_for_usage(db, job):
    """批准与分发共用闸门：验真通过 + 凭据对应当前成果 + 封存完好。"""
    v, _ = get_verification(db, job.id)
    if v is None:
        raise HTTPException(409, '历史试验缺少封存依据，标记为不可验真，不能批准或分发')
    if not seal_intact(v):
        raise HTTPException(409, '封存凭据已被改动而失效，不能批准或分发')
    if v.status != 'passed':
        raise HTTPException(409, '验真复算未通过（当前状态：%s），不能批准或分发' % v.status)
    if result_fingerprint(job.result or {}) != v.evidence.get('result_fingerprint'):
        raise HTTPException(409, '当前成果与封存凭据不一致，需重新封存并验真')
    return v


def evidence_bundle(v):
    """导出封存清单原文，供下载独立审计。"""
    return dict(v.evidence or {})
