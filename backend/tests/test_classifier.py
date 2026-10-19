import pytest
from services.classifier import _heuristic_classify, classify_contract_department

def test_heuristic_classify_datacenter():
    text = """
    WHEREAS, Customer desires to license colocation space within Provider's Tier-III facility.
    The primary service includes two (2) full 42U rack cabinets with 10 KVA redundant power and cooling.
    Monthly Recurring Charges: $4,500 for rack space and facility power.
    """
    res = _heuristic_classify(text, filename="Colocation_Agreement_DC.pdf")
    assert res["department"] == "Data Center"
    assert res["confidence"] >= 0.8

def test_heuristic_classify_cloud():
    text = """
    WHEREAS, Provider offers an elastic virtual machine compute environment (IaaS) and object storage.
    Customer is provisioned 32 vCPU compute instances with 128 GB RAM and 2TB cloud backup storage.
    Note: Compute instances reside in Provider's regional data center.
    """
    res = _heuristic_classify(text, filename="Cloud_Compute_Order.pdf")
    assert res["department"] == "Cloud Services"

def test_heuristic_classify_non_dc_or_cloud_is_general():
    consulting_text = """
    AGREEMENT FOR CONSULTING SERVICES
    Consultant will provide strategic corporate advisory, HR management, and business consulting.
    Monthly retainer fee shall be $5,000 payable upon invoice submission.
    """
    res_consulting = _heuristic_classify(consulting_text, filename="Consulting_Services.pdf")
    assert res_consulting["department"] == "General"

    saas_text = """
    Software License Agreement for Accounting Spreadsheet Tool.
    Customer licenses corporate accounting tool with user seats and technical support.
    """
    res_saas = _heuristic_classify(saas_text, filename="Software_License.pdf")
    assert res_saas["department"] == "General"


def test_heuristic_classify_general():
    text = """
    MUTUAL NON-DISCLOSURE AGREEMENT
    This Non-Disclosure Agreement is entered into between Party A and Party B.
    Both parties agree to hold proprietary and confidential information in strict confidence.
    """
    res = _heuristic_classify(text, filename="NDA_Mutual.pdf")
    assert res["department"] == "General"

def test_classify_contract_department_fallback():
    # Test top-level wrapper with monkeypatched failure
    pages = [{"text": "Colocation Rack Unit Service Agreement. Power 5 KVA."}]
    res = classify_contract_department("", ocr_pages=pages, filename="Colo_Contract.pdf")
    assert res["department"] == "Data Center"
