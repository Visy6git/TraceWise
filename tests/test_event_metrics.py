from openpyxl import Workbook
import pytest
from app.services.event_metrics import EventMetricRule, calculate_case_event_metric


def fixture(path):
    wb=Workbook(); ws=wb.active; ws.title='Events'
    ws.append(['Report title','Demo']); ws.append(['Case Number','Derived-Initial-Follow-up-Flag','Source','Approval Date','Event PT'])
    ws.append(['C1','Initial','Spontaneous','20240101','Insomnia'])
    ws.append(['C1','Follow-up','Spontaneous','20240102','Insomnia'])
    ws.append(['C2','Initial','Clinical Trial','20240103','Insomnia'])
    ws.append(['C3','Initial','Spontaneous','20220101','Headache'])
    wb.save(path)


def test_distinct_cases_and_explicit_filters(tmp_path):
    p=tmp_path/'x.xlsx'; fixture(p)
    rule=EventMetricRule('Insomnia','Events','Case Number','Event PT',('Insomnia',),initial_only=True,date_column='Approval Date',start_date_yyyymmdd='20230101',end_date_yyyymmdd='20241231',include_values={'Source':('Spontaneous',)})
    result=calculate_case_event_metric(p,rule)
    assert result['numerator_distinct_cases']==1
    assert result['denominator_distinct_cases']==1
    assert result['evidence'][0]['excel_row']==3


def test_approval_not_part_of_engine_and_invalid_dates_rejected(tmp_path):
    p=tmp_path/'x.xlsx'; fixture(p)
    with pytest.raises(ValueError):
        EventMetricRule('bad','Events','Case Number','Event PT',('Insomnia',),date_column='Approval Date',start_date_yyyymmdd='20250101',end_date_yyyymmdd='20240101').validate()
