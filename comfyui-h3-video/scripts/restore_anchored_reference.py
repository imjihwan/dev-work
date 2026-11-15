"""Restore authorized common fields from pre-unlock backups; expose aggregate counts only."""
import argparse
import json
from pathlib import Path
import re

if __package__:
    from . import apply_queued_style as helper
else:
    import apply_queued_style as helper

STYLE_FILE=helper.PROJECT/'logs/queue-style-waist45-reference-side-yaw.txt'
REMOVED_STYLE_FILES=(helper.PROJECT/'logs/queue-style-reference-person-yaw45.txt',helper.PROJECT/'logs/queue-style-reference-person-yaw45-clear.txt')
UNLOCKED_ONE_TAKE="One continuous take: keep the camera viewpoint, position and framing established at the start of this video stable throughout the shot, with no cuts, no scene changes and no new locations. Keep the environment established in the opening frame consistent throughout the video."
RESTORED_BACKGROUND="Keep the same environment, with perspective and occlusion consistent with the established camera viewpoint."


def section_replace(text,label,transform):
    pattern=r"(^"+label+r":[ \t]*)([\s\S]*?)(?=\n(?:"+helper.SECTIONS+r"):|\Z)"
    result,count=re.subn(pattern,lambda match:match[1]+transform(match[2]),text,count=1,flags=re.M)
    if count!=1:raise helper.StyleMismatch('missing_restore_section')
    return result


def prefix_replace(text,previous,replacement):
    if previous==replacement:return text
    if not previous.strip():raise helper.StyleMismatch('empty_restore_prefix')
    pattern=r"\s+".join(re.escape(part) for part in previous.split())
    match=re.match(pattern,text)
    if not match:raise helper.StyleMismatch('changed_restore_prefix')
    return replacement+text[match.end():]


def restore_subject(text,image_count):
    old=helper.REFERENCE_SUBJECT_OLD_MULTI if image_count>1 else helper.REFERENCE_SUBJECT_OLD_SINGLE
    if text.lstrip().startswith(helper.REFERENCE_SUBJECT_APPEARANCE):
        start=len(text)-len(text.lstrip())
        return text[:start]+old+text[start+len(helper.REFERENCE_SUBJECT_APPEARANCE):]
    return text


def restore_generated_retention(text):
    return (text.replace(' '+helper.REFERENCE_POSE_SCOPE,'').replace(helper.REFERENCE_POSE_SCOPE,'')
            .replace(UNLOCKED_ONE_TAKE,helper.PREVIOUS_ONE_TAKE_KEEP)
            .replace(helper.REFERENCE_BACKGROUND,RESTORED_BACKGROUND))


def read_originals(home,identities,style):
    originals={}
    root=home/'queue-style-backups'
    if not root.is_dir():return originals
    for path in sorted(root.glob('*.json'),key=lambda value:value.stat().st_mtime):
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        for record in data.get('entries',[]):
            entry=record.get('history') or {}
            if (entry.get('id') in identities and entry.get('anchor') is True
                    and entry.get('ui',{}).get('f',{}).get('style')==style):
                originals[entry['id']]=entry
    return originals


def prepare_restore(entry,item,style,env,original=None,allowed_styles=()):
    form=entry.get('ui',{}).get('f',{})
    current_style=form.get('style')
    if entry.get('mode')!='REF2VA' or current_style not in (*allowed_styles,style):
        raise helper.StyleMismatch('different_reference_policy')
    # New work created after unlocking has no old entry; only known common clauses are reverted.
    text=helper.replace_style(entry['prompt'],current_style,style)
    incoming={'f':{'style':style}}
    image_count=len(entry.get('images') or [])
    if not image_count:raise helper.StyleMismatch('missing_reference')
    for key,label in (('keep','retention_analysis'),('subject','subject_definitions')):
        current=form.get(key)
        if not isinstance(current,str):continue
        old=(original or {}).get('ui',{}).get('f',{}).get(key)
        if key=='keep':
            expected=helper.refresh_reference_background(old) if isinstance(old,str) else None
            restored=old if expected==current else current.replace(helper.REFERENCE_BACKGROUND,RESTORED_BACKGROUND)
        else:
            expected=helper.refresh_reference_subject(old) if isinstance(old,str) else None
            restored=old if expected==current else restore_subject(current,image_count)
        if restored!=current:
            text=section_replace(text,label,lambda body:prefix_replace(body,current,restored))
            incoming['f'][key]=restored
    text=section_replace(text,'subject_definitions',lambda body:restore_subject(body,image_count))
    text=section_replace(text,'retention_analysis',restore_generated_retention)
    expected=helper.patch_graph(item[2],env['DIRECTOR'],entry['prompt'],text)
    if not entry.get('anchor'):
        if env['ANCHOR'] in expected or env['ANCHOR_IMG'] in expected:
            raise helper.StyleMismatch('custom_anchor_graph')
        env['add_anchor'](expected,entry['images'][0])
    values=dict(entry,prompt=text,anchor=True,count=1,photo_sequence=False,edit_id=None)
    env['object_options']=lambda kind,field:[entry['model']] if kind=='UNETLoader' else [lora['name'] for lora in entry.get('loras',[])]
    candidate=env['build_and_queue'](values,reference={'entry':entry,'prompt':item[2]},prepare_only=True)['prompt']
    if helper.semantic_graph(candidate)!=helper.semantic_graph(expected):
        raise helper.StyleMismatch('other_graph_settings_would_change')
    if 'final' in entry.get('ui',{}):incoming['final']=text if isinstance(entry['ui']['final'],str) else None
    return {'edit_ids':[entry['id']],'bulk_fields':['content','anchor'],'anchor':True,'prompt':text,'ui':incoming},expected


def run(apply=False):
    style=STYLE_FILE.read_text(encoding='utf-8-sig').strip()
    removed=[path.read_text(encoding='utf-8-sig').strip() for path in REMOVED_STYLE_FILES]
    queue=helper.request('http://127.0.0.1:8188/queue')
    history=helper.entries()
    targets={item[1] for item in queue['queue_pending'] if item[1] in history}
    originals=read_originals(helper.HOME,targets,style)
    running={item[1]:item for item in queue['queue_running']}
    def prepare(entry,item,replacement,env):
        return prepare_restore(entry,item,replacement,env,originals.get(entry['id']),removed)
    counts=helper.run(style,apply=apply,prepare_fn=prepare)
    counts['pre_unlock_backups']=len(originals)
    print(json.dumps({'restoration':counts}),flush=True)
    if apply:
        live=helper.request('http://127.0.0.1:8188/queue');saved=helper.entries();env=helper.dry_builder(helper.HOME)
        audit={'pending_owned':0,'anchor_enabled':0,'policy_and_graph_match':0,'exact_pre_unlock_prompt':0,
               'original_running_active':0,'original_running_unchanged':0,'unmatched':0}
        for item in live['queue_pending']:
            entry=saved.get(item[1])
            if entry is None:continue
            audit['pending_owned']+=1;audit['anchor_enabled']+=entry.get('anchor') is True
            audit['exact_pre_unlock_prompt']+=entry.get('prompt')==(originals.get(item[1]) or {}).get('prompt')
            try:
                _,graph=prepare(entry,item,style,env)
                audit['policy_and_graph_match']+=(entry.get('ui',{}).get('f',{}).get('style')==style and helper.semantic_graph(graph)==helper.semantic_graph(item[2]))
            except (ValueError,KeyError,TypeError):audit['unmatched']+=1
        for item in live['queue_running']:
            if item[1] in running:
                audit['original_running_active']+=1;audit['original_running_unchanged']+=item==running[item[1]]
        print(json.dumps({'verification':audit}),flush=True)
        if (audit['pending_owned']!=audit['anchor_enabled'] or audit['pending_owned']!=audit['policy_and_graph_match']
            or audit['original_running_active']!=audit['original_running_unchanged'] or audit['unmatched']):return False
    return not any(counts[key] for key in ('failed','unmatched','changed_before_update'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    try:ok=run(args.apply)
    except Exception:
        print(json.dumps({'error':'restoration_stopped_without_exposing_private_data'}));ok=False
    raise SystemExit(0 if ok else 1)
