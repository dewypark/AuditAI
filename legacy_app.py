from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import io
from datetime import datetime

app = Flask(__name__)
last_result = {}

from access_check import inspect_terminated_accounts, InputError
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

@app.errorhandler(413)
def too_large(error):
    return "파일은 10MB 이하로 업로드해주세요.", 413

@app.route('/case01', methods=['GET', 'POST'])
def case01():
    if request.method == 'GET':
        return render_template('case01.html')
    file = request.files.get('file')
    if not file or not file.filename.lower().endswith('.xlsx'):
        return render_template('case01.html', error='xlsx 파일을 선택해주세요.'), 400
    try:
        hr = pd.read_excel(file, sheet_name='HR_Master')
        file.seek(0)
        erp = pd.read_excel(file, sheet_name='ERP_User_Master', usecols='A:F')
        result, unmatched = inspect_terminated_accounts(hr, erp)
    except (InputError, ValueError, KeyError) as exc:
        return render_template('case01.html', error=str(exc)), 400
    except Exception:
        app.logger.exception('Case01 workbook read failed')
        return render_template('case01.html', error='파일을 읽지 못했습니다. 정상적인 Excel 파일인지 확인해주세요.'), 400
    if request.form.get('action') == 'download':
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            result.to_excel(writer, sheet_name='퇴사자 검사', index=False)
            unmatched.to_excel(writer, sheet_name='HR 미연결', index=False)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name='case01_results.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return render_template('case01.html', counts=result['회수검사'].value_counts().to_dict(),
        total=len(erp), terminated_count=len(result), unmatched_count=len(unmatched),
        table=result.to_html(index=False, classes='results', na_rep='—'),
        unmatched_table=unmatched.to_html(index=False, classes='results', na_rep='—'))



from privileged_check import inspect_privileged_jml, read_case02, Case02InputError

@app.route('/case02', methods=['GET', 'POST'])
def case02():
    if request.method == 'GET':
        return render_template('case02.html')
    file = request.files.get('file')
    if not file or not file.filename.lower().endswith('.xlsx'):
        return render_template('case02.html', error='xlsx 파일을 선택해주세요.'), 400
    snapshot = request.form.get('snapshot') or '2026-09-30T18:00'
    try:
        tables = inspect_privileged_jml(*read_case02(file), snapshot=snapshot)
    except (Case02InputError, ValueError, KeyError, TypeError):
        app.logger.info('Case02 validation failed', exc_info=True)
        # Show expected validation errors without exposing filesystem details.
        import sys
        exc=sys.exc_info()[1]
        message=str(exc) if isinstance(exc, Case02InputError) else '파일의 열·날짜·기준일 형식을 확인해주세요.'
        return render_template('case02.html', error=message), 400
    except Exception:
        app.logger.exception('Case02 workbook read failed')
        return render_template('case02.html', error='정상적인 xlsx 파일인지 확인해주세요.'), 400
    if request.form.get('action') == 'download':
        buffer=io.BytesIO()
        with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
            for name,frame in tables.items():
                safe=frame.copy()
                # Prevent user-controlled Excel formulas in downloaded results.
                for col in safe.select_dtypes(include=['object','string']).columns:
                    safe[col]=safe[col].map(lambda v: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
                safe.to_excel(writer,sheet_name=name,index=False)
        buffer.seek(0)
        return send_file(buffer,as_attachment=True,download_name='case02_results.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    display={}
    cols=['assignment_id','user_id','employee_id','role_id','department','job_title','부서 검사','직무 검사','승인 시점 검사','승인자 검사','만료 검사','회수 기한','회수 검사','계정 검토','effective_date','hire_date','granted_at','removed_at']
    for name,frame in tables.items():
        if name in ['검사 기준','검사 요약','자료 확인']:
            selected=frame
        else:
            selected=frame[[c for c in cols if c in frame.columns]]
        display[name]=selected.head(200).to_html(index=False,classes='results',na_rep='—',escape=True)
    return render_template('case02.html',tables=display,snapshot=snapshot,total=len(tables['관리자권한 검사']),counts={k:len(v) for k,v in tables.items()})


from sod_check import inspect_sod, read_case03, SoDInputError

@app.route('/case03', methods=['GET','POST'])
def case03():
    if request.method=='GET':return render_template('case03.html')
    file=request.files.get('file')
    if not file or not file.filename.lower().endswith('.xlsx'):
        return render_template('case03.html',error='xlsx 파일을 선택해주세요.'),400
    snapshot=request.form.get('snapshot') or '2026-09-30T18:00'
    try:
        tables=inspect_sod(*read_case03(file),snapshot=snapshot)
    except SoDInputError as exc:
        return render_template('case03.html',error=str(exc)),400
    except Exception:
        app.logger.exception('Case03 input failed')
        return render_template('case03.html',error='정상적인 xlsx 파일과 필수 시트·열·날짜를 확인해주세요.'),400
    if request.form.get('action')=='download':
        buffer=io.BytesIO()
        with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
            for name,frame in tables.items():
                safe=frame.copy()
                for col in safe.select_dtypes(include=['object','string']).columns:
                    safe[col]=safe[col].map(lambda v: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
                safe.to_excel(writer,sheet_name=name,index=False)
        buffer.seek(0)
        return send_file(buffer,as_attachment=True,download_name='case03_results.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    c=tables['SoD 검토 후보']
    views={n:f.head(200).to_html(index=False,classes='results',na_rep='—',escape=True) for n,f in tables.items()}
    return render_template('case03.html',tables=views,snapshot=snapshot,candidates=len(c),users=c.user_id.nunique(),dq=len(tables['자료 확인']))


def load_file(file):
    filename = file.filename
    if filename.endswith('.csv'):
        return pd.read_csv(file)
    elif filename.endswith('.xlsx') or filename.endswith('.xls'):
        return pd.read_excel(file)
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    global last_result
    file = request.files['file']
    df = load_file(file)

    if df is None:
        return jsonify({'error': 'CSV 또는 엑셀 파일만 업로드 가능합니다'})

    amount_col = next((c for c in ['Amount', 'amount', '금액', '거래금액'] if c in df.columns), None)

    anomaly_count = 0
    anomalies = []
    if amount_col:
        amounts = df[[amount_col]].fillna(0)
        model = IsolationForest(contamination=0.05, random_state=42)
        df['anomaly'] = model.fit_predict(amounts)
        anomaly_df = df[df['anomaly'] == -1]
        anomaly_count = len(anomaly_df)
        anomalies = anomaly_df.head(10).fillna('-').to_dict('records')

    req_col = next((c for c in ['requester', '요청자', '구매요청자'] if c in df.columns), None)
    apr_col = next((c for c in ['approver', '승인자', '구매승인자'] if c in df.columns), None)
    pay_col = next((c for c in ['payer', '지급자', '지급담당자'] if c in df.columns), None)

    sod_count = 0
    sod_violations = []
    if req_col and apr_col and pay_col:
        violations = df[
            (df[req_col] == df[apr_col]) |
            (df[apr_col] == df[pay_col]) |
            (df[req_col] == df[pay_col])
        ]
        sod_count = len(violations)
        sod_violations = violations.head(10).fillna('-').to_dict('records')

    last_result = {
        'filename': file.filename,
        'total': len(df),
        'anomaly_count': anomaly_count,
        'sod_count': sod_count,
        'anomalies': anomalies,
        'sod_violations': sod_violations,
        'columns': list(df.columns)
    }

    return jsonify(last_result)

@app.route('/download_pdf')
def download_pdf():
    global last_result
    if not last_result:
        return "분석 결과가 없습니다", 400

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    title_style = ParagraphStyle('title', fontSize=18, fontName='Helvetica-Bold', spaceAfter=10)
    heading_style = ParagraphStyle('heading', fontSize=13, fontName='Helvetica-Bold', spaceAfter=6, spaceBefore=12)
    normal_style = ParagraphStyle('normal', fontSize=10, fontName='Helvetica', spaceAfter=4)

    elements.append(Paragraph('AuditAI - IT Internal Control Report', title_style))
    elements.append(Paragraph('File: ' + last_result.get('filename', '-'), normal_style))
    elements.append(Paragraph('Date: ' + datetime.now().strftime('%Y-%m-%d %H:%M'), normal_style))
    elements.append(Spacer(1, 12))

    total = last_result.get('total', 0)
    anomaly = last_result.get('anomaly_count', 0)
    sod = last_result.get('sod_count', 0)

    if anomaly > total * 0.1 or sod > 5:
        risk = 'HIGH'
    elif anomaly > total * 0.05 or sod > 0:
        risk = 'MEDIUM'
    else:
        risk = 'LOW'

    elements.append(Paragraph('Summary', heading_style))
    summary_data = [
        ['Item', 'Result'],
        ['Total Transactions', str(total)],
        ['Anomaly Detected', str(anomaly)],
        ['SOD Violations', str(sod)],
        ['Risk Level', risk],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f3')]),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph('Anomaly Transactions (Top 10)', heading_style))
    if last_result.get('anomalies'):
        cols = list(last_result['anomalies'][0].keys())[:4]
        anomaly_data = [cols]
        for row in last_result['anomalies']:
            anomaly_data.append([str(row.get(c, '-')) for c in cols])
        anomaly_table = Table(anomaly_data, colWidths=[120, 120, 120, 100])
        anomaly_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e24b4a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fff5f5')]),
        ]))
        elements.append(anomaly_table)
    else:
        elements.append(Paragraph('No anomalies detected.', normal_style))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name='AuditAI_Report.pdf', mimetype='application/pdf')

from case04_routes import register_case04
register_case04(app)

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)