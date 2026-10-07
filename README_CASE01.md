# AuditAI Case 01 업데이트
기존 거래 검사에 /case01 화면을 추가했습니다. 공개 배포는 아직 수행하지 않았습니다.

실행: `pip install -r requirements.txt` 후 `python app.py`, http://127.0.0.1:5000/case01 접속.
Render 기존 설정: `gunicorn app:app` (Procfile 유지).

HR_Master, ERP_User_Master 시트가 들어 있는 xlsx 파일을 업로드합니다. ERP 원본 열 순서는 연습 자료 A:F와 동일해야 합니다. 상태값은 HR Employed/Terminated, ERP Active/Disabled입니다. 열 매핑 및 회사별 정책 설정은 아직 구현하지 않았습니다.

access_check.py에 학습 코드 기반 검사 함수를 분리했습니다. 앱에서는 결과 표와 HR 미연결 표 두 개를 반환받습니다. 필수 열, 중복/빈 HR 사번, ERP ID, 상태값, 날짜 검증을 추가했습니다. 회수 기한은 퇴사일 다음 날 자정이며 일시는 KST로 해석합니다. 입력 파일의 완전성과 추출 기준일은 별도 확인해야 합니다.

업로드 자료와 결과를 영구 저장하지 않습니다. 다운로드는 선택한 파일을 재검사합니다. 증거 첨부/검토 저장, 사용자 인증, 회사별 양식 매핑은 후속 구현 대상입니다. 기존 1.0의 전역 last_result 방식은 기존 거래 기능에 남아 있어 다중 사용자 상용 서비스로 사용하면 안 됩니다. Case01은 전역 결과 저장을 사용하지 않습니다.

학습 포인트: def(검사 정의), return(결과 전달), Flask POST(업로드 수신), render_template(화면 출력), send_file(다운로드).
