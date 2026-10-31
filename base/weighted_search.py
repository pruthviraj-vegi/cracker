"""
Centralized weighted search engine for all entities.

Provides per-field scoring, record caching, sibling (product/brand) expansion,
cache invalidation utilities, and search-field constants for signal handlers.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from django.core.cache import cache
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from customer.models import Customer
from inventory.models import Category, GSTHsnCode, Product, ProductVariant, UOM
from invoice.models import Invoice
from supplier.models import Supplier

logger = logging.getLogger(__name__)

CUSTOMER_WEIGHTED_CACHE_KEY = "customer_weighted_records"
SUPPLIER_WEIGHTED_CACHE_KEY = "supplier_weighted_records"
INVOICE_WEIGHTED_CACHE_KEY = "invoice_weighted_records"
PRODUCT_WEIGHTED_CACHE_KEY = "product_weighted_records"
PRODUCT_VARIANT_WEIGHTED_CACHE_KEY = "product_variant_weighted_records"
CATEGORY_WEIGHTED_CACHE_KEY = "category_weighted_records"
UOM_WEIGHTED_CACHE_KEY = "uom_weighted_records"
GST_HSN_WEIGHTED_CACHE_KEY = "gst_hsn_weighted_records"


# ==========================================
# SEARCH FIELD CONSTANTS (used by signal handlers)
# ==========================================

CUSTOMER_SEARCH_FIELDS = ("name", "phone_number", "email", "address")
INVOICE_SEARCH_FIELDS = (
    "invoice_number",
    "customer__name",
    "customer__phone_number",
    "notes",
)
PRODUCT_SEARCH_FIELDS = ("brand", "name", "category__name")
PRODUCT_VARIANT_SEARCH_FIELDS = (
    "barcode",
    "product__name",
    "product__brand",
    "product__category__name",
)
SUPPLIER_SEARCH_FIELDS = (
    "name",
    "phone",
    "email",
    "gstin",
    "first_line",
    "second_line",
    "city",
    "state",
    "pincode",
    "country",
)


# ==========================================
# CACHE UTILITIES
# ==========================================

# Precompiled regex for token extraction (used by signal handlers)
TOKENIZER = re.compile(r"[a-zA-Z0-9]+")


def get_instance_tokens(instance, fields):
    """
    Extract searchable tokens from a single model instance.

    Used by signals to check if cache invalidation is actually needed
    by comparing old vs. new tokens.
    """
    tokens = set()
    for field_path in fields:
        value = instance
        parts = field_path.split("__")
        try:
            for part in parts:
                if value is None:
                    break
                value = getattr(value, part)
        except AttributeError:
            continue

        if value:
            found = TOKENIZER.findall(str(value).lower())
            tokens.update(t for t in found if len(t) > 2)
    return tokens


def invalidate_cache(cache_key):
    """
    Clear a specific cache key.

    Used by signals to invalidate cache on model changes.
    """
    try:
        cache.delete(cache_key)
        logger.debug("Cache invalidated for key: %s", cache_key)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Cache backends can raise various underlying backend-specific errors
        # (e.g., redis.exceptions.ConnectionError) that aren't wrapped by Django.
        logger.error("Failed to invalidate cache for key %s: %s", cache_key, e)

FIELD_WEIGHTS = {
    "brand": 3.0,
    "name": 2.0,
    "category__name": 1.0,
}

VARIANT_FIELD_WEIGHTS = {
    "barcode": 4.0,
    "product__brand": 3.0,
    "product__name": 2.5,
    "size__name": 1.5,
    "color__name": 1.5,
    "product__category__name": 1.0,
}


# ==========================================
# PRODUCT WEIGHTED SEARCH
# ==========================================


def get_product_records(
    cache_key: str = PRODUCT_WEIGHTED_CACHE_KEY,
    cache_timeout: Optional[int] = None,
    max_records: int = 50000,
) -> List[Dict[str, Any]]:
    """
    Retrieves active product records for weighted search from cache or database.

    Each record dictionary contains:
    - id: Product ID
    - brand: Product brand string
    - name: Product name string
    - category__name: Name of the associated category (or empty string)
    """
    # 1. Try cache first
    try:
        cached_records = cache.get(cache_key)
        if cached_records is not None:
            return cached_records
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache read failed for key '%s': %s. Querying database directly.",
            cache_key,
            e,
        )

    # 2. Query from database
    try:
        queryset = (
            Product.objects.filter(is_deleted=False)
            .values("id", "brand", "name", "category__name")
            .iterator()
        )

        records: List[Dict[str, Any]] = []
        for row in queryset:
            brand = (row["brand"] or "").strip()
            name = (row["name"] or "").strip()
            category = (row["category__name"] or "").strip()

            brand_lower = brand.lower()
            name_lower = name.lower()
            category_lower = category.lower()

            brand_name = f"{brand_lower} {name_lower}".strip()
            full_comp = f"{brand_lower} {name_lower} {category_lower}".strip()
            name_words = tuple(name_lower.split()) if name_lower else ()
            comp_words = tuple(full_comp.split()) if full_comp else ()

            records.append(
                {
                    "id": row["id"],
                    "brand": brand,
                    "name": name,
                    "category__name": category,
                    # Pre-computed normalized search blobs for zero-allocation scoring
                    "brand_lower": brand_lower,
                    "name_lower": name_lower,
                    "category_lower": category_lower,
                    "brand_name": brand_name,
                    "full_comp": full_comp,
                    "name_words": name_words,
                    "comp_words": comp_words,
                }
            )
            if len(records) >= max_records:
                break
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to load product records from database: %s", e)
        return []

    # 3. Store in cache
    try:
        cache.set(cache_key, records, cache_timeout)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache write failed for key '%s': %s. Results returned without caching.",
            cache_key,
            e,
        )

    return records


def word_match_quality(qw: str, cw: str) -> float:
    """
    Evaluates fuzzy match quality between a single query word and a candidate word.
    Protects against short-word partial_ratio false positives (e.g. 'r' matching 'hepper' at 90%).
    """
    if qw == cw:
        return 100.0
    # Prevent 1-2 char words from matching long words via partial ratio
    if (len(cw) <= 2 and len(qw) > 2) or (len(qw) <= 2 and len(cw) > 2):
        return 0.0
    if cw.startswith(qw):
        return 95.0
    sim = Levenshtein.normalized_similarity(qw, cw) * 100
    if sim >= 70.0:
        if qw[0] == cw[0]:
            sim = min(100.0, sim + 10.0)
        return float(sim)
    if len(qw) >= 3 and qw in cw:
        return 85.0
    return 0.0


def score_product(
    query: str,
    product: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Scores a single product record against a query using weighted field fuzzy matching,
    per-word alignment scoring (handles typos like 'special gald' -> 'special gold'),
    and token sort ratio (for unordered words like 'gold special').
    """
    if not query or not product:
        return 0.0

    if weights is None:
        weights = FIELD_WEIGHTS

    query_str = query.strip().lower()
    q_words = query_str.split()
    max_weight = max(weights.values()) if weights else 1.0

    # Retrieve pre-computed lowercase fields if present, fallback for backwards compatibility
    brand = product.get("brand_lower")
    if brand is None:
        brand = str(product.get("brand", "") or "").strip().lower()
    name = product.get("name_lower")
    if name is None:
        name = str(product.get("name", "") or "").strip().lower()
    category = product.get("category_lower")
    if category is None:
        category = str(product.get("category__name", "") or "").strip().lower()

    brand_name = product.get("brand_name")
    if brand_name is None:
        brand_name = f"{brand} {name}".strip()

    full_comp = product.get("full_comp")
    if full_comp is None:
        full_comp = f"{brand} {name} {category}".strip()

    name_words = product.get("name_words")
    if name_words is None:
        name_words = tuple(name.split()) if name else ()

    field_lower_map = {
        "brand": brand,
        "name": name,
        "category__name": category,
    }

    # 1. Direct field matches (WRatio and token_sort_ratio)
    best_field_score = 0.0
    for field_name, weight in weights.items():
        val_str = field_lower_map.get(field_name)
        if val_str is None:
            val = product.get(field_name, "")
            if not val:
                continue
            val_str = str(val).strip().lower()
        if not val_str:
            continue

        # Early exact-match exit
        if query_str == val_str:
            return 100.0

        f_wratio = fuzz.WRatio(query_str, val_str)
        f_sort = fuzz.token_sort_ratio(query_str, val_str)

        # Word-level match within field for single-word typo tolerance
        if field_name == "name" and name_words:
            val_words = name_words
        else:
            val_words = val_str.split()
        max_word_match = max((fuzz.WRatio(query_str, w) for w in val_words), default=0.0) if val_words else 0.0

        f_score = max(f_wratio, f_sort, max_word_match)

        # Prefix boost (consistency with score_generic_record)
        if val_str.startswith(query_str) or any(w.startswith(query_str) for w in val_words):
            f_score = min(100.0, f_score + 10.0)

        weight_multiplier = 0.7 + 0.3 * (weight / max_weight)
        weighted_score = f_score * weight_multiplier
        if weighted_score > best_field_score:
            best_field_score = weighted_score

    # 2. Composite string matches
    best_name_word_score = 0.0
    for w in name_words:
        if len(w) >= 2:
            sim = Levenshtein.normalized_similarity(query_str, w) * 100
            if sim >= 70.0 and query_str and w and query_str[0] == w[0]:
                sim = min(100.0, sim + 10.0)
            if sim > best_name_word_score:
                best_name_word_score = sim

    whole_name_score = max(fuzz.WRatio(query_str, name), fuzz.token_sort_ratio(query_str, name)) if name else 0.0
    name_score = max(whole_name_score, best_name_word_score)
    brand_name_score = max(fuzz.WRatio(query_str, brand_name), fuzz.token_sort_ratio(query_str, brand_name)) if brand_name else 0.0

    # 3. Word-by-word alignment for multi-word queries (handles typos & reordering with token coverage)
    if len(q_words) > 1 and full_comp:
        comp_words = product.get("comp_words")
        if comp_words is None:
            comp_words = tuple(full_comp.split())
        word_scores = []
        for qw in q_words:
            best_qw_score = max(
                (word_match_quality(qw, cw) for cw in comp_words),
                default=0.0,
            )
            word_scores.append(best_qw_score)

        avg_score = sum(word_scores) / len(word_scores)
        matched_words = sum(1 for s in word_scores if s >= 65.0)
        coverage = matched_words / len(q_words)
        if coverage < 0.6:
            word_alignment_score = avg_score * (coverage ** 2)
        else:
            word_alignment_score = avg_score
    else:
        word_alignment_score = 0.0

    final_score = max(
        best_field_score,
        name_score,
        brand_name_score,
        word_alignment_score,
    )
    return round(final_score, 2)


def search_products_weighted(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
    limit: int = 10,
    min_score: float = 50.0,
    anchor_confidence: float = 80.0,
    sibling_boost_factor: float = 0.85,
) -> List[Dict[str, Any]]:
    """
    Performs weighted product fuzzy search with anchor sibling (brand) expansion.

    Workflow:
    1. Score each product per-field with weights and composite string evaluation.
    2. Rank candidates by direct score.
    3. If the top candidate (anchor) meets or exceeds anchor_confidence:
       - Find sibling products under the same brand.
       - Boost sibling scores so they surface alongside the anchor.
       - Re-sort to incorporate siblings.
    4. Filter out any items below min_score and return the top `limit` results.
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_product_records()

    if not records:
        return []

    if weights is None:
        weights = FIELD_WEIGHTS

    query_clean = query.strip()
    query_lower = query_clean.lower()
    q_words = query_lower.split()

    # 1. Compute direct score for each product (with fast pre-filtering for large catalogs)
    scored_items: List[Dict[str, Any]] = []
    use_prefilter = len(records) > 200

    for product in records:
        if use_prefilter:
            full_comp = product.get("full_comp")
            if full_comp:
                comp_words = product.get("comp_words") or ()
                has_match = (
                    any(qw in full_comp for qw in q_words)
                    or any(fuzz.ratio(qw, cw, score_cutoff=70.0) >= 70.0 for qw in q_words for cw in comp_words)
                )
                if not has_match:
                    continue

        direct_score = score_product(query_clean, product, weights)
        scored_items.append(
            {
                "id": product.get("id"),
                "brand": product.get("brand", ""),
                "name": product.get("name", ""),
                "category__name": product.get("category__name", ""),
                "score": direct_score,
                "direct_score": direct_score,
                "is_anchor": False,
                "is_sibling": False,
            }
        )

    # 2. Sort descending by direct score
    scored_items.sort(key=lambda x: x["direct_score"], reverse=True)

    if not scored_items:
        return []

    # 3. Sibling expansion check
    top_item = scored_items[0]
    if top_item["direct_score"] >= anchor_confidence:
        top_item["is_anchor"] = True
        anchor_brand = top_item["brand"].strip().lower()
        anchor_score = top_item["direct_score"]

        if anchor_brand:
            boosted_score = anchor_score * sibling_boost_factor
            for item in scored_items[1:]:
                item_brand = item["brand"].strip().lower()
                if item_brand == anchor_brand:
                    item["is_sibling"] = True
                    if item["score"] < boosted_score:
                        item["score"] = boosted_score

            # Re-sort with boosted scores (tie-break on direct_score then name length)
            scored_items.sort(
                key=lambda x: (x["score"], x["direct_score"], -len(x["name"])),
                reverse=True,
            )

    # 4. Filter by min_score and limit results
    results = [item for item in scored_items if item["score"] >= min_score]
    return results[:limit]


def format_product_suggestion_label(brand: str, name: str, query: str) -> str:
    """
    Formats product suggestion label based on what the user is searching for:
    - If searching by name (e.g. 'special' or 'gold special'), formats as 'special gold' (omits brand prefix).
    - If searching by brand (e.g. 'saree'), formats as 'saree special gold'.
    - If searching by brand + name (e.g. 'saree gold'), formats as 'saree special gold'.
    """
    brand = brand.strip()
    name = name.strip()
    if not brand and not name:
        return ""
    if not brand:
        return name
    if not name:
        return brand

    q = query.strip().lower()
    b = brand.lower()
    n = name.lower()

    q_words = q.split()
    n_words = n.split()
    b_words = b.split()

    # If all query words match words in product name (e.g. 'gold special' matching 'special gold')
    if q_words and all(any(nw.startswith(qw) or fuzz.WRatio(qw, nw) >= 80 for nw in n_words) for qw in q_words):
        # And brand is not part of query words
        if not any(any(bw.startswith(qw) or fuzz.WRatio(qw, bw) >= 80 for bw in b_words) for qw in q_words):
            return name

    # Check if query directly matches or starts matching product name
    n_starts = n.startswith(q) or any(word.startswith(q) for word in n_words)
    b_starts = b.startswith(q) or any(word.startswith(q) for word in b_words)

    # If query matches name words and does NOT match brand, suggest by name directly
    if n_starts and not b_starts:
        return name

    # If fuzzy match on name is high and significantly stronger than brand
    n_score = max(fuzz.WRatio(q, n), fuzz.token_set_ratio(q, n))
    b_score = max(fuzz.WRatio(q, b), fuzz.token_set_ratio(q, b))
    if n_score >= 70 and n_score > b_score + 20:
        return name

    # Otherwise default to full 'Brand Name'
    return f"{brand} {name}"


def score_brand_or_category_match(query_clean: str, target_name: str) -> float:
    """
    Evaluates how strongly a single-word query matches a brand or category name.
    Requires an exact match, prefix match on the target name or its words,
    or a high full-ratio match (>= 75.0) for typo tolerance.
    Avoids loose partial-ratio matches that incorrectly match unrelated entities.
    """
    q = query_clean.strip().lower()
    t = target_name.strip().lower()
    if not q or not t:
        return 0.0
    if q == t:
        return 100.0
    t_words = t.split()
    if t.startswith(q):
        return 95.0
    if any(w.startswith(q) for w in t_words):
        return 90.0
    # Typo tolerance: full string ratio (NOT loose partial ratio)
    ratio = max(fuzz.ratio(q, t), fuzz.token_sort_ratio(q, t))
    if ratio >= 75.0:
        return float(ratio)
    return 0.0


def get_weighted_product_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 50.0,
    anchor_confidence: float = 80.0,
    rich: bool = False,
) -> List[Any]:
    """
    Returns unique formatted suggestions for autosuggestion dropdowns.

    Hierarchical Behavior:
    - If query is 1 word (e.g. 'mayra' or 'mayur'):
      1. Returns matching Brands (e.g. 'Mayra')
      2. Returns matching Categories (e.g. 'Shirts')
      3. Returns matching Products (e.g. 'Mayra Supreme' or 'Special Black')
    - If query is 2+ words (e.g. 'mayra sup' or 'special black'):
      1. Refines directly to matching products

    If rich=True:
      Returns list of dicts: [{"label": "...", "type": "brand"|"product"|"category"}, ...]
    If rich=False:
      Returns list of strings: ["...", ...]
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_product_records()

    if not records:
        return []

    query_clean = query.strip()
    tokens = query_clean.split()

    candidates: List[Any] = []
    seen = set()

    def add_candidate(score: float, label: str, item_type: str):
        label_clean = label.strip()
        if not label_clean:
            return
        label_lower = label_clean.lower()
        if label_lower not in seen:
            seen.add(label_lower)
            candidates.append((score, label_clean, item_type))

    # Case 1: Single-word query -> Check matching Brands & Categories (strict)
    if len(tokens) == 1:
        unique_brands: Dict[str, str] = {}
        unique_categories: Dict[str, str] = {}
        for item in records:
            brand = (item.get("brand") or "").strip()
            cat = (item.get("category__name") or "").strip()
            if brand:
                unique_brands[brand.lower()] = brand
            if cat:
                unique_categories[cat.lower()] = cat

        # Match Brands (strict prefix/exact/high-ratio)
        for brand_lower, brand_orig in unique_brands.items():
            b_score = score_brand_or_category_match(query_clean, brand_orig)
            if b_score >= min_score:
                add_candidate(b_score, brand_orig, "brand")

        # Match Categories (strict prefix/exact/high-ratio)
        for cat_lower, cat_orig in unique_categories.items():
            c_score = score_brand_or_category_match(query_clean, cat_orig)
            if c_score >= min_score:
                add_candidate(c_score, cat_orig, "category")

    # Match Products
    ranked_products = search_products_weighted(
        query=query_clean,
        records=records,
        limit=limit * 2,
        min_score=min_score,
        anchor_confidence=anchor_confidence,
    )

    for item in ranked_products:
        brand = item.get("brand", "").strip()
        name = item.get("name", "").strip()

        label = format_product_suggestion_label(brand, name, query_clean)
        if not label:
            continue

        add_candidate(item.get("score", 0.0), label, "product")

    # Sort all candidates together by relevance score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    results = [{"label": c[1], "type": c[2]} for c in candidates[:limit]]

    if rich:
        return results
    return [s["label"] for s in results]


# ==========================================
# PRODUCT VARIANT WEIGHTED SEARCH
# ==========================================


def get_variant_records(
    cache_key: str = PRODUCT_VARIANT_WEIGHTED_CACHE_KEY,
    cache_timeout: Optional[int] = None,
    max_records: int = 50000,
) -> List[Dict[str, Any]]:
    """
    Retrieves active product variant records for weighted search from cache or database.

    Each record dictionary contains:
    - id: Variant ID
    - barcode: Barcode string
    - product_id: Associated Product ID
    - product__brand: Associated Product Brand
    - product__name: Associated Product Name
    - product__category__name: Associated Category Name
    - size__name: Size name (or empty string)
    - color__name: Color name (or empty string)
    """
    # 1. Try cache first
    try:
        cached_records = cache.get(cache_key)
        if cached_records is not None:
            return cached_records
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache read failed for key '%s': %s. Querying database directly.",
            cache_key,
            e,
        )

    # 2. Query from database
    try:
        queryset = (
            ProductVariant.objects.filter(
                is_deleted=False,
                status="ACTIVE",
                product__is_deleted=False,
            )
            .values(
                "id",
                "barcode",
                "product_id",
                "product__brand",
                "product__name",
                "product__category__name",
                "size__name",
                "color__name",
            )
            .iterator()
        )

        records: List[Dict[str, Any]] = []
        for row in queryset:
            brand = (row["product__brand"] or "").strip()
            name = (row["product__name"] or "").strip()
            size = (row["size__name"] or "").strip()
            color = (row["color__name"] or "").strip()
            category = (row["product__category__name"] or "").strip()
            barcode = (row["barcode"] or "").strip()

            name_details = f"{name} {size} {color}".strip().lower()
            brand_name = f"{brand} {name}".strip().lower()
            full_composite = f"{brand} {name} {size} {color} {category}".strip().lower()
            search_blob = f"{brand} {name} {size} {color} {category} {barcode}".strip().lower()
            comp_words = tuple(full_composite.split()) if full_composite else ()
            brand_lower = brand.lower()
            name_lower = name.lower()
            name_words = tuple(name_lower.split()) if name_lower else ()

            records.append(
                {
                    "id": row["id"],
                    "barcode": barcode,
                    "product_id": row["product_id"],
                    "product__brand": brand,
                    "product__name": name,
                    "product__category__name": category,
                    "size__name": size,
                    "color__name": color,
                    # Pre-computed normalized search blobs for zero-allocation scoring
                    "product__brand_lower": brand_lower,
                    "product__name_lower": name_lower,
                    "name_words": name_words,
                    "name_details": name_details,
                    "brand_name": brand_name,
                    "full_composite": full_composite,
                    "search_blob": search_blob,
                    "comp_words": comp_words,
                }
            )
            if len(records) >= max_records:
                break
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to load variant records from database: %s", e)
        return []

    # 3. Store in cache
    try:
        cache.set(cache_key, records, cache_timeout)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache write failed for key '%s': %s. Results returned without caching.",
            cache_key,
            e,
        )

    return records


def score_variant(
    query: str,
    variant: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Scores a single variant record against a query using weighted field fuzzy matching,
    token set/sort ratio (for unordered words), and full composite string matching.
    """
    if not query or not variant:
        return 0.0

    if weights is None:
        weights = VARIANT_FIELD_WEIGHTS

    query_str = query.strip().lower()
    q_words = query_str.split()
    max_weight = max(weights.values()) if weights else 1.0

    # 1. Best field match score adjusted by field weight importance
    best_field_score = 0.0
    for field_name, weight in weights.items():
        val = variant.get(field_name, "")
        if not val:
            continue
        val_str = str(val).strip().lower()
        if not val_str:
            continue

        # Early exact-match exit
        if query_str == val_str:
            return 100.0

        if len(q_words) > 1:
            f_score = fuzz.token_sort_ratio(query_str, val_str)
        else:
            f_wratio = fuzz.WRatio(query_str, val_str)
            f_sort = fuzz.token_sort_ratio(query_str, val_str)
            val_words = val_str.split()
            max_word_match = max((fuzz.WRatio(query_str, w) for w in val_words), default=0.0) if val_words else 0.0
            f_score = max(f_wratio, f_sort, max_word_match)
            if val_str.startswith(query_str) or any(w.startswith(query_str) for w in val_words):
                f_score = min(100.0, f_score + 10.0)

        weight_multiplier = 0.7 + 0.3 * (weight / max_weight)
        weighted_score = f_score * weight_multiplier
        if weighted_score > best_field_score:
            best_field_score = weighted_score

    # 2. Composite string matching (use pre-computed normalized blobs if available)
    brand = variant.get("product__brand_lower")
    if brand is None:
        brand = str(variant.get("product__brand", "") or "").strip().lower()
    name = variant.get("product__name_lower")
    if name is None:
        name = str(variant.get("product__name", "") or "").strip().lower()

    barcode = str(variant.get("barcode", "") or "").strip().lower()

    # Product Name alone (crucial for queries targeting product name like 'special gald' -> 'special gold')
    name_words = variant.get("name_words")
    if name_words is None:
        name_words = tuple(name.split()) if name else ()
    best_name_word_score = 0.0
    for w in name_words:
        if len(w) >= 2:
            sim = Levenshtein.normalized_similarity(query_str, w) * 100
            if sim >= 70.0 and query_str and w and query_str[0] == w[0]:
                sim = min(100.0, sim + 10.0)
            if sim > best_name_word_score:
                best_name_word_score = sim

    whole_name_score = max(fuzz.WRatio(query_str, name), fuzz.token_sort_ratio(query_str, name)) if name else 0.0
    name_score = max(whole_name_score, best_name_word_score)

    # Name + Size + Color
    name_details = variant.get("name_details")
    if name_details is None:
        size = str(variant.get("size__name", "") or "").strip().lower()
        color = str(variant.get("color__name", "") or "").strip().lower()
        name_details = f"{name} {size} {color}".strip()
    name_details_score = max(fuzz.WRatio(query_str, name_details), fuzz.token_sort_ratio(query_str, name_details)) if name_details else 0.0

    # Brand + Name
    brand_name = variant.get("brand_name")
    if brand_name is None:
        brand_name = f"{brand} {name}".strip()
    brand_name_score = max(fuzz.WRatio(query_str, brand_name), fuzz.token_sort_ratio(query_str, brand_name)) if brand_name else 0.0

    # Full Composite
    full_composite = variant.get("full_composite")
    if full_composite is None:
        size = str(variant.get("size__name", "") or "").strip().lower()
        color = str(variant.get("color__name", "") or "").strip().lower()
        category = str(variant.get("product__category__name", "") or "").strip().lower()
        full_composite = f"{brand} {name} {size} {color} {category}".strip()
    full_comp_wratio = fuzz.WRatio(query_str, full_composite) if full_composite else 0.0
    full_comp_sort = fuzz.token_sort_ratio(query_str, full_composite) if full_composite else 0.0

    # Barcode
    barcode_score = fuzz.WRatio(query_str, barcode) if barcode else 0.0

    # 3. Word-by-word alignment for multi-word queries (handles typos & reordering)
    if len(q_words) > 1 and full_composite:
        comp_words = variant.get("comp_words")
        if comp_words is None:
            comp_words = tuple(full_composite.split())
        word_scores = []
        for qw in q_words:
            best_qw_score = max(
                (word_match_quality(qw, cw) for cw in comp_words),
                default=0.0,
            )
            word_scores.append(best_qw_score)

        avg_score = sum(word_scores) / len(word_scores)
        matched_words = sum(1 for s in word_scores if s >= 65.0)
        coverage = matched_words / len(q_words)
        if coverage < 0.6:
            word_alignment_score = avg_score * (coverage ** 2)
            full_comp_wratio = 0.0
            full_comp_sort = 0.0
            name_score = 0.0
            name_details_score = 0.0
            brand_name_score = 0.0
        else:
            word_alignment_score = avg_score
            full_comp_sort = fuzz.token_sort_ratio(query_str, full_composite)
            name_score = fuzz.token_sort_ratio(query_str, name) if name else 0.0
            name_details_score = fuzz.token_sort_ratio(query_str, name_details) if name_details else 0.0
            brand_name_score = fuzz.token_sort_ratio(query_str, brand_name) if brand_name else 0.0
    else:
        word_alignment_score = 0.0

    final_score = max(
        best_field_score,
        name_score,
        name_details_score,
        brand_name_score,
        full_comp_wratio,
        full_comp_sort,
        barcode_score,
        word_alignment_score,
    )
    return round(final_score, 2)


def search_variants_weighted(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    weights: Optional[Dict[str, float]] = None,
    limit: int = 10,
    min_score: float = 50.0,
    anchor_confidence: float = 80.0,
    product_sibling_boost: float = 0.90,
    brand_sibling_boost: float = 0.75,
) -> List[Dict[str, Any]]:
    """
    Performs weighted variant fuzzy search with hierarchical sibling expansion:
    1. Direct per-field scoring for each variant record.
    2. Identify top scoring anchor variant.
    3. If anchor score meets anchor_confidence:
       - Boost other variants of the SAME product (product siblings).
       - Boost other variants of the SAME brand (brand siblings).
    4. Re-sort and filter by min_score.
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_variant_records()

    if not records:
        return []

    if weights is None:
        weights = VARIANT_FIELD_WEIGHTS

    query_clean = query.strip()
    query_lower = query_clean.lower()
    q_words = query_lower.split()

    # 1. Compute direct score for each variant (with fast pre-filtering for large record sets)
    scored_items: List[Dict[str, Any]] = []
    use_prefilter = len(records) > 200

    for variant in records:
        if use_prefilter:
            search_blob = variant.get("search_blob")
            if search_blob:
                comp_words = variant.get("comp_words") or ()
                # Fast gate: check if query tokens appear as substrings OR have word-level typo tolerance
                has_match = (
                    any(qw in search_blob for qw in q_words)
                    or any(fuzz.ratio(qw, cw, score_cutoff=70.0) >= 70.0 for qw in q_words for cw in comp_words)
                )
                if not has_match:
                    continue

        direct_score = score_variant(query_clean, variant, weights)
        scored_items.append(
            {
                "id": variant.get("id"),
                "barcode": variant.get("barcode", ""),
                "product_id": variant.get("product_id"),
                "product__brand": variant.get("product__brand", ""),
                "product__name": variant.get("product__name", ""),
                "product__category__name": variant.get("product__category__name", ""),
                "size__name": variant.get("size__name", ""),
                "color__name": variant.get("color__name", ""),
                "score": direct_score,
                "direct_score": direct_score,
                "is_anchor": False,
                "is_product_sibling": False,
                "is_brand_sibling": False,
            }
        )

    # 2. Sort descending by direct score
    scored_items.sort(key=lambda x: x["direct_score"], reverse=True)

    if not scored_items:
        return []

    # 3. Sibling expansion check
    top_item = scored_items[0]
    if top_item["direct_score"] >= anchor_confidence:
        top_item["is_anchor"] = True
        anchor_product_id = top_item.get("product_id")
        anchor_brand = top_item.get("product__brand", "").strip().lower()
        anchor_score = top_item["direct_score"]

        boosted_prod_score = anchor_score * product_sibling_boost
        boosted_brand_score = anchor_score * brand_sibling_boost

        for item in scored_items[1:]:
            # Check same product sibling
            if anchor_product_id and item.get("product_id") == anchor_product_id:
                item["is_product_sibling"] = True
                if item["score"] < boosted_prod_score:
                    item["score"] = boosted_prod_score
            # Check same brand sibling
            elif anchor_brand and item.get("product__brand", "").strip().lower() == anchor_brand:
                item["is_brand_sibling"] = True
                if item["score"] < boosted_brand_score:
                    item["score"] = boosted_brand_score

        # Re-sort with boosted scores
        scored_items.sort(
            key=lambda x: (x["score"], x["direct_score"]),
            reverse=True,
        )

    # 4. Filter by min_score with relative drop-off threshold to prune unrelated noise
    if scored_items:
        top_score = scored_items[0]["score"]
        # If top score is high (>= 80), prune items that fall far below the top match
        threshold = max(min_score, top_score * 0.65) if top_score >= 80.0 else min_score
    else:
        threshold = min_score

    results = [item for item in scored_items if item["score"] >= threshold]
    return results[:limit]


def get_weighted_variant_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 50.0,
    anchor_confidence: float = 80.0,
    rich: bool = False,
) -> List[Any]:
    """
    Returns unique formatted suggestions for variant autosuggestion dropdowns.

    Hierarchical Behavior:
    - If 1 word: Brand -> Product -> Variant
    - If 2+ words: Refined Variant/Product

    If rich=True:
      Returns list of dicts: [{"label": "...", "type": "brand"|"product"|"variant"|"barcode"}]
    If rich=False:
      Returns list of strings
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_variant_records()

    if not records:
        return []

    query_clean = query.strip()
    tokens = query_clean.split()

    candidates: List[Any] = []
    seen = set()

    def add_candidate(score: float, label: str, item_type: str):
        label_clean = label.strip()
        if not label_clean:
            return
        label_lower = label_clean.lower()
        if label_lower not in seen:
            seen.add(label_lower)
            candidates.append((score, label_clean, item_type))

    # Case 1: Single-word query -> Check matching Brands (strict)
    if len(tokens) == 1:
        unique_brands: Dict[str, str] = {}
        for item in records:
            brand = (item.get("product__brand") or "").strip()
            if brand:
                unique_brands[brand.lower()] = brand

        for brand_lower, brand_orig in unique_brands.items():
            b_score = score_brand_or_category_match(query_clean, brand_orig)
            if b_score >= min_score:
                add_candidate(b_score, brand_orig, "brand")

    # Variant & product matches
    ranked_variants = search_variants_weighted(
        query=query_clean,
        records=records,
        limit=limit * 2,
        min_score=min_score,
        anchor_confidence=anchor_confidence,
    )

    for item in ranked_variants:
        brand = item.get("product__brand", "").strip()
        name = item.get("product__name", "").strip()
        size = item.get("size__name", "").strip()
        color = item.get("color__name", "").strip()
        barcode = item.get("barcode", "").strip()

        prod_label = format_product_suggestion_label(brand, name, query_clean)
        details = [p for p in (size, color) if p]

        if prod_label:
            label = f"{prod_label} {' '.join(details)}".strip() if details else prod_label
            item_type = "variant" if details else ("product" if (brand and name) else "brand")
        elif barcode:
            label = barcode
            item_type = "barcode"
        elif details:
            label = " ".join(details)
            item_type = "variant"
        else:
            continue

        add_candidate(item.get("score", 0.0), label, item_type)

    # Sort all candidates together by relevance score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    results = [{"label": c[1], "type": c[2]} for c in candidates[:limit]]

    if rich:
        return results
    return [s["label"] for s in results]


# ==========================================
# GENERIC WEIGHTED SEARCH & SUGGESTION ENGINE
# ==========================================


@dataclass
class GenericSearchConfig:
    """
    Declarative configuration for the Generic Weighted Search Engine.
    """

    name: str
    model_class: Any
    cache_key: str
    fields: List[str]
    weights: Dict[str, float]
    filter_kwargs: Dict[str, Any] = field(default_factory=lambda: {"is_deleted": False})
    label_builder: Optional[Callable[[Dict[str, Any], str], str]] = None
    item_type: str = "item"
    max_records: int = 50000
    cache_timeout: Optional[int] = None


def get_generic_records(config: GenericSearchConfig) -> List[Dict[str, Any]]:
    """
    Retrieves records for a generic search configuration from cache or database.
    """
    # 1. Try cache
    try:
        cached_records = cache.get(config.cache_key)
        if cached_records is not None:
            return cached_records
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache read failed for key '%s': %s. Querying database directly.",
            config.cache_key,
            e,
        )

    # 2. Database query
    try:
        qs = config.model_class.objects.filter(**config.filter_kwargs).values(*config.fields)
        records: List[Dict[str, Any]] = []
        for row in qs.iterator():
            rec = {f: (row.get(f) or "") for f in config.fields}

            # Pre-compute normalized fields and composite search blob for zero-allocation scoring
            lower_fields: Dict[str, str] = {}
            field_words_map: Dict[str, tuple] = {}
            comp_parts: List[str] = []
            for f in config.fields:
                val = rec[f]
                val_str = str(val).strip().lower() if val else ""
                lower_fields[f] = val_str
                if val_str:
                    w_tup = tuple(val_str.split())
                    field_words_map[f] = w_tup
                    if f in config.weights:
                        comp_parts.append(val_str)

            composite_str = " ".join(comp_parts).strip()
            comp_words = tuple(composite_str.split()) if composite_str else ()

            rec["__lower_fields__"] = lower_fields
            rec["__field_words__"] = field_words_map
            rec["__composite_str__"] = composite_str
            rec["__comp_words__"] = comp_words

            records.append(rec)
            if len(records) >= config.max_records:
                break
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to load records for '%s': %s", config.name, e)
        return []

    # 3. Store in cache
    try:
        cache.set(config.cache_key, records, config.cache_timeout)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Cache write failed for key '%s': %s. Results returned without caching.",
            config.cache_key,
            e,
        )

    return records


def score_generic_record(
    query: str,
    record: Dict[str, Any],
    config: GenericSearchConfig,
) -> float:
    """
    Scores a single dictionary record using field weights, composite matching,
    word alignment (for typo tolerance), and token sort (for reversed/unordered words).
    """
    if not query or not record:
        return 0.0

    query_str = query.strip().lower()
    q_words = query_str.split()
    weights = config.weights
    max_weight = max(weights.values()) if weights else 1.0

    lower_fields = record.get("__lower_fields__")
    field_words_map = record.get("__field_words__")
    composite_str = record.get("__composite_str__")
    comp_words = record.get("__comp_words__")

    # Fallback if record was cached prior to pre-computation optimization
    if lower_fields is None:
        lower_fields = {}
        field_words_map = {}
        comp_parts = []
        for f in config.fields:
            val = record.get(f, "")
            val_str = str(val).strip().lower() if val else ""
            lower_fields[f] = val_str
            if val_str:
                field_words_map[f] = tuple(val_str.split())
                if f in weights:
                    comp_parts.append(val_str)
        composite_str = " ".join(comp_parts).strip()
        comp_words = tuple(composite_str.split()) if composite_str else ()

    # 1. Direct field matches
    best_field_score = 0.0
    for field_name, weight in weights.items():
        val_str = lower_fields.get(field_name, "")
        if not val_str:
            continue

        # Early exact-match exit
        if query_str == val_str:
            return 100.0

        f_wratio = fuzz.WRatio(query_str, val_str)
        f_sort = fuzz.token_sort_ratio(query_str, val_str)

        # Word-level match within field for single-word typo tolerance
        val_words = field_words_map.get(field_name) or ()
        max_word_match = max((fuzz.WRatio(query_str, w) for w in val_words), default=0.0) if val_words else 0.0

        f_score = max(f_wratio, f_sort, max_word_match)

        # Prefix bonus
        if val_str.startswith(query_str) or any(w.startswith(query_str) for w in val_words):
            f_score = min(100.0, f_score + 10.0)

        weight_multiplier = 0.7 + 0.3 * (weight / max_weight)
        weighted_score = f_score * weight_multiplier
        if weighted_score > best_field_score:
            best_field_score = weighted_score

    # 2. Composite string match
    comp_wratio = fuzz.WRatio(query_str, composite_str) if composite_str else 0.0
    comp_sort = fuzz.token_sort_ratio(query_str, composite_str) if composite_str else 0.0

    # 3. Word-by-word alignment for multi-word queries
    if len(q_words) > 1 and composite_str:
        word_scores = []
        for qw in q_words:
            best_qw_score = max(
                (fuzz.WRatio(qw, cw) for cw in comp_words),
                default=0.0,
            )
            if any(cw.startswith(qw) for cw in comp_words):
                best_qw_score = max(best_qw_score, 95.0)
            word_scores.append(best_qw_score)
        word_alignment_score = sum(word_scores) / len(word_scores)
    else:
        word_alignment_score = 0.0

    final_score = max(
        best_field_score,
        comp_wratio,
        comp_sort,
        word_alignment_score,
    )
    return round(final_score, 2)


def search_generic_weighted(
    query: str,
    config: GenericSearchConfig,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
) -> List[Dict[str, Any]]:
    """
    Performs weighted fuzzy search across a generic configuration.
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_generic_records(config)

    if not records:
        return []

    query_clean = query.strip()
    query_lower = query_clean.lower()
    q_words = query_lower.split()

    use_prefilter = len(records) > 200
    scored = []
    for item in records:
        if use_prefilter:
            composite_str = item.get("__composite_str__")
            if composite_str:
                comp_words = item.get("__comp_words__") or ()
                has_match = (
                    any(qw in composite_str for qw in q_words)
                    or any(fuzz.ratio(qw, cw, score_cutoff=70.0) >= 70.0 for qw in q_words for cw in comp_words)
                )
                if not has_match:
                    continue

        score = score_generic_record(query_clean, item, config)
        if score >= min_score:
            scored.append({"item": item, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return [x["item"] for x in scored[:limit]]


def get_generic_suggestions(
    query: str,
    config: GenericSearchConfig,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    """
    Returns unique, formatted suggestions for a generic configuration.
    """
    if not query or len(query.strip()) < 2:
        return []

    if records is None:
        records = get_generic_records(config)

    if not records:
        return []

    query_clean = query.strip()
    matched = search_generic_weighted(
        query=query_clean,
        config=config,
        records=records,
        limit=limit * 2,
        min_score=min_score,
    )

    suggestions: List[Dict[str, str]] = []
    seen = set()

    for item in matched:
        if config.label_builder:
            label = config.label_builder(item, query_clean)
        else:
            label_field = "name" if "name" in config.fields else next((f for f in config.fields if f != "id"), config.fields[0])
            label = str(item.get(label_field, "")).strip()

        if not label:
            continue
        label_lower = label.lower()
        if label_lower not in seen:
            seen.add(label_lower)
            suggestions.append({"label": label, "type": config.item_type})
        if len(suggestions) >= limit:
            break

    if rich:
        return suggestions[:limit]
    return [s["label"] for s in suggestions[:limit]]


# ==========================================
# ENTITY LABEL BUILDERS & SEARCH CONFIGURATIONS
# ==========================================


def format_customer_suggestion_label(record: Dict[str, Any], query: str) -> str:
    """
    Smart label builder for Customer / Member records:
    - If user types digits / phone: displays 'Name Phone'
    - If user types email: displays 'Name Email'
    - Otherwise displays 'Name'
    """
    name = str(record.get("name") or "").strip()
    phone = str(record.get("phone_number") or "").strip()
    email = str(record.get("email") or "").strip()
    q = query.strip().lower()

    if not name and not phone:
        return ""
    if not name:
        return phone
    if not phone:
        return name

    # If query contains digits or matches phone prefix/suffix
    if any(c.isdigit() for c in q) and (phone.startswith(q) or phone.endswith(q) or q in phone):
        return f"{name} {phone}".strip()

    # If query targets email specifically
    if email and q in email.lower() and q not in name.lower():
        return f"{name} {email}".strip()

    return name


def format_supplier_suggestion_label(record: Dict[str, Any], query: str) -> str:
    """
    Smart label builder for Supplier records:
    - If user searches by city: displays 'Name City'
    - If user searches by phone: displays 'Name Phone'
    - If user searches by GSTIN: displays 'Name GSTIN'
    - Otherwise displays 'Name'
    """
    name = str(record.get("name") or "").strip()
    phone = str(record.get("phone") or "").strip()
    city = str(record.get("city") or "").strip()
    gstin = str(record.get("gstin") or "").strip()
    q = query.strip().lower()

    if not name:
        return phone or gstin or city

    if city and (city.lower().startswith(q) or city.lower() in q) and q not in name.lower():
        return f"{name} {city}".strip()

    if any(c.isdigit() for c in q) and phone and (phone.startswith(q) or q in phone):
        return f"{name} {phone}".strip()

    if gstin and (gstin.lower().startswith(q) or q in gstin.lower()) and q not in name.lower():
        return f"{name} {gstin}".strip()

    return name


def format_invoice_suggestion_label(record: Dict[str, Any], query: str) -> str:
    """
    Query-aware label builder for Invoices:
    - If searching by customer name (e.g. 'desai'): suggests 'Saradha Desai' (omits invoice number prefix).
    - If searching by customer phone: suggests 'Saradha Desai 9876543210'.
    - If searching by invoice number (e.g. '1097' or '26-27'): suggests '26-27/1097' or '26-27/1097 Saradha Desai'.
    """
    inv_num = str(record.get("invoice_number") or "").strip()
    cust_name = str(record.get("customer__name") or "").strip()
    cust_phone = str(record.get("customer__phone_number") or "").strip()
    q = query.strip().lower()

    if not inv_num and not cust_name:
        return ""
    if not inv_num:
        return cust_name
    if not cust_name:
        return inv_num

    q_words = q.split()
    name_lower = cust_name.lower()
    inv_lower = inv_num.lower()

    # Check if query matches customer name (e.g. 'desai', 'saradha')
    matches_name = any(word in name_lower or fuzz.WRatio(word, name_lower) >= 75 for word in q_words)
    matches_inv = any(word in inv_lower or fuzz.WRatio(word, inv_lower) >= 80 for word in q_words)

    # 1. Searching by Customer Name only (e.g. 'desai') -> Suggest customer name directly!
    if matches_name and not matches_inv:
        return cust_name

    # 2. Searching by Customer Phone -> Suggest 'Name Phone'
    if any(c.isdigit() for c in q) and cust_phone and q in cust_phone and not matches_inv:
        return f"{cust_name} {cust_phone}".strip()

    # 3. Searching by Invoice Number only (e.g. '26-27', '1097', 'cash')
    if matches_inv and not matches_name:
        return f"{inv_num} {cust_name}".strip() if cust_name else inv_num

    # 4. Searching both Customer + Invoice No (e.g. 'desai 1097')
    if matches_name and matches_inv:
        if q_words and (name_lower.startswith(q_words[0]) or q_words[0] in name_lower):
            return f"{cust_name} {inv_num}".strip()
        return f"{inv_num} {cust_name}".strip()

    # Fallback default
    return f"{inv_num} {cust_name}".strip()


# Pre-defined Configurations
CUSTOMER_SEARCH_CONFIG = GenericSearchConfig(
    name="Customer",
    model_class=Customer,
    cache_key=CUSTOMER_WEIGHTED_CACHE_KEY,
    fields=["id", "name", "phone_number", "email", "address"],
    weights={
        "phone_number": 4.0,
        "name": 3.0,
        "email": 1.5,
        "address": 1.0,
    },
    filter_kwargs={"is_deleted": False},
    label_builder=format_customer_suggestion_label,
    item_type="customer",
)

SUPPLIER_SEARCH_CONFIG = GenericSearchConfig(
    name="Supplier",
    model_class=Supplier,
    cache_key=SUPPLIER_WEIGHTED_CACHE_KEY,
    fields=["id", "name", "phone", "email", "gstin", "city", "state"],
    weights={
        "phone": 4.0,
        "gstin": 3.5,
        "name": 3.0,
        "city": 1.5,
        "email": 1.5,
    },
    filter_kwargs={"is_deleted": False},
    label_builder=format_supplier_suggestion_label,
    item_type="supplier",
)

INVOICE_SEARCH_CONFIG = GenericSearchConfig(
    name="Invoice",
    model_class=Invoice,
    cache_key=INVOICE_WEIGHTED_CACHE_KEY,
    fields=["id", "invoice_number", "customer__name", "customer__phone_number", "notes"],
    weights={
        "invoice_number": 5.0,
        "customer__name": 3.0,
        "customer__phone_number": 3.0,
        "notes": 1.0,
    },
    filter_kwargs={},
    label_builder=format_invoice_suggestion_label,
    item_type="invoice",
)


# Convenience API Helpers
def get_customer_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=CUSTOMER_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )


def get_supplier_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=SUPPLIER_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )


def get_invoice_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=INVOICE_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )


# ==========================================
# INVENTORY ENTITY SEARCH CONFIGURATIONS
# ==========================================


def format_gst_hsn_suggestion_label(record: Dict[str, Any], query: str) -> str:
    """
    Smart label builder for GST/HSN Code records.

    Combines code and description into a human-friendly label:
    - '61091000 - T-shirts, singlets and other vests, knitted or crocheted'
    """
    code = str(record.get("code") or "").strip()
    description = str(record.get("description") or "").strip()
    if not code:
        return description
    if not description:
        return code
    return f"{code} - {description}"


CATEGORY_SEARCH_CONFIG = GenericSearchConfig(
    name="Category",
    model_class=Category,
    cache_key=CATEGORY_WEIGHTED_CACHE_KEY,
    fields=["id", "name", "description"],
    weights={"name": 3.0, "description": 1.0},
    filter_kwargs={},
    item_type="category",
)

UOM_SEARCH_CONFIG = GenericSearchConfig(
    name="UOM",
    model_class=UOM,
    cache_key=UOM_WEIGHTED_CACHE_KEY,
    fields=["id", "name", "short_code", "category", "description"],
    weights={"name": 3.0, "short_code": 2.5, "category": 1.5, "description": 1.0},
    filter_kwargs={},
    item_type="uom",
)

GST_HSN_SEARCH_CONFIG = GenericSearchConfig(
    name="GSTHsnCode",
    model_class=GSTHsnCode,
    cache_key=GST_HSN_WEIGHTED_CACHE_KEY,
    fields=["id", "code", "description"],
    weights={"code": 4.0, "description": 2.0},
    filter_kwargs={"is_active": True},
    label_builder=format_gst_hsn_suggestion_label,
    item_type="gst_hsn",
)


def get_category_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=CATEGORY_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )


def get_uom_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=UOM_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )


def get_gst_hsn_suggestions(
    query: str,
    records: Optional[List[Dict[str, Any]]] = None,
    limit: int = 10,
    min_score: float = 40.0,
    rich: bool = False,
) -> List[Any]:
    return get_generic_suggestions(
        query=query,
        config=GST_HSN_SEARCH_CONFIG,
        records=records,
        limit=limit,
        min_score=min_score,
        rich=rich,
    )

