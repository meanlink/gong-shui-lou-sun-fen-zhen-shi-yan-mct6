import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def fingerprint(value):
    """规范化 JSON 的 SHA256，用于封存内容与当前成果的对应关系判定。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
def result_fingerprint(result):
    """对当前成果（完整分析结果）取指纹，验真通过且指纹一致才允许批准/分发。"""
    return fingerprint(result)
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def verification_dict(v):
    """复算状态对外视图；evidence 原文走独立下载接口，避免列表响应过大。"""
    evidence=v.evidence or {}
    return {
        'id':v.id,'job_id':v.job_id,'status':v.status,'progress':v.progress,
        'attempts':v.attempts,'differences':v.differences or [],
        'sealed_at':v.sealed_at,'checked_at':v.checked_at,'updated_at':v.updated_at,
        'rule_version':evidence.get('rule_version',''),
        'evidence_hash':v.evidence_hash,
        'has_evidence':bool(evidence),
        'seal_intact':evidence.get('seal_hash','')==v.evidence_hash if evidence else False,
    }
