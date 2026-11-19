"""Shared counts and fixed failure categories; never stores jobs or prompt text."""
from contextlib import contextmanager
import threading
import time
import uuid

FAILURE_MESSAGES={
    "framing":"인물 보호: 원본 비율에서도 안전한 크기를 찾지 못함",
    "started":"처리 중 생성이 시작되었거나 대기열에서 제외됨",
    "changed":"다른 수정과 겹침: 다시 적용 필요",
    "verification":"반영·복원 확인 실패: 복구 사본 보관",
    "rejected":"ComfyUI 수정 거절: 기존 항목 유지",
    "other":"기타 설정·통신 오류",
}

def failure_code(error):
    # Never retain arbitrary exception text, paths, prompts or job IDs.
    message=str(error)
    if message=="이 사진 조합은 원본 비율에서도 인물이 잘릴 수 있어 등록하지 않았습니다. 첫·끝 사진을 같은 비율로 맞춰 주세요.":return "framing"
    if message in ("이미 시작됐거나 대기열에서 빠진 항목입니다.","수정하는 동안 생성이 시작됐습니다. 실행 중인 작업은 변경하지 않았습니다."):return "started"
    if message in ("적용 중 다른 수정이 감지됐습니다. 다시 적용해 주세요.","조회 후 문구가 바뀌었습니다. 다시 조회해 주세요."):return "changed"
    if message in ("복원 여부를 확인하지 못했습니다. 복구 사본을 보관했습니다.","반영 상태가 달라 복구 사본을 보관했습니다.","반영 확인에 실패했습니다. 복구 사본을 보관했습니다.","반영 내용이 일치하지 않아 완료로 처리하지 않았습니다. 복구 사본을 보관했습니다."):return "verification"
    if message in ("ComfyUI가 수정 요청을 수락하지 않았습니다.","수정에 실패해 원래 대기 항목을 유지했습니다."):return "rejected"
    return "other"


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
                succeeded=0,failed=0,verified=0,failure_counts={},all_pending=bool(all_pending),started_at=now,updated_at=now)
        try:
            yield self
        except BaseException:
            with self.lock:self.value.update(state='error',updated_at=self.clock(),finished_at=self.clock())
            raise
        else:
            with self.lock:
                state='done' if self.value['processed']==total else 'error'
                self.value.update(state=state,updated_at=self.clock(),finished_at=self.clock())

    def advance(self,success,verified=False,error=None):
        with self.lock:
            if not self.value or self.value['state']!='running' or self.value['processed']>=self.value['total']:raise RuntimeError("진행 상태와 처리 건수가 맞지 않습니다.")
            self.value['processed']+=1
            self.value['succeeded' if success else 'failed']+=1
            self.value['verified']+=int(bool(success and verified))
            if not success:
                code=failure_code(error)
                self.value['failure_counts'][code]=self.value['failure_counts'].get(code,0)+1
            self.value['updated_at']=self.clock()

    def snapshot(self):
        with self.lock:
            if not self.value:return {'state':'idle'}
            result=dict(self.value)
            reasons=dict(result.pop('failure_counts',{}))
        result['failure_reasons']=[dict(code=code,message=FAILURE_MESSAGES[code],count=count) for code,count in reasons.items()]
        now=self.clock();end=result.get('finished_at',now)
        result['elapsed_seconds']=max(0,round(end-result['started_at'],1))
        result['finished_age_seconds']=max(0,now-end) if 'finished_at' in result else 0
        result['percent']=round(result['processed']*100/result['total'],1) if result['total'] else (100 if result['state']=='done' else 0)
        return result
