"""Case 01: 합성 자료용 퇴사자 계정 회수 검사."""
import pandas as pd

class InputError(ValueError):
    pass

def inspect_terminated_accounts(hr, erp):
    hr = hr.copy(); erp = erp.copy()
    required = [(hr, ['employee_id','employment_status','termination_date'], 'HR'),
                (erp, ['user_id','employee_id','account_status','disabled_at'], 'ERP')]
    for frame, cols, label in required:
        missing = set(cols) - set(frame.columns)
        if missing:
            raise InputError(f'{label} 필수 열 누락: {", ".join(sorted(missing))}')
        frame['employee_id'] = frame['employee_id'].astype('string').str.strip().replace('', pd.NA)
    if hr['employee_id'].isna().any() or hr['employee_id'].duplicated().any():
        raise InputError('HR 사번에 빈 값 또는 중복이 있습니다. 원본을 확인해주세요.')
    if erp['user_id'].isna().any() or erp['user_id'].duplicated().any():
        raise InputError('ERP 계정 ID에 빈 값 또는 중복이 있습니다.')
    for frame, col in [(hr,'termination_date'), (erp,'disabled_at')]:
        raw = frame[col].replace(r'^\s*$', None, regex=True)
        dates = pd.to_datetime(raw, errors='coerce')
        if (raw.notna() & dates.isna()).any():
            raise InputError(f'{col}에 해석할 수 없는 날짜가 있습니다.')
        frame[col] = dates
    if not hr['employment_status'].isin(['Employed','Terminated']).all():
        raise InputError('HR 상태값은 Employed 또는 Terminated여야 합니다.')
    if not erp['account_status'].isin(['Active','Disabled']).all():
        raise InputError('ERP 상태값은 Active 또는 Disabled여야 합니다.')
    if hr.loc[hr['employment_status'].eq('Terminated'),'termination_date'].isna().any():
        raise InputError('퇴사자의 퇴사일이 누락되었습니다.')
    # HR 원본 열만 연결: 업로드 파일에 있는 Excel 계산 열과 충돌 방지
    merged = erp.merge(hr[['employee_id','employment_status','termination_date']],
                       on='employee_id', how='left', validate='many_to_one', indicator=True)
    unmatched = merged.loc[merged['_merge'].eq('left_only')].drop(columns='_merge').copy()
    terminated = merged.loc[merged['employment_status'].eq('Terminated')].drop(columns='_merge').copy()
    terminated['회수 기한'] = terminated['termination_date'].dt.normalize() + pd.Timedelta(days=1)
    terminated['회수검사'] = '추가 확인 필요'
    terminated.loc[terminated['disabled_at'] < terminated['회수 기한'],'회수검사'] = '기한 내 회수'
    terminated.loc[terminated['disabled_at'] >= terminated['회수 기한'],'회수검사'] = '회수 지연'
    terminated['검토 메모'] = ''
    terminated.loc[terminated['account_status'].eq('Active'),'검토 메모'] = '퇴사 후 활성 상태 확인 필요'
    terminated.loc[terminated['account_status'].eq('Active') & terminated['disabled_at'].notna(),'검토 메모'] = '활성 상태와 비활성화 기록 불일치: 변경 이력 확인 필요'
    return terminated, unmatched
