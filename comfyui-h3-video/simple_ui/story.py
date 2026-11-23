"""User-approved four-clip projects; only exact project-owned jobs and media are used."""
import http.client
import base64
import copy
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import uuid
import zlib

import av
from PIL import Image, ImageOps
from story_workflow import CLIP_COUNT, CLIP_SECONDS, DIRECTOR, compose_prompt, continuation_graph


def replace_file(source, target):
    """Atomic replace that survives a short Windows lock on either file.

    A scanner, indexer or another reader briefly holding the file makes os.replace
    fail with PermissionError. Without the retry a finished clip or merge is reported
    as failed, or the worker stops tracking a job that is still running.
    """
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(.02 * (attempt + 1))


def media_path(root, descriptor):
    if not isinstance(descriptor,dict) or descriptor.get("type")!="output":
        raise ValueError("이 프로젝트의 영상 출력을 확인하지 못했습니다.")
    name=descriptor.get("filename", "")
    if not name or Path(name).name!=name or "\\" in name or "/" in name:
        raise ValueError("올바르지 않은 영상 경로입니다.")
    path=(Path(root)/descriptor.get("subfolder", "")/name).resolve()
    if not path.is_relative_to(Path(root).resolve()): raise ValueError("영상 경로가 허용 범위를 벗어났습니다.")
    return path


# 네 편의 영상 형식이 같으면 영상 트랙은 다시 인코딩하지 않고 그대로 이어 붙인다(화질 손실 없음).
# 실측(docs/PERFORMANCE.md '이어 만들기 병합 화질'): 조각 47.1dB → 예전 방식(libx264 veryfast crf 18) 43.4dB, 그대로 복사 47.1dB.
COPY_CODECS={"av1","h264","hevc","vp9"}


def clip_format(path):
    """(크기·FPS), (영상 코덱·화소 형식·프로파일 + 소리 코덱·표본율·채널 수), 프레임 수.

    앞의 둘이 네 편 모두 같아야 다시 인코딩하지 않고 붙일 수 있다. 목록 입력은 영상도 소리도 디코더가 하나라,
    소리 형식이 다른 편이 섞이면 그 편의 소리가 깨진다."""
    with av.open(str(path)) as container:
        video=next(iter(container.streams.video),None)
        audio=next(iter(container.streams.audio),None)
        if video is None or audio is None: raise ValueError("각 편에 영상·소리 트랙이 모두 필요합니다.")
        context=video.codec_context;sound=audio.codec_context
        codec=getattr(context.codec,"canonical_name","") or context.name
        return ((video.width,video.height,video.average_rate),
            (codec,context.pix_fmt,context.profile,sound.name,sound.sample_rate,sound.channels),int(video.frames or 0))


def frame_checksums(path):
    """영상을 처음부터 끝까지 풀어 프레임마다 밝기 화소의 체크섬을 낸다.

    그대로 이어 붙인 파일은 각 편과 프레임이 한 화소도 달라지면 안 된다. 프레임 수만 세면, 코덱 설정이 다른 편이 섞여
    한 편 전체가 깨진 화면으로 풀리는 파일도 통과한다(프레임은 나오기 때문)."""
    with av.open(str(path)) as container:
        stream=container.streams.video[0]
        stream.thread_type="AUTO"
        return [zlib.crc32(frame.to_ndarray(format="gray").tobytes()) for frame in container.decode(stream)]


def run_ffmpeg(command,cancel):
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=="nt" else 0)
    try:
        while process.poll() is None:
            if cancel.wait(.25):
                process.terminate()
                raise ValueError("병합을 취소했습니다.")
        return process.returncode
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()


def merge_clips(paths, destination, cancel, bgm=None):
    """Join exactly the four accepted clips on CPU; audio is always normalized.

    The video track is copied as it is when all four clips share one format, so the final keeps the
    clips' quality (and codec). Otherwise, or when the copied file does not verify, it is re-encoded.
    SIMPLEUI_STORY_MERGE=reencode always re-encodes to H.264."""
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg: raise ValueError("영상 병합에 필요한 FFmpeg를 찾지 못했습니다.")
    if len(paths)!=CLIP_COUNT: raise ValueError("네 편이 모두 확정되어야 합니다.")
    shape=None;formats=set();frames=[]
    for path in paths:
        current,form,count=clip_format(path)
        if shape is not None and current!=shape: raise ValueError("네 편의 영상 크기와 FPS가 서로 다릅니다.")
        shape=current;formats.add(form);frames.append(count)
    final=Path(destination)
    final.parent.mkdir(parents=True,exist_ok=True)
    # 병합 중·실패한 파일이 갤러리(output/story 의 .mp4)에 보이지 않게 임시 이름으로 쓴 뒤 검증하고 옮긴다
    destination=final.with_name(final.name+".part")
    manifest=final.with_suffix(".concat")
    # Generated absolute paths are quoted for FFmpeg's concat syntax, never a shell.
    manifest.write_text("".join("file '"+str(Path(path).resolve()).replace("\\","/").replace("'","'\\''")+"'\n" for path in paths),encoding="utf-8")
    seconds=CLIP_COUNT*CLIP_SECONDS
    head=[ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y"]
    music="volume=0.2,afade=t=out:st=19:d=1[m];{voice}[m]amix=inputs=2:duration=first:normalize=0[a]"
    tail=["-t",str(seconds),"-c:a","aac","-ar","48000","-b:a","192k","-movflags","+faststart","-f","mp4",str(destination)]
    # (1) 그대로 붙이기: 목록 하나를 입력으로 받아 영상 패킷을 복사한다. 소리만 다시 인코딩한다.
    copy=head+["-f","concat","-safe","0","-i",str(manifest)]
    # Simple audio filters cannot be combined with a mapped complex audio graph.
    # 편의 소리가 영상보다 짧으면 그만큼 비는데, 맞춰 주지 않으면 뒤 편의 소리가 점점 앞당겨진다(배경음악이 없을 때의 -af 와 같은 처리)
    if bgm: copy += ["-stream_loop","-1","-i",str(bgm),"-filter_complex","[0:a]aresample=async=1:first_pts=0[voice];[1:a]"+music.format(voice="[voice]"),"-map","0:v:0","-map","[a]"]
    else: copy += ["-map","0:v:0","-map","0:a:0","-af","aresample=async=1:first_pts=0"]
    copy += ["-c:v","copy"]+tail
    # (2) 다시 인코딩: 편마다 따로 풀어서 잇는다. 목록 입력은 디코더가 하나라 코덱이 다른 편의 프레임을 통째로 잃는다.
    encode=list(head)
    for path in paths: encode += ["-i",str(path)]
    graph="".join(f"[{i}:v:0][{i}:a:0]" for i in range(CLIP_COUNT))+f"concat=n={CLIP_COUNT}:v=1:a=1[v]"
    if bgm:
        encode += ["-stream_loop","-1","-i",str(bgm)]
        graph += f"[voice];[{CLIP_COUNT}:a]"+music.format(voice="[voice]")
    else: graph += "[a]"
    encode += ["-filter_complex",graph,"-map","[v]","-map","[a]","-c:v","libx264","-preset","medium","-crf","16","-threads","2"]+tail
    attempts=[]
    if (len(formats)==1 and next(iter(formats))[0] in COPY_CODECS and all(frames)
            and os.environ.get("SIMPLEUI_STORY_MERGE","").strip().lower()!="reencode"):
        attempts.append(("copy",copy))
    attempts.append(("encode",encode))
    expected=min(sum(frames),round(seconds*float(shape[2])))
    try:
        for kind,command in attempts:
            last=kind=="encode"
            if run_ffmpeg(command,cancel):
                if last: raise ValueError("영상 병합에 실패했습니다. 각 편의 영상은 유지됩니다.")
                continue
            try:
                with av.open(str(destination)) as result:
                    length=float(result.duration or 0)/av.time_base
                intact=last
                if not last:
                    # 그대로 붙인 영상은 모든 프레임이 각 편의 프레임과 같은지 확인한다(끝의 한두 프레임은 20초에서 잘릴 수 있다)
                    joined=frame_checksums(destination)
                    intact=abs(len(joined)-expected)<=3 and joined==[value for path in paths for value in frame_checksums(path)][:len(joined)]
            except (av.error.FFmpegError,OSError,ValueError,IndexError):
                length,intact=0,False
            # 검증하는 동안 누른 중지도 반영한다(임시 파일은 아래에서 지운다)
            if cancel.is_set(): raise ValueError("병합을 취소했습니다.")
            if 19.8<=length<=20.2 and intact:
                replace_file(destination,final)
                return final
            if last: raise ValueError("병합 길이를 확인하지 못했습니다. 각 편의 영상은 유지됩니다.")
    finally:
        manifest.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


class StoryProjects:
    def __init__(self,home,output,prepare,comfy,upload,status,track,merge=merge_clips,client_id=""):
        self.home=Path(home)
        self.output=Path(output).resolve()
        self.prepare,self.comfy,self.upload,self.status,self.track=prepare,comfy,upload,status,track
        self.merge=merge
        self.client_id=client_id
        self.lock=threading.RLock()
        self.workers={}
        self.cancels={}

    def _path(self,project_id):
        if not isinstance(project_id,str) or not re.fullmatch(r"[0-9a-f]{32}",project_id):
            raise ValueError("프로젝트를 찾을 수 없습니다.")
        return self.home/project_id/"project.json"

    def _read(self,project_id):
        try:
            with self._path(project_id).open(encoding="utf-8") as handle: return json.load(handle)
        except FileNotFoundError:
            # 지워졌거나 다른 PC 의 프로젝트 번호: 서버 경로가 담긴 원문 오류 대신 알린다
            raise ValueError("프로젝트를 찾을 수 없습니다.") from None

    def _write(self,project):
        path=self._path(project["id"])
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix(".tmp")
        with temp.open("w",encoding="utf-8") as handle:
            handle.write(json.dumps(project,ensure_ascii=False));handle.flush();os.fsync(handle.fileno())
        replace_file(temp,path)

    def _public(self,project):
        result=copy.deepcopy(project)
        result.pop("bgm_path",None)
        for run in result["renders"]:
            run["has_video"]=bool(run.get("video_path"))
            for key in ("video_path","job_id","checkpoint","parent_checkpoint","signature"):
                run.pop(key,None)
        if result.get("merged"): result["merged"].pop("video_path",None)
        if result.get("active"): result["active"]={"kind":result["active"]["kind"],"index":result["active"].get("index")}
        return result

    def get(self,project_id):
        with self.lock:
            project=self._read(project_id)
            # Resume only an operation previously requested for this exact project.
            if project.get("active") and project_id not in self.workers:
                self._launch(project_id)
            return self._public(project)

    def save(self,body):
        definition=body.get("definition")
        if not isinstance(definition,dict) or len(definition.get("clips",[]))!=CLIP_COUNT:
            raise ValueError("네 편의 시나리오를 입력해 주세요.")
        if len(json.dumps(definition,ensure_ascii=False))>100000: raise ValueError("프로젝트 내용이 너무 깁니다.")
        common=definition.get("common")
        if not isinstance(common,dict): raise ValueError("공통 설정을 확인해 주세요.")
        # 이어 만들기에서 검증한 속도 우선 방식은 희소 어텐션뿐이다(스텝 캐시를 함께 쓰는 방식은 이어 붙는 편에서 확인하지 않았다)
        if common.get("speed") not in (None,"","sparse"): raise ValueError("이어 만들기에서 쓸 수 없는 속도 우선 방식입니다. 기본이나 '빠르게 — 희소 어텐션'으로 바꿔 주세요.")
        for clip in definition["clips"]:
            if not isinstance(clip,dict) or not isinstance(clip.get("scenario",""),str): raise ValueError("시나리오를 확인해 주세요.")
        boundaries=definition.get("boundaries",[""]*(CLIP_COUNT+1))
        if not isinstance(boundaries,list) or len(boundaries)!=CLIP_COUNT+1 or not all(isinstance(x,str) for x in boundaries):
            raise ValueError("연결 지점의 상태를 확인해 주세요.")
        definition=copy.deepcopy(definition);definition["boundaries"]=boundaries
        with self.lock:
            project_id=body.get("id")
            if project_id:
                project=self._read(project_id)
                if body.get("revision")!=project["revision"]: raise ValueError("다른 기기에서 내용이 바뀌었습니다. 프로젝트를 다시 불러와 주세요.")
                if project.get("active"): raise ValueError("생성·병합이 끝나거나 중지된 뒤 설정을 저장해 주세요.")
            else:
                project_id=uuid.uuid4().hex
                project={"id":project_id,"revision":0,"definition":{},"photos":[],"renders":[{"state":"empty","approved":False,"stale":False} for _ in range(CLIP_COUNT)],"merged":None,"active":None}
            first_change=CLIP_COUNT
            old=project["definition"]
            if old.get("common")!=common: first_change=0
            for i,clip in enumerate(definition["clips"]):
                if i>=len(old.get("clips",[])) or old["clips"][i]!=clip: first_change=min(first_change,i)
            for i,value in enumerate(boundaries):
                if i>=len(old.get("boundaries",[])) or old["boundaries"][i]!=value: first_change=min(first_change,max(0,i-1))
            if "images" in body:
                images=body["images"]
                if not isinstance(images,list) or not 0<=len(images)<=9: raise ValueError("원본 사진은 1~9장 사용할 수 있습니다.")
                photos=[]
                for data in images:
                    if not isinstance(data,str) or not re.match(r"^data:image/[\w.+-]+;base64,",data): raise ValueError("사진 형식을 확인해 주세요.")
                    raw=base64.b64decode(data.split(",",1)[1],validate=True)
                    with Image.open(io.BytesIO(raw)) as source, ImageOps.exif_transpose(source) as image:
                        with io.BytesIO() as normalized:
                            image.save(normalized,format="PNG")
                            photos.append({"name":self.upload(normalized.getvalue(),"png"),"width":image.width,"height":image.height})
                project["photos"]=photos;first_change=0
            if "bgm" in body:
                value=body["bgm"]
                if value:
                    if not isinstance(value,str) or "," not in value: raise ValueError("배경음악 파일을 확인해 주세요.")
                    raw=base64.b64decode(value.split(",",1)[1],validate=True)
                    if len(raw)>50*1024**2: raise ValueError("배경음악은 50MB 이하로 선택해 주세요.")
                    path=self._path(project_id).parent/"background.audio"
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with av.open(io.BytesIO(raw)) as audio:
                        if not audio.streams.audio: raise ValueError("오디오 트랙이 있는 파일을 선택해 주세요.")
                    path.write_bytes(raw);project["bgm_path"]=str(path)
                else: project.pop("bgm_path",None)
                project["merged"]=None
            for run in project["renders"][first_change:]:
                if run.get("video_path"): run.update(stale=True,approved=False)
            if first_change<CLIP_COUNT: project["merged"]=None
            project.update(definition=definition,revision=project["revision"]+1)
            self._write(project)
            return self._public(project)

    def start(self,project_id,index):
        if type(index) is not int or not 0<=index<CLIP_COUNT: raise ValueError("생성할 편을 선택해 주세요.")
        with self.lock:
            project=self._read(project_id)
            if project.get("active"): raise ValueError("현재 단계가 끝난 뒤 진행해 주세요.")
            if not project["photos"]: raise ValueError("공통 원본 사진을 등록해 주세요.")
            if index and not self._accepted(project["renders"][index-1]): raise ValueError("직전 영상을 확인하고 확정한 뒤 진행해 주세요.")
            compose_prompt(project["definition"]["common"],project["definition"]["clips"][index],index,project["definition"]["boundaries"])
            for run in project["renders"][index:]:
                run.update(approved=False)
                if run.get("video_path"): run["stale"]=True
            project["merged"]=None
            project["active"]={"kind":"render","index":index,"job_id":None}
            project["renders"][index].update(state="preparing",pct=0,error=None)
            self._write(project);self._launch(project_id)
            return self._public(project)

    @staticmethod
    def _accepted(run):
        return run.get("state")=="done" and run.get("approved") and not run.get("stale")

    def approve(self,project_id,index):
        with self.lock:
            project=self._read(project_id)
            if type(index) is not int or not 0<=index<CLIP_COUNT: raise ValueError("확정할 편을 선택해 주세요.")
            run=project["renders"][index]
            if project.get("active") or run.get("state")!="done" or run.get("stale"): raise ValueError("현재 설정으로 완료된 영상만 확정할 수 있습니다.")
            if index and not self._accepted(project["renders"][index-1]): raise ValueError("앞 영상을 먼저 확정해 주세요.")
            run["approved"]=True;self._write(project)
            return self._public(project)

    def start_merge(self,project_id):
        with self.lock:
            project=self._read(project_id)
            if project.get("active"): raise ValueError("현재 단계가 끝난 뒤 병합해 주세요.")
            if not all(self._accepted(run) for run in project["renders"]): raise ValueError("네 편을 모두 확인하고 확정해 주세요.")
            project["active"]={"kind":"merge"}
            project.pop("merge_error",None)
            self._write(project);self._launch(project_id)
            return self._public(project)

    def cancel(self,project_id):
        with self.lock:
            project=self._read(project_id)
            operation=project.get("active")
            if not operation: return {"ok":True}
            project["active"]["cancelled"]=True;self._write(project)
            job_id=operation.get("job_id")
        with self.lock:
            if project_id in self.cancels: self.cancels[project_id].set()
        if job_id:
            try:
                with self._post("/queue",{"delete":[job_id]}) as response: response.read()
                with self._post("/interrupt",{"prompt_id":job_id}) as response: response.read()
            except (OSError,http.client.HTTPException):
                pass
        return {"ok":True}

    def _post(self,path,body):
        return self.comfy(path,json.dumps(body,ensure_ascii=False).encode(),{"Content-Type":"application/json"})

    def _launch(self,project_id):
        if project_id in self.workers: return
        event=threading.Event();self.cancels[project_id]=event
        thread=threading.Thread(target=self._work,args=(project_id,event),daemon=True)
        self.workers[project_id]=thread;thread.start()

    def _reference(self,project):
        photos=project["photos"]
        items=[{"type":"image","enabled":True,"value":photo["name"],"source_width":photo["width"],"source_height":photo["height"],"slot":i,"order":i,"start":i,"duration":1,"id":f"reference-{i}"} for i,photo in enumerate(photos)]
        return {"entry":{"images":[photo["name"] for photo in photos]},"prompt":{DIRECTOR:{"inputs":{"timeline_data":json.dumps({"items":items})}}}}

    def _checkpoint(self,project,parent,path):
        directory=self.output/"df_h3_continuity"/project["id"]
        with (directory/"latest.json").open(encoding="utf-8") as handle: identifier=json.load(handle)["clip_id"]
        if not isinstance(identifier,str) or not re.fullmatch(r"[0-9a-f]{32}",identifier): raise ValueError("이어 생성 기준을 확인하지 못했습니다.")
        with (directory/identifier/"clip.json").open(encoding="utf-8") as handle: metadata=json.load(handle)
        if metadata.get("status")!="ready" or metadata.get("session")!=project["id"] or metadata.get("parent_id","")!=(parent or "") or Path(metadata.get("output_path","")).resolve()!=path:
            raise ValueError("이번 영상의 이어 생성 기준이 맞지 않습니다.")
        return identifier

    def _work(self,project_id,cancel):
        index=None
        try:
            with self.lock: project=self._read(project_id)
            operation=project["active"]
            if operation.get("cancelled"): raise ValueError("작업을 중지했습니다.")
            if operation["kind"]=="merge":
                destination=self.output/"story"/project_id/(uuid.uuid4().hex+".mp4")
                path=self.merge([Path(run["video_path"]) for run in project["renders"]],destination,cancel,project.get("bgm_path"))
                with self.lock:
                    project=self._read(project_id)
                    if project["active"].get("cancelled"):
                        # 병합이 끝나는 순간에 누른 중지: 방금 만든 파일을 남기지 않는다(각 편의 영상은 그대로다)
                        Path(path).unlink(missing_ok=True)
                        raise ValueError("작업을 중지했습니다.")
                    project["merged"]={"state":"done","video_path":str(path)}
                    project["active"]=None;self._write(project)
                return
            index=operation["index"]
            definition=project["definition"];common=dict(definition["common"],reference_count=len(project["photos"]));clip=definition["clips"][index]
            parent=project["renders"][index-1].get("checkpoint") if index else None
            if not operation.get("job_id"):
                prompt=compose_prompt(common,clip,index,definition["boundaries"])
                seed=str(clip.get("seed") or random.randint(1,2**53))
                request={**common,"prompt":prompt,"mode":"REF2VA","duration":CLIP_SECONDS,"count":1,"anchor":index==0,"seed":seed}
                prepared=self.prepare(request,self._reference(project))
                graph=continuation_graph(prepared["prompt"],project_id,index,parent,prompt)
                job_id=str(uuid.uuid4())
                with self.lock:
                    project=self._read(project_id)
                    if project["active"].get("cancelled"): raise ValueError("작업을 중지했습니다.")
                    project["active"]["job_id"]=job_id
                    project["renders"][index].update(job_id=job_id,seed=int(seed),parent_checkpoint=parent,
                        state="queued",pct=0,width=prepared["width"],height=prepared["height"])
                    self._write(project)
                    self.track(job_id,graph)
                    # The ID is persisted first; a lost response must never cause duplicate jobs.
                    try:
                        with self._post("/prompt",{"prompt_id":job_id,"prompt":graph,"client_id":self.client_id}) as response:
                            result=json.load(response)
                        if result.get("prompt_id")!=job_id: raise ValueError("생성 요청을 확인하지 못했습니다.")
                    except urllib.error.HTTPError:
                        raise ValueError("이어 생성 요청을 처리하지 못했습니다. 모델·설정을 확인해 주세요.") from None
                    except (urllib.error.URLError,TimeoutError,ConnectionError):
                        # Acceptance is uncertain; follow the saved ID without resubmitting.
                        pass
            else: job_id=operation["job_id"]
            missing=0
            while not cancel.is_set():
                try: state=self.status(job_id)
                except (OSError,http.client.HTTPException,json.JSONDecodeError):
                    # URLError·TimeoutError·ConnectionResetError 는 모두 OSError. ComfyUI 작업은 계속 돌고 있을 수 있다
                    if cancel.wait(2): break
                    continue
                if state["state"]=="done":
                    path=media_path(self.output,state.get("video"))
                    if not path.is_file(): raise ValueError("이번 단계의 완료 출력을 확인하지 못했습니다.")
                    checkpoint=self._checkpoint(project,parent,path)
                    with self.lock:
                        project=self._read(project_id)
                        if project["active"].get("cancelled"): raise ValueError("작업을 중지했습니다.")
                        project["renders"][index].update(state="done",approved=False,stale=False,pct=100,video_path=str(path),checkpoint=checkpoint,error=None)
                        project["active"]=None;self._write(project)
                    return
                if state["state"]=="error": raise ValueError("이번 단계의 생성이 중단됐습니다. 이전 단계는 유지됩니다.")
                missing=missing+1 if state["state"]=="unknown" else 0
                if missing>=10: raise ValueError("생성 요청을 찾지 못했습니다. 중복 요청 없이 중지했습니다.")
                with self.lock:
                    project=self._read(project_id)
                    project["renders"][index].update(state=state["state"],pct=state.get("pct",0),position=state.get("position"),label=state.get("label",""))
                    try: self._write(project)
                    except OSError: pass  # 진행 표시만 한 번 건너뛴다. 생성 작업은 계속 돌고 있으므로 실패로 끝내지 않는다
                cancel.wait(2)
            raise ValueError("작업을 중지했습니다.")
        except (OSError,ValueError,KeyError,TypeError) as error:
            with self.lock:
                project=self._read(project_id)
                message=str(error) if isinstance(error,ValueError) else "현재 단계를 완료하지 못했습니다. 이전 단계는 유지됩니다."
                if index is not None: project["renders"][index].update(state="error",error=message,approved=False)
                else: project["merge_error"]=message
                project["active"]=None;self._write(project)
        finally:
            with self.lock:
                self.workers.pop(project_id,None);self.cancels.pop(project_id,None)

    def video(self,project_id,which):
        with self.lock:
            project=self._read(project_id)
            if which=="merged": run=project.get("merged") or {}
            else:
                index=int(which)
                if not 0<=index<CLIP_COUNT: raise ValueError("영상을 선택해 주세요.")
                run=project["renders"][index]
            path=Path(run.get("video_path","")).resolve()
            if not run.get("video_path") or not path.is_relative_to(self.output) or not path.is_file():
                raise ValueError("선택한 단계의 영상이 아직 준비되지 않았습니다.")
            relative=path.relative_to(self.output)
            return {"filename":relative.name,"subfolder":relative.parent.as_posix(),"type":"output"}
