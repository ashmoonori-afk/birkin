import zipfile
from pathlib import Path
from birkin.office.adapters.xlsx import XlsxAdapter
FIX=Path(__file__).parent/'fixtures/xlsx/formulas-hidden-chart.xlsx'
def test_xlsx_cell_patch_preserves_formula_format_merge_chart_and_hidden_state(tmp_path):
    a=XlsxAdapter(); before=a.part_hashes(FIX); out=tmp_path/'draft.xlsx'; result=a.patch_cell(FIX,out,'A1',42)
    after=a.part_hashes(out); assert result['calculated'] is False
    assert before['xl/charts/chart1.xml']==after['xl/charts/chart1.xml'] and before['xl/workbook.xml']==after['xl/workbook.xml']
    with zipfile.ZipFile(out) as z:
        sheet=z.read('xl/worksheets/sheet1.xml'); assert b'<v>42</v>' in sheet and b'<f>A1*2</f>' in sheet and b'mergeCell ref="A1:B1"' in sheet
