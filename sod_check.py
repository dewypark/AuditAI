"""Permission-based SoD candidates, with evidence traceability."""
import pandas as pd

class SoDInputError(ValueError):pass
SCHEMA={
 'ERP_Users':['user_id','employee_id','department','account_status'],
 'User_Roles':['assignment_id','user_id','role_id','granted_at','removed_at'],
 'Role_Permissions':['role_id','permission_id'],
 'SoD_Rules':['rule_id','permission_a','permission_b','risk_description','severity'],
 'Mitigations':['mitigation_id','user_id','rule_id','approval_status','approved_at','expires_at','control_description','evidence_ref']
}

def read_case03(file):
    with pd.ExcelFile(file) as book:
        missing=set(SCHEMA)-set(book.sheet_names)
        if missing:raise SoDInputError('필수 시트 누락: '+', '.join(sorted(missing)))
        return [pd.read_excel(book,sheet_name=n,usecols=lambda c:c in cols) for n,cols in SCHEMA.items()]

def inspect_sod(users,assignments,mappings,rules,mitigations,snapshot='2026-09-30 18:00:00'):
    clean=[]
    for (name,cols),f in zip(SCHEMA.items(),[users,assignments,mappings,rules,mitigations]):
        missing=set(cols)-set(f.columns)
        if missing:raise SoDInputError(name+': 필수 열 누락 '+', '.join(sorted(missing)))
        f=f[cols].copy()
        for col in f.columns:
            if not col.endswith('_at'):f[col]=f[col].astype('string').str.strip().replace('',pd.NA)
        clean.append(f)
    users,a,mp,rules,mit=clean
    for name,f,key in [('계정',users,'user_id'),('권한 배정',a,'assignment_id'),('규칙',rules,'rule_id'),('완화 통제',mit,'mitigation_id')]:
        if f[key].isna().any() or f[key].duplicated().any():raise SoDInputError(f'{name}: {key} 누락 또는 중복')
    for f,cols,name in [(a,['user_id','role_id'],'권한 배정'),(mp,['role_id','permission_id'],'역할-권한'),(rules,['permission_a','permission_b','severity'],'규칙'),(mit,['user_id','rule_id','approval_status'],'완화 통제')]:
        if f[cols].isna().any().any():raise SoDInputError(name+': 필수 값 누락')
    if mp.duplicated(['role_id','permission_id']).any():raise SoDInputError('역할-권한 매핑 중복')
    if mit.duplicated(['user_id','rule_id']).any():raise SoDInputError('완화 통제는 계정·규칙별 한 건으로 정리해주세요.')
    if rules.permission_a.eq(rules.permission_b).any():raise SoDInputError('충돌 규칙의 두 권한은 달라야 합니다.')
    pairs=rules.apply(lambda r:tuple(sorted([r.permission_a,r.permission_b])),axis=1)
    if pairs.duplicated().any():raise SoDInputError('같은 권한 조합의 규칙이 중복되었습니다.')
    if not users.account_status.isin(['Active','Disabled']).all():raise SoDInputError('계정 상태는 Active/Disabled를 사용해주세요.')
    if not mit.approval_status.isin(['Approved','Pending','Rejected']).all():raise SoDInputError('완화 통제 승인 상태 오류')
    for f,cols in [(a,['granted_at','removed_at']),(mit,['approved_at','expires_at'])]:
        for c in cols:
            raw=f[c].replace('',pd.NA);parsed=pd.to_datetime(raw,format='mixed',errors='coerce')
            if (raw.notna() & parsed.isna()).any():raise SoDInputError(c+': 날짜 형식 오류')
            if isinstance(parsed.dtype,pd.DatetimeTZDtype):raise SoDInputError('시간대 표기 없이 KST로 입력해주세요.')
            f[c]=parsed
    if a.granted_at.isna().any():raise SoDInputError('권한 부여일 누락')
    if (a.removed_at<a.granted_at).any():raise SoDInputError('회수일이 부여일보다 빠릅니다.')
    snap=pd.Timestamp(snapshot)
    if snap.tzinfo:raise SoDInputError('기준일은 시간대 표기 없이 KST로 입력해주세요.')
    joined=a.merge(users,on='user_id',how='left',validate='many_to_one')
    in_period=(joined.granted_at<=snap)&(joined.removed_at.isna()|(joined.removed_at>snap))
    active=joined[in_period & joined.account_status.eq('Active').fillna(False)].copy()
    # Many-to-many is intended: one role expands into multiple permissions.
    expanded=active.merge(mp,on='role_id',how='left',validate='many_to_many')
    dq=[]
    for label,rows in [('계정 명부 미연결',joined[joined.account_status.isna()]),('현재 역할의 권한 매핑 없음',expanded[expanded.permission_id.isna()]),('동일 계정·역할 중복 배정',active[active.duplicated(['user_id','role_id'],keep=False)])]:
        for _,row in rows.iterrows():dq.append({'assignment_id':row.assignment_id,'user_id':row.user_id,'role_id':row.role_id,'자료 확인':label})
    known=set(mp.permission_id)
    unknown_rules=set(rules.permission_a)|set(rules.permission_b)
    for perm in sorted(unknown_rules-known):dq.append({'assignment_id':'','user_id':'','role_id':'','자료 확인':'규칙 권한 매핑 없음: '+perm})
    candidates=[]
    for uid,group in expanded.groupby('user_id',sort=True):
        permissions=set(group.permission_id.dropna())
        for _,rule in rules.iterrows():
            if not {rule.permission_a,rule.permission_b}.issubset(permissions):continue
            row={'user_id':uid,'employee_id':group.employee_id.iloc[0],'department':group.department.iloc[0],'rule_id':rule.rule_id,'permission_a':rule.permission_a,'permission_b':rule.permission_b,'risk_description':rule.risk_description,'severity':rule.severity}
            for suffix,perm in [('a',rule.permission_a),('b',rule.permission_b)]:
                source=group[group.permission_id.eq(perm)]
                row['role_'+suffix]=', '.join(sorted(set(source.role_id)))
                row['assignment_'+suffix]=', '.join(sorted(set(source.assignment_id)))
            match=mit[mit.user_id.eq(uid)&mit.rule_id.eq(rule.rule_id)]
            row.update({'완화 통제 검토':'완화 통제 기록 없음','mitigation_id':'','control_description':'','evidence_ref':''})
            if len(match):
                record=match.iloc[0]
                row.update({k:record[k] for k in ['mitigation_id','control_description','evidence_ref']})
                if record.approval_status!='Approved':row['완화 통제 검토']='완화 통제 승인 확인 필요'
                elif pd.isna(record.approved_at) or record.approved_at>snap:row['완화 통제 검토']='완화 통제 승인 시점 확인 필요'
                elif pd.isna(record.expires_at):row['완화 통제 검토']='완화 통제 유효기간 확인 필요'
                elif record.expires_at<=snap:row['완화 통제 검토']='완화 통제 만료 검토'
                elif pd.isna(record.evidence_ref) or pd.isna(record.control_description):row['완화 통제 검토']='완화 통제 증빙 확인 필요'
                else:row['완화 통제 검토']='유효 승인 기록 있음·운영 증빙 검토'
            candidates.append(row)
    columns=['user_id','employee_id','department','rule_id','permission_a','permission_b','role_a','role_b','assignment_a','assignment_b','risk_description','severity','완화 통제 검토','mitigation_id','control_description','evidence_ref']
    conflicts=pd.DataFrame(candidates,columns=columns)
    summary=conflicts.groupby(['rule_id','완화 통제 검토']).size().reset_index(name='건수') if len(conflicts) else pd.DataFrame(columns=['rule_id','완화 통제 검토','건수'])
    meta=pd.DataFrame([{'항목':k,'값':str(v)} for k,v in [('기준일(KST)',snap),('전체 계정',len(users)),('전체 권한 배정',len(a)),('현재 활성계정 권한 배정',len(active)),('권한 확장 행',len(expanded)),('충돌 계정·규칙 조합',len(conflicts)),('충돌 고유 계정',conflicts.user_id.nunique()),('규칙 버전','case03-v1.0'),('검사 범위','계정 단위 잠재적 권한 충돌; 실제 거래 위반 판정 별도')]])
    return {'검사 기준':meta,'충돌 요약':summary,'SoD 검토 후보':conflicts,'자료 확인':pd.DataFrame(dq,columns=['assignment_id','user_id','role_id','자료 확인']),'현재 권한 상세':expanded,'검사 규칙':rules}
