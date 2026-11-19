"""Server-owned display transcript. No executable plans, media or draft inputs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from grok_cli import clean_progress


def display_plan(actions):
    steps=[]
    for action in actions[:24]:
        changes=[]
        if action.get("kind")=="set":changes=[{"before":action.get("before",""),"after":action.get("value","")}]
        elif action.get("kind")=="api":
            try:changes=json.loads(action.get("args","{}")).get("edits",[])
            except (ValueError,AttributeError):pass
        if not isinstance(changes,list):changes=[]
        steps.append({"label":str(action.get("label",""))[:600],"changes":[
            {"before":change["before"][:8000],"after":change["after"][:8000]}
            for change in changes[:24] if isinstance(change,dict) and isinstance(change.get("before"),str) and isinstance(change.get("after"),str)]})
    return {"steps":steps,"state":"확인 대기"} if steps else None


def clean_messages(messages):
    if not isinstance(messages,list):raise ValueError("대화 기록 형식을 확인해 주세요.")
    result=[]
    for row in messages[-100:]:
        if not isinstance(row,dict) or row.get("role") not in ("user","assistant") or not isinstance(row.get("text"),str):
            raise ValueError("대화 기록 형식을 확인해 주세요.")
        entry={"id":row.get("id") if isinstance(row.get("id"),str) and len(row["id"])<=80 else uuid.uuid4().hex,
               "role":row["role"],"text":row["text"][:8000]}
        plan=row.get("plan")
        if row["role"]=="assistant" and isinstance(plan,dict) and isinstance(plan.get("steps"),list):
            steps=[]
            for step in plan["steps"][:24]:
                if not isinstance(step,dict) or not isinstance(step.get("label"),str):continue
                changes=step.get("changes",[])
                steps.append({"label":step["label"][:600],"changes":[{"before":change["before"][:8000],"after":change["after"][:8000]}
                    for change in (changes if isinstance(changes,list) else [])[:24]
                    if isinstance(change,dict) and isinstance(change.get("before"),str) and isinstance(change.get("after"),str)]})
            entry["plan"]={"state":str(plan.get("state","읽기 전용"))[:100],"steps":steps}
        result.append(entry)
    while len(result)>1 and len(json.dumps(result,ensure_ascii=False))>750000:result.pop(0)
    if len(json.dumps(result,ensure_ascii=False))>750000:
        for row in result:
            for step in row.get("plan",{}).get("steps",[]):step["changes"]=[]
    return result


class ProductionChat:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.state=None;self.live_progress={}

    def _load(self):
        if self.state is not None:return
        try:
            if self.path.stat().st_size>3_000_000:raise ValueError
            data=json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version")!=1 or type(data.get("revision")) is not int or data["revision"]<0:raise ValueError
            self.state={"version":1,"revision":data["revision"],"session_id":str(data.get("session_id") or uuid.uuid4().hex),
                "messages":clean_messages(data.get("messages")),"active":None,"latest_turn":data.get("latest_turn")}
            recovered=False
            for row in self.state["messages"]:
                if row.get("plan",{}).get("state")=="실행 중":row["plan"]["state"]="이전 실행 · 앱 상태 확인";recovered=True
            if data.get("active"):
                self.state["messages"].append({"id":uuid.uuid4().hex,"role":"assistant","text":"이전 도우미 요청이 서버 재시작으로 중단됐습니다. 자동 재실행하지 않으므로 앱 상태를 확인해 주세요."});recovered=True
            if recovered:self._save(copy.deepcopy(self.state))
        except FileNotFoundError:
            if self.state is not None:
                self.state=None
                raise ValueError("서버 대화의 복구 기록을 저장하지 못했습니다. 원본은 덮어쓰지 않았습니다.") from None
            self.state={"version":1,"revision":0,"session_id":uuid.uuid4().hex,"messages":[],"active":None,"latest_turn":None}
        except (OSError,ValueError,TypeError,AttributeError,KeyError):
            self.state=None
            raise ValueError("서버의 대화 기록을 읽지 못했습니다. 기록을 덮어쓰지 않았습니다.") from None

    def _save(self,data):
        data["messages"]=clean_messages(data["messages"]);data["revision"]+=1
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,temporary=tempfile.mkstemp(prefix="production-chat-",suffix=".tmp",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle:
                json.dump(data,handle,ensure_ascii=False,separators=(",",":"));handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,self.path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        self.state=data

    def snapshot(self,revision=None,session=None):
        with self.lock:
            self._load()
            active=copy.deepcopy(self.state["active"])
            if active and active["phase"]=="model":active.update(self.live_progress)
            if str(revision)==str(self.state["revision"]) and session==self.state["session_id"]:
                return copy.deepcopy({**{key:self.state[key] for key in ("revision","session_id")},"active":active,"unchanged":True})
            return copy.deepcopy({**{key:self.state[key] for key in ("revision","session_id","messages")},"active":active})

    def _check_revision(self,revision):
        if type(revision) is not int or revision!=self.state["revision"]:
            raise ValueError("다른 기기에서 대화가 갱신됐습니다. 최신 대화를 확인한 뒤 다시 요청해 주세요.")

    def import_once(self,revision,messages):
        with self.lock:
            self._load();self._check_revision(revision)
            if self.state["messages"] or self.state["active"] or self.state["revision"]!=0:
                raise ValueError("서버에 대화가 이미 있습니다. 최신 대화를 불러와 주세요.")
            imported=clean_messages(messages)
            for row in imported:
                row["id"]=uuid.uuid4().hex
                if row.get("plan",{}).get("state") in ("확인 대기","실행 중"):row["plan"]["state"]="가져온 기록 · 읽기 전용"
            data=copy.deepcopy(self.state);data["messages"]=imported;self._save(data)
            return self.snapshot()

    def clear(self,revision):
        with self.lock:
            self._load();self._check_revision(revision)
            if self.state["active"]:raise ValueError("도우미 응답이 끝나거나 취소된 뒤 새 대화를 시작해 주세요.")
            data=copy.deepcopy(self.state);data.update(messages=[],active=None,latest_turn=None,session_id=uuid.uuid4().hex);self._save(data)
            return self.snapshot()

    def begin(self,revision,identity,message):
        with self.lock:
            self._load();self._check_revision(revision)
            if self.state["active"]:raise ValueError("다른 기기에서 도우미가 처리 중입니다.")
            data=copy.deepcopy(self.state)
            for row in data["messages"]:
                if row.get("plan",{}).get("state")=="확인 대기":row["plan"]["state"]="새 요청으로 대체됨"
            turns=[]
            for row in data["messages"][-12:]:
                text=row["text"]
                if row.get("plan"):
                    text+="\n[이전 변경안 기록 · "+row["plan"]["state"]+"]\n"+"\n".join(step["label"]+"\n"+"\n".join("기존: "+change["before"]+"\n변경: "+change["after"] for change in step["changes"]) for step in row["plan"]["steps"])
                turns.append({"role":row["role"],"text":text[:8000]})
            entry={"id":uuid.uuid4().hex,"role":"user","text":message[:8000]};data["messages"].append(entry)
            data["active"]={"id":identity,"phase":"prepare","round":0,"created":time.time()};data["latest_turn"]=identity;self._save(data)
            self.live_progress={}
            return {"conversation":turns,"revision":self.state["revision"],"user_id":entry["id"]}

    def progress(self,identity,phase,round_number):
        with self.lock:
            self._load()
            if not self.state["active"] or self.state["active"]["id"]!=identity:return
            data=copy.deepcopy(self.state);data["active"].update(phase=phase,round=round_number);self._save(data)
            self.live_progress={}

    def activity(self,identity,info):
        """Ephemeral allowlisted status; no transcript rewrite for each heartbeat."""
        with self.lock:
            self._load()
            if self.state["active"] and self.state["active"]["id"]==identity and self.state["active"]["phase"]=="model":
                self.live_progress=clean_progress(info)

    def complete(self,identity,text,plan=None):
        with self.lock:
            self._load()
            if not self.state["active"] or self.state["active"]["id"]!=identity:return None
            data=copy.deepcopy(self.state);entry={"id":uuid.uuid4().hex,"role":"assistant","text":text[:8000]}
            if plan:entry["plan"]=plan
            data["messages"].append(entry);data["active"]=None;self._save(data)
            self.live_progress={}
            return {"revision":self.state["revision"],"message_id":entry["id"]}

    def current(self,identity):
        with self.lock:self._load();return self.state["latest_turn"]==identity

    def plan_state(self,message_id,state,receipt=None):
        with self.lock:
            self._load();data=copy.deepcopy(self.state)
            row=next((row for row in data["messages"] if row["id"]==message_id and row.get("plan")),None)
            if row is None or row["plan"]["state"]==state:return
            row["plan"]["state"]=state
            if receipt:data["messages"].append({"id":uuid.uuid4().hex,"role":"assistant","text":receipt[:8000]})
            self._save(data)
