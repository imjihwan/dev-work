"""No workflow nodes or model changes; a count-only native queue control API."""
from pathlib import Path
from aiohttp import web
from server import PromptServer
from .control import QueuePauseGate

NODE_CLASS_MAPPINGS={}
server=PromptServer.instance
queue=server.prompt_queue
gate=getattr(queue,'h3_video_pause_gate',None)
if gate is None:
    gate=QueuePauseGate(queue,Path(__file__).with_name('pause-state.json')).install()
    queue.h3_video_pause_gate=gate


@server.routes.get('/h3-video/queue-pause')
async def queue_pause_state(request):
    return web.json_response(gate.snapshot())


@server.routes.post('/h3-video/queue-pause')
async def queue_pause_set(request):
    try:
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'paused'} or type(body['paused']) is not bool:
            return web.json_response({'error':'일시정지 상태를 확인해 주세요.'},status=400)
        return web.json_response(gate.set_paused(body['paused']))
    except (OSError,ValueError):
        return web.json_response({'error':'일시정지 상태를 저장하지 못했습니다. 기존 상태를 유지합니다.'},status=500)
