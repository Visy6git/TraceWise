"""PBRER (Periodic Benefit-Risk Evaluation Report - ICH E2C(R2)) Sample Bundle Generator.
Creates realistic sample documents for testing Document Intelligence & Agent Autonomy.
"""
from pathlib import Path
from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


def generate_pbrer_sample_bundle(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "PBRER_Annual_Report_2024_Nexipril.docx"
    clinical_path = output_dir / "Nexipril_Clinical_Trial_Exposure.xlsx"
    sales_path = output_dir / "Nexipril_Global_Sales_Exposure.xlsx"
    icsr_path = output_dir / "Nexipril_PostMarketing_ICSR_Adverse_Events.xlsx"
    signals_path = output_dir / "Nexipril_Safety_Signal_Tracker.xlsx"

    _create_target_pbrer_docx(target_path)
    _create_clinical_exposure_xlsx(clinical_path)
    _create_sales_exposure_xlsx(sales_path)
    _create_icsr_adverse_events_xlsx(icsr_path)
    _create_safety_signals_xlsx(signals_path)

    return {
        "target": target_path,
        "clinical": clinical_path,
        "sales": sales_path,
        "icsr": icsr_path,
        "signals": signals_path,
    }


def _create_target_pbrer_docx(path: Path):
    doc = Document()
    doc.add_heading("PERIODIC BENEFIT-RISK EVALUATION REPORT (PBRER)", level=0)
    doc.add_paragraph("Active Substance: Nexipril Sodium (10 mg, 20 mg, 40 mg tablets)")
    doc.add_paragraph("International Birth Date (IBD): 15-Jan-2018")
    doc.add_paragraph("Reporting Period: 01-Jan-2024 to 31-Dec-2024")
    doc.add_paragraph("Marketing Authorisation Holder: Apex BioPharma Global Ltd.")

    # Section 1
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph(
        "Nexipril is a selective dual angiotensin receptor-neprilysin inhibitor indicated for the treatment of "
        "symptomatic chronic heart failure with reduced ejection fraction (HFrEF) and essential hypertension. "
        "This PBRER presents an integrated evaluation of worldwide safety and efficacy data received during the reporting period."
    )

    # Section 2
    doc.add_heading("2. Worldwide Marketing Approval Status", level=1)
    doc.add_paragraph(
        "As of 31-Dec-2024, Nexipril is approved in 48 countries worldwide. Initial approval was granted by the European Medicines "
        "Agency on 15-Jan-2018, followed by US FDA approval on 22-Aug-2018."
    )

    # Section 5
    doc.add_heading("5. Estimated Exposure and Use Patterns", level=1)

    # Section 5.1
    doc.add_heading("5.1 Cumulative Subject Exposure in Clinical Trials", level=2)
    doc.add_paragraph(
        "During completed and ongoing clinical trials up to the data lock point of 31-Dec-2024, a cumulative total of "
        "12,450 subjects have been enrolled and exposed to Nexipril. In the current reporting interval (2024), 1,820 new subjects "
        "were exposed across Phase II and Phase III development programs."
    )
    t1 = doc.add_table(rows=1, cols=4)
    hdr1 = t1.rows[0].cells
    hdr1[0].text = "Study Phase"
    hdr1[1].text = "Indication"
    hdr1[2].text = "Cumulative Subjects (N)"
    hdr1[3].text = "Interval 2024 Subjects (N)"
    row_data1 = [
        ("Phase I Clinical Pharmacology", "Healthy Volunteers", "450", "60"),
        ("Phase II Dose-Ranging Studies", "Essential Hypertension", "2,800", "340"),
        ("Phase III Confirmatory Trials", "Chronic Heart Failure (HFrEF)", "8,200", "1,220"),
        ("Phase IIIb / IV Post-Approval", "Diabetic Nephropathy", "1,000", "200"),
    ]
    for sp, ind, cum, inv in row_data1:
        row = t1.add_row().cells
        row[0].text = sp
        row[1].text = ind
        row[2].text = cum
        row[3].text = inv

    # Section 5.2
    doc.add_heading("5.2 Cumulative and Interval Patient Exposure from Marketing Experience", level=2)
    doc.add_paragraph(
        "Worldwide post-marketing exposure to Nexipril is calculated on the basis of market volume sales and Defined Daily Dose (DDD = 20 mg). "
        "For the 2024 reporting period, total interval patient exposure is estimated at 384,500 patient-years (PY). "
        "Cumulative patient exposure since launch is estimated at 1,425,000 patient-years."
    )

    # Section 6.1
    doc.add_heading("6.1 Reference Safety Information (RSI) Revisions", level=1)
    doc.add_paragraph(
        "The Reference Safety Information in effect at the start of the period was the Company Core Data Sheet (CCDS) Version 4.0. "
        "During 2024, CCDS Version 5.0 was approved to include warnings regarding acute symptomatic hypotension in volume-depleted patients."
    )

    # Section 7
    doc.add_heading("7. Summary Tabulations of Safety Data", level=1)

    # Section 7.1
    doc.add_heading("7.1 Summary Tabulations of Serious Adverse Events from Clinical Trials", level=2)
    doc.add_paragraph(
        "A total of 84 serious adverse events (SAEs) were reported from sponsored clinical trials during the 2024 reporting interval. "
        "The most frequent SAEs by MedDRA System Organ Class were Cardiac disorders (38 events), Renal and urinary disorders (22 events), "
        "and Vascular disorders (14 events)."
    )

    # Section 7.2
    doc.add_heading("7.2 Tabulations of Serious Adverse Reactions from Post-Marketing Sources", level=2)
    doc.add_paragraph(
        "During the period 01-Jan-2024 to 31-Dec-2024, apex received 342 spontaneous individual case safety reports (ICSRs) "
        "qualifying as serious adverse reactions. The predominant MedDRA Preferred Terms observed included Hypotension (46 cases), "
        "Hyperkalaemia (38 cases), Renal impairment (29 cases), Angioedema (14 cases), and Acute pancreatitis (8 cases)."
    )

    # Section 9
    doc.add_heading("9. Overview of Signals", level=1)

    # Section 9.1
    doc.add_heading("9.1 Summary of Safety Signals", level=2)
    doc.add_paragraph(
        "Three safety signals were evaluated during the reporting interval: "
        "1. Signal SIG-2024-01: Acute Pancreatitis (Triggered by 8 post-marketing reports; closed with recommendation for RSI update). "
        "2. Signal SIG-2024-02: Drug-Induced Liver Injury (Hepatotoxicity) - Ongoing signal under close monitoring. "
        "3. Signal SIG-2023-04: Severe Orthostatic Syncope in elderly cohort - Evaluated and closed with no regulatory action needed."
    )

    # Section 10
    doc.add_heading("10. Integrated Benefit-Risk Evaluation", level=1)
    doc.add_paragraph(
        "The overall benefit-risk profile of Nexipril remains favorable in its approved indications. "
        "No new safety concerns arose that alter the positive balance of benefits over risks."
    )

    doc.add_heading("16. Signal and Risk Evaluation", level=1)
    doc.add_heading("16.1 Summary of Safety Concerns", level=2)
    doc.add_paragraph("The established safety concerns remain under routine pharmacovigilance review.")
    doc.add_heading("16.2 Signal Evaluation", level=2)
    doc.add_paragraph("Signals are reviewed separately from the risk evaluation in Section 16.3.")
    doc.add_heading("16.3 Evaluation of Risks and New Information", level=2)
    doc.add_heading("16.3.1 New information on important identified risks", level=3)
    doc.add_heading("16.3.1.1 Cardiac failure", level=4)
    doc.add_paragraph("Serious post-marketing reports for cardiac failure were reviewed for the reporting interval.")
    doc.add_heading("16.3.1.2 Angioedema", level=4)
    doc.add_paragraph("The available serious case reports for angioedema were reviewed.")
    doc.add_heading("16.3.2 New information on important potential risks", level=3)
    doc.add_heading("16.3.2.1 Acute pancreatitis", level=4)
    doc.add_paragraph("The available reports for acute pancreatitis were reviewed as a potential risk.")
    doc.add_heading("16.4 Characterisation of Risks", level=2)
    doc.add_paragraph("Risk characterisation is presented separately from the Section 16.3 evaluation.")

    doc.save(path)


def _style_headers(ws):
    hdr_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _create_clinical_exposure_xlsx(path: Path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Trial_Exposure_Summary"
    ws1.append(["Study_ID", "Study_Phase", "Target_Indication", "Treatment_Arm", "Cumulative_Enrolled_N", "Interval_2024_Enrolled_N", "Mean_Duration_Days", "Status"])
    data1 = [
        ["NEX-101", "Phase I Clinical Pharmacology", "Healthy Volunteers", "Nexipril 10/20/40mg", 450, 60, 28, "Completed"],
        ["NEX-201", "Phase II Dose-Ranging", "Essential Hypertension", "Nexipril 20mg QD", 1400, 160, 180, "Completed"],
        ["NEX-202", "Phase II Dose-Ranging", "Essential Hypertension", "Nexipril 40mg QD", 1400, 180, 180, "Completed"],
        ["NEX-301", "Phase III Confirmatory", "Chronic Heart Failure (HFrEF)", "Nexipril 20mg BID", 4100, 610, 365, "Ongoing"],
        ["NEX-302", "Phase III Confirmatory", "Chronic Heart Failure (HFrEF)", "Nexipril 40mg BID", 4100, 610, 365, "Ongoing"],
        ["NEX-401", "Phase IIIb / IV Post-Approval", "Diabetic Nephropathy", "Nexipril 20mg QD", 1000, 200, 270, "Ongoing"],
    ]
    for row in data1:
        ws1.append(row)
    _style_headers(ws1)

    ws2 = wb.create_sheet(title="Demographics_Breakdown")
    ws2.append(["Study_ID", "Age_Group", "Gender", "Race", "Interval_Subject_Count", "Cumulative_Subject_Count"])
    data2 = [
        ["NEX-301", "18-64 years", "Male", "Caucasian", 320, 2150],
        ["NEX-301", "18-64 years", "Female", "Caucasian", 180, 1150],
        ["NEX-301", ">=65 years", "Male", "Caucasian", 70, 500],
        ["NEX-301", ">=65 years", "Female", "Caucasian", 40, 300],
        ["NEX-302", "18-64 years", "Male", "Asian", 310, 2100],
        ["NEX-302", "18-64 years", "Female", "Asian", 190, 1200],
        ["NEX-302", ">=65 years", "Male", "Black/African American", 65, 480],
        ["NEX-302", ">=65 years", "Female", "Black/African American", 45, 320],
    ]
    for row in data2:
        ws2.append(row)
    _style_headers(ws2)
    wb.save(path)


def _create_sales_exposure_xlsx(path: Path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Sales_Units_and_DDD"
    ws1.append(["Region", "Country_Code", "Formulation", "Dose_mg", "DDD_Standard_mg", "Standard_Units_Sold_2024", "Cumulative_Units_Sold", "Patient_Years_2024", "Cumulative_Patient_Years"])
    data = [
        ["North America", "USA", "Oral Tablet", 20, 20, 73000000, 270000000, 200000, 740000],
        ["North America", "CAN", "Oral Tablet", 20, 20, 10950000, 42000000, 30000, 115000],
        ["Europe", "DEU", "Oral Tablet", 20, 20, 18250000, 70000000, 50000, 192000],
        ["Europe", "FRA", "Oral Tablet", 20, 20, 14600000, 55000000, 40000, 151000],
        ["Europe", "GBR", "Oral Tablet", 20, 20, 12775000, 48000000, 35000, 131500],
        ["Asia-Pacific", "JPN", "Oral Tablet", 10, 20, 7300000, 28000000, 10000, 38500],
        ["Asia-Pacific", "AUS", "Oral Tablet", 20, 20, 3650000, 14500000, 10000, 39500],
        ["Rest of World", "BRA", "Oral Tablet", 20, 20, 3467500, 6750000, 9500, 18500],
    ]
    for row in data:
        ws1.append(row)
    _style_headers(ws1)
    wb.save(path)


def _create_icsr_adverse_events_xlsx(path: Path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "ICSR_Line_Listing"
    headers = [
        "Case_Number", "Receipt_Date", "Initial_Followup_Flag", "Country", "Patient_Age", "Patient_Sex",
        "Primary_Suspect_Drug", "Indication", "Event_PT", "MedDRA_SOC", "Serious_Flag",
        "Seriousness_Criteria", "Outcome", "Dechallenge", "Rechallenge"
    ]
    ws1.append(headers)

    import random
    random.seed(42)

    # Specific predefined cases matching report
    predefined = [
        ("NEX-ICSR-0001", "20240110", "Initial", "USA", 67, "M", "Nexipril Sodium", "Heart Failure", "Hypotension", "Vascular disorders", "Yes", "Hospitalization", "Recovered", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0002", "20240114", "Initial", "DEU", 71, "F", "Nexipril Sodium", "Hypertension", "Hyperkalaemia", "Metabolism and nutrition disorders", "Yes", "Medically Significant", "Recovered", "Positive", "Negative"),
        ("NEX-ICSR-0003", "20240203", "Initial", "GBR", 59, "M", "Nexipril Sodium", "Heart Failure", "Angioedema", "Immune system disorders", "Yes", "Life Threatening", "Recovered with Sequelae", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0004", "20240219", "Initial", "USA", 63, "F", "Nexipril Sodium", "Heart Failure", "Acute pancreatitis", "Gastrointestinal disorders", "Yes", "Hospitalization", "Recovering", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0005", "20240301", "Initial", "FRA", 74, "M", "Nexipril Sodium", "Hypertension", "Renal impairment", "Renal and urinary disorders", "Yes", "Hospitalization", "Recovered", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0006", "20240315", "Initial", "CAN", 58, "F", "Nexipril Sodium", "Heart Failure", "Hepatic enzyme increased", "Hepatobiliary disorders", "Yes", "Medically Significant", "Recovering", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0007", "20240402", "Initial", "JPN", 69, "M", "Nexipril Sodium", "Heart Failure", "Acute pancreatitis", "Gastrointestinal disorders", "Yes", "Hospitalization", "Recovered", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0008", "20240420", "Initial", "USA", 80, "F", "Nexipril Sodium", "Heart Failure", "Syncope", "Nervous system disorders", "Yes", "Hospitalization", "Recovered", "Positive", "Not Rechallenged"),
        ("NEX-ICSR-0009", "20240502", "Initial", "USA", 72, "M", "Nexipril Sodium", "Heart Failure", "Cardiac failure chronic", "Cardiac disorders", "Yes", "Hospitalization", "Recovering", "Positive", "Not Rechallenged"),
    ]

    for p in predefined:
        ws1.append(list(p))

    # Add remaining to reach 342 serious cases across 2024
    soc_pts = [
        ("Vascular disorders", "Hypotension", 44),
        ("Metabolism and nutrition disorders", "Hyperkalaemia", 37),
        ("Renal and urinary disorders", "Renal impairment", 28),
        ("Immune system disorders", "Angioedema", 13),
        ("Gastrointestinal disorders", "Acute pancreatitis", 6),
        ("Hepatobiliary disorders", "Hepatic enzyme increased", 12),
        ("Hepatobiliary disorders", "Drug-induced liver injury", 5),
        ("Nervous system disorders", "Syncope", 24),
        ("Cardiac disorders", "Atrial fibrillation", 35),
        ("Cardiac disorders", "Cardiac failure chronic", 39),
        ("Respiratory disorders", "Cough", 50),
        ("General disorders", "Asthenia", 40),
    ]

    case_idx = 10
    countries = ["USA", "DEU", "FRA", "GBR", "CAN", "JPN", "AUS"]
    criteria = ["Hospitalization", "Medically Significant", "Disability", "Life Threatening"]
    outcomes = ["Recovered", "Recovering", "Not Recovered", "Fatal"]

    for soc, pt, count in soc_pts:
        for _ in range(count):
            c_num = f"NEX-ICSR-{case_idx:04d}"
            date_int = f"2024{random.randint(1,12):02d}{random.randint(1,28):02d}"
            flag = "Initial" if random.random() < 0.85 else "Follow-up"
            c_cntry = random.choice(countries)
            age = random.randint(45, 84)
            sex = "M" if random.random() > 0.45 else "F"
            crit = random.choice(criteria)
            outc = random.choice(outcomes)
            ws1.append([
                c_num, date_int, flag, c_cntry, age, sex, "Nexipril Sodium", "Heart Failure",
                pt, soc, "Yes", crit, outc, "Positive", "Not Rechallenged"
            ])
            case_idx += 1

    _style_headers(ws1)
    wb.save(path)


def _create_safety_signals_xlsx(path: Path):
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Signal_Registry_2024"
    ws1.append([
        "Signal_ID", "Safety_Concern", "MedDRA_PT_Terms", "Detection_Date", "Trigger_Source",
        "Interval_Cases_Evaluated", "Signal_Status", "Action_Proposed", "Target_PBRER_Section"
    ])
    signals = [
        ["SIG-2024-01", "Acute Pancreatitis", "Acute pancreatitis; Pancreatitis necrotising", "20240315", "Spontaneous ICSR Disproportionality", 8, "Closed", "RSI update to include Pancreatitis in Special Warnings", "9.1"],
        ["SIG-2024-02", "Drug-Induced Liver Injury (DILI)", "Drug-induced liver injury; Hepatotoxicity; Hepatic enzyme increased", "20240620", "Literature & Clinical Trial SAE", 18, "Ongoing", "Targeted questionnaire for prospective cases", "9.1"],
        ["SIG-2023-04", "Severe Orthostatic Syncope", "Syncope; Orthostatic hypotension", "20231110", "Spontaneous ICSR", 25, "Closed", "No regulatory action needed; covered in section 4.4", "9.1"],
    ]
    for s in signals:
        ws1.append(s)
    _style_headers(ws1)
    wb.save(path)


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[2] / "runtime" / "sample_pbrer_data"
    res = generate_pbrer_sample_bundle(out)
    print(f"Generated {len(res)} files at {out}")
