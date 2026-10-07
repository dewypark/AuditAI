"""AuditAI 2.0: eight analyses + persistent evidence review. Single-user MVP."""
import os,io,json,sqlite3,secrets,hashlib,uuid
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
from flask import Flask,render_template,request,session,redirect,url_for,send_file,abort
from engine import execute,SCHEMAS,NAMES,RISKS,CONTROLS
ROOT=Path(__file__).parent
DATA=Path(os.environ.get('AUDITAI_DATA_DIR',str(ROOT/'instance')));DATA.mkdir(parents=True,exist_ok=True)
secret=DATA/'session.key'
if not secret.exists():
    try:
        with secret.open('x') as f:f.write(secrets.token_hex(32))
        secret.chmod(0o600)
    except FileExistsError:pass
app=Flask(__name__);app.secret_key=os.environ.get('SECRET_KEY') or secret.read_text()
app.config.update(MAX_CONTENT_LENGTH=10*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('AUDITAI_SECURE_COOKIE')=='1')
DB=DATA/'auditai.sqlite3'

def db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
with db() as c:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,owner TEXT,case_no INTEGER,created TEXT,filename TEXT,hash TEXT,raw BLOB,config TEXT,population INTEGER,result TEXT,conclusion TEXT DEFAULT '',conclusion_by TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS candidates(run_id TEXT,id TEXT,entity TEXT,rule TEXT,reason TEXT,evidence_request TEXT,source_ref TEXT,severity TEXT,status TEXT DEFAULT '미검토',reviewer TEXT DEFAULT '',note TEXT DEFAULT '',evidence_ref TEXT DEFAULT '',updated TEXT DEFAULT '',PRIMARY KEY(run_id,id),FOREIGN KEY(run_id) REFERENCES runs(id));
    CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,candidate_id TEXT,created TEXT,payload TEXT);
    CREATE TABLE IF NOT EXISTS mappings(owner TEXT,case_no INTEGER,payload TEXT,PRIMARY KEY(owner,case_no));
    ''')
# UI labels are Korean; internal persisted values also use Korean.
STATUSES=['미검토','증빙 요청','증빙 수령','검토 완료·설명 가능','검토 완료·지적 후보']
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def owner():
    if 'owner' not in session:session['owner']=secrets.token_hex(20)
    if 'csrf' not in session:session['csrf']=secrets.token_hex(24)
    return session['owner']
@app.before_request
def guard():
    owner()
    if request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),session['csrf']):abort(400,'페이지를 새로 열고 다시 시도해주세요.')
@app.errorhandler(413)
def large(e):return render_template('workspace.html',error='파일은 10MB 이하로 업로드해주세요.',names=NAMES),413

def get_run(rid):
    with db() as c:r=c.execute('SELECT * FROM runs WHERE id=? AND owner=?',(rid,owner())).fetchone()
    if not r:abort(404)
    return r

def serialize(f):return json.loads(f.to_json(orient='records',date_format='iso',force_ascii=False))
def load_input(raw,filename):
    if filename.lower().endswith('.json'):
        obj=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(obj,dict):raise ValueError('JSON은 자료명: 행 목록 구조')
        return {n:pd.DataFrame(rows) for n,rows in obj.items()}
    if filename.lower().endswith('.xlsx'):
        return pd.read_excel(io.BytesIO(raw),sheet_name=None)
    raise ValueError('xlsx 또는 JSON 파일 사용')

def configuration():
    cfg={'snapshot':request.form.get('snapshot') or '2026-09-30T18:00','tolerance':float(request.form.get('tolerance') or .01),'high_amount':float(request.form.get('high_amount') or 1000000),'contamination':float(request.form.get('contamination') or .05),'emergency_hours':float(request.form.get('emergency_hours') or 48),'rule_version':'auditai-2.0-mvp.1'}
    mapping=json.loads(request.form.get('mapping') or '{}')
    if not isinstance(mapping,dict):raise ValueError('열 매핑은 JSON 객체')
    cfg['mapping']=mapping
    return cfg

@app.route('/')
def home():
    with db() as c:
        runs=c.execute('SELECT id,case_no,created,population FROM runs WHERE owner=? ORDER BY created DESC',(owner(),)).fetchall()
        counts=c.execute('SELECT status,count(*) n FROM candidates WHERE run_id IN (SELECT id FROM runs WHERE owner=?) GROUP BY status',(owner(),)).fetchall()
    return render_template('workspace.html',names=NAMES,runs=runs,counts=counts)

@app.route('/case/<int:case>',methods=['GET','POST'])
def case_page(case):
    if case not in NAMES:abort(404)
    with db() as c:m=c.execute('SELECT payload FROM mappings WHERE owner=? AND case_no=?',(owner(),case)).fetchone()
    kwargs=dict(names=NAMES,case=case,schema=SCHEMAS[case],risk=RISKS[case],control=CONTROLS[case],mapping=m['payload'] if m else '{}')
    if request.method=='GET':return render_template('workspace.html',**kwargs)
    try:
        cfg=configuration()
        if request.form.get('action')=='demo':
            filename=f'case{case:02}.json';raw=(ROOT/'sample_data'/filename).read_bytes()
        else:
            f=request.files.get('file')
            if not f or not f.filename:raise ValueError('입력 파일 선택')
            filename=Path(f.filename.replace('\\','/')).name;raw=f.read()
        tables=load_input(raw,filename)
        for name,rename in cfg['mapping'].items():
            if name not in tables or not isinstance(rename,dict):raise ValueError('매핑의 자료명 확인')
            if set(rename)-set(tables[name].columns):raise ValueError('매핑 원본 열 없음')
            tables[name]=tables[name].rename(columns=rename)
            if tables[name].columns.duplicated().any():raise ValueError('매핑 후 열 이름 중복')
        result,candidates,population=execute(case,tables,cfg)
        rid=uuid.uuid4().hex
        with db() as c:
            c.execute('INSERT INTO runs(id,owner,case_no,created,filename,hash,raw,config,population,result) VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,owner(),case,now(),filename,hashlib.sha256(raw).hexdigest(),raw,json.dumps(cfg,ensure_ascii=False),population,json.dumps({n:serialize(f) for n,f in result.items()},ensure_ascii=False)))
            for v in candidates:c.execute('INSERT INTO candidates(run_id,id,entity,rule,reason,evidence_request,source_ref,severity,status) VALUES (?,?,?,?,?,?,?,?,?)',(rid,v['candidate_id'],v['entity_id'],v['rule_id'],v['reason'],v['evidence_request'],v['source_ref'],v['severity'],'미검토'))
            c.execute('INSERT OR REPLACE INTO mappings VALUES (?,?,?)',(owner(),case,json.dumps(cfg['mapping'],ensure_ascii=False)))
        return redirect(url_for('run_page',rid=rid))
    except (ValueError,KeyError,TypeError) as e:return render_template('workspace.html',error=str(e),**kwargs),400
    except Exception:
        app.logger.exception('Analysis input failed')
        return render_template('workspace.html',error='파일 구조·형식 확인 필요. 정상 파일로 다시 실행해주세요.',**kwargs),400

@app.route('/run/<rid>')
def run_page(rid):
    r=get_run(rid)
    with db() as c:
        cs=c.execute('SELECT * FROM candidates WHERE run_id=?',(rid,)).fetchall()
        h=c.execute('SELECT * FROM history WHERE run_id=? ORDER BY seq DESC',(rid,)).fetchall()
    tables={n:pd.DataFrame(rows).head(200).to_html(index=False,escape=True,na_rep='—') for n,rows in json.loads(r['result']).items()}
    return render_template('workspace.html',names=NAMES,run=r,candidates=cs,history=h,tables=tables,risk=RISKS[r['case_no']],control=CONTROLS[r['case_no']],statuses=STATUSES)

@app.post('/run/<rid>/review/<cid>')
def review(rid,cid):
    get_run(rid)
    status=request.form.get('status');reviewer=request.form.get('reviewer','').strip();note=request.form.get('note','').strip();ref=request.form.get('evidence_ref','').strip()
    if len(reviewer)>100 or len(note)>4000 or len(ref)>1000:abort(400,'입력 길이가 너무 깁니다.')
    if status not in STATUSES or not reviewer or not note:abort(400,'검토자·검토 사유·상태를 입력해주세요.')
    if status in STATUSES[2:] and not ref:abort(400,'증빙 수령 또는 검토 완료에는 증빙 참조가 필요합니다.')
    payload=dict(status=status,reviewer=reviewer,note=note,evidence_ref=ref)
    with db() as c:
        cur=c.execute('UPDATE candidates SET status=?,reviewer=?,note=?,evidence_ref=?,updated=? WHERE run_id=? AND id=?',(status,reviewer,note,ref,now(),rid,cid))
        if cur.rowcount!=1:abort(404)
        c.execute('INSERT INTO history(run_id,candidate_id,created,payload) VALUES (?,?,?,?)',(rid,cid,now(),json.dumps(payload,ensure_ascii=False)))
        c.execute('UPDATE runs SET conclusion=?,conclusion_by=? WHERE id=?',('','',rid))
    return redirect(url_for('run_page',rid=rid))

@app.post('/run/<rid>/conclusion')
def conclusion(rid):
    get_run(rid);text=request.form.get('conclusion','').strip();who=request.form.get('reviewer','').strip()
    if not text or not who:abort(400,'결론과 작성자를 입력해주세요.')
    with db() as c:
        pending=c.execute('SELECT count(*) FROM candidates WHERE run_id=? AND status NOT IN (?,?)',(rid,*STATUSES[3:])).fetchone()[0]
        if pending:abort(400,'미완료 후보가 있습니다. 증빙 검토를 완료한 뒤 결론을 저장해주세요.')
        c.execute('UPDATE runs SET conclusion=?,conclusion_by=? WHERE id=?',(text,who,rid))
        c.execute('INSERT INTO history(run_id,candidate_id,created,payload) VALUES (?,?,?,?)',(rid,'CONCLUSION',now(),json.dumps({'conclusion':text,'reviewer':who},ensure_ascii=False)))
    return redirect(url_for('run_page',rid=rid))

@app.get('/sample/<int:case>')
def sample(case):
    if case not in NAMES:abort(404)
    return send_file(ROOT/'sample_data'/f'case{case:02}.json',as_attachment=True)

@app.get('/run/<rid>/source')
def source(rid):
    r=get_run(rid);return send_file(io.BytesIO(r['raw']),as_attachment=True,download_name=r['filename'])

@app.get('/run/<rid>/export')
def export(rid):
    r=get_run(rid)
    with db() as c:
        cs=pd.read_sql_query('SELECT * FROM candidates WHERE run_id=?',c,params=(rid,))
        h=pd.read_sql_query('SELECT * FROM history WHERE run_id=?',c,params=(rid,))
    tables={n:pd.DataFrame(rows) for n,rows in json.loads(r['result']).items()}
    tables['검토 기록']=cs;tables['검토 이력']=h
    tables['실행·RCM']=pd.DataFrame([{'항목':k,'값':str(v)} for k,v in {'실행 ID':rid,'입력 SHA256':r['hash'],'기준 설정':r['config'],'모집단':r['population'],'Risk':RISKS[r['case_no']],'Control':CONTROLS[r['case_no']],'결론':r['conclusion'] or '증빙 검토 후 작성 필요','작성자':r['conclusion_by'],'범위':'합성/업로드 자료의 규칙 검사; 고객 실무 감사 의견 아님'}.items()])
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        for n,f in tables.items():
            for col in f.select_dtypes(include=['object','string']):f[col]=f[col].map(lambda v:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
            f.to_excel(w,index=False,sheet_name=n[:31])
    b.seek(0);return send_file(b,as_attachment=True,download_name=f'auditai_case{r["case_no"]}_{rid[:8]}.xlsx')

@app.get('/run/<rid>/workpaper')
def workpaper(rid):
    r=get_run(rid)
    with db() as c:rows=c.execute('SELECT * FROM candidates WHERE run_id=?',(rid,)).fetchall()
    lines=[f'# Case {r["case_no"]:02} — {NAMES[r["case_no"]]}',f'실행 ID: {rid}',f'입력: {r["filename"]}',f'SHA256: {r["hash"]}',f'설정: {r["config"]}',f'모집단: {r["population"]}; 후보: {len(rows)}',f'Risk: {RISKS[r["case_no"]]}',f'Control: {CONTROLS[r["case_no"]]}','범위: 제공 자료에 대한 규칙 검사. 자료의 외부 완전성·진위 확인은 별도.']
    for x in rows:lines.extend([f'\n## {x["id"]} / {x["entity"]} / {x["rule"]}',f'추출 이유: {x["reason"]}',f'원본 참조: {x["source_ref"]}',f'증빙 요청: {x["evidence_request"]}',f'상태: {x["status"]}; 검토자: {x["reviewer"]}; 시각: {x["updated"]}',f'증빙 참조: {x["evidence_ref"]}',f'검토 사유: {x["note"]}'])
    lines.extend(['\n## 결론',r['conclusion'] or '미작성: 증빙 검토 후 범위·확인사항·한계를 포함해 사람이 작성',f'작성자: {r["conclusion_by"]}'])
    return send_file(io.BytesIO('\n'.join(lines).encode()),as_attachment=True,download_name='workpaper.md',mimetype='text/markdown')

@app.get('/health')
def health():return {'status':'ok','version':'2.0-mvp.1'}
if __name__=='__main__':app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=False)
