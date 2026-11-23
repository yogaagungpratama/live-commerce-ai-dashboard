import os, json, re, csv, io, math
from collections import Counter
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
import psycopg
from psycopg.rows import dict_row

app=FastAPI(title='Live Commerce Analytics Dashboard')
DB=os.getenv('DATABASE_URL','')
STOP={'yang','dan','atau','ini','itu','untuk','dengan','saya','kamu','bisa','ada','berapa','dong','min','kak','the','and','you','how','what','nya','mau','buat','yg'}
POS=['bagus','suka','mantap','keren','menarik']
NEG=['jelek','kecewa','mahal','buruk','tidak','nggak','gak']
QW=['berapa','ada','stok','size','ukuran','harga','bisa','kapan','warna']
INTENT=['checkout','keep','beli','order','cari','harga','ready','stok','cod','promo']
def db(): return psycopg.connect(DB,row_factory=dict_row)
def safe_text(x): return str(x or '')
def hour(ts): return ts.astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)
def sentiment(low):
    if any(x in low for x in POS): return 'positive'
    if any(x in low for x in NEG): return 'negative'
    return 'neutral'
def is_question(c): return '?' in c or any(w in c.lower() for w in QW)
def decode(c):
    c=safe_text(c)
    if c.startswith('"'):
        try: return json.loads(c)
        except Exception: pass
    return c
def _mean(v): return sum(v)/len(v) if v else None
def _var(v):
    if len(v)<2: return 0.0
    m=_mean(v); return sum((x-m)**2 for x in v)/(len(v)-1)
def _inv(A):
    n=len(A); M=[row[:]+[1.0 if i==j else 0.0 for j in range(n)] for i,row in enumerate(A)]
    for c in range(n):
        piv=max(range(c,n),key=lambda r:abs(M[r][c]))
        if abs(M[piv][c])<1e-12: return None
        M[c],M[piv]=M[piv],M[c]; d=M[c][c]; M[c]=[x/d for x in M[c]]
        for r in range(n):
            if r!=c and M[r][c]:
                f=M[r][c]; M[r]=[a-f*b for a,b in zip(M[r],M[c])]
    return [row[n:] for row in M]
def ols(X,y,names):
    """OLS sederhana: koefisien, SE, t, R². Untuk monitoring; analisis final tetap di SPSS/SmartPLS."""
    n,k=len(y),len(X[0])
    if n<=k+1: return None
    XtX=[[sum(r[i]*r[j] for r in X) for j in range(k)] for i in range(k)]; inv=_inv(XtX)
    if not inv: return None
    Xty=[sum(r[i]*yy for r,yy in zip(X,y)) for i in range(k)]; b=[sum(inv[i][j]*Xty[j] for j in range(k)) for i in range(k)]
    res=[yy-sum(bi*xi for bi,xi in zip(b,r)) for r,yy in zip(X,y)]; sse=sum(e*e for e in res); my=_mean(y); sst=sum((yy-my)**2 for yy in y)
    s2=sse/(n-k)
    return {'n':n,'r2':round(1-sse/sst,3) if sst else None,'coef':[{'name':nm,'b':round(bi,3),'se':round(math.sqrt(max(s2*inv[i][i],0)),3),
            't':round(bi/math.sqrt(s2*inv[i][i]),2) if s2*inv[i][i]>0 else None} for i,(nm,bi) in enumerate(zip(names,b))]}
def survey_rows(surveys):
    return [s['answers'] for s in surveys if isinstance(s.get('answers'),dict) and s['answers'].get('v')]
def survey_stats(surveys):
    resp=survey_rows(surveys)
    valid=[a for a in resp if a.get('eligible') and all(isinstance(a.get(k),list) and len(a[k])==4 for k in 'XYZ')]
    out={'total':len(resp),'valid':len(valid),'screened_out':sum(1 for a in resp if not a.get('eligible')),'dummy':any(a.get('dummy') for a in resp),
         'versions':dict(Counter(a.get('v') for a in resp)),'seen_ai':dict(Counter((a.get('screen') or {}).get('seen_ai') for a in valid)),
         'platform':dict(Counter((a.get('profile') or {}).get('platform') or 'n/a' for a in valid)),'constructs':{},'items':{},'h1':None,'h2':None,'r_xy':None}
    for k in 'XYZ':
        cols=[[a[k][i] for a in valid] for i in range(4)]; sc=[_mean(a[k]) for a in valid]; tv=_var([sum(a[k]) for a in valid])
        out['constructs'][k]={'mean':round(_mean(sc),2) if sc else None,'sd':round(math.sqrt(_var(sc)),2) if len(sc)>1 else None,
            'alpha':round(4/3*(1-sum(_var(c) for c in cols)/tv),3) if tv else None}
        out['items'][k]=[round(_mean(c),2) if c else None for c in cols]
    if len(valid)>=10:
        x=[_mean(a['X']) for a in valid]; y=[_mean(a['Y']) for a in valid]; z=[_mean(a['Z']) for a in valid]
        mx,mz=_mean(x),_mean(z); xc=[v-mx for v in x]; zc=[v-mz for v in z]
        out['h1']=ols([[1,a] for a in xc],y,['const','X'])
        out['h2']=ols([[1,a,b,a*b] for a,b in zip(xc,zc)],y,['const','X','Z','X×Z'])
        sx,sy=math.sqrt(_var(x)),math.sqrt(_var(y))
        if sx and sy: out['r_xy']=round(sum((a-mx)*(b-_mean(y)) for a,b in zip(x,y))/(len(x)-1)/(sx*sy),3)
    return out
def analyze():
    if not DB: return {'error':'DATABASE_URL not configured'}
    with db() as c:
        events=c.execute("SELECT platform,event_type,payload,created_at FROM events WHERE created_at >= now()-interval '24 hours' ORDER BY created_at DESC LIMIT 10000").fetchall()
        products=c.execute('SELECT name,price::float AS price,tags,description,stock FROM product_catalog ORDER BY name').fetchall()
        interactions=c.execute("SELECT comment,recommendation,platform,created_at FROM research_interactions WHERE created_at >= now()-interval '24 hours' ORDER BY created_at DESC LIMIT 3000").fetchall()
        surveys=c.execute('SELECT answers FROM trust_surveys ORDER BY id DESC LIMIT 5000').fetchall()
    now=hour(datetime.now(timezone.utc))
    tl={now-timedelta(hours=i):{'comments':0,'likes':0,'gifts':0,'shares':0,'follows':0,'viewers':0,'pos':0,'neg':0,'neu':0,'intent':0} for i in range(23,-1,-1)}
    counts=Counter(e['event_type'].lower() for e in events); platforms=Counter(e['platform'] for e in events)
    chats=[]; locations=Counter(); products_asked=Counter(); questions=Counter(); sentiments=Counter(); keywords=Counter()
    viewers=set(); vp={}; latest_view={}; likes=gifts=follows=shares=intent=0; has_dummy=False
    pstats={p['name']:{'mentions':0,'questions':0,'pos':0,'neg':0} for p in products}
    for e in events:
        p=e['payload'] or {}; typ=e['event_type'].lower(); b=tl.get(hour(e['created_at']))
        has_dummy=has_dummy or bool(p.get('dummy'))
        comment=safe_text(p.get('comment') or p.get('message') or p.get('text'))
        uid=p.get('viewer_hash') or p.get('viewer_code') or p.get('user_id') or p.get('username')
        if uid: viewers.add(str(uid))
        if typ in ('chat','comment','message') and comment:
            low=comment.lower(); s=sentiment(low); q=is_question(comment)
            chats.append({'platform':e['platform'],'comment':comment,'user':p.get('nickname') or p.get('username') or 'Anon','time':e['created_at'].isoformat(),'sentiment':s,'region':p.get('region') or ''})
            sentiments[s]+=1
            if q: questions[comment]+=1
            it=any(w in low for w in INTENT)
            if it: intent+=1
            if b:
                b['comments']+=1; b[s[:3]]+=1; b['intent']+=it
            for pr in products:
                if pr['name'].lower() in low:
                    products_asked[pr['name']]+=1; st=pstats[pr['name']]; st['mentions']+=1; st['questions']+=q
                    if s=='positive': st['pos']+=1
                    elif s=='negative': st['neg']+=1
            for w in re.findall(r'[a-zA-ZÀ-ÿ]{3,}',low):
                if w not in STOP: keywords[w]+=1
        loc=p.get('country') or p.get('location_country') or p.get('region')
        if loc: locations[str(loc)]+=1
        if typ in ('viewer_count','roomuserseq','viewers'):
            v=int(p.get('viewer_count') or p.get('viewerCount') or p.get('count') or 0)
            latest_view.setdefault(e['platform'],v)
            if b: k=(hour(e['created_at']),e['platform']); vp[k]=max(vp.get(k,0),v)
        if 'like' in typ:
            n=int(p.get('count') or p.get('like_count') or p.get('totalLikes') or 1); likes+=n
            if b: b['likes']+=n
        for key,word in (('gifts','gift'),('follows','follow'),('shares','share')):
            if word in typ and b: b[key]+=1
        if 'gift' in typ: gifts+=1
        if 'follow' in typ: follows+=1
        if 'share' in typ: shares+=1
    for (h,_),v in vp.items(): tl[h]['viewers']+=v
    explained=0; recent=[]
    for it in interactions:
        cmt=decode(it['comment']); rec=it['recommendation'] or {}
        for pr in products:
            if pr['name'].lower() in cmt.lower(): products_asked[pr['name']]+=1
        if '?' in cmt: questions[cmt]+=1
        if rec.get('reasons'): explained+=1
        if len(recent)<25:
            recent.append({'comment':cmt,'platform':it['platform'],'time':it['created_at'].isoformat(),
              'product':(rec.get('product') or {}).get('name'),'reasons':rec.get('reasons') or [],'score':rec.get('score')})
    catalog=[{**p,'category':(p['tags'] or ['-'])[0],**pstats[p['name']]} for p in products]
    return {'events':len(events),'chat_count':len(chats),'unique_users_proxy':len(viewers),'viewer_count_latest':sum(latest_view.values()),
      'likes':likes,'gifts':gifts,'follows':follows,'shares':shares,'intent_comments':intent,'platforms':platforms,
      'product_interest':products_asked.most_common(12),'questions':questions.most_common(12),'keywords':keywords.most_common(20),
      'locations':locations.most_common(15),'sentiment':sentiments,'recent_comments':chats[:60],'event_types':counts,'catalog':catalog,
      'interactions':len(interactions),'explained':explained,'recent_interactions':recent,
      'survey':survey_stats(surveys),
      'timeline':[{'t':k.isoformat(),**v} for k,v in sorted(tl.items())],'has_dummy':has_dummy,
      'updated':datetime.now(timezone.utc).isoformat()}
# ---------- Akun live, Copilot, Overlay (tulis hanya dari origin yang sama)
UNAME=re.compile(r'^[A-Za-z0-9._]{2,24}$')
def cfg_get(c,k,d=None):
    r=c.execute('SELECT value FROM live_config WHERE key=%s',(k,)).fetchone(); return (r or {}).get('value') or d
def cfg_set(c,k,v): c.execute("INSERT INTO live_config(key,value,updated_at) VALUES(%s,%s,now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(k,json.dumps(v)))
@app.on_event('startup')
def _init():
    try:
        with db() as c: c.execute("CREATE TABLE IF NOT EXISTS live_config(key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    except Exception as e: print('live_config init deferred:',e)
def same_origin(req:Request):
    o=req.headers.get('origin') or req.headers.get('referer') or ''
    if req.headers.get('x-requested-with')!='liveai' or (o and req.headers.get('host','') not in o): raise HTTPException(403,'forbidden')
@app.get('/api/live/config')
def live_cfg():
    with db() as c: return {'tiktok':cfg_get(c,'tiktok',{}),'tiktok_status':cfg_get(c,'tiktok_status',{}),'shopee':cfg_get(c,'shopee',{})}
@app.post('/api/live/config')
async def live_cfg_set(req:Request):
    same_origin(req); b=await req.json(); plat=b.get('platform'); u=str(b.get('username') or '').strip().lstrip('@')
    if plat not in ('tiktok','shopee') or (u and not UNAME.match(u)): raise HTTPException(400,'username tidak valid')
    with db() as c: cfg_set(c,plat,{'username':u,'enabled':bool(b.get('enabled')) and bool(u)})
    return live_cfg()
INTENTS=[('harga',['harga','berapa','price']),('stok',['ready','stok','stock','ada gak','masih']),('ukuran',['size','ukuran','xl',' l ',' m ']),
  ('warna',['warna','color','hitam','putih','navy']),('cod',['cod','bayar']),('promo',['promo','diskon','voucher']),('rekomendasi',['cari','rekomendasi','budget','cocok','bagus buat'])]
def _intent(low): return next((k for k,ws in INTENTS if any(w in f' {low} ' for w in ws)),None)
def _rp(v): return 'Rp '+f'{int(v):,}'.replace(',','.') if v is not None else '-'
def copilot_items(limit=25):
    with db() as c:
        rows=c.execute("SELECT platform,payload,created_at FROM events WHERE event_type IN ('comment','chat','message') ORDER BY id DESC LIMIT 300").fetchall()
        prods=c.execute('SELECT name,price::float AS price,tags,description,stock FROM product_catalog').fetchall()
    out=[]
    for r in rows:
        p=r['payload'] or {}; cm=safe_text(p.get('comment') or p.get('message') or p.get('text')); low=cm.lower(); it=_intent(low)
        if not it: continue
        nick=p.get('nickname') or p.get('username') or 'kak'
        prod=next((x for x in prods if x['name'].lower() in low),None); reasons=[]
        if not prod:
            m=re.search(r'(?:budget|harga|di bawah|under)\s*(?:rp)?\s*([0-9][0-9.,]*)',low); bud=float(re.sub(r'[.,]','',m.group(1))) if m else None
            best=(0,None)
            for x in prods:
                sc=sum(2 for t in (x['tags'] or []) if t!='dummy' and t in low)+(2 if bud and x['price'] and x['price']<=bud else 0)
                if sc>best[0]: best=(sc,x)
            prod=best[1]
            if prod:
                reasons=[f'Kata kunci cocok: {t}' for t in (prod['tags'] or []) if t!='dummy' and t in low]+([f'Harga {_rp(prod["price"])} sesuai budget {_rp(bud)}'] if bud and prod['price'] and prod['price']<=bud else [])
        n=f'Kak {nick}'; pn=prod['name'] if prod else 'produknya'
        d={'harga':f"{n}, {pn} harganya {_rp(prod['price']) if prod else 'ada di keranjang kuning'} ya.",
           'stok':f"{n}, {pn} stoknya {prod['stock'] if prod else 'bisa dicek di keranjang'} ya, langsung checkout aja.",
           'ukuran':f"{n}, ukuran {pn} bisa dicek di pilihan varian; sebutkan ukuran yang dicari, nanti kami bantu cek.",
           'warna':f"{n}, warna {pn} bisa dilihat di pilihan varian ya.",
           'cod':f"{n}, metode COD mengikuti ketersediaan di halaman checkout ya.",
           'promo':f"{n}, cek voucher toko di keranjang kuning sebelum checkout ya.",
           'rekomendasi':(f"{n}, rekomendasi kami {pn} ({_rp(prod['price'])}). Alasannya: "+'; '.join(reasons or ['sesuai kebutuhan yang disebut'])+'. (Rekomendasi dibantu AI)') if prod else f"{n}, boleh sebutkan kebutuhan dan budgetnya?"}[it]
        out.append({'platform':r['platform'],'user':nick,'comment':cm,'time':r['created_at'].isoformat(),'intent':it,'draft':d,
          'product':({'name':prod['name'],'price':prod['price'],'stock':prod['stock'],'desc':safe_text(prod['description']).replace('[DUMMY] ','')} if prod else None),'reasons':reasons})
        if len(out)>=limit: break
    return out
@app.get('/api/copilot')
def copilot(): return JSONResponse(copilot_items())
@app.get('/api/overlay')
def overlay_get():
    with db() as c: return cfg_get(c,'overlay',{'visible':False})
@app.post('/api/overlay')
async def overlay_set(req:Request):
    same_origin(req); b=await req.json(); pr=b.get('product') or {}
    v={'visible':bool(b.get('visible')),'product':{'name':safe_text(pr.get('name'))[:80],'price':pr.get('price') if isinstance(pr.get('price'),(int,float)) else None,'desc':safe_text(pr.get('desc'))[:160]},
       'reasons':[safe_text(x)[:120] for x in (b.get('reasons') or [])][:4]}
    with db() as c: cfg_set(c,'overlay',v)
    return v
@app.get('/overlay',response_class=HTMLResponse)
def overlay_page(): return HTMLResponse(OVERLAY)
OVERLAY=r"""<!doctype html><html><head><meta charset="utf-8"><title>Overlay</title><style>
html,body{margin:0;background:transparent;font-family:Inter,system-ui,Segoe UI,Arial}#c{position:fixed;left:24px;bottom:24px;width:420px;opacity:0;transform:translateY(20px);transition:.4s}
#c.on{opacity:1;transform:none}.k{background:linear-gradient(160deg,#172554ee,#0b1730ee);color:#fff;border:1px solid #2563eb;border-radius:18px;padding:16px;box-shadow:0 10px 40px #0008}
.ai{display:inline-block;background:#2563eb;border-radius:20px;padding:3px 10px;font-size:12px;font-weight:700;margin-bottom:8px}.n{font-size:22px;font-weight:800}.p{color:#67e8f9;font-size:20px;font-weight:800;margin:2px 0 6px}
.d{color:#cbd5e1;font-size:13px;margin-bottom:8px}ul{margin:0;padding-left:18px;font-size:14px}li{margin:3px 0}.w{font-size:12px;color:#93c5fd;margin-bottom:4px;font-weight:700}</style></head><body>
<div id="c"><div class="k"><span class="ai">✦ Rekomendasi dibantu AI</span><div class="n" id="n"></div><div class="p" id="p"></div><div class="d" id="d"></div><div class="w">Kenapa direkomendasikan?</div><ul id="r"></ul></div></div>
<script>const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function t(){try{const v=await (await fetch('api/overlay',{cache:'no-store'})).json();const c=document.getElementById('c');if(!v.visible){c.className='';return}
document.getElementById('n').textContent=v.product.name;document.getElementById('p').textContent=v.product.price!=null?'Rp '+Math.round(v.product.price).toLocaleString('id-ID'):'';
document.getElementById('d').textContent=v.product.desc||'';document.getElementById('r').innerHTML=(v.reasons.length?v.reasons:['Sesuai komentar penonton']).map(x=>'<li>'+e(x)+'</li>').join('');c.className='on'}catch(_){}}
t();setInterval(t,2000)</script></body></html>"""
@app.get('/api/survey.csv')
def survey_csv():
    with db() as c:
        rows=c.execute('SELECT respondent_code,answers,created_at FROM trust_surveys ORDER BY id').fetchall()
    buf=io.StringIO(); w=csv.writer(buf)
    w.writerow(['respondent_code','created_at','version','eligible','age18','watched3m','seen_ai',*[f'{k}{i}' for k in 'XYZ' for i in range(1,5)],'age_range','platform','freq','duration_s','dummy'])
    for r in rows:
        a=r['answers']
        if not isinstance(a,dict) or not a.get('v'): continue
        sc=a.get('screen') or {}; pf=a.get('profile') or {}
        w.writerow([r['respondent_code'],r['created_at'].isoformat(),a.get('v'),int(bool(a.get('eligible'))),int(bool(sc.get('age18'))),int(bool(sc.get('watched3m'))),sc.get('seen_ai'),
            *[(a.get(k) or ['']*4)[i] for k in 'XYZ' for i in range(4)],pf.get('age_range') or '',pf.get('platform') or '',pf.get('freq') or '',a.get('duration_s'),int(bool(a.get('dummy')))])
    return Response('﻿'+buf.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="kuesioner_xyz.csv"'})
@app.get('/api/analytics')
def data(): return JSONResponse(analyze())
@app.get('/',response_class=HTMLResponse)
def dashboard():
 return HTMLResponse(HTML.replace('__API__','/api/analytics'))
HTML=r'''<!DOCTYPE html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Live AI Dashboard</title><style>
:root{--bg:#0b1220;--bg2:#0f172a;--card:#111c33;--card2:#16233f;--line:#22314d;--txt:#e6edf7;--muted:#94a3b8;--pur:#3b82f6;--pur2:#2563eb;--teal:#22d3ee;--green:#22c55e;--red:#f43f5e;--amber:#f59e0b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#1e3a8a40,transparent),var(--bg);color:var(--txt);font:14px Inter,system-ui,Segoe UI,Arial;min-height:100vh}
a{color:inherit;text-decoration:none}button{font:inherit;cursor:pointer}
nav.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:18px;padding:0 3vw;height:64px;background:linear-gradient(90deg,#0f1b33,#13264a);border-bottom:1px solid var(--line);box-shadow:0 4px 20px #0006}
.brand{display:flex;align-items:center;gap:10px;min-width:max-content}.brand b{font-size:20px;letter-spacing:.5px}.brand small{display:block;color:var(--muted);font-size:11px}
.menu{display:flex;align-items:stretch;height:100%;overflow-x:auto;scrollbar-width:none;flex:1}.menu::-webkit-scrollbar{display:none}
.menu a,.dd>button{display:flex;align-items:center;gap:8px;padding:0 16px;color:#cbd5e1;white-space:nowrap;background:none;border:0;height:100%}
.menu a:hover,.dd>button:hover{background:#ffffff10}.menu a.on{background:linear-gradient(180deg,#2563eb,#1d4ed8);color:#fff}
.menu svg,.ic svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.dd{position:relative}.dd .list{display:none;position:fixed;min-width:190px;background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:6px;box-shadow:0 10px 30px #0008}
.dd.open .list{display:block}.dd .list a,.dd .list button{display:block;width:100%;text-align:left;padding:9px 12px;border-radius:7px;height:auto;color:var(--txt);background:none;border:0}.dd .list a:hover,.dd .list button:hover{background:#ffffff12}
.right{display:flex;gap:10px;align-items:center;min-width:max-content}
.pill{display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border:1px solid var(--line);border-radius:10px;background:#ffffff08;color:#cbd5e1;font-size:13px}
.pill.ok{color:#4ade80;border-color:#14532d;background:#052e1655}.pill.bad{color:#fda4af;border-color:#7f1d1d}.pill.demo{color:#fcd34d;border-color:#78350f;background:#451a0355}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor}
main{padding:22px 3vw 10px;max-width:1600px;margin:auto}.view{display:none}.view.on{display:block}
.head h1{margin:0;font-size:28px}.head p{margin:4px 0 18px;color:var(--muted)}
.card{background:linear-gradient(180deg,var(--card),var(--bg2));border:1px solid var(--line);border-radius:16px;padding:18px}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.g3{display:grid;grid-template-columns:320px 1fr 340px;gap:14px;margin-top:14px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:1200px){.g4{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:1fr 1fr}.g3>.wide{grid-column:1/-1;order:-1}}
@media(max-width:1100px){.right .pill:not(.ok):not(.demo){display:none}}
@media(max-width:760px){.g4,.g3,.g2{grid-template-columns:1fr}nav.top{gap:10px}.brand small,.right .pill:not(.ok){display:none}}
.kpi{display:flex;gap:14px;align-items:flex-start;position:relative;overflow:hidden}.ic{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;flex:none}
.ic.p{background:#2563eb33;color:#93c5fd}.ic.t{background:#14b8a633;color:#67e8f9}.ic.b{background:#3b82f633;color:#93c5fd}.ic svg{width:24px;height:24px}
.kpi .lab{color:#cbd5e1;font-size:14px}.kpi .val{font-size:30px;font-weight:750;margin:4px 0}.kpi .val small{font-size:15px;color:var(--muted);font-weight:500}
.delta{font-size:13px}.up{color:#4ade80}.down{color:#fb7185}.flat{color:var(--muted)}.spark{position:absolute;right:14px;top:30px;width:90px;height:40px}
h2{font-size:17px;margin:0 0 14px;display:flex;align-items:center;gap:8px;justify-content:space-between}h2 .l{display:flex;gap:8px;align-items:center}
.muted{color:var(--muted)}.small{font-size:12px}
.live{position:relative;min-height:380px;padding:0;overflow:hidden;background:radial-gradient(circle at 50% 35%,#3b82f655,transparent 60%),linear-gradient(160deg,#172554,#0b1730)}
.live .tag{position:absolute;top:14px;left:14px;display:flex;gap:8px}.badge{padding:5px 10px;border-radius:8px;font-weight:700;font-size:13px}.badge.r{background:var(--red)}.badge.d{background:#0008}
.live .hero{position:absolute;inset:50px 20px 200px;display:grid;place-items:center;text-align:center}.live .hero .big{width:72px;height:72px;margin:auto;border-radius:20px;display:grid;place-items:center;font-size:28px;font-weight:800;background:linear-gradient(135deg,#60a5fa,#2563eb);box-shadow:0 10px 40px #3b82f680}
.live .float{position:absolute;left:12px;right:12px;bottom:76px;display:flex;flex-direction:column;gap:5px}.live .float div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:#0007;border-radius:10px;padding:6px 10px;font-size:12px;animation:fl .5s ease}
@keyframes fl{from{opacity:0;transform:translateY(8px)}}
.live .bar{position:absolute;left:12px;right:12px;bottom:12px;display:flex;align-items:center;gap:10px;background:#ffffffe6;color:#0f172a;border-radius:12px;padding:10px}
.thumb{width:42px;height:42px;border-radius:9px;display:grid;place-items:center;font-weight:800;color:#fff;flex:none}
.cartbtn{margin-left:auto;background:var(--pur2);color:#fff;border:0;border-radius:9px;width:38px;height:38px;display:grid;place-items:center}
.chartwrap{position:relative}.tip{position:absolute;pointer-events:none;background:#0b1220f0;border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:12px;display:none;white-space:nowrap}
.legend{display:flex;gap:14px;font-size:12px;color:#cbd5e1;font-weight:400}.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
svg text{fill:var(--muted);font-size:11px}
.copilot .msg{background:linear-gradient(135deg,#1e40afaa,#172554);border:1px solid #2563eb66;border-radius:14px;padding:14px;margin-bottom:10px;line-height:1.5}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.chip{padding:6px 12px;border:1px solid var(--line);border-radius:9px;background:#ffffff08;font-size:13px}
.lbtn{background:#2563eb33;color:#bfdbfe;border:1px solid #2563eb66;border-radius:8px;padding:5px 10px;font-size:12px}
table{width:100%;border-collapse:collapse}th{color:#cbd5e1;font-weight:600;font-size:13px;text-align:left;padding:10px;border-bottom:1px solid var(--line)}td{padding:10px;border-bottom:1px solid #22314d80;vertical-align:middle}
.pname{display:flex;gap:10px;align-items:center}.pname small{display:block;color:var(--muted)}
.gpill{display:inline-block;padding:4px 10px;border-radius:8px;background:#05966933;color:#4ade80;font-weight:600;font-size:13px}.gpill.n{background:#e11d4833;color:#fb7185}.gpill.z{background:#ffffff10;color:var(--muted)}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}.tile{display:flex;gap:12px;align-items:flex-start;background:#ffffff06;border:1px solid var(--line);border-radius:12px;padding:14px;position:relative;overflow:hidden}
.tile .val{font-size:24px;font-weight:750;margin:2px 0}.tile .spark{top:auto;bottom:10px;width:70px;height:30px}
.barrow{margin:10px 0}.barlabel{display:flex;justify-content:space-between;margin-bottom:5px;gap:10px}.barbg{height:8px;background:#22314d;border-radius:8px;overflow:hidden}.fill{height:100%;border-radius:8px;background:linear-gradient(90deg,var(--pur2),var(--pur))}
.feed{max-height:520px;overflow:auto}.comment{padding:10px;border-bottom:1px solid #22314d80}.tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
input,select{background:#0b1220;color:var(--txt);border:1px solid var(--line);padding:9px 11px;border-radius:9px}
.btn{background:linear-gradient(180deg,#3b82f6,#2563eb);color:#fff;border:0;border-radius:9px;padding:9px 14px}.btn.g{background:#ffffff10;border:1px solid var(--line)}
.s{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.s.positive{background:var(--green)}.s.negative{background:var(--red)}.s.neutral{background:#94a3b8}
.chip{display:inline-block;padding:2px 8px;border-radius:7px;background:#2563eb33;color:#bfdbfe;font-size:12px}.donutwrap{display:flex;gap:20px;align-items:center;flex-wrap:wrap}.empty{color:var(--muted);padding:8px 0}
.set{display:grid;grid-template-columns:220px 1fr;gap:12px 20px;align-items:center}@media(max-width:760px){.set{grid-template-columns:1fr}}
.lang{display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}.lang button{background:none;border:0;color:var(--muted);padding:7px 10px;font-weight:700;font-size:12px}.lang button.on{background:var(--pur2);color:#fff}
footer{padding:18px 3vw 26px;color:var(--muted);font-size:12px;text-align:center}
</style></head><body>
<nav class="top"><a class="brand" href="#overview"><svg width="36" height="36" viewBox="0 0 36 36"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#60a5fa"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient></defs><path d="M8 5l23 13L8 31z" fill="url(#lg)"/><path d="M13 12l11 6-11 6z" fill="#0b1220"/></svg><span><b>LIVE AI</b><small>Live Commerce AI Copilot</small></span></a>
<div class="menu" id="menu">
<a href="#overview" data-v="overview"><svg viewBox="0 0 24 24"><path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"/></svg><span data-i="nav_overview"></span></a>
<a href="#live" data-v="live"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2"/><path d="M8 8a6 6 0 000 8M16 8a6 6 0 010 8M5 5a10 10 0 000 14M19 5a10 10 0 010 14"/></svg><span data-i="nav_live"></span></a>
<a href="#products" data-v="products"><svg viewBox="0 0 24 24"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/></svg><span data-i="nav_products"></span></a>
<a href="#insights" data-v="insights"><svg viewBox="0 0 24 24"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg><span data-i="nav_insights"></span></a>
<a href="#copilot" data-v="copilot"><svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8"/></svg><span data-i="nav_copilot"></span></a>
<a href="#research" data-v="research"><svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3"/></svg><span data-i="nav_research"></span></a>
<div class="dd" id="dd"><button onclick="toggleDD(event)"><svg viewBox="0 0 24 24"><path d="M4 17v2a1 1 0 001 1h14a1 1 0 001-1v-2M12 4v12M7 11l5 5 5-5"/></svg>Data ▾</button><div class="list"><button onclick="downloadJSON()">Export JSON</button><button onclick="downloadCSV()" data-i="exp_comments"></button><button onclick="downloadProducts()" data-i="exp_products"></button><a href="#" onclick="openResearch();return false" data-i="open_mvp"></a></div></div>
<a href="#settings" data-v="settings"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/></svg><span data-i="nav_settings"></span></a>
</div>
<div class="right"><div class="lang" role="group" aria-label="Language"><button data-l="id" onclick="setLang('id')">ID</button><button data-l="en" onclick="setLang('en')">EN</button></div><span class="pill demo" id="demo" style="display:none">DEMO DATA</span><span class="pill">🗓 <span data-i="period"></span></span><span class="pill" id="status"><span class="dot"></span>Loading</span></div></nav>
<main>
<section class="view" id="v-overview"><div class="head"><h1>Live Commerce Intelligence</h1><p>AI Copilot for Live Commerce • XAI • AI Transparency • Consumer Trust</p></div>
<div class="g4" id="kpis"></div>
<div class="g3"><div class="card live" id="livecard"></div>
<div class="card wide"><h2><span class="l" data-i="perf_title"></span><span class="legend"><span><i style="background:var(--pur)"></i><span data-i="engagement"></span></span><span><i style="background:var(--teal)"></i><span data-i="trust_signal"></span></span></span></h2><div class="chartwrap" id="perf"></div></div>
<div class="card copilot"><h2><span class="l"><span style="color:#93c5fd">✦</span> AI Copilot</span><button class="lbtn" onclick="go('insights')">Live Insight</button></h2><div id="copilot"></div><div class="chips"><span class="chip">XAI</span><span class="chip">AI Transparency</span><span class="chip">Rule-based</span></div></div></div>
<div class="g2"><div class="card"><h2><span class="l">🛒 <span data-i="rank_title"></span></span><a class="lbtn" href="#products" data-i="view_all"></a></h2><div id="ranking"></div></div>
<div class="card"><h2><span class="l">⚗ <span data-i="rmon_title"></span></span><a class="lbtn" href="#research" data-i="detail"></a></h2><div class="tiles" id="rmon"></div></div></div></section>

<section class="view" id="v-live"><div class="head"><h1 data-i="nav_live"></h1><p data-i="live_sub"></p></div>
<div class="g4" id="livekpis"></div>
<div class="card" style="margin-top:14px"><h2><span class="l" data-i="trend_title"></span><span class="legend"><span><i style="background:var(--pur)"></i><span data-i="comments_hr"></span></span><span><i style="background:var(--amber)"></i><span data-i="viewers_peak"></span></span></span></h2><div class="chartwrap" id="trend"></div></div>
<div class="g2"><div class="card"><h2 data-i="platform_mix"></h2><div id="platDonut"></div></div><div class="card"><h2 data-i="regions"></h2><div id="locations"></div><p class="muted small" data-i="regions_note"></p></div></div>
<div class="card" style="margin-top:14px"><h2>Live Comment Feed</h2><div class="tools"><input id="filter" data-ip="search_comment" oninput="renderFeed()"><select id="platformFilter" onchange="renderFeed()"><option value="" data-i="all_platforms"></option><option value="tiktok">TikTok</option><option value="shopee">Shopee</option><option value="instagram">Instagram</option><option value="manual">Manual</option></select><select id="sentFilter" onchange="renderFeed()"><option value="" data-i="all_sentiment"></option><option value="positive" data-i="positive"></option><option value="neutral" data-i="neutral"></option><option value="negative" data-i="negative"></option></select></div><div class="feed" id="feed"></div></div></section>

<section class="view" id="v-products"><div class="head"><h1 data-i="nav_products"></h1><p data-i="prod_sub"></p></div>
<div class="card"><div class="tools"><input id="psearch" data-ip="search_product" oninput="renderProducts()"><select id="pcat" onchange="renderProducts()"><option value="" data-i="all_categories"></option></select><select id="psort" onchange="renderProducts()"><option value="mentions" data-i="sort_mentions"></option><option value="questions" data-i="sort_questions"></option><option value="pos" data-i="sort_pos"></option><option value="price" data-i="sort_price"></option><option value="name" data-i="sort_name"></option></select></div><div id="ptable" style="overflow-x:auto"></div></div>
<div class="card" style="margin-top:14px"><h2 data-i="most_mentioned"></h2><div id="products"></div></div></section>

<section class="view" id="v-insights"><div class="head"><h1 data-i="nav_insights"></h1><p data-i="ins_sub"></p></div>
<div class="card copilot"><h2><span class="l"><span style="color:#93c5fd">✦</span> <span data-i="copilot_rec"></span></span></h2><div id="copilotFull"></div></div>
<div class="g2"><div class="card"><h2 data-i="sent_mix"></h2><div id="sentDonut"></div><p class="muted small" data-i="heuristic"></p></div><div class="card"><h2 data-i="keywords"></h2><div id="keywords"></div></div></div>
<div class="g2"><div class="card"><h2 data-i="faq"></h2><div id="questions"></div></div><div class="card"><h2 data-i="event_types"></h2><div id="eventtypes"></div></div></div></section>

<section class="view" id="v-copilot"><div class="head"><h1 data-i="nav_copilot"></h1><p data-i="cp_sub"></p></div>
<div class="g2" style="margin-top:0"><div class="card"><h2 data-i="cp_conn"></h2><div id="cpstatus" class="muted">-</div><p class="small muted" data-i="cp_readonly"></p></div>
<div class="card"><h2 data-i="cp_ovl"></h2><p class="small muted" data-i="cp_ovl_help"></p><div class="tools"><input id="ovlurl" readonly style="flex:1;min-width:220px"><button class="btn g" onclick="copyText($('ovlurl').value)" data-i="copy"></button><button class="btn g" onclick="hideOverlay()" data-i="cp_hide"></button></div><div id="ovlnow" class="small muted"></div></div></div>
<div class="card" style="margin-top:14px"><h2 data-i="cp_queue"></h2><div class="feed" id="cplist"></div></div></section>
<section class="view" id="v-research"><div class="head"><h1 data-i="nav_research"></h1><p data-i="res_sub"></p></div>
<div class="tiles" id="rmon2" style="grid-template-columns:repeat(4,1fr)"></div>
<div class="card" style="margin-top:14px"><h2><span class="l" data-i="sv_title"></span><span style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" onclick="openSurvey()" data-i="sv_open"></button><a class="btn g" href="api/survey.csv" data-i="sv_csv"></a></span></h2><div id="svbox"></div></div>
<div class="g2"><div class="card"><h2><span class="l" data-i="recent_inter"></span><button class="btn" onclick="openResearch()" data-i="open_mvp"></button></h2><div class="feed" id="rinter"></div></div>
<div class="card"><h2 data-i="most_rec"></h2><div id="recprod"></div><p class="muted small" data-i="xai_note"></p></div></div></section>

<section class="view" id="v-settings"><div class="head"><h1 data-i="nav_settings"></h1><p data-i="set_sub"></p></div>
<div class="card"><div class="set">
<label data-i="set_lang"></label><select id="setLang" onchange="setLang(this.value)"><option value="id">Bahasa Indonesia</option><option value="en">English</option></select>
<label data-i="set_refresh"></label><select id="setRefresh" onchange="saveSet()"><option value="0" data-i="off"></option><option value="10" data-i="s10"></option><option value="15" data-i="s15"></option><option value="30" data-i="s30"></option><option value="60" data-i="s60"></option></select>
<label data-i="set_home"></label><select id="setHome" onchange="saveSet()"><option value="overview" data-i="nav_overview"></option><option value="live" data-i="nav_live"></option><option value="products" data-i="nav_products"></option><option value="insights" data-i="nav_insights"></option><option value="research" data-i="nav_research"></option></select>
<label data-i="set_port"></label><input id="setPort" type="number" min="1" max="65535" onchange="saveSet()">
<label>Data</label><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" onclick="load()" data-i="refresh_now"></button><button class="btn g" onclick="downloadJSON()">Export JSON</button><button class="btn g" onclick="downloadCSV()" data-i="exp_comments"></button><button class="btn g" onclick="downloadProducts()" data-i="exp_products"></button></div>
<label>Info</label><div class="muted" id="info">-</div>
</div></div><div class="card" style="margin-top:14px"><h2 data-i="acc_title"></h2><p class="small" style="color:#fcd34d" data-i="acc_warn"></p><div class="set">
<label>TikTok</label><div class="tools" style="margin:0"><input id="ttuser" placeholder="@username" maxlength="25" autocomplete="off"><label class="small"><input type="checkbox" id="tton"> <span data-i="acc_on"></span></label><button class="btn" onclick="saveAcc('tiktok')" data-i="save"></button></div>
<label data-i="acc_status"></label><div id="ttstatus" class="muted">-</div>
<label>Shopee</label><div class="tools" style="margin:0"><input id="spuser" placeholder="username toko" maxlength="25" autocomplete="off"><button class="btn g" onclick="saveAcc('shopee')" data-i="save"></button></div>
<label></label><div class="small muted" data-i="acc_shopee"></div>
</div></div></section>
</main>
<footer data-i="footer"></footer>
<div class="tip" id="tip"></div>
<script>
const API='__API__';let latest=null,timer=null;
const $=id=>document.getElementById(id);
const I18N={id:{nav_overview:'Ringkasan',nav_live:'Sesi Live',nav_products:'Produk',nav_insights:'Insight AI',nav_research:'Lab Riset',nav_settings:'Pengaturan',
exp_comments:'Export CSV komentar',exp_products:'Export CSV produk',open_mvp:'Buka Research MVP ↗',period:'24 jam terakhir',perf_title:'Performa Live & Sentimen Komentar',engagement:'Tingkat Engagement',trust_signal:'Sentimen Positif',
rank_title:'Peringkat Produk (Sesi Live)',view_all:'Lihat Semua →',rmon_title:'Monitor Riset (Tesis)',detail:'Detail →',live_sub:'Aktivitas penonton, engagement, dan komentar dari event yang diterima.',
trend_title:'Tren Aktivitas 24 Jam',comments_hr:'Komentar/jam',viewers_peak:'Penonton (puncak)',platform_mix:'Komposisi Platform',regions:'Distribusi Wilayah',regions_note:'Hanya dari field wilayah yang dikirim sumber event; tidak disimpulkan dari username.',
search_comment:'Cari komentar / user...',all_platforms:'Semua platform',all_sentiment:'Semua sentimen',positive:'Positif',neutral:'Netral',negative:'Negatif',
prod_sub:'Katalog produk dan minat penonton per produk (disebut, ditanya, sentimen).',search_product:'Cari produk...',all_categories:'Semua kategori',sort_mentions:'Urut: paling disebut',sort_questions:'Urut: paling ditanya',sort_pos:'Urut: sentimen positif',sort_price:'Urut: harga',sort_name:'Urut: nama',most_mentioned:'Produk Paling Dicari / Disebut',
ins_sub:'Ringkasan otomatis berbasis aturan dari komentar & interaksi (bukan model AI tervalidasi).',copilot_rec:'Rekomendasi Copilot',sent_mix:'Komposisi Sentimen',heuristic:'Heuristik kata kunci sederhana.',keywords:'Topik & Keyword Penonton',faq:'Pertanyaan / FAQ Berulang',event_types:'Platform & Jenis Event',
res_sub:'Monitor data penelitian tesis: XAI, transparansi rekomendasi, dan kepercayaan konsumen.',recent_inter:'Interaksi Rekomendasi Terbaru',most_rec:'Produk Paling Direkomendasikan',xai_note:'Penjelasan (XAI) tersimpan per interaksi: alasan, data yang dipakai, dan batasan sistem.',
set_sub:'Preferensi tampilan dashboard (tersimpan di browser ini saja).',set_lang:'Bahasa',set_refresh:'Auto refresh',set_home:'Halaman awal',set_port:'Port Research MVP (API)',off:'Mati',s10:'10 detik',s15:'15 detik',s30:'30 detik',s60:'60 detik',refresh_now:'Refresh sekarang',
footer:'Dashboard prototipe • Analytics hanya dari event yang diterima & disimpan • Lokasi tidak ditebak tanpa data platform yang sah • Data bertanda DEMO adalah dummy untuk uji tampilan.',
vs_prev:'vs 12 jam sebelumnya',last12:'12 jam terakhir',nodata:'Belum ada data yang dapat dianalisis.',na:'Belum tersedia.',question:'Pertanyaan',count:'Jumlah',
k_viewers:'Penonton Live',k_eng:'Tingkat Engagement',k_intent:'Niat Beli',k_trust:'Sentimen Komentar Positif',k_comments:'Komentar (24j)',k_likes:'Likes (perkiraan)',k_gifts:'Gift',k_follows:'Follower Baru',
c_comments:'Komentar',c_viewers:'Penonton',no_product:'Belum ada produk',spotlight:'produk paling disorot',see_product:'Lihat produk',no_mention:'Belum ada produk yang disebut.',
th_product:'Produk',th_share:'Porsi Disebut',th_trust:'Dampak Trust',th_cat:'Kategori',th_price:'Harga',th_stock:'Stok',th_mentions:'Disebut',th_pos:'Sentimen +',
t_cov:'Cakupan Penjelasan XAI',t_cov_sub:'{a} dari {b} interaksi',t_inter:'Interaksi Riset',t_survey:'Consumer Trust (Y) Kuesioner',t_likert:'skala Likert 1–5',t_sample:'Responden Valid',t_consent:'dengan persetujuan',nav_copilot:'Copilot Live',cp_sub:'Draf jawaban & rekomendasi untuk host. Host yang memutuskan dan menyampaikan sendiri — tidak ada auto-comment.',cp_conn:'Status Connector TikTok',cp_readonly:'Hanya membaca (read-only): tidak login, tidak mengirim komentar/like/follow.',cp_ovl:'Overlay Live (OBS / TikTok LIVE Studio)',cp_ovl_help:'Tambahkan URL ini sebagai Browser Source (1920×1080). Latar transparan.',cp_hide:'Sembunyikan overlay',cp_queue:'Antrian Komentar Penting',cp_show:'Tampilkan di overlay',cp_showing:'Sedang tampil',cp_hidden:'Overlay tersembunyi',cp_empty:'Belum ada komentar yang perlu dijawab.',copy:'Salin',save:'Simpan',saved:'Tersimpan.',acc_title:'Akun Live',acc_warn:'⚠ Isi USERNAME saja. Jangan pernah memasukkan password atau kode OTP.',acc_on:'Aktifkan connector',acc_status:'Status',acc_shopee:'Membaca live Shopee belum didukung: butuh akses partner resmi Shopee Open Platform. Username hanya disimpan.',acc_bad:'Username tidak valid (2–24 huruf/angka/titik/garis bawah).',sv_title:'Hasil Kuesioner (X · Y · Z)',sv_open:'Buka Kuesioner ↗',sv_csv:'Export CSV (SPSS/SmartPLS)',sv_empty:'Belum ada jawaban kuesioner.',sv_valid:'Responden Valid',sv_of:'{a} valid dari {b} isian',sv_out:'{n} tidak lolos penyaring',sv_need:'Butuh minimal 10 responden valid.',sv_sig:'indikatif signifikan',sv_ns:'belum signifikan',sv_hyp:'Uji Hipotesis (indikatif)',sv_path:'Jalur',sv_items:'Rata-rata per Item',sv_note:'Regresi OLS dengan X dan Z di-center (moderasi X×Z). |t| ≥ 1,96 ≈ signifikan 5% untuk sampel besar. Analisis final tetap di SPSS/SmartPLS sesuai arahan pembimbing. α ≥ 0,70 = reliabel.',sv_dummy:'Berisi jawaban DUMMY untuk uji tampilan — hapus sebelum pengumpulan data asli; jangan dipakai di BAB IV.',
no_match:'tidak ada kecocokan',score:'skor',no_inter:'Belum ada interaksi.',no_prod_match:'Tidak ada produk yang cocok.',no_comment_match:'Tidak ada komentar yang cocok.',connected:'Terhubung',api_down:'API tidak tersedia',
info:'{e} event • {u} ID unik • {p} produk • {s} share • update {t}',has_dummy:'berisi data dummy',no_insight:'Belum ada data untuk membuat insight.',
i_top:'<b>{n}</b> paling banyak disebut ({c}×). Sorot produk ini di awal sesi dan tampilkan alasan rekomendasinya secara jelas.',
i_q:'Pertanyaan terbanyak tentang <b>{n}</b> ({c} pertanyaan). Siapkan jawaban ukuran, harga, dan stok agar penonton tidak menunggu.',
i_trust:'Sentimen komentar positif {v}/100 (indikator operasional dari komentar, bukan variabel Y kuesioner).',i_neg:' Ada {c} komentar negatif — umumnya soal harga/kualitas; tanggapi dengan penjelasan atribut produk.',
i_peak:'Jam paling ramai: <b>{h}</b> ({c} komentar/jam). Jadwalkan live berikutnya di sekitar jam ini.',
i_xai:'{v}% rekomendasi menyertakan penjelasan (XAI). Penjelasan atribut produk yang jelas dapat memperkuat kepercayaan konsumen.'},
en:{nav_overview:'Overview',nav_live:'Live Sessions',nav_products:'Products',nav_insights:'AI Insights',nav_research:'Research Lab',nav_settings:'Settings',
exp_comments:'Export comments CSV',exp_products:'Export products CSV',open_mvp:'Open Research MVP ↗',period:'Last 24 hours',perf_title:'Live Performance & Comment Sentiment',engagement:'Engagement Rate',trust_signal:'Positive Sentiment',
rank_title:'Product Ranking (Live Session)',view_all:'View All →',rmon_title:'Research Monitor (Thesis)',detail:'Details →',live_sub:'Audience activity, engagement, and comments from received events.',
trend_title:'24-Hour Activity Trend',comments_hr:'Comments/hour',viewers_peak:'Viewers (peak)',platform_mix:'Platform Mix',regions:'Regional Distribution',regions_note:'Only from region fields sent by the event source; never inferred from usernames.',
search_comment:'Search comments / users...',all_platforms:'All platforms',all_sentiment:'All sentiment',positive:'Positive',neutral:'Neutral',negative:'Negative',
prod_sub:'Product catalog and audience interest per product (mentions, questions, sentiment).',search_product:'Search products...',all_categories:'All categories',sort_mentions:'Sort: most mentioned',sort_questions:'Sort: most asked',sort_pos:'Sort: positive sentiment',sort_price:'Sort: price',sort_name:'Sort: name',most_mentioned:'Most Searched / Mentioned Products',
ins_sub:'Rule-based automatic summary of comments & interactions (not a validated AI model).',copilot_rec:'Copilot Recommendations',sent_mix:'Sentiment Mix',heuristic:'Simple keyword heuristic.',keywords:'Audience Topics & Keywords',faq:'Recurring Questions / FAQ',event_types:'Platform & Event Types',
res_sub:'Thesis research monitor: XAI, recommendation transparency, and consumer trust.',recent_inter:'Latest Recommendation Interactions',most_rec:'Most Recommended Products',xai_note:'An explanation (XAI) is stored per interaction: reasons, data used, and system limitations.',
set_sub:'Dashboard display preferences (saved in this browser only).',set_lang:'Language',set_refresh:'Auto refresh',set_home:'Start page',set_port:'Research MVP (API) port',off:'Off',s10:'10 seconds',s15:'15 seconds',s30:'30 seconds',s60:'60 seconds',refresh_now:'Refresh now',
footer:'Prototype dashboard • Analytics only from received & stored events • Location is never guessed without valid platform data • Data marked DEMO is dummy data for display testing.',
vs_prev:'vs previous 12 hours',last12:'last 12 hours',nodata:'No data to analyze yet.',na:'Not available yet.',question:'Question',count:'Count',
k_viewers:'Live Viewers',k_eng:'Engagement Rate',k_intent:'Purchase Intent',k_trust:'Positive Comment Sentiment',k_comments:'Comments (24h)',k_likes:'Likes (approx)',k_gifts:'Gift Events',k_follows:'New Follows',
c_comments:'Comments',c_viewers:'Viewers',no_product:'No product yet',spotlight:'most highlighted product',see_product:'View products',no_mention:'No products mentioned yet.',
th_product:'Product',th_share:'Mention Share',th_trust:'Trust Impact',th_cat:'Category',th_price:'Price',th_stock:'Stock',th_mentions:'Mentions',th_pos:'Sentiment +',
t_cov:'XAI Explanation Coverage',t_cov_sub:'{a} of {b} interactions',t_inter:'Research Interactions',t_survey:'Consumer Trust (Y) Survey',t_likert:'Likert scale 1–5',t_sample:'Valid Respondents',t_consent:'with consent',nav_copilot:'Live Copilot',cp_sub:'Draft replies & recommendations for the host. The host decides and delivers them — no auto-comment.',cp_conn:'TikTok Connector Status',cp_readonly:'Read-only: no login, never sends comments/likes/follows.',cp_ovl:'Live Overlay (OBS / TikTok LIVE Studio)',cp_ovl_help:'Add this URL as a Browser Source (1920×1080). Transparent background.',cp_hide:'Hide overlay',cp_queue:'Important Comment Queue',cp_show:'Show on overlay',cp_showing:'Now showing',cp_hidden:'Overlay hidden',cp_empty:'No comments need a reply yet.',copy:'Copy',save:'Save',saved:'Saved.',acc_title:'Live Accounts',acc_warn:'⚠ Enter the USERNAME only. Never enter a password or OTP code.',acc_on:'Enable connector',acc_status:'Status',acc_shopee:'Reading Shopee live is not supported yet: requires official Shopee Open Platform partner access. Username is stored only.',acc_bad:'Invalid username (2–24 letters/digits/dot/underscore).',sv_title:'Questionnaire Results (X · Y · Z)',sv_open:'Open Questionnaire ↗',sv_csv:'Export CSV (SPSS/SmartPLS)',sv_empty:'No questionnaire responses yet.',sv_valid:'Valid Respondents',sv_of:'{a} valid of {b} submissions',sv_out:'{n} screened out',sv_need:'Needs at least 10 valid respondents.',sv_sig:'indicatively significant',sv_ns:'not significant',sv_hyp:'Hypothesis Test (indicative)',sv_path:'Path',sv_items:'Mean per Item',sv_note:'OLS regression with mean-centered X and Z (X×Z moderation). |t| ≥ 1.96 ≈ 5% significance for large samples. Final analysis in SPSS/SmartPLS as directed by the supervisor. α ≥ 0.70 = reliable.',sv_dummy:'Contains DUMMY responses for display testing — delete before real data collection; do not use in Chapter IV.',
no_match:'no match',score:'score',no_inter:'No interactions yet.',no_prod_match:'No matching products.',no_comment_match:'No matching comments.',connected:'Connected',api_down:'API unavailable',
info:'{e} events • {u} unique IDs • {p} products • {s} shares • updated {t}',has_dummy:'contains dummy data',no_insight:'Not enough data for insights yet.',
i_top:'<b>{n}</b> is the most mentioned product ({c}×). Feature it early in the session and show its recommendation reasons clearly.',
i_q:'Most questions are about <b>{n}</b> ({c} questions). Prepare answers on size, price, and stock so viewers do not wait.',
i_trust:'Positive comment sentiment {v}/100 (operational indicator from comments, not the questionnaire Y variable).',i_neg:' {c} negative comments — mostly about price/quality; respond by explaining product attributes.',
i_peak:'Busiest hour: <b>{h}</b> ({c} comments/hour). Schedule the next live around this time.',
i_xai:'{v}% of recommendations include an explanation (XAI). Clear explanations of product attributes can strengthen consumer trust.'}};
let LANG='id';try{LANG=localStorage.getItem('liveai-lang')||'id'}catch(e){}
function t(k,v){let s=(I18N[LANG]||I18N.id)[k]??I18N.id[k]??k;if(v)for(const x in v)s=s.replaceAll('{'+x+'}',v[x]);return s}
function applyLang(){document.documentElement.lang=LANG;document.querySelectorAll('[data-i]').forEach(e=>e.textContent=t(e.dataset.i));document.querySelectorAll('[data-ip]').forEach(e=>e.placeholder=t(e.dataset.ip));document.querySelectorAll('.lang button').forEach(b=>b.classList.toggle('on',b.dataset.l==LANG));const s=$('setLang');if(s)s.value=LANG}
function setLang(l){LANG=l;try{localStorage.setItem('liveai-lang',l)}catch(e){}applyLang();if(latest)render(latest);setStatus()}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const fmt=n=>Number(n||0).toLocaleString(LOC()),rp=n=>n==null?'-':'Rp '+fmt(Math.round(n)),pct=(a,b)=>b?a/b*100:0,hh=t=>String(new Date(t).getHours()).padStart(2,'0')+':00';
const HUES=[270,190,330,150,30,220,0,90];function hue(s){let h=0;for(const c of String(s))h=(h*31+c.charCodeAt(0))%997;return HUES[h%HUES.length]}
function thumb(name,size=42){const h=hue(name),ini=String(name).split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();return `<span class="thumb" style="width:${size}px;height:${size}px;background:linear-gradient(135deg,hsl(${h} 80% 65%),hsl(${h+30} 70% 45%))">${esc(ini)}</span>`}
const IC={live:'<circle cx="12" cy="12" r="2"/><path d="M8 8a6 6 0 000 8M16 8a6 6 0 010 8M5 5a10 10 0 000 14M19 5a10 10 0 010 14"/>',users:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M16 4.5a3.5 3.5 0 010 7M18 14a6 6 0 013.5 6"/>',cart:'<path d="M3 4h2l2.4 11h10.8L21 8H6.2"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',shield:'<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',layers:'<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',chat:'<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',heart:'<path d="M12 20s-7-4.5-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.5-7 10-7 10z"/>',gift:'<path d="M4 10h16v10H4zM3 7h18v3H3zM12 7v13M12 7c-2-4-6-3-5 0M12 7c2-4 6-3 5 0"/>',plus:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M19 8v6M16 11h6"/>',share:'<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 11l7.6-4M8.2 13l7.6 4"/>'};
const icon=(k,c='p')=>`<div class="ic ${c}"><svg viewBox="0 0 24 24">${IC[k]}</svg></div>`;
function spark(arr,color){arr=(arr||[]).map(Number);if(arr.length<2||!arr.some(x=>x))return '';const mx=Math.max(...arr),mn=Math.min(...arr),r=mx-mn||1,pts=arr.map((v,i)=>[i/(arr.length-1)*100,36-(v-mn)/r*32]);const id='g'+Math.random().toString(36).slice(2,7);return `<svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><path d="M${pts.map(p=>p.join(',')).join(' L')} L100,40 L0,40Z" fill="url(#${id})"/><polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="2.2" vector-effect="non-scaling-stroke"/></svg>`}
function delta(arr,unit='%',isPP=false){const a=arr.slice(0,12),b=arr.slice(12),sa=a.reduce((x,y)=>x+y,0),sb=b.reduce((x,y)=>x+y,0);let d;if(isPP){const ma=sa/(a.filter(x=>x).length||1),mb=sb/(b.filter(x=>x).length||1);d=mb-ma;return `<span class="delta ${d>0.05?'up':d<-0.05?'down':'flat'}">${d>=0?'↑':'↓'} ${Math.abs(d).toFixed(1)} ${unit}</span> <span class="muted small">${t('vs_prev')}</span>`}if(!sa)return `<span class="muted small">${t('last12')}</span>`;d=(sb-sa)/sa*100;return `<span class="delta ${d>0?'up':d<0?'down':'flat'}">${d>=0?'↑':'↓'} ${Math.abs(d).toFixed(0)}%</span> <span class="muted small">${t('vs_prev')}</span>`}
function kpi(ic,c,lab,val,sub,sp,col){return `<div class="card kpi">${icon(ic,c)}<div><div class="lab">${lab}</div><div class="val">${val}</div>${sub}</div>${sp?spark(sp,col):''}</div>`}
function tile(ic,c,lab,val,sub,sp,col){return `<div class="tile">${icon(ic,c)}<div><div class="lab">${lab}</div><div class="val">${val}</div>${sub||''}</div>${sp?spark(sp,col):''}</div>`}
function roll(tl,i,f){let a=0;for(let j=Math.max(0,i-2);j<=i;j++)a+=f(tl[j]);return a}
function series(d){const tl=d.timeline||[];const R=(num,den)=>tl.map((x,i)=>{const b=roll(tl,i,den);return b?roll(tl,i,num)/b*100:0});return{er:R(x=>x.comments+x.gifts+x.shares+x.follows,x=>x.viewers),tr:R(x=>x.pos,x=>x.pos+x.neg),it:R(x=>x.intent,x=>x.comments),vw:tl.map(x=>x.viewers),cm:tl.map(x=>x.comments),lk:tl.map(x=>x.likes),gf:tl.map(x=>x.gifts),fl:tl.map(x=>x.follows),sh:tl.map(x=>x.shares)}}
function bars(items){if(!items||!items.length)return `<p class="empty">${t('nodata')}</p>`;let max=Math.max(...items.map(x=>x[1]),1);return items.map(([n,v])=>`<div class="barrow"><div class="barlabel"><span>${esc(n)}</span><b>${fmt(v)}</b></div><div class="barbg"><div class="fill" style="width:${Math.max(3,v/max*100)}%"></div></div></div>`).join('')}
function table(items){if(!items?.length)return `<p class="empty">${t('na')}</p>`;return `<table><thead><tr><th>${t('question')}</th><th>${t('count')}</th></tr></thead><tbody>`+items.map(([a,b])=>`<tr><td>${esc(a)}</td><td>${b}</td></tr>`).join('')+'</tbody></table>'}
function donut(obj,C){let e=Object.entries(obj||{}).filter(x=>x[1]>0).sort((a,b)=>b[1]-a[1]);if(!e.length)return `<p class="empty">${t('nodata')}</p>`;let tot=e.reduce((a,x)=>a+x[1],0),r=60,c=2*Math.PI*r,off=0,col=(k,i)=>C[k]||C._[i%C._.length];let s=`<svg viewBox="0 0 160 160" width="160" height="160"><g transform="rotate(-90 80 80)">`;e.forEach(([k,v],i)=>{let len=c*v/tot;s+=`<circle cx="80" cy="80" r="${r}" fill="none" stroke="${col(k,i)}" stroke-width="22" stroke-dasharray="${len} ${c-len}" stroke-dashoffset="${-off}"><title>${esc(k)}: ${v}</title></circle>`;off+=len});s+=`</g><text x="80" y="87" text-anchor="middle" style="font-size:22px;fill:var(--txt);font-weight:700">${fmt(tot)}</text></svg>`;return `<div class="donutwrap">${s}<div style="flex:1;min-width:170px">`+e.map(([k,v],i)=>`<div class="barlabel" style="margin:9px 0"><span><span class="s" style="background:${col(k,i)}"></span>${esc(k)}</span><b>${fmt(v)} (${Math.round(v/tot*100)}%)</b></div>`).join('')+'</div></div>'}
const SC={positive:'#22c55e',neutral:'#94a3b8',negative:'#f43f5e',_:['#3b82f6']},PC={tiktok:'#3b82f6',shopee:'#f97316',instagram:'#ec4899',manual:'#22d3ee',_:['#94a3b8','#facc15']};
/* chart: lines = [{v:[],color,axis:'l'|'r',area:bool,name,fmt}] , bars same with type:'bar' */
function chart(el,tl,defs,opt){if(!tl.length||!defs.some(d=>d.v.some(x=>x))){el.innerHTML=`<p class="empty">${t('nodata')}</p>`;return}
const W=900,H=opt.h||300,L=44,R=46,T=14,B=30,n=tl.length,ih=H-T-B,step=(W-L-R)/n;const mx={l:opt.lmax||Math.max(...defs.filter(d=>d.axis=='l').flatMap(d=>d.v),1)*1.15,r:opt.rmax||Math.max(...defs.filter(d=>d.axis=='r').flatMap(d=>d.v),1)*1.15};
const X=i=>L+i*step+step/2,Y=(v,a)=>T+ih-(v/mx[a])*ih;let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img"><defs>`;defs.forEach((d,k)=>s+=`<linearGradient id="ar${opt.id}${k}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${d.color}" stop-opacity=".45"/><stop offset="1" stop-color="${d.color}" stop-opacity="0"/></linearGradient>`);s+='</defs>';
for(let g=0;g<=4;g++){const y=T+ih*g/4;s+=`<line x1="${L}" x2="${W-R}" y1="${y}" y2="${y}" stroke="#22314d"/>`;if(defs.some(d=>d.axis=='l'))s+=`<text x="${L-8}" y="${y+4}" text-anchor="end">${opt.lf(mx.l*(1-g/4))}</text>`;if(defs.some(d=>d.axis=='r'))s+=`<text x="${W-R+8}" y="${y+4}">${opt.rf(mx.r*(1-g/4))}</text>`}
tl.forEach((x,i)=>{if(i%3==0)s+=`<text x="${X(i)}" y="${H-8}" text-anchor="middle">${hh(x.t)}</text>`});
defs.forEach((d,k)=>{if(d.type=='bar'){d.v.forEach((v,i)=>{const h=ih*v/mx[d.axis];s+=`<rect x="${X(i)-step/2+3}" y="${T+ih-h}" width="${Math.max(1,step-6)}" height="${h}" rx="3" fill="${d.color}" opacity=".85"/>`});return}
const pts=d.v.map((v,i)=>`${X(i)},${Y(v,d.axis)}`);if(d.area)s+=`<path d="M${pts.join(' L')} L${X(n-1)},${T+ih} L${X(0)},${T+ih}Z" fill="url(#ar${opt.id}${k})"/>`;s+=`<polyline points="${pts.join(' ')}" fill="none" stroke="${d.color}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>`});
s+=`<line id="cx${opt.id}" y1="${T}" y2="${T+ih}" stroke="#93c5fd" stroke-dasharray="4 4" style="display:none"/>`;defs.forEach((d,k)=>{if(d.type!='bar')s+=`<circle id="cd${opt.id}${k}" r="5.5" fill="${d.color}" stroke="#fff" stroke-width="2" style="display:none"/>`});
s+=`<rect x="${L}" y="${T}" width="${W-L-R}" height="${ih}" fill="transparent" id="ov${opt.id}"/></svg>`;el.innerHTML=s;
const svg=el.querySelector('svg'),ov=el.querySelector('#ov'+opt.id),tip=$('tip');
ov.onmousemove=ev=>{const r=svg.getBoundingClientRect(),xx=(ev.clientX-r.left)*W/r.width,i=Math.max(0,Math.min(n-1,Math.floor((xx-L)/step)));const cx=el.querySelector('#cx'+opt.id);cx.setAttribute('x1',X(i));cx.setAttribute('x2',X(i));cx.style.display='';defs.forEach((d,k)=>{const c=el.querySelector('#cd'+opt.id+k);if(c){c.setAttribute('cx',X(i));c.setAttribute('cy',Y(d.v[i],d.axis));c.style.display=''}});tip.innerHTML=`<b>${hh(tl[i].t)}</b>`+defs.map(d=>`<div><span class="s" style="background:${d.color}"></span>${d.name}: <b>${d.fmt(d.v[i])}</b></div>`).join('');tip.style.display='block';const tw=tip.offsetWidth;tip.style.left=Math.min(window.innerWidth-tw-10,ev.clientX+14)+'px';tip.style.top=(ev.clientY+window.scrollY-20)+'px'};
ov.onmouseleave=()=>{tip.style.display='none';el.querySelector('#cx'+opt.id).style.display='none';defs.forEach((d,k)=>{const c=el.querySelector('#cd'+opt.id+k);if(c)c.style.display='none'})}}
function insights(d,full){const L=[];const cat=d.catalog||[],top=[...cat].sort((a,b)=>b.mentions-a.mentions)[0],tq=[...cat].sort((a,b)=>b.questions-a.questions)[0];const s=d.sentiment||{},sp=s.positive||0,sn=s.negative||0;const tl=d.timeline||[],peak=tl.reduce((a,x)=>x.comments>(a?.comments||0)?x:a,null);
if(top&&top.mentions)L.push(t('i_top',{n:esc(top.name),c:top.mentions}));
if(tq&&tq.questions)L.push(t('i_q',{n:esc(tq.name),c:tq.questions}));
if(sp+sn)L.push(t('i_trust',{v:Math.round(sp/(sp+sn)*100)})+(sn?t('i_neg',{c:sn}):''));
if(peak&&peak.comments)L.push(t('i_peak',{h:hh(peak.t),c:peak.comments}));
if(d.interactions)L.push(t('i_xai',{v:Math.round(pct(d.explained,d.interactions))}));
if(!L.length)return `<p class="empty">${t('no_insight')}</p>`;return (full?L:L.slice(0,2)).map(t=>`<div class="msg">${t}</div>`).join('')}
let feedIdx=0;function liveCard(d){const cat=d.catalog||[],top=[...cat].sort((a,b)=>b.mentions-a.mentions)[0]||{name:t('no_product'),price:null};const cm=(d.recent_comments||[]).slice(0,3);
$('livecard').innerHTML=`<div class="tag"><span class="badge r">● LIVE</span><span class="badge d">👁 ${fmt(d.viewer_count_latest)}</span></div><div class="hero"><div><div class="big">${esc(String(top.name).split(' ').map(w=>w[0]).join('').slice(0,2))}</div><div style="margin-top:14px;font-weight:700">${esc(top.name)}</div><div class="muted small">${t('spotlight')}</div></div></div><div class="float">${cm.map(c=>`<div><b>${esc(c.user)}</b> ${esc(c.comment)}</div>`).join('')}</div><div class="bar">${thumb(top.name)}<div><b>${esc(top.name)}</b><div>${rp(top.price)}</div></div><button class="cartbtn" onclick="go('products')" title="${t('see_product')}"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2">${IC.cart}</svg></button></div>`}
function ranking(d,limit){const r=[...(d.catalog||[])].filter(p=>p.mentions).sort((a,b)=>b.mentions-a.mentions).slice(0,limit);if(!r.length)return `<p class="empty">${t('no_mention')}</p>`;const tot=d.chat_count||1;
return `<div style="overflow-x:auto"><table><thead><tr><th>#</th><th>${t('th_product')}</th><th>${t('th_share')}</th><th>${t('question')}</th><th>${t('th_trust')}</th></tr></thead><tbody>`+r.map((p,i)=>{const t=p.pos+p.neg?Math.round(p.pos/(p.pos+p.neg)*100):null;return `<tr><td>${i+1}</td><td><div class="pname">${thumb(p.name)}<div><b>${esc(p.name)}</b><small>${esc(p.category)} • ${rp(p.price)}</small></div></div></td><td>${pct(p.mentions,tot).toFixed(1)}%</td><td>${p.questions}</td><td>${t==null?'<span class="gpill z">–</span>':`<span class="gpill ${t<50?'n':''}">${t>=50?'↑':'↓'} ${t}/100</span>`}</td></tr>`}).join('')+'</tbody></table></div>'}
function research(d,sr){const cov=d.interactions?Math.round(pct(d.explained,d.interactions)):0,sv=d.survey||{},Y=(sv.constructs||{}).Y||{},tr=Y.mean;return tile('layers','p',t('t_cov'),`${cov}<small>%</small>`,`<span class="muted small">${t('t_cov_sub',{a:d.explained,b:d.interactions})}</span>`)+tile('chat','t',t('t_inter'),fmt(d.interactions),`<span class="muted small">${t('period')}</span>`)+tile('shield','t',t('t_survey'),tr==null?'–':`${tr}<small>/5</small>`,`<span class="muted small">${Y.alpha!=null?'α '+Y.alpha+' · ':''}${t('t_likert')}</span>`)+tile('users','p',t('t_sample'),fmt(sv.valid||0),`<span class="muted small">${t('sv_of',{a:sv.valid||0,b:sv.total||0})}</span>`)}
function survey(sv){if(!sv||!sv.total)return `<p class="empty">${t('sv_empty')}</p>`;const C=sv.constructs||{},N={X:'Explainable AI',Y:'Consumer Trust',Z:'AI Transparency'};
const al=a=>a==null?'–':`<span class="gpill ${a<0.7?'n':''}">α ${a}</span>`;
let h='<div class="tiles" style="grid-template-columns:repeat(4,1fr)">'+tile('users','p',t('sv_valid'),fmt(sv.valid),`<span class="muted small">${t('sv_of',{a:sv.valid,b:sv.total})} · ${t('sv_out',{n:sv.screened_out})}</span>`)+
['X','Y','Z'].map(k=>tile(k=='Y'?'shield':k=='X'?'layers':'chat',k=='Y'?'t':'p',`${k} — ${N[k]}`,C[k]?.mean==null?'–':`${C[k].mean}<small>/5</small>`,`<span class="muted small">SD ${C[k]?.sd??'–'}</span> ${al(C[k]?.alpha)}`)).join('')+'</div>';
const row=(lab,m,name)=>{const c=m&&m.coef.find(x=>x.name==name);if(!c)return `<tr><td>${lab}</td><td colspan="4" class="muted">${t('sv_need')}</td></tr>`;const sig=c.t!=null&&Math.abs(c.t)>=1.96;return `<tr><td>${lab}</td><td>${c.b}</td><td>${c.se}</td><td>${c.t??'–'}</td><td><span class="gpill ${sig?'':'z'}">${sig?t('sv_sig'):t('sv_ns')}</span></td></tr>`};
h+=`<div class="g2"><div><h2 style="margin-top:6px">${t('sv_hyp')}</h2><div style="overflow-x:auto"><table><thead><tr><th>${t('sv_path')}</th><th>b</th><th>SE</th><th>t</th><th></th></tr></thead><tbody>${row('H1: X → Y',sv.h1,'X')}${row('H2: X×Z → Y',sv.h2,'X×Z')}${row('Z → Y',sv.h2,'Z')}</tbody></table></div>
<p class="muted small">R² H1 = ${sv.h1?.r2??'–'} · R² H2 = ${sv.h2?.r2??'–'} · r(X,Y) = ${sv.r_xy??'–'} · n = ${sv.valid}</p><p class="muted small">${t('sv_note')}</p></div>
<div><h2 style="margin-top:6px">${t('sv_items')}</h2>${bars(['X','Y','Z'].flatMap(k=>(sv.items[k]||[]).map((v,i)=>[k+(i+1),v||0])))}</div></div>`;
if(sv.dummy)h+=`<p class="small" style="color:#fcd34d">⚠ ${t('sv_dummy')}</p>`;return h}
function render(d){const s=series(d),sum=a=>a.reduce((x,y)=>x+y,0),avg=a=>{const f=a.filter(x=>x);return f.length?sum(f)/f.length:0};const sp=(d.sentiment||{}).positive||0,sn=(d.sentiment||{}).negative||0;
$('demo').style.display=d.has_dummy?'':'none';
$('kpis').innerHTML=kpi('live','p',t('k_viewers'),fmt(d.viewer_count_latest),delta(s.vw),s.vw,'#3b82f6')+kpi('users','p',t('k_eng'),avg(s.er).toFixed(1)+'%',delta(s.er,'pp',true),s.er,'#3b82f6')+kpi('cart','t',t('k_intent'),pct(d.intent_comments,d.chat_count).toFixed(1)+'%',delta(s.it,'pp',true),s.it,'#22d3ee')+kpi('shield','b',t('k_trust'),(sp+sn?Math.round(sp/(sp+sn)*100):0)+'<small> /100</small>',delta(s.tr,'pts',true),s.tr,'#38bdf8');
liveCard(d);
chart($('perf'),d.timeline||[],[{v:s.tr,color:'#22d3ee',axis:'r',area:true,name:t('trust_signal'),fmt:v=>Math.round(v)},{v:s.er,color:'#3b82f6',axis:'l',area:false,name:t('engagement'),fmt:v=>v.toFixed(1)+'%'}],{id:'p',h:290,rmax:100,lf:v=>v.toFixed(1)+'%',rf:v=>Math.round(v)});
$('copilot').innerHTML=insights(d,false);$('copilotFull').innerHTML=insights(d,true);$('ranking').innerHTML=ranking(d,5);$('rmon').innerHTML=research(d);$('rmon2').innerHTML=research(d);$('svbox').innerHTML=survey(d.survey);
$('livekpis').innerHTML=kpi('chat','p',t('k_comments'),fmt(d.chat_count),delta(s.cm),s.cm,'#3b82f6')+kpi('heart','t',t('k_likes'),fmt(d.likes),delta(s.lk),s.lk,'#22d3ee')+kpi('gift','p',t('k_gifts'),fmt(d.gifts),delta(s.gf),s.gf,'#3b82f6')+kpi('plus','b',t('k_follows'),fmt(d.follows),delta(s.fl),s.fl,'#38bdf8');
chart($('trend'),d.timeline||[],[{v:s.cm,color:'#3b82f6',axis:'l',type:'bar',name:t('c_comments'),fmt:fmt},{v:s.vw,color:'#f59e0b',axis:'r',name:t('c_viewers'),fmt:fmt}],{id:'t',h:280,lf:v=>Math.round(v),rf:v=>fmt(Math.round(v))});
$('platDonut').innerHTML=donut(d.platforms,PC);$('locations').innerHTML=bars(d.locations);$('sentDonut').innerHTML=donut(d.sentiment,SC);$('keywords').innerHTML=bars(d.keywords.slice(0,12));$('questions').innerHTML=table(d.questions);$('eventtypes').innerHTML=bars(Object.entries(d.event_types||{}).sort((a,b)=>b[1]-a[1]));$('products').innerHTML=bars(d.product_interest);
const cats=[...new Set((d.catalog||[]).map(p=>p.category))].sort(),pc=$('pcat'),cur=pc.value;pc.innerHTML=`<option value="">${t('all_categories')}</option>`+cats.map(c=>`<option ${c==cur?'selected':''}>${esc(c)}</option>`).join('');
renderProducts();renderFeed();
$('rinter').innerHTML=(d.recent_interactions||[]).map(r=>`<div class="comment"><div class="muted small">${esc(r.platform)} · ${new Date(r.time).toLocaleString(LOC())}</div><div>💬 ${esc(r.comment)}</div><div style="margin-top:4px">→ <b>${esc(r.product||t('no_match'))}</b> ${r.score!=null?`<span class="muted small">${t('score')} ${r.score}</span>`:''}</div>${(r.reasons||[]).map(x=>`<div class="muted small">• ${esc(x)}</div>`).join('')}</div>`).join('')||`<p class="empty">${t('no_inter')}</p>`;
const rc={};(d.recent_interactions||[]).forEach(r=>{if(r.product)rc[r.product]=(rc[r.product]||0)+1});$('recprod').innerHTML=bars(Object.entries(rc).sort((a,b)=>b[1]-a[1]));
$('info').innerHTML=t('info',{e:fmt(d.events),u:fmt(d.unique_users_proxy),p:(d.catalog||[]).length,s:fmt(d.shares),t:new Date(d.updated).toLocaleString(LOC())})+(d.has_dummy?` • <b style="color:#fcd34d">${t('has_dummy')}</b>`:'')}
function renderProducts(){if(!latest)return;const q=$('psearch').value.toLowerCase(),c=$('pcat').value,k=$('psort').value,tot=latest.chat_count||1;let r=(latest.catalog||[]).filter(p=>(!q||p.name.toLowerCase().includes(q)||(p.tags||[]).join(' ').includes(q))&&(!c||p.category==c));
r.sort((a,b)=>k=='name'?a.name.localeCompare(b.name):k=='price'?(b.price||0)-(a.price||0):k=='pos'?(b.pos/(b.pos+b.neg||1))-(a.pos/(a.pos+a.neg||1)):b[k]-a[k]);
$('ptable').innerHTML=r.length?`<table><thead><tr><th>${t('th_product')}</th><th>${t('th_cat')}</th><th>${t('th_price')}</th><th>${t('th_stock')}</th><th>${t('th_mentions')}</th><th>${t('question')}</th><th>${t('th_pos')}</th></tr></thead><tbody>`+r.map(p=>{const t=p.pos+p.neg?Math.round(p.pos/(p.pos+p.neg)*100):null;return `<tr><td><div class="pname">${thumb(p.name,36)}<div><b>${esc(p.name)}</b><small>${esc(String(p.description||'').replace('[DUMMY] ',''))}</small></div></div></td><td>${esc(p.category)}</td><td>${rp(p.price)}</td><td>${esc(p.stock)}</td><td>${p.mentions} <span class="muted small">(${pct(p.mentions,tot).toFixed(1)}%)</span></td><td>${p.questions}</td><td>${t==null?'–':`<span class="gpill ${t<50?'n':''}">${t}%</span>`}</td></tr>`}).join('')+'</tbody></table>':`<p class="empty">${t('no_prod_match')}</p>`}
function renderFeed(){if(!latest)return;let q=$('filter').value.toLowerCase(),plat=$('platformFilter').value,sf=$('sentFilter').value;let items=(latest.recent_comments||[]).filter(c=>(!q||c.comment.toLowerCase().includes(q)||String(c.user).toLowerCase().includes(q))&&(!plat||c.platform==plat)&&(!sf||c.sentiment==sf));
$('feed').innerHTML=items.map(c=>`<div class="comment"><span class="s ${c.sentiment}"></span><b>${esc(c.user)}</b> <span class="muted small">${esc(c.platform)}${c.region?' · '+esc(c.region):''} · ${new Date(c.time).toLocaleString(LOC())}</span><div>${esc(c.comment)}</div></div>`).join('')||`<p class="empty">${t('no_comment_match')}</p>`}
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'liveai'},body:JSON.stringify(b)}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
function copyText(t){try{navigator.clipboard.writeText(t)}catch(e){}}
const ST={connected:'#4ade80',waiting:'#fcd34d',checking:'#93c5fd',ended:'#94a3b8',idle:'#94a3b8',error:'#fb7185'};
function stat(s){if(!s||!s.state)return '-';return `<span class="s" style="background:${ST[s.state]||'#999'}"></span>${esc(s.detail||s.state)}${s.events?` · ${fmt(s.events)} event`:''}`}
let CP=[];async function loadLive(){try{const [c,items,ov]=await Promise.all([fetch('api/live/config').then(r=>r.json()),fetch('api/copilot').then(r=>r.json()),fetch('api/overlay').then(r=>r.json())]);
if(document.activeElement!==$('ttuser'))$('ttuser').value=c.tiktok?.username?'@'+c.tiktok.username:'';$('tton').checked=!!c.tiktok?.enabled;if(document.activeElement!==$('spuser'))$('spuser').value=c.shopee?.username||'';
$('ttstatus').innerHTML=stat(c.tiktok_status);$('cpstatus').innerHTML=stat(c.tiktok_status);$('ovlurl').value=location.origin+location.pathname.replace(/\/$/,'')+'/overlay';
$('ovlnow').innerHTML=ov.visible?`${t('cp_showing')}: <b>${esc(ov.product?.name)}</b>`:t('cp_hidden');CP=items;
$('cplist').innerHTML=items.map((x,i)=>`<div class="comment"><span class="chip">${esc(x.intent)}</span> <b>${esc(x.user)}</b> <span class="muted small">${esc(x.platform)} · ${new Date(x.time).toLocaleTimeString(LOC())}</span><div>💬 ${esc(x.comment)}</div>
<textarea id="dr${i}" rows="2" style="width:100%;margin-top:6px;background:#0b1220;color:var(--txt);border:1px solid var(--line);border-radius:9px;padding:8px">${esc(x.draft)}</textarea>
<div class="tools" style="margin:6px 0 0"><button class="btn g" onclick="copyText($('dr${i}').value)">${t('copy')}</button>${x.product?`<button class="btn" onclick="showOverlay(${i})">${t('cp_show')}</button>`:''}</div></div>`).join('')||`<p class="empty">${t('cp_empty')}</p>`}catch(e){}}
async function saveAcc(p){try{await post('api/live/config',p=='tiktok'?{platform:p,username:$('ttuser').value,enabled:$('tton').checked}:{platform:p,username:$('spuser').value,enabled:false});loadLive();alert(t('saved'))}catch(e){alert(t('acc_bad'))}}
async function showOverlay(i){const x=CP[i];await post('api/overlay',{visible:true,product:x.product,reasons:x.reasons});loadLive()}
async function hideOverlay(){await post('api/overlay',{visible:false});loadLive()}
async function load(){loadLive();try{let r=await fetch(API);if(!r.ok)throw 0;let d=await r.json();if(d.error)throw 0;latest=d;lastOk=new Date();render(d);setStatus()}catch(e){lastOk=null;setStatus()}}
let lastOk=null,loaded=false;function setStatus(){const s=$('status');if(lastOk){s.className='pill ok';s.innerHTML=`<span class="dot"></span>${t('connected')} · ${lastOk.toLocaleTimeString(LOC(),{hour:'2-digit',minute:'2-digit'})}`}else{s.className='pill bad';s.innerHTML=`<span class="dot"></span>${t('api_down')}`}}
const LOC=()=>LANG=='en'?'en-GB':'id-ID';
const VIEWS=['overview','live','products','insights','copilot','research','settings'];function go(v){location.hash=v}
function show(){let v=location.hash.slice(1);if(!VIEWS.includes(v))v=SET.home||'overview';VIEWS.forEach(x=>$('v-'+x).classList.toggle('on',x==v));document.querySelectorAll('#menu a[data-v]').forEach(a=>a.classList.toggle('on',a.dataset.v==v));closeDD();window.scrollTo(0,0)}
function toggleDD(e){e.stopPropagation();const dd=$('dd'),b=dd.querySelector('button').getBoundingClientRect(),l=dd.querySelector('.list');dd.classList.toggle('open');l.style.top=(b.bottom+4)+'px';l.style.left=Math.min(b.left,window.innerWidth-200)+'px'}function closeDD(){$('dd').classList.remove('open')}document.addEventListener('click',closeDD);window.addEventListener('scroll',closeDD);
function openSurvey(){window.open(location.protocol+'//'+location.hostname+':'+(SET.port||18080)+'/survey','_blank','noopener')}
function openResearch(){window.open(location.protocol+'//'+location.hostname+':'+(SET.port||18080)+'/research','_blank','noopener')}
let SET={refresh:15,home:'overview',port:18080};try{Object.assign(SET,JSON.parse(localStorage.getItem('liveai-set')||'{}'))}catch(e){}
function applySet(){$('setRefresh').value=SET.refresh;$('setHome').value=SET.home;$('setPort').value=SET.port;clearInterval(timer);if(+SET.refresh)timer=setInterval(load,SET.refresh*1000)}
function saveSet(){SET={refresh:+$('setRefresh').value,home:$('setHome').value,port:+$('setPort').value||18080};try{localStorage.setItem('liveai-set',JSON.stringify(SET))}catch(e){}applySet()}
function downloadJSON(){if(!latest)return;downloadFile('live-commerce-analytics.json',JSON.stringify(latest,null,2),'application/json')}
function toCSV(rows){return '﻿'+rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n')}
function downloadCSV(){if(!latest)return;downloadFile('live-comments.csv',toCSV([['platform','user','region','sentiment','time','comment'],...(latest.recent_comments||[]).map(c=>[c.platform,c.user,c.region,c.sentiment,c.time,c.comment])]),'text/csv;charset=utf-8')}
function downloadProducts(){if(!latest)return;downloadFile('products.csv',toCSV([['name','category','price','stock','mentions','questions','positive','negative'],...(latest.catalog||[]).map(p=>[p.name,p.category,p.price,p.stock,p.mentions,p.questions,p.pos,p.neg])]),'text/csv;charset=utf-8')}
function downloadFile(name,data,type){let blob=new Blob([data],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
window.addEventListener('hashchange',show);applyLang();applySet();show();load();
</script></body></html>'''
