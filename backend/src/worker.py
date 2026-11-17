import time, json, logging, uuid
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, Verification
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services import verification as verify
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            db.flush()
            # 新试验完成即封存原输入、参数、规则版本与独立计算依据。
            verify.seal_job(db,j)
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def run_verification(verification_id):
    # 每次领取生成独立占用令牌；迟到的旧执行凭旧令牌写回会被拒绝。
    token=uuid.uuid4().hex
    with Session() as db:
        mine=verify.claim(db,verification_id,token)
    if not mine:return
    with Session() as db:
        verify.run_verification(db,verification_id,token)
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        due=list(db.scalars(select(Verification.id).where(Verification.status=='running').limit(3)))
    for verification_id in due:run_verification(verification_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        # 复算中断后恢复同次核验：清掉失效占用令牌，由 tick 重新认领。
        verify.recover_stale(db)
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            vitem=r.blpop(verify.QUEUE_KEY,timeout=1)
            if vitem:run_verification(int(vitem[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
