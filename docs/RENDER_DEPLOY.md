# Render 배포 설정

Python Web Service로 앱 폴더를 배포합니다. Git 저장소에 이 폴더의 파일이 들어 있어야 합니다.

- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120`
- 환경 변수: SECRET_KEY(무작위 비밀값), AUDITAI_SECURE_COOKIE=1
- Health Check: /
- render.yaml: 무료 데모 설정. 유료 결제는 포함하지 않습니다.

무료 데모의 로컬 SQLite와 원본 파일은 영구 보존이 보장되지 않습니다. 재배포·인스턴스 교체 때 기록이 사라질 수 있습니다. 합성 자료 시연 및 결과 다운로드용으로 사용합니다. 영구 보존 운영은 지속 디스크 또는 외부 데이터베이스로 별도 구성해야 합니다. 실제 고객 자료 운영은 현재 범위가 아닙니다.

배포 후 확인: 8개 합성 예제 실행, 후보 목록, 결과 XLSX 다운로드, 검토 기록 및 작업조서 다운로드. 배포 URL은 서비스가 Live가 되고 공개 주소에서 기능 확인을 마친 뒤 이력서에 기재합니다.
