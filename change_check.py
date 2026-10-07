"""Case04: synthetic-company change policy; findings require human review."""
import pandas as pd

class ChangeInputError(ValueError):
    pass

SCHEMA = {
 'Deployment_Log':['deployment_id','change_id','system','environment','deployed_at','deployed_by','deployment_status','log_ref'],
 'Change_Requests':['change_id','change_type','requested_at','developer_id','approval_status','approved_at','approver_id','emergency_reason','ticket_ref'],
 'Test_Results':['change_id','test_status','tested_at','tester_id','evidence_ref']}

def read_case04(file):
    return [pd.read_excel(file,sheet_name=s) for s in SCHEMA]

def inspect_changes(deployments, requests, tests, snapshot='2026-09-30 18:00', emergency_hours=48):
    snapshot=pd.Timestamp(snapshot)
    if pd.isna(snapshot) or snapshot.tzinfo is not None:
        raise ChangeInputError('기준일은 시간대 없는 한국 현지 날짜·시간이어야 합니다.')
    if not 0 < float(emergency_hours) <= 720:
        raise ChangeInputError('긴급 승인 기한은 0시간 초과 720시간 이하입니다.')
    frames=[]
    for (sheet,cols),data in zip(SCHEMA.items(),[deployments,requests,tests]):
        missing=set(cols)-set(data.columns)
        if missing:raise ChangeInputError(f'{sheet} 필수 열 누락: {sorted(missing)}')
        f=data[cols].copy()
        for col in f.select_dtypes(include=['object','string']).columns:
            f[col]=f[col].map(lambda x:x.strip() if isinstance(x,str) else x)
            f[col]=f[col].replace('',pd.NA)
        key='deployment_id' if sheet=='Deployment_Log' else 'change_id'
        if f[key].isna().any() or f[key].duplicated().any():
            raise ChangeInputError(f'{sheet}.{key}: 빈값·중복 불가. 테스트는 변경별 최종 결과 한 건을 제공하세요.')
        for col in [c for c in cols if c.endswith('_at')]:
            original=f[col];parsed=pd.to_datetime(original,errors='coerce')
            if (original.notna() & parsed.isna()).any():raise ChangeInputError(f'{sheet}.{col} 날짜 형식 오류')
            if getattr(parsed.dt,'tz',None) is not None:raise ChangeInputError('날짜는 한국 현지 시각으로 통일해주세요.')
            f[col]=parsed
        frames.append(f)
    d,r,t=frames
    for f,col,allowed in [(d,'environment',{'Production','Test'}),(d,'deployment_status',{'Success','Failed'}),(r,'change_type',{'Normal','Emergency'}),(r,'approval_status',{'Approved','Pending','Rejected'}),(t,'test_status',{'Passed','Failed','Pending'})]:
        if (~f[col].isin(allowed)).any():raise ChangeInputError(f'{col} 허용값: {sorted(allowed)}')
    if d.deployed_at.isna().any():raise ChangeInputError('배포 시각은 필수입니다.')
    eligible=d[(d.environment=='Production')&(d.deployment_status=='Success')&(d.deployed_at<=snapshot)]
    joined=eligible.merge(r,on='change_id',how='left',validate='many_to_one',indicator='_request').merge(t,on='change_id',how='left',validate='many_to_one',indicator='_test')
    issues=[];dq=[];rows=[]
    def issue(row,code,reason,evidence,status='검토 대상'):
        issues.append({'candidate_id':f"{row.deployment_id}:{code}",'deployment_id':row.deployment_id,'change_id':row.change_id,'rule_id':code,'검토 상태':status,'추출 이유':reason,'요청 증빙':evidence,'log_ref':row.log_ref,'ticket_ref':row.get('ticket_ref')})
    for _,row in joined.iterrows():
        approval='기준 충족';testing='기준 충족';separation='기준 충족'
        if row['_request']=='left_only':
            approval='요청 미연결';separation='추가 확인 필요'
            dq.append({'deployment_id':row.deployment_id,'change_id':row.change_id,'자료 확인':'변경 요청 미연결'})
            issue(row,'CHG01','배포에 연결되는 변경 요청 없음','변경 티켓 및 ID 연결 근거')
        else:
            emergency=row.change_type=='Emergency'
            deadline=row.deployed_at+pd.Timedelta(hours=float(emergency_hours)) if emergency else row.deployed_at
            if emergency and pd.isna(row.emergency_reason):
                issue(row,'CHG02','긴급 사유 기록 없음','긴급 변경 사유 및 예외 승인')
            if row.approval_status!='Approved' or pd.isna(row.approved_at):
                pending=emergency and snapshot<deadline
                approval='기한 미도래·후속 확인' if pending else '승인 확인 필요'
                issue(row,'CHG03','승인 상태 또는 승인 시각 미충족','승인 이력·승인서',approval)
            elif row.approved_at>deadline:
                approval='승인 지연';issue(row,'CHG04','정책상 승인 기한 이후 승인','승인·배포 이력 및 지연 사유')
            elif row.approved_at>snapshot:
                approval='기준일 이후 승인';issue(row,'CHG03','기준일 현재 승인 증빙 없음','기준일 이전 승인 이력')
            if pd.isna(row.requested_at) or row.requested_at>row.deployed_at:
                issue(row,'CHG05','요청 시각 누락 또는 배포 이후 요청','변경 요청 원본 및 긴급 처리 절차')
            if pd.isna(row.developer_id) or pd.isna(row.deployed_by) or pd.isna(row.approver_id):
                separation='담당자 확인 필요';issue(row,'CHG06','개발·배포·승인 담당자 기록 누락','담당자 및 직무분리 증빙')
            else:
                if row.developer_id==row.deployed_by:
                    separation='직무분리 검토';issue(row,'CHG07','개발자와 운영 배포자가 동일','배포 권한·독립 검토·예외 승인')
                if row.developer_id==row.approver_id:
                    separation='직무분리 검토';issue(row,'CHG08','개발자와 승인자가 동일','독립 승인 및 보완통제 증빙')
        if row['_test']=='left_only':
            testing='테스트 미연결';issue(row,'CHG09','연결되는 테스트 기록 없음','해당 버전의 배포 전 테스트 결과')
            dq.append({'deployment_id':row.deployment_id,'change_id':row.change_id,'자료 확인':'테스트 기록 미연결'})
        elif row.test_status!='Passed' or pd.isna(row.tested_at) or row.tested_at>row.deployed_at:
            testing='테스트 기준 미충족';issue(row,'CHG10','테스트 실패·미완료 또는 배포 후 테스트','배포 버전별 테스트 결과·완료 시각')
        if row['_test']=='both' and (pd.isna(row.evidence_ref) or pd.isna(row.tester_id)):
            issue(row,'CHG11','테스트 담당자 또는 증빙 참조 누락','테스트 담당자·결과 원본')
        rows.append({**row.to_dict(),'승인 검사':approval,'테스트 검사':testing,'직무분리 검사':separation})
    result=pd.DataFrame(rows,columns=[*joined.columns,'승인 검사','테스트 검사','직무분리 검사']).drop(columns=['_request','_test'])
    candidates=pd.DataFrame(issues,columns=['candidate_id','deployment_id','change_id','rule_id','검토 상태','추출 이유','요청 증빙','log_ref','ticket_ref'])
    summary=pd.DataFrame([['전체 배포',len(d)],['검사 모집단',len(eligible)],['제외 배포',len(d)-len(eligible)],['검토 후보(규칙별)',len(candidates)],['검토 대상 배포',candidates.deployment_id.nunique()]],columns=['항목','건수'])
    policy=pd.DataFrame([['기준일',str(snapshot)],['긴급 승인 기한(시간)',str(emergency_hours)],['일반 승인','Approved 및 승인 시각 ≤ 배포 시각'],['테스트','Passed 및 테스트 시각 ≤ 배포 시각'],['정책','합성 회사 정책. 최종 감사 판단은 검토자 수행']],columns=['항목','기준'])
    return {'검사 요약':summary,'검토 후보':candidates,'배포 검사':result,'자료 확인':pd.DataFrame(dq,columns=['deployment_id','change_id','자료 확인']),'검사 기준':policy}
