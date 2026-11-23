"""Windows backend restart with opaque local backups and guarded queue replay.

Never prints prompts, job identifiers, source/result filenames or model settings.
Running work restarts from the beginning unless --after-current is selected.
--after-current --pause-after installs the queue gate without interrupting a job.
Requires the guarded UI server.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
COMFY_URL='http://127.0.0.1:8188'
UI_URL='http://127.0.0.1:8190'

def emit(phase,**fields):
    print(json.dumps({'phase':phase,**fields},ensure_ascii=False),flush=True)

def api(base,path,body=None,timeout=20):
    request=urllib.request.Request(base+path,json.dumps(body).encode() if body is not None else None,{'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        raw=response.read()
        return json.loads(raw) if raw.strip() else {}

def atomic_json(path,value):
    temporary=path.with_suffix(path.suffix+'.writing')
    with temporary.open('w',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False);handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)

def ordered_items(queue):
    running=queue.get('queue_running',[])
    pending=sorted(queue.get('queue_pending',[]),key=lambda x:x[0])
    result=list(running)+pending
    ids=[]
    for item in result:
        if len(item)<5 or not isinstance(item[2],dict) or not isinstance(item[3],dict) or not isinstance(item[4],list):
            raise ValueError('Unsupported queue entry structure')
        if str(uuid.UUID(item[1]))!=item[1]:raise ValueError('Unsupported job identifier')
        ids.append(item[1])
    if len(set(ids))!=len(ids):raise ValueError('Duplicate job identity')
    return result

def replay_body(item):
    # Fresh backend counter must advance so future normal additions stay last.
    result={'prompt_id':item[1],'prompt':copy.deepcopy(item[2]),'extra_data':copy.deepcopy(item[3]),
            'partial_execution_targets':copy.deepcopy(item[4])}
    if item[3].get('client_id'):result['client_id']=item[3]['client_id']
    return result

def comparable_extra(extra):
    return {key:value for key,value in extra.items() if key!='create_time'}

def verify_replay(expected,queue,history):
    actual=ordered_items(queue)
    actual_map={item[1]:item for item in actual}
    expected_map={item[1]:item for item in expected}
    if set(actual_map)-set(expected_map):raise ValueError('Unexpected queue additions during restart')
    completed={pid for pid,entry in history.items() if entry.get('status',{}).get('status_str')=='success'}
    if set(actual_map)|completed != set(expected_map):raise ValueError('Restored queue identity coverage mismatch')
    if [item[1] for item in actual] != [item[1] for item in expected if item[1] not in completed]:
        raise ValueError('Restored queue order mismatch')
    for pid,item in expected_map.items():
        found=actual_map.get(pid) or history[pid].get('prompt')
        # Backend validation returns output targets from a set; iteration order
        # may change across processes without changing the execution graph.
        if not found or found[2]!=item[2] or comparable_extra(found[3])!=comparable_extra(item[3]) or set(found[4])!=set(item[4]):
            raise ValueError('Restored data differs from backup')
    return len(actual),len(completed)

def finalize_restored(comfy,backup):
    ui=comfy/'simple_ui';backup=backup.resolve()
    if not backup.is_relative_to((ui/'restart_backups').resolve()):raise ValueError('Recovery path is outside private restart backups')
    receipt=json.loads((backup/'receipt.json').read_bytes())
    if receipt.get('complete') or not receipt.get('backend_stopped'):raise ValueError('Expected an unfinished, restarted backend operation')
    finished=json.loads((backup/'finished-before-restart.json').read_bytes())
    expected=[item for item in ordered_items(json.loads((backup/'queue.json').read_bytes())) if item[1] not in finished]
    if receipt.get('restored_count')!=len(expected):raise ValueError('Queue replay is incomplete; do not clear protection')
    live=api(COMFY_URL,'/queue');present={item[1] for item in ordered_items(live)}
    completed={}
    for item in expected:
        if item[1] not in present:completed.update(api(COMFY_URL,'/history/'+urllib.parse.quote(item[1])))
    active_count,complete_count=verify_replay(expected,live,completed)
    receipt.update(complete=True,active_count=active_count,completed_during_restore=complete_count,
                   identities_preserved=True,order_preserved=True,graph_and_settings_preserved=True,
                   output_target_sets_preserved=True,progress_reset=True)
    receipt.pop('error_type',None);receipt.pop('safe_error_reason',None)
    atomic_json(backup/'receipt.json',receipt)
    (ui/'backend-restart.tmp').unlink()
    assert api(UI_URL,'/api/health').get('backend_restarting') is False
    emit('restart_complete',restored_count=len(expected),active_count=active_count,
         completed_during_restore=complete_count,ids_order_data_verified=True)

def listener_pid(port):
    import psutil
    pids={entry.pid for entry in psutil.net_connections(kind='tcp') if entry.status==psutil.CONN_LISTEN and entry.laddr.port==port}
    if len(pids)!=1 or None in pids:raise ValueError('Expected a single owned listener')
    return pids.pop()

def wait_for_idle(ids,after_current=False,initial_running=()):
    """Opaque queue bookkeeping only; after-current never sends interrupt."""
    seen=set(initial_running);deadline=time.monotonic()+(86400 if after_current else 60)
    if after_current:emit('waiting_for_current_completion',running=len(seen))
    while True:
        current=api(COMFY_URL,'/queue');current_items=ordered_items(current)
        if any(item[1] not in ids for item in current_items):raise ValueError('New work arrived while quiescing')
        if current['queue_pending']:
            api(COMFY_URL,'/queue',{'delete':[item[1] for item in current['queue_pending']]})
        running=current['queue_running'];seen.update(item[1] for item in running)
        if not running:return seen
        if not after_current:
            for item in running:api(COMFY_URL,'/interrupt',{'prompt_id':item[1]})
        if time.monotonic()>deadline:raise ValueError('Running work did not quiesce; backend was not terminated')
        time.sleep(1)


def perform(comfy,resume=None,after_current=False,pause_after=False):
    import psutil
    ui=comfy/'simple_ui';hold=ui/'backend-restart.tmp'
    if hold.exists() and resume is None:raise ValueError('A restart marker already exists; recover that operation first')
    if resume is not None:
        resume=resume.resolve()
        if not resume.is_relative_to((ui/'restart_backups').resolve()):raise ValueError('Recovery path is outside private restart backups')
    health=api(UI_URL,'/api/health')
    if not health.get('backend_restart_guard'):raise ValueError('UI restart guard is not installed')
    if api(UI_URL,'/api/queue/bulk-progress').get('state')=='running':raise ValueError('A queue edit is active; no work was stopped')
    for path in (ui/'story_data').glob('*/project.json'):
        if json.loads(path.read_bytes()).get('active'):raise ValueError('A UI-owned operation is active')
    old=psutil.Process(listener_pid(8188))
    command=old.cmdline()
    if not any(Path(arg).name=='main.py' for arg in command):raise ValueError('Backend listener is not ComfyUI')
    if Path(old.cwd()).resolve()!=comfy:raise ValueError('Unexpected backend working directory')
    python=comfy/'.venv/Scripts/python.exe'
    if not python.is_file():raise ValueError('Expected backend Python environment')
    backup=resume or (ui/'restart_backups'/time.strftime('%Y%m%d-%H%M%S'))
    if resume is None:
        backup.mkdir(parents=True,exist_ok=False)
        receipt={'complete':False,'backend_stopped':False,'restored_count':0,'private_content_printed':False,
                 'after_current':after_current,'pause_after':pause_after}
        snapshot=api(COMFY_URL,'/queue')
    else:
        receipt=json.loads((backup/'receipt.json').read_bytes())
        after_current=receipt.get('after_current',after_current);pause_after=receipt.get('pause_after',pause_after)
        if receipt.get('complete') or receipt.get('backend_stopped') or receipt.get('restored_count'):
            raise ValueError('This recovery mode requires the original backend to still be running')
        snapshot=json.loads((backup/'queue.json').read_bytes())
        original_ids={item[1] for item in ordered_items(snapshot)}
        if any(item[1] not in original_ids for item in ordered_items(api(COMFY_URL,'/queue'))):
            raise ValueError('Unexpected work appeared before recovery')
        emit('resuming_verified_backup',count=len(original_ids))
    items=ordered_items(snapshot)
    if not items:emit('empty_queue')
    initial_running={item[1] for item in snapshot['queue_running']} if after_current else set()
    def set_hold(values):atomic_json(hold,{'jobs':{item[1]:index+1 for index,item in enumerate(values) if item[1] not in initial_running}})
    try:
        set_hold(items)
        assert api(UI_URL,'/api/health').get('backend_restarting') is True
        # Verify writes are blocked without submitting any real work.
        try:api(UI_URL,'/api/prompt-helper/start',{})
        except urllib.error.HTTPError as exc:
            if exc.code!=503:raise ValueError('UI write guard did not engage')
        else:raise ValueError('UI write guard did not engage')
        if resume is None:
            snapshot=api(COMFY_URL,'/queue');items=ordered_items(snapshot)
            if after_current:initial_running={item[1] for item in snapshot['queue_running']}
            set_hold(items)
        ids={item[1] for item in items}
        if resume is None:
            atomic_json(backup/'queue.json',snapshot)
            history_bytes=(ui/'history.json').read_bytes() if (ui/'history.json').is_file() else b'[]'
            (backup/'history.json').write_bytes(history_bytes)
            assert (backup/'history.json').read_bytes()==history_bytes
        assert ordered_items(json.loads((backup/'queue.json').read_bytes()))==items
        emit('backup_verified',running=len(snapshot['queue_running']),pending=len(snapshot['queue_pending']))
        atomic_json(backup/'receipt.json',receipt)
        atomic_json(backup/'launch.json',{'arguments':command[1:]})
        pending=[item[1] for item in snapshot['queue_pending']]
        if pending:api(COMFY_URL,'/queue',{'delete':pending})
        # Confirm held statuses prevent stale/missing-job transitions and clear old progress.
        for item in items:
            if item[1] in initial_running:continue
            held=api(UI_URL,'/api/status?'+urllib.parse.urlencode({'id':item[1]}))
            if held.get('state')!='queued' or held.get('pct')!=0:raise ValueError('UI status guard did not engage')
        seen_running=wait_for_idle(ids,after_current,initial_running)
        # A job may have naturally finished while pending work was being detached.
        finished={}
        if after_current:
            # No result lookup: vanished running items have ended and must not
            # be replayed, regardless of their success/error outcome.
            finished={pid:{'finished_before_restart':True} for pid in seen_running}
        else:
            for item in items:
                found=api(COMFY_URL,'/history/'+urllib.parse.quote(item[1]))
                if found.get(item[1],{}).get('status',{}).get('status_str')=='success':finished.update(found)
        atomic_json(backup/'finished-before-restart.json',finished)
        replay=[item for item in items if item[1] not in finished];set_hold(replay)
        for pid in finished:api(UI_URL,'/api/status?'+urllib.parse.urlencode({'id':pid}))
        emit('quiesced',naturally_completed=len(finished),to_restore=len(replay))
        if pause_after:
            extension=comfy/'custom_nodes/H3VideoQueuePause'
            if not (extension/'control.py').is_file():raise ValueError('Queue pause extension is not installed')
            atomic_json(extension/'pause-state.json',{'paused':True})
        # The owned, now-idle backend is the only process stopped here.
        old.terminate();old.wait(timeout=15);receipt['backend_stopped']=True
        emit('backend_stopped')
        env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
        with (backup/'startup.stdout.log').open('wb') as out,(backup/'startup.stderr.log').open('wb') as err:
            started=subprocess.Popen([str(python),'-X','utf8',*command[1:]],cwd=comfy,env=env,stdout=out,stderr=err,
                                     creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
        receipt['new_launcher_pid']=started.pid
        try:
            # Bookkeeping for Start/Stop scripts only. The old backend is already stopped here, so a
            # missing logs folder (start_comfyui.bat users never create it) must not abort the
            # restore and strand the detached queue behind the restart marker.
            (ROOT/'logs').mkdir(exist_ok=True);(ROOT/'logs/comfyui.pid').write_text(str(started.pid),encoding='ascii')
        except OSError:pass
        deadline=time.monotonic()+180
        while True:
            if started.poll() is not None:raise ValueError('Backend exited during startup; private startup log retained')
            try:
                if api(COMFY_URL,'/system_stats',timeout=2).get('system',{}).get('comfyui_version'):break
            except (OSError,ValueError):pass
            if time.monotonic()>deadline:raise ValueError('Backend startup timed out')
            time.sleep(1)
        if ordered_items(api(COMFY_URL,'/queue')):raise ValueError('Fresh backend already contains unexpected work')
        emit('backend_ready')
        if pause_after:
            state=api(COMFY_URL,'/h3-video/queue-pause')
            if state.get('paused') is not True:raise ValueError('Queue pause gate was not activated; no work was replayed')
        time.sleep(3) # Existing UI websocket clients reconnect without changing client IDs.
        for index,item in enumerate(replay):
            response=api(COMFY_URL,'/prompt',replay_body(item),timeout=60)
            if response.get('prompt_id')!=item[1]:raise ValueError('Restored job identity changed')
            receipt['restored_count']=index+1
            atomic_json(backup/'receipt.json',receipt)
        live=api(COMFY_URL,'/queue');present={item[1] for item in ordered_items(live)}
        completed={}
        for item in replay:
            if item[1] not in present:completed.update(api(COMFY_URL,'/history/'+urllib.parse.quote(item[1])))
        active_count,complete_count=verify_replay(replay,live,completed)
        if pause_after and (live['queue_running'] or not api(COMFY_URL,'/h3-video/queue-pause').get('paused')):
            raise ValueError('Restored queue did not remain paused')
        receipt.update(complete=True,restored_count=len(replay),active_count=active_count,
                       completed_during_restore=complete_count,identities_preserved=True,order_preserved=True,
                       graph_and_settings_preserved=True,progress_reset=True)
        atomic_json(backup/'receipt.json',receipt)
        hold.unlink()
        assert api(UI_URL,'/api/health').get('backend_restarting') is False
        emit('restart_complete',restored_count=len(replay),active_count=active_count,
             completed_during_restore=complete_count,ids_order_data_verified=True,paused=pause_after)
    except Exception as exc:
        receipt['error_type']=type(exc).__name__
        if type(exc) is ValueError:receipt['safe_error_reason']=str(exc)
        atomic_json(backup/'receipt.json',receipt)
        # Keep the marker: never expose missing jobs or allow ambiguous resubmission.
        emit('restart_requires_recovery',backend_stopped=receipt['backend_stopped'],restored_count=receipt['restored_count'],error_type=type(exc).__name__,reason=receipt.get('safe_error_reason','Private diagnostic retained'))
        raise SystemExit(1)

if __name__=='__main__':
    # README 의 위치 규칙: --comfy → <프로젝트>\\ComfyUI → %USERPROFILE%\\ComfyUI
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--comfy',type=Path,default=ROOT/'ComfyUI' if (ROOT/'ComfyUI').is_dir() else Path.home()/'ComfyUI')
    parser.add_argument('--resume-backup',type=Path,help='Verified private backup to resume before the original backend was stopped')
    parser.add_argument('--verify-restored-backup',type=Path,help='Reverify a fully replayed backup and release UI protection without resubmitting')
    parser.add_argument('--after-current',action='store_true',help='Let running work finish without interruption before restarting')
    parser.add_argument('--pause-after',action='store_true',help='Activate the installed pause gate before restoring the queue')
    args=parser.parse_args()
    try:
        if args.verify_restored_backup:finalize_restored(args.comfy.resolve(),args.verify_restored_backup)
        else:perform(args.comfy.resolve(),args.resume_backup,args.after_current,args.pause_after)
    except SystemExit:raise
    except Exception as exc:
        emit('restart_preflight_failed',error_type=type(exc).__name__,backend_stopped=False)
        raise SystemExit(1)
