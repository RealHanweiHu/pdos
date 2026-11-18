import json,glob,sys
def load(f):
    o=json.load(open(f)); ts=int(f.split('/')[-1].split('-')[0])
    first=None; usage=None; ucreated=None; content=''; calls={}; fin=None
    for packet in o['raw'].replace('\r\n','\n').split('\n\n'):
        for line in packet.splitlines():
            if not line.startswith('data:') or line[5:].strip()=='[DONE]': continue
            c=json.loads(line[5:])
            if c.get('choices') and first is None: first=c['created']
            if c.get('usage'): usage=c['usage']; ucreated=c['created']
            for ch in c.get('choices',[]):
                d=ch.get('delta',{})
                content+=d.get('content') or ''
                for t in d.get('tool_calls') or []:
                    k=calls.setdefault(t['index'],{'name':'','arguments':''})
                    k['name']+=t.get('function',{}).get('name','') or ''
                    k['arguments']+=t.get('function',{}).get('arguments','') or ''
                fin=ch.get('finish_reason') or fin
    return o,ts,first,usage,ucreated,content,calls,fin
if __name__=='__main__':
    d=sys.argv[1]
    print('tag n_msg elapsed prewait prompt cached out reasoning content_len tools args_ok')
    for f in sorted(glob.glob(d+'/*.json')):
        o,ts,first,usage,ucreated,content,calls,fin=load(f)
        req=o['request']; n=req.get('n_messages') or len(req['messages'])
        ok=[]
        for i,k in sorted(calls.items()):
            try: json.loads(k['arguments']); ok.append('ok')
            except Exception: ok.append('BAD@%d'%len(k['arguments']))
        tag=f.split('/')[-1].split('-',1)[1][:-12]
        print(tag[:28],n,o['elapsed_ms'],None if first is None or ucreated is None else first-ucreated,
          usage and usage['prompt_tokens'],usage and usage['prompt_tokens_details']['cached_tokens'],usage and usage['completion_tokens'],
          usage and usage['completion_tokens_details'].get('reasoning_tokens'),len(content),','.join(k['name'] for _,k in sorted(calls.items())),ok,fin)
        if 'ok'!=tag:
            for i,k in sorted(calls.items()):
                print('   ARGS TAIL:',k['arguments'][-400:])
            if content: print('   CONTENT:',content[:300])
