"""Shared count-only progress for queue edits. Never stores jobs or prompt text."""
from contextlib import contextmanager
import threading
import time
import uuid


class BulkProgress:
    def __init__(self, clock=time.time):
        self.clock=clock;self.lock=threading.Lock();self.value=None

    @contextmanager
    def operation(self,total,all_pending=False):
        if type(total) is not int or total<0:raise ValueError("일괄 수정 대상 수를 확인해 주세요.")
        with self.lock:
            if self.value and self.value['state']=='running':raise ValueError("다른 일괄 수정이 진행 중입니다. 진행률을 확인해 주세요.")
            now=self.clock()
            self.value=dict(operation_id=uuid.uuid4().hex,state='running',total=total,processed=0,
                succeeded=0,failed=0,verified=0,all_pending=bool(all_pending),started_at=now,updated_at=now)
        try:
            yield self
        except BaseException:
            with self.lock:self.value.update(state='error',updated_at=self.clock(),finished_at=self.clock())
            raise
        else:
            with self.lock:
                state='done' if self.value['processed']==total else 'error'
                self.value.update(state=state,updated_at=self.clock(),finished_at=self.clock())

    def advance(self,success,verified=False):
        with self.lock:
            if not self.value or self.value['state']!='running' or self.value['processed']>=self.value['total']:raise RuntimeError("진행 상태와 처리 건수가 맞지 않습니다.")
            self.value['processed']+=1
            self.value['succeeded' if success else 'failed']+=1
            self.value['verified']+=int(bool(success and verified))
            self.value['updated_at']=self.clock()

    def snapshot(self):
        with self.lock:
            if not self.value:return {'state':'idle'}
            result=dict(self.value)
        now=self.clock();end=result.get('finished_at',now)
        result['elapsed_seconds']=max(0,round(end-result['started_at'],1))
        result['finished_age_seconds']=max(0,now-end) if 'finished_at' in result else 0
        result['percent']=round(result['processed']*100/result['total'],1) if result['total'] else (100 if result['state']=='done' else 0)
        return result
