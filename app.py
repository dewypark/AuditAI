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

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)