import io
import pandas as pd
from flask import request, render_template, send_file
from change_check import read_case04,inspect_changes,ChangeInputError

def register_case04(app):
    @app.route('/case04',methods=['GET','POST'])
    def case04():
        if request.method=='GET':return render_template('case04.html')
        file=request.files.get('file')
        if not file or not file.filename.lower().endswith('.xlsx'):
            return render_template('case04.html',error='xlsx 파일을 선택해주세요.'),400
        try:
            tables=inspect_changes(*read_case04(file),snapshot=request.form.get('snapshot') or '2026-09-30T18:00',emergency_hours=float(request.form.get('hours') or 48))
        except ChangeInputError as e:return render_template('case04.html',error=str(e)),400
        except Exception:
            app.logger.exception('Case04 validation failed')
            return render_template('case04.html',error='필수 시트·열·날짜 및 기준 설정을 확인해주세요.'),400
        if request.form.get('action')=='download':
            b=io.BytesIO()
            with pd.ExcelWriter(b,engine='openpyxl') as writer:
                for name,f in tables.items():
                    safe=f.copy()
                    for col in safe.select_dtypes(include=['object','string']).columns:
                        safe[col]=safe[col].map(lambda v:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
                    safe.to_excel(writer,sheet_name=name,index=False)
            b.seek(0)
            return send_file(b,as_attachment=True,download_name='case04_results.xlsx')
        views={name:f.head(200).to_html(index=False,escape=True,na_rep='—') for name,f in tables.items()}
        return render_template('case04.html',tables=views)
