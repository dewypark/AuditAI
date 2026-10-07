import argparse
from pathlib import Path
import pandas as pd
from sod_check import read_case03,inspect_sod
parser=argparse.ArgumentParser();parser.add_argument('input');args=parser.parse_args()
r=inspect_sod(*read_case03(args.input))
print(r['검사 기준'].to_string(index=False))
print(r['SoD 검토 후보'].to_string(index=False))
output=Path(args.input).with_name('case03_results.xlsx')
with pd.ExcelWriter(output,engine='openpyxl') as writer:
    for n,f in r.items():f.to_excel(writer,sheet_name=n,index=False)
print('저장:',output)
