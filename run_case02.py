import argparse
from pathlib import Path
import pandas as pd
from privileged_check import read_case02, inspect_privileged_jml
parser=argparse.ArgumentParser()
parser.add_argument('input')
args=parser.parse_args()
results=inspect_privileged_jml(*read_case02(args.input))
output=Path(args.input).with_name('case02_results.xlsx')
with pd.ExcelWriter(output,engine='openpyxl') as writer:
    for name,frame in results.items():
        frame.to_excel(writer,sheet_name=name,index=False)
print(results['검사 요약'].to_string(index=False))
print('저장:',output)
