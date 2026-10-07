"""Deterministic risk indicators; human evidence review is required."""
from decimal import Decimal
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

SCHEMAS={
5:{'Source':['transaction_id','amount','currency'],'Target':['transaction_id','amount','currency']},
6:{'Journal':['line_id','journal_id','posted_at','account','debit','credit','currency','entry_type','created_by','approved_by']},
7:{'Payments':['payment_id','vendor_id','invoice_no','amount','currency','paid_at','status'],'Vendors':['vendor_id','vendor_name','bank_account','status']},
8:{'Transactions':['transaction_id','amount','currency','posted_at','user_id']}}

def validate(tables,schema):
    out={}
    for name,cols in schema.items():
        if name not in tables:raise ValueError('필수 자료 누락: '+name)
        f=tables[name].copy().reset_index(drop=True)
        missing=set(cols)-set(f.columns)
        if missing:raise ValueError(name+' 필수 열 누락: '+', '.join(sorted(missing)))
        f=f[cols].copy();f['_source_row']=f.index+2
        for c in cols:
            f[c]=f[c].map(lambda x:x.strip() if isinstance(x,str) else x).replace('',pd.NA)
        if f[cols].isna().any().any():raise ValueError(name+' 필수 값 누락')
        for c in ['amount','debit','credit']:
            if c in cols:
                f[c]=pd.to_numeric(f[c],errors='coerce')
                if not np.isfinite(f[c]).all():raise ValueError(name+' '+c+' 숫자 오류')
        for c in ['posted_at','paid_at']:
            if c in cols:
                f[c]=pd.to_datetime(f[c],errors='coerce',format='mixed')
                if f[c].isna().any() or isinstance(f[c].dtype,pd.DatetimeTZDtype):raise ValueError(c+' 날짜 오류: KST로 입력')
        key=cols[0]
        f[key]=f[key].astype(str)
        if f[key].duplicated().any():raise ValueError(name+' '+key+' 중복')
        if 'currency' in cols:f['currency']=f.currency.astype(str).str.upper()
        out[name]=f
    return out

def inspect_finance(case,tables,config):
    t=validate(tables,SCHEMAS[case]); candidates=[]; details={}
    def add(rule,entity,reason,evidence,source,severity='Medium'):
        candidates.append(dict(entity_id=str(entity),rule_id=rule,reason=reason,evidence_request=evidence,source_ref=source,severity=severity))
    tolerance=Decimal(str(config.get('tolerance',0.01)))
    if not tolerance.is_finite() or tolerance<0:raise ValueError('허용 오차는 0 이상의 유한 숫자')
    if case==5:
        a,b=t['Source'],t['Target']
        m=a.merge(b,on='transaction_id',how='outer',suffixes=('_source','_target'),indicator=True,validate='one_to_one')
        for _,r in m.iterrows():
            ref=f"Source:{r.get('_source_row_source','')}; Target:{r.get('_source_row_target','')}"
            if r['_merge']!='both':add('REC01',r.transaction_id,'상대 자료에 거래 없음: '+str(r['_merge']),'전송·수신 로그 및 원장',ref)
            elif r.currency_source!=r.currency_target:add('REC02',r.transaction_id,'통화 불일치','원거래·환산 기준',ref)
            elif abs(Decimal(str(r.amount_source))-Decimal(str(r.amount_target)))>tolerance:add('REC03',r.transaction_id,'금액 차이가 허용 오차 초과','전송 금액·수정 이력',ref)
        details['양방향 대사']=m
        details['통화별 집계']=pd.concat([f.groupby('currency').agg(건수=('transaction_id','count'),금액=('amount','sum')).reset_index().assign(자료=n) for n,f in t.items()],ignore_index=True)
        population=len(m)
    elif case==6:
        f=t['Journal'];threshold=float(config.get('high_amount',1000000))
        if not np.isfinite(threshold) or threshold<=0:raise ValueError('고액 기준은 양수')
        if (f[['debit','credit']]<0).any().any():raise ValueError('차변·대변은 음수가 될 수 없음')
        if not f.entry_type.isin(['Manual','System']).all():raise ValueError('entry_type은 Manual/System')
        snap=pd.Timestamp(config.get('snapshot','2026-09-30 18:00'))
        if pd.isna(snap) or snap.tzinfo:raise ValueError('기준일 오류')
        for (jid,cur),g in f.groupby(['journal_id','currency']):
            delta=sum(map(lambda v:Decimal(str(v)),g.debit))-sum(map(lambda v:Decimal(str(v)),g.credit))
            if abs(delta)>tolerance:add('JE01',f'{jid}:{cur}','통화별 차변·대변 불일치','전표 전체·통화별 균형 기준','Journal:'+','.join(g._source_row.astype(str)), 'High')
        for _,r in f.iterrows():
            ref='Journal:'+str(r._source_row)
            if r.entry_type=='Manual' and r.posted_at.dayofweek>=5:add('JE02',r.line_id,'주말 수동 전표','전표·업무 사유·승인',ref)
            if max(r.debit,r.credit)>=threshold:add('JE03',r.line_id,'고액 전표 라인','거래 계약·전표 증빙',ref)
            if r.entry_type=='Manual' and str(r.created_by)==str(r.approved_by):add('JE04',r.line_id,'작성자와 승인자 동일','독립 승인·보완통제',ref,'High')
            if r.posted_at>snap:add('JE05',r.line_id,'기준일 이후 전표: 기간 확인','추출 범위·회계 기간',ref)
        details['전표 상세']=f;population=len(f)
    elif case==7:
        p,v=t['Payments'],t['Vendors']
        if not p.status.isin(['Paid','Void']).all() or not v.status.isin(['Active','Inactive']).all():raise ValueError('지급 Paid/Void; 공급업체 Active/Inactive 상태 사용')
        paid=p[p.status.eq('Paid')].copy()
        paid['invoice_key']=paid.invoice_no.astype(str).str.strip().str.upper()
        paid['amount_key']=paid.amount.map(lambda x:str(Decimal(str(x)).normalize()))
        dup=paid.duplicated(['vendor_id','invoice_key','amount_key','currency'],keep=False)
        m=paid.merge(v,on='vendor_id',how='left',suffixes=('_payment','_vendor'),indicator=True,validate='many_to_one')
        for _,r in paid[dup].iterrows():add('AP01',r.payment_id,'동일 공급업체·송장·금액·통화의 복수 지급','송장·지급취소·은행 거래','Payments:'+str(r._source_row),'High')
        for _,r in m.iterrows():
            ref='Payments:'+str(r._source_row_payment)
            if r['_merge']=='left_only':add('AP02',r.payment_id,'공급업체 명부 미연결','공급업체 등록·ID 연결',ref)
            elif r.status_vendor=='Inactive':add('AP03',r.payment_id,'비활성 공급업체에 지급','등록 상태 이력·지급 승인',ref)
        v['bank_key']=v.bank_account.astype(str).str.replace(r'[\s-]','',regex=True)
        for _,r in v[v.bank_key.duplicated(keep=False)].iterrows():add('VEN01',r.vendor_id,'다른 공급업체와 은행 계좌 공유','계좌 소유·관계사 여부','Vendors:'+str(r._source_row))
        details['지급 상세']=m;details['공급업체 상세']=v;population=len(paid)
    else:
        f=t['Transactions'].copy();contamination=float(config.get('contamination',0.05))
        if not 0<contamination<=0.5:raise ValueError('이상치 비율은 0 초과 0.5 이하')
        threshold=float(config.get('high_amount',1000000))
        if not np.isfinite(threshold) or threshold<=0:raise ValueError('고액 기준은 양수')
        f['rule_score']=0;f['ml_score']=np.nan;f['ml_flag']=False;f['ml_status']='통화별 20건 미만: 모델 미실행'
        f['rule_score']=(f.amount.abs().ge(threshold).astype(int)*40+f.posted_at.dt.dayofweek.ge(5).astype(int)*20+f.posted_at.dt.hour.lt(6).astype(int)*20)
        for cur,g in f.groupby('currency'):
            if len(g)<20:continue
            X=np.column_stack([np.log1p(g.amount.abs()),g.posted_at.dt.hour,g.posted_at.dt.dayofweek])
            model=IsolationForest(random_state=42,contamination=contamination,n_estimators=100)
            labels=model.fit_predict(X)
            f.loc[g.index,'ml_score']=-model.decision_function(X)
            f.loc[g.index,'ml_flag']=labels==-1
            f.loc[g.index,'ml_status']='같은 모집단 학습·점수화: 탐색용'
        for _,r in f.iterrows():
            if r.rule_score>0:add('ANA01',r.transaction_id,'규칙 점수 '+str(r.rule_score)+' (고액40·주말20·새벽20)','원거래·업무 시간·승인','Transactions:'+str(r._source_row))
            if r.ml_flag:add('ANA02',r.transaction_id,'동일 통화 모집단에서 모델 이상치 후보','원거래·모델 점수·업무 맥락','Transactions:'+str(r._source_row))
        details['위험 점수']=f.sort_values(['rule_score','ml_score'],ascending=False);population=len(f)
    cols=['entity_id','rule_id','reason','evidence_request','source_ref','severity']
    details['검토 후보']=pd.DataFrame(candidates,columns=cols)
    details['검사 기준']=pd.DataFrame([{'항목':k,'값':str(v)} for k,v in config.items()])
    return details,population
