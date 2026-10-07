import pandas as pd
from access_check import inspect_terminated_accounts
from privileged_check import inspect_privileged_jml,SCHEMA as S2
from sod_check import inspect_sod,SCHEMA as S3
from change_check import inspect_changes,SCHEMA as S4
from finance_checks import inspect_finance,SCHEMAS
SCHEMAS.update({1:{'HR_Master':['employee_id','employment_status','termination_date'],'ERP_User_Master':['user_id','employee_id','account_status','disabled_at']},2:S2,3:S3,4:S4})
NAMES={1:'퇴사자 계정',2:'관리자 권한·JML',3:'직무분리',4:'변경관리',5:'인터페이스 대사',6:'전표 검사',7:'지급·공급업체',8:'위험 점수·이상치'}
RISKS={1:'퇴사 후 무단 접근',2:'과도한 권한·인사 변경 후 권한 잔존',3:'상충 권한을 통한 승인 우회',4:'미승인·미검증 변경의 운영 반영',5:'누락·중복·금액 불일치',6:'비정상 전표·승인 우회',7:'중복 지급·부적절한 공급업체',8:'통상 패턴에서 벗어난 거래'}
CONTROLS={1:'퇴사자 권한 적시 회수',2:'업무 필요성·독립 승인·JML 회수',3:'상충 권한 제한 및 보완통제',4:'승인·테스트·독립 배포',5:'전송·수신 완전성 및 금액 대사',6:'전표 균형·독립 승인·기간 검토',7:'송장 중복 통제·공급업체 관리',8:'위험 기반 거래 검토'}

def execute(case,tables,config):
    for n,cols in SCHEMAS[case].items():
        if n not in tables or set(cols)-set(tables[n].columns):raise ValueError(n+' 필수 시트·열 확인')
    cand=[]
    def add(entity,rule,reason,evidence,ref,severity='Medium'):
        cand.append(dict(entity_id=str(entity),rule_id=rule,reason=str(reason),evidence_request=evidence,source_ref=ref,severity=severity))
    if case>=5:
        result,population=inspect_finance(case,tables,config);cand=result['검토 후보'].to_dict('records')
    elif case==1:
        erp=tables['ERP_User_Master'];hr=tables['HR_Master'].copy()
        snap=pd.Timestamp(config['snapshot'])
        if pd.isna(snap) or snap.tzinfo:raise ValueError('기준일 오류')
        # Validate complete input first, then restrict termination population to snapshot.
        result0,unmatched=inspect_terminated_accounts(hr,erp)
        r=result0[result0.termination_date.le(snap)].copy()
        for _,row in r.iterrows():
            if row.account_status=='Active' or row['회수검사']!='기한 내 회수':
                add(row.user_id,'ACC01',row['회수검사']+'; '+str(row['검토 메모']),'비활성화 로그·처리 티켓·기준일 계정 추출', 'ERP_User_Master:user_id='+str(row.user_id))
        for _,row in unmatched.iterrows():add(row.user_id,'DQ01','HR 미연결 계정','계정 소유자·서비스 계정 등록','ERP_User_Master:user_id='+str(row.user_id))
        result={'퇴사자 검사':r,'HR 미연결':unmatched};population=len(erp)
    elif case==2:
        result=inspect_privileged_jml(*[tables[n] for n in S2],snapshot=config['snapshot']);population=len(tables['ERP_User_Roles'])
        checks={'부서 검사':{'부서 일치'},'직무 검사':{'직무 일치'},'승인 시점 검사':{'승인시점 충족'},'승인자 검사':{'승인자 일치'},'만료 검사':{'만료일 없음','유효기간 내','만료 후 회수 기록 있음'}}
        # Actual engine success labels are resolved explicitly below.
        checks['부서 검사'].update({'허용 부서 일치'});checks['직무 검사'].update({'허용 직무 일치'});checks['승인 시점 검사'].update({'부여 전 또는 동시 승인','기한 내 승인'})
        for _,row in result['관리자권한 검사'].iterrows():
            for col,ok in checks.items():
                if row[col] not in ok:add(row.assignment_id,'PRV-'+col,row[col],'권한 요청·독립 승인·직무 근거','ERP_User_Roles:assignment_id='+str(row.assignment_id))
        for label in ['입사전 권한부여','이동후 권한잔존']:
            for _,row in result[label].iterrows():add(row.assignment_id,'JML-'+label,label,'인사 이벤트·권한 변경 로그','ERP_User_Roles:assignment_id='+str(row.assignment_id))
        for _,row in result['퇴사자 권한 검토'].iterrows():
            if row['회수 검사'] not in ['기한 내 권한 회수 기록','회수 기한 미도래'] or row['계정 검토']=='퇴사자 활성 계정 검토':add(row.assignment_id,'JML-Leaver',row['회수 검사']+'; '+row['계정 검토'],'퇴사 처리 티켓·권한 및 계정 회수 로그','ERP_User_Roles:assignment_id='+str(row.assignment_id))
        for _,row in result['자료 확인'].iterrows():add(row.assignment_id,'DQ02',row['자료 확인 사항'],'원본 연결·ID 확인','ERP_User_Roles:assignment_id='+str(row.assignment_id))
    elif case==3:
        result=inspect_sod(*[tables[n] for n in S3],snapshot=config['snapshot']);population=len(tables['ERP_Users'])
        for _,row in result['SoD 검토 후보'].iterrows():add(row.user_id,row.rule_id,row.risk_description+'; '+row['완화 통제 검토'],'역할 승인·보완통제 운영 증빙',f'User_Roles:{row.assignment_a};{row.assignment_b}',row.severity)
        for _,row in result['자료 확인'].iterrows():add(row.get('assignment_id',''),'DQ03',row['자료 확인'],'권한 매핑·계정 명부','User_Roles:'+str(row.get('assignment_id','')))
    else:
        result=inspect_changes(*[tables[n] for n in S4],snapshot=config['snapshot'],emergency_hours=config['emergency_hours']);population=len(result['배포 검사'])
        for _,row in result['검토 후보'].iterrows():add(row.deployment_id,row.rule_id,row['추출 이유'],row['요청 증빙'],str(row.log_ref)+';'+str(row.ticket_ref))
    # Stable within a run, repeated entity/rule candidates retain distinct IDs.
    for i,c in enumerate(cand,1):c['candidate_id']=f'C{case:02}-{i:04}'
    return result,cand,population
