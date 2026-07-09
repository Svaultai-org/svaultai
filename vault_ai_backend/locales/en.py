

from __future__ import annotations

from typing import Optional

from .base import Locale, LocaleFormatter


def _build_english_locale() -> Locale:


    from document_understanding import (
        DOC_TYPE_RULES, _COUNTRY_NAMES, _MONTH_MAP,
    )
    return Locale(
        locale_id="en",
        direction="ltr",
                             
        doc_type_rules=tuple(DOC_TYPE_RULES),
        country_names=_COUNTRY_NAMES,
        country_short_canon={
            "uk": "United Kingdom",
            "usa": "United States",
            "uae": "United Arab Emirates",
        },
        month_map=dict(_MONTH_MAP),
                                                            
        expiry_anchors=("expir", "valid until", "valid till", "date of expiry"),
        issue_anchors=("issue", "issued", "date of issue"),
        due_anchors=("due", "payment due"),
        boarding_anchors=("departure", "depart", "boarding"),
        check_in_anchors=("check-in", "check in", "checkin", "arrival"),
        check_out_anchors=("check-out", "check out", "checkout", "departure"),
        purchase_anchors=("date", "purchased", "paid", "purchase"),
        effective_anchors=("effective", "commences", "commencement",
                           "effective date", "dated"),
        renewal_anchors=("renewal", "renews", "expir", "expires"),
                                 
        passport_num_labels=("passport no", "passport number"),
        id_num_labels=("national id", "id no", "id number"),
        license_num_labels=(
            "license no", "license number", "licence number", "licence no",
        ),
        policy_num_labels=("policy no", "policy number"),
        invoice_num_labels=("invoice no", "invoice number"),
                   
        education_field_phrases=(
            "computer science", "engineering", "mathematics", "physics",
            "business", "law", "medicine", "biology", "chemistry",
            "economics",
        ),
                                                                    
                                                    
        tax_form_keywords={
            "1099": "1099", "w-2": "W2", "w2": "W2", "tax return": "RETURN",
        },
        date_disambiguation="DMY",
    )


ENGLISH_LOCALE: Locale = _build_english_locale()


_FIELD_LABELS = {
    "username": "Username",
    "email":    "Email",
    "password": "Password",
    "pin":      "PIN",
    "note":     "Note",
}


class EnglishFormatter(LocaleFormatter):


    locale_id = "en"

                                                                     
    def expiry_status_absolute(self, iso_date: Optional[str]) -> Optional[str]:
        if not iso_date:
            return None
        try:
            from datetime import date
            parts = iso_date.split("-")
            if len(parts) != 3:
                return None
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            exp = date(y, m, d)
            today = date.today()
            if exp < today:
                return "Expired"
            delta = (exp - today).days
            if delta < 30:
                return f"Expires in {delta} day{'s' if delta != 1 else ''}"
            if delta < 365:
                months = delta // 30
                return f"Expires in {months} month{'s' if months != 1 else ''}"
            years = delta // 365
            return f"Valid (~{years} year{'s' if years != 1 else ''} remaining)"
        except Exception:
            return None

    def date_relative(self, field: str, days_delta: int) -> str:
        n = abs(days_delta)
        plural = "" if n == 1 else "s"
        if days_delta < 0:
            if field == "renewal_date":
                return f"Renewal overdue by {n} day{plural}"
            if field == "due_date":
                return f"Past due by {n} day{plural}"
            if field == "departure_date":
                return f"Departed {n} day{plural} ago"
            if field == "check_out":
                return f"Checked out {n} day{plural} ago"
            if field == "event_date":
                return f"Event was {n} day{plural} ago"
            return f"Expired {n} day{plural} ago"
        if days_delta == 0:
            if field == "renewal_date":   return "Renews today"
            if field == "due_date":       return "Due today"
            if field == "departure_date": return "Departs today"
            if field == "check_out":      return "Checks out today"
            if field == "event_date":     return "Event today"
            return "Expires today"
        if field == "renewal_date":   return f"Renews in {days_delta} day{plural}"
        if field == "due_date":       return f"Due in {days_delta} day{plural}"
        if field == "departure_date": return f"Departs in {days_delta} day{plural}"
        if field == "check_out":      return f"Checks out in {days_delta} day{plural}"
        if field == "event_date":     return f"Event in {days_delta} day{plural}"
        return f"Expires in {days_delta} day{plural}"

                                                                     
    def found_login(self, pretty_service: str) -> str:
        return f"I found your {pretty_service} login."

    def found_login_decrypt_failed(self, service_title: str) -> str:
        return f"I found a saved login for {service_title}, but I could not decrypt it."

    def field_label(self, key: str) -> str:
        return _FIELD_LABELS.get(key, key.title())

                                                                     
    def vault_empty(self) -> str:
        return "Your vault contains no saved secrets yet."

    def vault_list_header(self) -> str:
        return "Here is what I found in your vault:"

    def no_saved_logins(self) -> str:
        return "I don't see any saved logins in this vault yet."

    def saved_logins_header(self) -> str:
        return "Here are your saved logins:"

    def remember_header(self) -> str:
        return "Here is what I remember:"

                                                                     
    def tag_list_header(self, tag: str) -> str:
        return f"Here are your {tag} items:"

    def files_section_header(self) -> str:
        return "Files:"

    def logins_section_header(self) -> str:
        return "Logins:"

    def and_more_files(self, n: int) -> str:
        return f"...and {n} more {'file' if n == 1 else 'files'}."

    def and_more_logins(self, n: int) -> str:
        return f"...and {n} more {'login' if n == 1 else 'logins'}."

                                                           
    def severity_label(self, level: str) -> str:
        return {
            "critical": "Critical",
            "warning":  "Warning",
            "info":     "Info",
        }.get((level or "").lower(), (level or "").title())

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:
        if days_until < 0:
            n = abs(days_until)
            unit = "day" if n == 1 else "days"
            return f"{doc_label} expired {n} {unit} ago"
        if days_until == 0:
            return f"{doc_label} expires today"
        unit = "day" if days_until == 1 else "days"
        return f"{doc_label} expires in {days_until} {unit}"

    def doc_type_label(self, doc_type: str) -> str:
        return {
            "passport":         "Passport",
            "visa":             "Visa",
            "id_card":          "ID card",
            "driver_license":   "Driver license",
            "boarding_pass":    "Boarding pass",
            "hotel_itinerary":  "Hotel reservation",
            "ticket":           "Ticket",
            "invoice":          "Invoice",
            "receipt":          "Receipt",
            "contract":         "Contract",
            "agreement":        "Agreement",
            "degree":           "Degree",
            "certificate":      "Certificate",
            "insurance":        "Insurance",
            "tax_document":     "Tax document",
            "medical_record":   "Medical record",
        }.get(doc_type, (doc_type or "").replace("_", " ").title() or "Document")


ENGLISH_FORMATTER: LocaleFormatter = EnglishFormatter()
