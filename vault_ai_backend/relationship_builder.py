

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

from vault_core import get_db
from taxonomy import (
    RELATION_TYPES,
    TAG_TO_RELATION,
    DOC_FAMILY_TO_RELATION,
    SERVICE_CATEGORY_TO_RELATION,
    IDENTITY_DOC_TYPES,
    TRAVEL_DOC_TYPES,
    FINANCE_DOC_TYPES,
    LEGAL_DOC_TYPES,
    MEDICAL_DOC_TYPES,
    EDUCATION_DOC_TYPES,
)


logger = logging.getLogger(__name__)


_ALLOWED_RELATIONS: frozenset[str] = frozenset(RELATION_TYPES)
_ALLOWED_KINDS: frozenset[str] = frozenset(("uploaded_file", "vault_item"))


_DOC_FAMILIES: dict[str, frozenset[str]] = {
    "IDENTITY":  IDENTITY_DOC_TYPES,
    "TRAVEL":    TRAVEL_DOC_TYPES,
    "FINANCE":   FINANCE_DOC_TYPES,
    "LEGAL":     LEGAL_DOC_TYPES,
    "MEDICAL":   MEDICAL_DOC_TYPES,
    "EDUCATION": EDUCATION_DOC_TYPES,
}


_INHERITANCE_KEYWORDS_EN: tuple[str, ...] = (
    "will", "estate", "beneficiary", "heir", "inheritance",
    "bequest", "trust deed", "executor", "probate", "testament",
)


_RULE_CONFIDENCE: float = 1.0


_MAX_TAGS_PER_ASSET = 32
_MAX_COUNTRIES_PER_ASSET = 4
_MAX_MERCHANTS_PER_ASSET = 4


@dataclass(frozen=True)
class Endpoint:


    kind: str
    file_id: Optional[str] = None
    item_id: Optional[int] = None

    def __post_init__(self):
                                               
        if self.kind == "uploaded_file":
            assert self.file_id is not None and self.item_id is None, self
        elif self.kind == "vault_item":
            assert self.item_id is not None and self.file_id is None, self
        else:
            raise ValueError(f"unknown endpoint kind: {self.kind!r}")

    @property
    def sort_key(self) -> tuple:
                                                                      
        return (self.kind, self.file_id or "", self.item_id or 0)


@dataclass
class Asset:


    endpoint: Endpoint
    tags: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()                   
    merchants: tuple[str, ...] = ()                   
    service_category: Optional[str] = None
    doc_type: Optional[str] = None
    name_haystack: str = ""                                                  


@dataclass(frozen=True)
class Relationship:

    source: Endpoint
    target: Endpoint
    relation_type: str
    confidence: float = _RULE_CONFIDENCE


def _canonical_pairs(members: Iterable[Endpoint]) -> Iterator[tuple[Endpoint, Endpoint]]:


    unique = sorted(set(members), key=lambda e: e.sort_key)
    n = len(unique)
    for i in range(n):
        for j in range(i + 1, n):
            yield unique[i], unique[j]


def _normalize_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    return v or None


def _normalize_merchant(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    return v or None


def _matches_inheritance_keywords(haystack: str) -> bool:
    if not haystack:
        return False
    h = haystack.lower()
    return any(kw in h for kw in _INHERITANCE_KEYWORDS_EN)


def derive_relationships(assets: Iterable[Asset]) -> list[Relationship]:


    by_tag:           dict[str, list[Endpoint]] = defaultdict(list)
    by_country:       dict[str, list[Endpoint]] = defaultdict(list)
    by_merchant:      dict[str, list[Endpoint]] = defaultdict(list)
    by_service_cat:   dict[str, list[Endpoint]] = defaultdict(list)
    by_doc_family:    dict[str, list[Endpoint]] = defaultdict(list)
    inheritance_set:  list[Endpoint] = []

    for a in assets:
        ep = a.endpoint
        for tag in a.tags[:_MAX_TAGS_PER_ASSET]:
            if tag in TAG_TO_RELATION:
                by_tag[tag].append(ep)
        for country in a.countries[:_MAX_COUNTRIES_PER_ASSET]:
            if country:
                by_country[country].append(ep)
        for merchant in a.merchants[:_MAX_MERCHANTS_PER_ASSET]:
            if merchant:
                by_merchant[merchant].append(ep)
        if a.service_category and a.service_category in SERVICE_CATEGORY_TO_RELATION:
            by_service_cat[a.service_category].append(ep)
        if a.doc_type:
            for family, types in _DOC_FAMILIES.items():
                if a.doc_type in types:
                    by_doc_family[family].append(ep)
        if _matches_inheritance_keywords(a.name_haystack):
            inheritance_set.append(ep)

                                           
    raw: list[Relationship] = []

    for tag, members in by_tag.items():
        relation = TAG_TO_RELATION[tag]
        for a, b in _canonical_pairs(members):
            raw.append(Relationship(a, b, relation, _RULE_CONFIDENCE))

    for country, members in by_country.items():
        for a, b in _canonical_pairs(members):
            raw.append(Relationship(a, b, "travel_related", _RULE_CONFIDENCE))

    for merchant, members in by_merchant.items():
        for a, b in _canonical_pairs(members):
            raw.append(Relationship(a, b, "finance_related", _RULE_CONFIDENCE))

    for cat, members in by_service_cat.items():
        relation = SERVICE_CATEGORY_TO_RELATION[cat]
        for a, b in _canonical_pairs(members):
            raw.append(Relationship(a, b, relation, _RULE_CONFIDENCE))

    for family, members in by_doc_family.items():
        relation = DOC_FAMILY_TO_RELATION[family]
        for a, b in _canonical_pairs(members):
            raw.append(Relationship(a, b, relation, _RULE_CONFIDENCE))

    for a, b in _canonical_pairs(inheritance_set):
        raw.append(Relationship(a, b, "inheritance_related", _RULE_CONFIDENCE))

                                                             
    seen: dict[tuple, Relationship] = {}
    for r in raw:
        key = (r.source, r.target, r.relation_type)
        if key not in seen or r.confidence > seen[key].confidence:
            seen[key] = r
                                    
    return sorted(
        seen.values(),
        key=lambda r: (r.source.sort_key, r.target.sort_key, r.relation_type),
    )


def is_enabled() -> bool:


    return os.getenv("VAULTAI_RELATIONSHIPS_ENABLED", "true").lower() == "true"


def _load_metadata_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _collect_assets_from_db(vault_id: str) -> list[Asset]:


    files_by_id: dict[str, Asset] = {}
    items_by_id: dict[int, Asset] = {}

    conn = get_db()
    try:
        with conn.cursor() as cur:
                   
            cur.execute(
                """SELECT id, file_name, saved_name, detected_service
                   FROM uploaded_files
                   WHERE vault_id=%s
                     AND upload_status='complete'""",
                (vault_id,),
            )
            for fid, file_name, saved_name, detected_service in cur.fetchall() or []:
                ep = Endpoint(kind="uploaded_file", file_id=fid)
                hay = " ".join(p for p in (file_name, saved_name) if p).lower()
                files_by_id[fid] = Asset(endpoint=ep, name_haystack=hay)

                   
            cur.execute(
                """SELECT id, service, item_type
                   FROM vault_items
                   WHERE vault_id=%s""",
                (vault_id,),
            )
            for iid, service, item_type in cur.fetchall() or []:
                ep = Endpoint(kind="vault_item", item_id=int(iid))
                items_by_id[int(iid)] = Asset(endpoint=ep, name_haystack=(service or "").lower())

                         
            cur.execute(
                """SELECT uploaded_file_id, tag
                   FROM vault_asset_tags
                   WHERE vault_id=%s
                     AND uploaded_file_id IS NOT NULL""",
                (vault_id,),
            )
            tags_for_file: dict[str, list[str]] = defaultdict(list)
            for fid, tag in cur.fetchall() or []:
                tags_for_file[fid].append(tag)
            for fid, tags in tags_for_file.items():
                if fid in files_by_id:
                    files_by_id[fid].tags = tuple(tags)

                         
            cur.execute(
                """SELECT vault_item_id, tag
                   FROM vault_asset_tags
                   WHERE vault_id=%s
                     AND vault_item_id IS NOT NULL""",
                (vault_id,),
            )
            tags_for_item: dict[int, list[str]] = defaultdict(list)
            for iid, tag in cur.fetchall() or []:
                tags_for_item[int(iid)].append(tag)
            for iid, tags in tags_for_item.items():
                if iid in items_by_id:
                    items_by_id[iid].tags = tuple(tags)

                                           
            cur.execute(
                """SELECT uploaded_file_id, doc_type, metadata_json
                   FROM vault_document_metadata
                   WHERE vault_id=%s""",
                (vault_id,),
            )
            for fid, doc_type, raw in cur.fetchall() or []:
                if fid not in files_by_id:
                    continue
                md = _load_metadata_json(raw)
                countries = []
                merchants = []
                c = _normalize_country(md.get("country"))
                if c:
                    countries.append(c)
                m = _normalize_merchant(md.get("merchant"))
                if m:
                    merchants.append(m)
                files_by_id[fid].doc_type = doc_type
                files_by_id[fid].countries = tuple(countries)
                files_by_id[fid].merchants = tuple(merchants)

                                                
            cur.execute(
                """SELECT service_name, category FROM vault_service_categories
                   WHERE locale='en' OR locale IS NOT NULL""",
            )
            category_by_service: dict[str, str] = {}
            for sn, cat in cur.fetchall() or []:
                if cat and cat != "unknown":
                    category_by_service[(sn or "").lower()] = cat

                                                                             
            cur.execute(
                """SELECT id, detected_service
                   FROM uploaded_files
                   WHERE vault_id=%s
                     AND upload_status='complete'
                     AND detected_service IS NOT NULL""",
                (vault_id,),
            )
            for fid, ds in cur.fetchall() or []:
                if fid in files_by_id and ds:
                    cat = category_by_service.get(ds.strip().lower())
                    if cat:
                        files_by_id[fid].service_category = cat

                                                            
            for iid, asset in items_by_id.items():
                                                                 
                cat = category_by_service.get(asset.name_haystack)
                if cat:
                    asset.service_category = cat
    finally:
        conn.close()

    return list(files_by_id.values()) + list(items_by_id.values())


def _insert_relationships(
    cur, vault_id: str, rels: Iterable[Relationship],
) -> int:


    rows = []
    for r in rels:
        if r.relation_type not in _ALLOWED_RELATIONS:
            continue
        rows.append((
            vault_id,
            r.source.kind, r.source.file_id, r.source.item_id,
            r.target.kind, r.target.file_id, r.target.item_id,
            r.relation_type, float(r.confidence),
        ))
    if not rows:
        return 0
    cur.executemany(
        """
        INSERT INTO vault_relationships
            (vault_id,
             source_kind, source_file_id, source_item_id,
             target_kind, target_file_id, target_item_id,
             relation_type, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def _delete_relationships_touching_endpoint(
    cur, vault_id: str, ep: Endpoint,
) -> None:


    if ep.kind == "uploaded_file":
        cur.execute(
            """DELETE FROM vault_relationships
               WHERE vault_id=%s
                 AND (source_file_id=%s OR target_file_id=%s)""",
            (vault_id, ep.file_id, ep.file_id),
        )
    else:
        cur.execute(
            """DELETE FROM vault_relationships
               WHERE vault_id=%s
                 AND (source_item_id=%s OR target_item_id=%s)""",
            (vault_id, ep.item_id, ep.item_id),
        )


def build_relationships_for_file_safe(
    vault_id: str, file_id: str, *, replace: bool = False,
) -> None:


    try:
        if not is_enabled():
            return
        assets = _collect_assets_from_db(vault_id)
        if not assets:
            return
        rels = derive_relationships(assets)
                                                      
        ep = Endpoint(kind="uploaded_file", file_id=file_id)
        touching = [r for r in rels if r.source == ep or r.target == ep]
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_relationships_touching_endpoint(cur, vault_id, ep)
                if touching:
                    _insert_relationships(cur, vault_id, touching)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "build_relationships_for_file_safe failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def build_relationships_for_item_safe(
    vault_id: str, item_id: int, *, replace: bool = False,
) -> None:

    try:
        if not is_enabled():
            return
        assets = _collect_assets_from_db(vault_id)
        if not assets:
            return
        rels = derive_relationships(assets)
        ep = Endpoint(kind="vault_item", item_id=int(item_id))
        touching = [r for r in rels if r.source == ep or r.target == ep]
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    _delete_relationships_touching_endpoint(cur, vault_id, ep)
                if touching:
                    _insert_relationships(cur, vault_id, touching)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "build_relationships_for_item_safe failed vault=%s item=%s: %s",
            vault_id, item_id, e,
        )


def rebuild_vault_relationships_safe(
    vault_id: str,
) -> None:


    try:
        if not is_enabled():
            return
        assets = _collect_assets_from_db(vault_id)
        rels = derive_relationships(assets)
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM vault_relationships
                       WHERE vault_id=%s""",
                    (vault_id,),
                )
                if rels:
                    _insert_relationships(cur, vault_id, rels)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "rebuild_vault_relationships_safe failed vault=%s: %s",
            vault_id, e,
        )


def build_relationships_for_memory_safe(
    vault_id: str, memory_type: str, memory_key: str,
) -> None:


    return


RELATED_RENDER_MAX = 8


def _label_for_endpoint(
    ep: Endpoint, label_cache: dict, vault_id: str,
) -> str:


    if ep in label_cache:
        return label_cache[ep]
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if ep.kind == "uploaded_file":
                    cur.execute(
                        """SELECT saved_name, file_name FROM uploaded_files
                           WHERE id=%s AND vault_id=%s""",
                        (ep.file_id, vault_id),
                    )
                    row = cur.fetchone()
                    if row:
                        label_cache[ep] = (row[0] or row[1] or "file").strip() or "file"
                    else:
                        label_cache[ep] = "file"
                else:
                    cur.execute(
                        """SELECT service, item_type FROM vault_items
                           WHERE id=%s AND vault_id=%s""",
                        (ep.item_id, vault_id),
                    )
                    row = cur.fetchone()
                    if row:
                        service = (row[0] or "untitled").strip().title()
                        item_type = (row[1] or "login").strip().title()
                        label_cache[ep] = f"{service} ({item_type})"
                    else:
                        label_cache[ep] = "login"
        finally:
            conn.close()
    except Exception:
        label_cache[ep] = "asset"
    return label_cache[ep]


def _resolve_anchor_endpoints(
    vault_id: str, anchor_text: str,
) -> list[Endpoint]:


    if not anchor_text or not anchor_text.strip():
        return []
    needle = anchor_text.strip().lower()
    found: list[Endpoint] = []
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                             
                cur.execute(
                    """SELECT uploaded_file_id FROM vault_document_metadata
                       WHERE vault_id=%s
                         AND lower(doc_type)=%s""",
                    (vault_id, needle),
                )
                for (fid,) in cur.fetchall() or []:
                    found.append(Endpoint(kind="uploaded_file", file_id=fid))

                                                                    
                cur.execute(
                    """SELECT uploaded_file_id FROM vault_document_metadata
                       WHERE vault_id=%s
                         AND lower(coalesce(metadata_json ->> 'country','')) = %s""",
                    (vault_id, needle),
                )
                for (fid,) in cur.fetchall() or []:
                    found.append(Endpoint(kind="uploaded_file", file_id=fid))

                                        
                cur.execute(
                    """SELECT id FROM vault_items
                       WHERE vault_id=%s
                         AND lower(service) = %s""",
                    (vault_id, needle),
                )
                for (iid,) in cur.fetchall() or []:
                    found.append(Endpoint(kind="vault_item", item_id=int(iid)))

                                                                   
                cur.execute(
                    """SELECT id FROM uploaded_files
                       WHERE vault_id=%s
                         AND upload_status='complete'
                         AND (lower(coalesce(file_name,'')) LIKE %s
                              OR lower(coalesce(saved_name,'')) LIKE %s)""",
                    (vault_id, f"%{needle}%", f"%{needle}%"),
                )
                for (fid,) in cur.fetchall() or []:
                    found.append(Endpoint(kind="uploaded_file", file_id=fid))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("_resolve_anchor_endpoints failed: %s", e)
        return []
                             
    seen = set()
    unique: list[Endpoint] = []
    for ep in found:
        if ep not in seen:
            seen.add(ep)
            unique.append(ep)
    return unique


def _fetch_relationships_touching(
    vault_id: str, anchors: list[Endpoint],
) -> list[tuple[Endpoint, Endpoint, str]]:


    if not anchors:
        return []
    out: list[tuple[Endpoint, Endpoint, str]] = []
    try:
        anchor_files = [a.file_id for a in anchors if a.kind == "uploaded_file"]
        anchor_items = [a.item_id for a in anchors if a.kind == "vault_item"]
        conn = get_db()
        try:
            with conn.cursor() as cur:
                                                                   
                queries = []
                params = []
                if anchor_files:
                    queries.append(
                        "(source_file_id = ANY(%s) OR target_file_id = ANY(%s))"
                    )
                    params.extend([anchor_files, anchor_files])
                if anchor_items:
                    queries.append(
                        "(source_item_id = ANY(%s) OR target_item_id = ANY(%s))"
                    )
                    params.extend([anchor_items, anchor_items])
                if not queries:
                    return []
                where = " OR ".join(queries)
                cur.execute(
                    f"""SELECT source_kind, source_file_id, source_item_id,
                              target_kind, target_file_id, target_item_id,
                              relation_type
                       FROM vault_relationships
                       WHERE vault_id=%s AND ({where})""",
                    (vault_id, *params),
                )
                anchor_set = set(anchors)
                for (sk, sfid, siid, tk, tfid, tiid, rel) in cur.fetchall() or []:
                    src = Endpoint(kind=sk, file_id=sfid, item_id=siid)
                    tgt = Endpoint(kind=tk, file_id=tfid, item_id=tiid)
                    if src in anchor_set:
                        out.append((src, tgt, rel))
                    elif tgt in anchor_set:
                        out.append((tgt, src, rel))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("_fetch_relationships_touching failed: %s", e)
        return []
    return out


def handle_related_items(
    vault_id: str, anchor_text: str,
) -> Optional[str]:


    try:
        anchors = _resolve_anchor_endpoints(vault_id, anchor_text)
        if not anchors:
            return None

        rows = _fetch_relationships_touching(vault_id, anchors)
        if not rows:
            label_cache: dict = {}
            primary = _label_for_endpoint(anchors[0], label_cache, vault_id)
            return f"I don't see anything connected to {primary} yet."

                                                                  
        label_cache: dict = {}
        anchor_labels = {
            ep: _label_for_endpoint(ep, label_cache, vault_id)
            for ep in anchors
        }
        grouped: dict[str, list[str]] = defaultdict(list)
        for anchor_ep, other_ep, relation in rows:
            other_label = _label_for_endpoint(other_ep, label_cache, vault_id)
            grouped[relation].append(other_label)

        anchor_label_text = ", ".join(sorted(set(anchor_labels.values())))
        lines: list[str] = [
            f"Things related to {anchor_label_text}:"
        ]
                                                            
        for relation in RELATION_TYPES:
            members = grouped.get(relation)
            if not members:
                continue
            unique_sorted = sorted(set(members), key=lambda s: s.lower())
            shown = unique_sorted[:RELATED_RENDER_MAX]
            extra = len(unique_sorted) - len(shown)
            label = relation.replace("_related", "").title()
            lines.append("")
            lines.append(f"{label}:")
            for m in shown:
                lines.append(f"- {m}")
            if extra > 0:
                lines.append(f"...and {extra} more.")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("handle_related_items failed: %s", e)
        return None
