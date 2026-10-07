"""Case02: synthetic-data access review; outputs are review candidates."""
import pandas as pd

class Case02InputError(ValueError):
    pass

SCHEMA = {
    "HR_Master": ["employee_id", "department", "job_title", "employment_status", "hire_date", "termination_date"],
    "ERP_User_Roles": ["assignment_id", "user_id", "employee_id", "account_status", "role_id", "granted_at", "removed_at", "request_id"],
    "Role_Catalog": ["role_id", "is_privileged", "allowed_department", "allowed_job_title", "required_approver_role"],
    "Access_Requests": ["request_id", "assignment_id", "approval_status", "approved_at", "approver_role", "expires_at"],
    "JML_Events": ["employee_id", "event_type", "effective_date", "old_department", "new_department"]
}

def inspect_privileged_jml(hr, erp, roles, requests, jml, snapshot="2026-09-30 18:00:00"):
    """Validate five populations, preserve ERP rows, classify review candidates.
    This version expects at most one JML event per employee in the review period.
    Dates are timezone-naive KST. Revocation must precede next-day midnight.
    """
    frames = [hr, erp, roles, requests, jml]
    clean = []
    for (name, required), frame in zip(SCHEMA.items(), frames):
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise Case02InputError(f"{name}: 필수 열 누락 {', '.join(missing)}")
        f = frame[required].copy()
        for col in f.columns:
            if not col.endswith(('_at', '_date')):
                f[col] = f[col].astype('string').str.strip().replace('', pd.NA)
        clean.append(f)
    hr, erp, roles, requests, jml = clean
    for name, f, key in [("HR",hr,"employee_id"),("ERP",erp,"assignment_id"),("역할",roles,"role_id"),("승인",requests,"request_id"),("인사 변경",jml,"employee_id")]:
        if f[key].isna().any() or f[key].duplicated().any():
            raise Case02InputError(f"{name}: {key} 누락 또는 중복. 인사 변경은 직원당 한 건으로 정리해주세요.")
    for name, f, col, allowed in [("HR",hr,"employment_status",['Employed','Terminated']), ("ERP",erp,"account_status",['Active','Disabled']), ("역할",roles,"is_privileged",['Yes','No']), ("승인",requests,"approval_status",['Approved','Pending','Rejected']), ("인사 변경",jml,"event_type",['Joiner','Mover','Leaver'])]:
        if not f[col].isin(allowed).all():
            raise Case02InputError(f"{name}: {col} 상태값은 {allowed}를 사용해주세요.")
    for f, cols in [(hr,['hire_date','termination_date']), (erp,['granted_at','removed_at']), (requests,['approved_at','expires_at']), (jml,['effective_date'])]:
        for c in cols:
            raw=f[c].replace('',pd.NA)
            parsed=pd.to_datetime(raw, format='mixed', errors='coerce')
            if (raw.notna() & parsed.isna()).any():
                raise Case02InputError(f"{c}: 해석할 수 없는 날짜가 있습니다.")
            if isinstance(parsed.dtype, pd.DatetimeTZDtype):
                raise Case02InputError(f"{c}: 시간대 표기 없이 KST로 입력해주세요.")
            f[c]=parsed
    snapshot=pd.Timestamp(snapshot)
    if snapshot.tzinfo is not None:
        raise Case02InputError('기준일은 시간대 표기 없이 KST로 입력해주세요.')
    m=erp.merge(hr,on='employee_id',how='left',validate='many_to_one')
    m=m.merge(roles,on='role_id',how='left',validate='many_to_one')
    m=m.merge(requests,on='request_id',how='left',validate='many_to_one',suffixes=('','_request'))
    m=m.merge(jml,on='employee_id',how='left',validate='many_to_one')
    if len(m)!=len(erp):
        raise Case02InputError('연결 전후 권한 행 수가 다릅니다.')
    # All uploaded assignments must already have been granted by snapshot.
    if m.granted_at.isna().any() or (m.granted_at > snapshot).any():
        raise Case02InputError('권한 부여일 누락 또는 기준일 이후 권한이 있습니다. 기준일 모집단을 확인해주세요.')
    outstanding=m.removed_at.isna() | (m.removed_at > snapshot)
    priv=m[m.is_privileged.eq('Yes').fillna(False)].copy()
    for source, target, label in [('department','allowed_department','부서'),('job_title','allowed_job_title','직무')]:
        priv[label+' 검사']=label+' 일치'
        priv.loc[priv[source].ne(priv[target]).fillna(False),label+' 검사']=label+' 불일치 검토'
        priv.loc[priv[source].isna(),label+' 검사']='소유자 확인 필요'
    approved=priv.approval_status.eq('Approved').fillna(False)
    has_date=priv.approved_at.notna() & priv.granted_at.notna()
    priv['승인 시점 검사']='승인 확인 필요'
    priv.loc[approved & ~has_date,'승인 시점 검사']='날짜 확인 필요'
    priv.loc[approved & has_date & (priv.approved_at<=priv.granted_at),'승인 시점 검사']='승인시점 충족'
    priv.loc[approved & has_date & (priv.approved_at>priv.granted_at),'승인 시점 검사']='사후 승인 검토'
    priv['승인자 검사']='승인 확인 필요'
    has_approver=priv.approver_role.notna() & priv.required_approver_role.notna()
    priv.loc[approved & ~has_approver,'승인자 검사']='승인자 정보 확인 필요'
    same=priv.approver_role.eq(priv.required_approver_role).fillna(False)
    priv.loc[approved & has_approver & same,'승인자 검사']='승인자 일치'
    priv.loc[approved & has_approver & ~same,'승인자 검사']='승인자 불일치 검토'
    priv['만료 검사']='만료일 없음'
    priv.loc[priv.expires_at.notna(),'만료 검사']='유효기간 내'
    expired=priv.expires_at < snapshot
    priv.loc[expired,'만료 검사']='만료 후 회수 기록 있음'
    active=priv.removed_at.isna() | (priv.removed_at>snapshot)
    priv.loc[expired & active,'만료 검사']='만료 후 권한 잔존 검토'
    priv.loc[priv.assignment_id_request.isna(),'만료 검사']='승인 기록 확인 필요'
    # Preserve all permissions for JML tests; compare against actual event dates.
    leaver=m.employment_status.eq('Terminated').fillna(False)
    leavers=m[leaver].copy()
    leavers['회수 기한']=leavers.termination_date.dt.normalize()+pd.Timedelta(days=1)
    leavers['회수 검사']='기한 내 권한 회수 기록'
    leavers.loc[leavers.removed_at.isna(),'회수 검사']='권한 회수 기록 확인 필요'
    leavers.loc[leavers.removed_at>=leavers['회수 기한'],'회수 검사']='권한 회수 지연 검토'
    leavers.loc[leavers['회수 기한']>snapshot,'회수 검사']='회수 기한 미도래'
    leavers.loc[leavers.termination_date.isna(),'회수 검사']='퇴사일 확인 필요'
    leavers['계정 검토']='비활성화 일시 증빙 필요'
    leavers.loc[leavers.account_status.eq('Active'),'계정 검토']='퇴사자 활성 계정 검토'
    joiners=m[m.hire_date.notna() & (m.granted_at<m.hire_date.dt.normalize())].copy()
    mover=m.event_type.eq('Mover').fillna(False)
    old_role=m.allowed_department.eq(m.old_department).fillna(False)
    changed=m.department.ne(m.allowed_department).fillna(False)
    previous=m.granted_at<m.effective_date
    deadline=m.effective_date.dt.normalize()+pd.Timedelta(days=1)
    late=m.removed_at.isna() | (m.removed_at>=deadline)
    movers=m[mover & old_role & changed & previous & late & (deadline<=snapshot)].copy()
    movers['회수 기한']=deadline.loc[movers.index]
    issues=[]
    for label, mask in [('HR 미연결',m.employment_status.isna()),('역할 기준 미연결',m.is_privileged.isna()),('승인 기록 미연결',m.assignment_id_request.isna()),('승인-권한 배정 ID 불일치',m.assignment_id_request.notna() & m.assignment_id.ne(m.assignment_id_request).fillna(False)),('동일 계정·역할 중복',m.duplicated(['user_id','role_id'],keep=False)),('회수일이 부여일보다 빠름',m.removed_at<m.granted_at)]:
        rows=m.loc[mask,['assignment_id','user_id','employee_id','role_id']].copy()
        rows['자료 확인 사항']=label
        issues.append(rows)
    dq=pd.concat(issues,ignore_index=True)
    summary=[]
    for c in ['부서 검사','직무 검사','승인 시점 검사','승인자 검사','만료 검사']:
        for result,n in priv[c].value_counts().items():
            summary.append({'검사':c,'분류':result,'건수':int(n)})
    for label,f in [('퇴사자 권한 검토',leavers),('입사 전 권한 부여',joiners),('이동 후 기존 권한',movers)]:
        summary.append({'검사':label,'분류':'검토 행 수','건수':len(f)})
    meta=pd.DataFrame([{'항목':'기준일(KST)','값':str(snapshot)}, {'항목':'ERP 권한 배정 건수','값':str(len(erp))},{'항목':'관리자 권한 배정 건수','값':str(len(priv))},{'항목':'규칙 버전','값':'case02-v1.0'}, {'항목':'회수 기한','값':'인사 변경일 다음 날 00:00 이전'}, {'항목':'결과 성격','값':'예외 후보; 증빙 검토 및 최종 감사 결론 별도'}])
    return {'검사 기준':meta,'검사 요약':pd.DataFrame(summary),'자료 확인':dq,'관리자권한 검사':priv,'퇴사자 권한 검토':leavers,'입사전 권한부여':joiners,'이동후 권한잔존':movers}

def read_case02(file):
    with pd.ExcelFile(file) as book:
        missing=set(SCHEMA)-set(book.sheet_names)
        if missing:
            raise Case02InputError('필수 시트 누락: '+', '.join(sorted(missing)))
        return [pd.read_excel(book,sheet_name=name,usecols=lambda c: c in cols) for name,cols in SCHEMA.items()]
