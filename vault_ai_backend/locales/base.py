

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Locale:


    locale_id: str

                                                                      
    direction: str = "ltr"

                                                                      
    doc_type_rules: tuple = ()
    country_names: tuple = ()
    country_short_canon: dict = field(default_factory=dict)
    month_map: dict = field(default_factory=dict)

                                                           
    expiry_anchors:    tuple = ()
    issue_anchors:     tuple = ()
    due_anchors:       tuple = ()
    boarding_anchors:  tuple = ()
    check_in_anchors:  tuple = ()
    check_out_anchors: tuple = ()
    purchase_anchors:  tuple = ()
    effective_anchors: tuple = ()
    renewal_anchors:   tuple = ()

                                                                
    passport_num_labels: tuple = ()
    id_num_labels:       tuple = ()
    license_num_labels:  tuple = ()
    policy_num_labels:   tuple = ()
    invoice_num_labels:  tuple = ()

                                       
    education_field_phrases: tuple = ()

                                                                       
    tax_form_keywords: dict = field(default_factory=dict)

                                                                   
    date_disambiguation: str = "DMY"


class LocaleFormatter:


    locale_id: str = "base"

                                                                     
    def expiry_status_absolute(self, iso_date: Optional[str]) -> Optional[str]:


        raise NotImplementedError

    def date_relative(self, field: str, days_delta: int) -> str:


        raise NotImplementedError

                                                                     
    def found_login(self, pretty_service: str) -> str:

        raise NotImplementedError

    def found_login_decrypt_failed(self, service_title: str) -> str:

        raise NotImplementedError

    def field_label(self, key: str) -> str:


        raise NotImplementedError

                                                                     
    def vault_empty(self) -> str:

        raise NotImplementedError

    def vault_list_header(self) -> str:

        raise NotImplementedError

    def no_saved_logins(self) -> str:


        raise NotImplementedError

    def saved_logins_header(self) -> str:

        raise NotImplementedError

    def remember_header(self) -> str:

        raise NotImplementedError

                                                                     
    def tag_list_header(self, tag: str) -> str:

        raise NotImplementedError

    def files_section_header(self) -> str:

        raise NotImplementedError

    def logins_section_header(self) -> str:

        raise NotImplementedError

    def and_more_files(self, n: int) -> str:

        raise NotImplementedError

    def and_more_logins(self, n: int) -> str:

        raise NotImplementedError

                                                                     
    def severity_label(self, level: str) -> str:


        raise NotImplementedError

    def expiry_phrase(self, doc_label: str, days_until: int) -> str:


        raise NotImplementedError

    def doc_type_label(self, doc_type: str) -> str:


        raise NotImplementedError
