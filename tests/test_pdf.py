from okf_platform.pdf import validate_pdf


def test_invalid_pdf_signature_is_recorded() -> None:
    evidence = validate_pdf(b"not really a pdf")
    assert not evidence.valid
    assert evidence.error == "missing PDF signature"
    assert len(evidence.sha256) == 64


def test_truncated_pdf_is_recorded() -> None:
    evidence = validate_pdf(b"%PDF-1.7\nbody without final marker")
    assert not evidence.valid
    assert evidence.error == "missing PDF end marker"
