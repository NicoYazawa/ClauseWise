"""Display masking (design doc 3.5.3): API outputs uniformly mask ID numbers / phone numbers."""


def mask_phone(phone: str | None) -> str | None:
    """138****5678"""
    if not phone or len(phone) != 11:
        return phone or ""
    return f"{phone[:3]}****{phone[7:]}"


def mask_id_no(id_no: str | None) -> str | None:
    """Keep the first 3 and last 2 characters: 911*********Z4"""
    if not id_no or len(id_no) < 8:
        return id_no or ""
    return f"{id_no[:3]}{'*' * (len(id_no) - 5)}{id_no[-2:]}"
