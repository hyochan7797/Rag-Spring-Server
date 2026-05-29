import asyncio
import os
from typing import Dict, List, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv("/app/.env")

FSS_BASE_URL = "https://finlife.fss.or.kr/finlifeapi"
FSS_API_KEY = os.getenv("FSS_API_KEY")
BANK_GROUP_CODE = "020000"

LOAN_ENDPOINTS = {
    "sinyoung": "creditLoanProductsSearch",
    "dambo_mortgage": "mortgageLoanProductsSearch",
    "dambo_jeonse": "rentHouseLoanProductsSearch",
}

LOAN_TYPE_LABELS = {
    "sinyoung": "신용대출",
    "dambo_mortgage": "주택담보대출",
    "dambo_jeonse": "전세자금대출",
}

NORMALIZED_LOAN_TYPES = {
    "sinyoung": "sinyoung",
    "dambo_mortgage": "dambo",
    "dambo_jeonse": "dambo",
}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "none" else text


def _append_if(parts: List[str], label: str, value: object) -> None:
    text = _clean_text(value)
    if text:
        parts.append(f"[{label}] {text}")


def _append_block_if(parts: List[str], label: str, value: object) -> None:
    text = _clean_text(value)
    if text:
        parts.append(f"[{label}]\n{text}")


def _fetch_rate(value: object, suffix: str = "%") -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return text if text.endswith(suffix) else f"{text}{suffix}"


def _format_mortgage_option_summary(option: Dict[str, object]) -> str:
    head = " / ".join(
        part
        for part in [
            _clean_text(option.get("mrtg_type_nm")),
            _clean_text(option.get("rpay_type_nm")),
            _clean_text(option.get("lend_rate_type_nm")),
        ]
        if part
    )
    details = [
        f"최저 {_fetch_rate(option.get('lend_rate_min'))}" if _clean_text(option.get("lend_rate_min")) else "",
        f"최고 {_fetch_rate(option.get('lend_rate_max'))}" if _clean_text(option.get("lend_rate_max")) else "",
        f"평균 {_fetch_rate(option.get('lend_rate_avg'))}" if _clean_text(option.get("lend_rate_avg")) else "",
    ]
    detail_text = ", ".join(item for item in details if item) or "금리 정보 없음"
    return f"- {head or '옵션'}: {detail_text}"


def _format_credit_grade_lines(option: Dict[str, object]) -> List[str]:
    grade_lines = []
    for grade in range(1, 11):
        value = _clean_text(option.get(f"crdt_grad_{grade}"))
        if value:
            grade_lines.append(f"{grade}등급 {value}%")
    return grade_lines


def _format_credit_option_summary(option: Dict[str, object]) -> str:
    head = " / ".join(
        part
        for part in [
            _clean_text(option.get("crdt_prdt_type_nm")),
            _clean_text(option.get("crdt_lend_rate_type_nm")),
        ]
        if part
    )
    avg = _clean_text(option.get("crdt_grad_avg"))
    pieces = [f"평균 {avg}%" if avg else ""]
    pieces.extend(_format_credit_grade_lines(option))
    detail_text = ", ".join(item for item in pieces if item) or "금리 정보 없음"
    return f"- {head or '옵션'}: {detail_text}"


async def _fetch_page(client: httpx.AsyncClient, endpoint: str, page_no: int) -> dict:
    url = f"{FSS_BASE_URL}/{endpoint}.json"
    params = {
        "auth": FSS_API_KEY,
        "topFinGrpNo": BANK_GROUP_CODE,
        "pageNo": page_no,
    }
    response = await client.get(url, params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()


async def _fetch_all_pages(endpoint: str) -> Tuple[list, list]:
    all_base, all_options = [], []
    async with httpx.AsyncClient() as client:
        page = 1
        while True:
            try:
                data = await _fetch_page(client, endpoint, page)
            except httpx.HTTPStatusError as exc:
                print(f"  HTTP error {exc.response.status_code} (page {page})")
                break

            result = data.get("result", {})
            base_list = result.get("baseList", [])
            option_list = result.get("optionList", [])

            if not base_list:
                break

            all_base.extend(base_list)
            all_options.extend(option_list)

            max_page = int(result.get("max_page_no", 1))
            now_page = int(result.get("now_page_no", page))
            if now_page >= max_page:
                break

            page += 1
            await asyncio.sleep(0.3)

    return all_base, all_options


def _merge_products(base_list: list, option_list: list, loan_type: str) -> List[Dict[str, object]]:
    options_by_code: Dict[str, List[Dict[str, object]]] = {}
    for option in option_list:
        product_code = _clean_text(option.get("fin_prdt_cd"))
        if product_code:
            options_by_code.setdefault(product_code, []).append(option)

    products: List[Dict[str, object]] = []
    for base in base_list:
        product_code = _clean_text(base.get("fin_prdt_cd"))
        product = {
            "loan_type": loan_type,
            "loan_type_label": LOAN_TYPE_LABELS.get(loan_type, loan_type),
            "loan_type_normalized": NORMALIZED_LOAN_TYPES.get(loan_type, loan_type),
            "bank_name": _clean_text(base.get("kor_co_nm")),
            "fin_co_no": _clean_text(base.get("fin_co_no")),
            "product_name": _clean_text(base.get("fin_prdt_nm")),
            "product_code": product_code,
            "join_way": _clean_text(base.get("join_way")),
            "loan_limit": _clean_text(base.get("loan_lmt")),
            "extra_cost": _clean_text(base.get("loan_inci_expn")),
            "early_repay_fee": _clean_text(base.get("erly_rpay_fee")),
            "overdue_rate": _clean_text(base.get("dly_rate")),
            "dcls_month": _clean_text(base.get("dcls_month")),
            "dcls_strt_day": _clean_text(base.get("dcls_strt_day")),
            "dcls_end_day": _clean_text(base.get("dcls_end_day")) or "현재",
            "fin_co_subm_day": _clean_text(base.get("fin_co_subm_day")),
            "options": options_by_code.get(product_code, []),
        }
        products.append(product)

    return products


def _build_master_doc(product: Dict[str, object]) -> str:
    parts: List[str] = ["[청크유형] 상품 기본정보"]
    _append_if(parts, "은행명", product.get("bank_name"))
    _append_if(parts, "금융상품명", product.get("product_name"))
    _append_if(parts, "대출종류", product.get("loan_type_label"))
    _append_if(parts, "금융회사코드", product.get("fin_co_no"))
    _append_if(parts, "금융상품코드", product.get("product_code"))
    _append_if(parts, "가입방법", product.get("join_way"))
    _append_block_if(parts, "대출부대비용", product.get("extra_cost"))
    _append_block_if(parts, "중도상환수수료", product.get("early_repay_fee"))
    _append_block_if(parts, "연체이자율", product.get("overdue_rate"))
    _append_block_if(parts, "대출한도", product.get("loan_limit"))

    dcls_period = f"{product.get('dcls_strt_day', '')} ~ {product.get('dcls_end_day', '')}"
    if _clean_text(product.get("dcls_month")):
        dcls_period += f" (공시월: {product['dcls_month']})"
    _append_if(parts, "공시기간", dcls_period.strip())
    _append_if(parts, "금융회사 제출일", product.get("fin_co_subm_day"))

    options: List[Dict[str, object]] = product.get("options", [])  # type: ignore[assignment]
    if options:
        option_lines = []
        if product["loan_type"] == "sinyoung":
            option_lines = [_format_credit_option_summary(option) for option in options]
        else:
            option_lines = [_format_mortgage_option_summary(option) for option in options]
        parts.append("[옵션요약]\n" + "\n".join(option_lines))

    return "\n".join(part for part in parts if part.strip())


def _build_common_metadata(product: Dict[str, object], chunk_type: str) -> Dict[str, object]:
    return {
        "chunk_type": chunk_type,
        "bank_name": product["bank_name"],
        "loan_type": product["loan_type_normalized"],
        "loan_type_detail": product["loan_type"],
        "loan_type_label": product["loan_type_label"],
        "product_name": product["product_name"],
        "product_code": product["product_code"],
        "fin_co_no": product["fin_co_no"],
        "dcls_month": product["dcls_month"],
        "dcls_strt_day": product["dcls_strt_day"],
        "dcls_end_day": product["dcls_end_day"],
        "fin_co_subm_day": product["fin_co_subm_day"],
    }


def _build_master_metadata(product: Dict[str, object]) -> Dict[str, object]:
    metadata = _build_common_metadata(product, "product_master")
    metadata.update({"option_count": len(product.get("options", []))})
    return metadata


def _build_mortgage_option_doc(
    product: Dict[str, object], option: Dict[str, object], option_index: int
) -> str:
    parts: List[str] = ["[청크유형] 상품 옵션"]
    _append_if(parts, "은행명", product.get("bank_name"))
    _append_if(parts, "금융상품명", product.get("product_name"))
    _append_if(parts, "대출종류", product.get("loan_type_label"))
    _append_if(parts, "금융회사코드", product.get("fin_co_no"))
    _append_if(parts, "금융상품코드", product.get("product_code"))
    _append_if(parts, "옵션순번", option_index)
    _append_if(parts, "가입방법", product.get("join_way"))
    _append_block_if(parts, "대출한도", product.get("loan_limit"))
    _append_if(parts, "담보유형코드", option.get("mrtg_type"))
    _append_if(parts, "담보유형", option.get("mrtg_type_nm"))
    _append_if(parts, "대출상환유형코드", option.get("rpay_type"))
    _append_if(parts, "대출상환유형", option.get("rpay_type_nm"))
    _append_if(parts, "대출금리유형코드", option.get("lend_rate_type"))
    _append_if(parts, "대출금리유형", option.get("lend_rate_type_nm"))
    _append_if(parts, "대출금리_최저", _fetch_rate(option.get("lend_rate_min")))
    _append_if(parts, "대출금리_최고", _fetch_rate(option.get("lend_rate_max")))
    _append_if(parts, "전월취급평균금리", _fetch_rate(option.get("lend_rate_avg")))
    _append_if(parts, "공시기간", f"{product.get('dcls_strt_day', '')} ~ {product.get('dcls_end_day', '')}")
    return "\n".join(part for part in parts if part.strip())


def _build_credit_option_doc(
    product: Dict[str, object], option: Dict[str, object], option_index: int
) -> str:
    parts: List[str] = ["[청크유형] 상품 옵션"]
    _append_if(parts, "은행명", product.get("bank_name"))
    _append_if(parts, "금융상품명", product.get("product_name"))
    _append_if(parts, "대출종류", product.get("loan_type_label"))
    _append_if(parts, "금융회사코드", product.get("fin_co_no"))
    _append_if(parts, "금융상품코드", product.get("product_code"))
    _append_if(parts, "옵션순번", option_index)
    _append_if(parts, "가입방법", product.get("join_way"))
    _append_block_if(parts, "대출한도", product.get("loan_limit"))
    _append_if(parts, "신용상품유형코드", option.get("crdt_prdt_type"))
    _append_if(parts, "신용상품유형", option.get("crdt_prdt_type_nm"))
    _append_if(parts, "대출금리유형코드", option.get("crdt_lend_rate_type"))
    _append_if(parts, "대출금리유형", option.get("crdt_lend_rate_type_nm"))
    _append_if(parts, "전월취급평균금리", _fetch_rate(option.get("crdt_grad_avg")))

    grade_lines = _format_credit_grade_lines(option)
    if grade_lines:
        parts.append("[신용등급별금리]\n" + ", ".join(grade_lines))

    _append_if(parts, "공시기간", f"{product.get('dcls_strt_day', '')} ~ {product.get('dcls_end_day', '')}")
    return "\n".join(part for part in parts if part.strip())


def _build_mortgage_option_metadata(
    product: Dict[str, object], option: Dict[str, object], option_index: int
) -> Dict[str, object]:
    metadata = _build_common_metadata(product, "product_option")
    metadata.update(
        {
            "option_index": option_index,
            "mrtg_type": _clean_text(option.get("mrtg_type")),
            "mrtg_type_nm": _clean_text(option.get("mrtg_type_nm")),
            "rpay_type": _clean_text(option.get("rpay_type")),
            "rpay_type_nm": _clean_text(option.get("rpay_type_nm")),
            "lend_rate_type": _clean_text(option.get("lend_rate_type")),
            "lend_rate_type_nm": _clean_text(option.get("lend_rate_type_nm")),
            "lend_rate_min": _clean_text(option.get("lend_rate_min")),
            "lend_rate_max": _clean_text(option.get("lend_rate_max")),
            "lend_rate_avg": _clean_text(option.get("lend_rate_avg")),
        }
    )
    return metadata


def _build_credit_option_metadata(
    product: Dict[str, object], option: Dict[str, object], option_index: int
) -> Dict[str, object]:
    metadata = _build_common_metadata(product, "product_option")
    metadata.update(
        {
            "option_index": option_index,
            "crdt_prdt_type": _clean_text(option.get("crdt_prdt_type")),
            "crdt_prdt_type_nm": _clean_text(option.get("crdt_prdt_type_nm")),
            "crdt_lend_rate_type": _clean_text(option.get("crdt_lend_rate_type")),
            "crdt_lend_rate_type_nm": _clean_text(option.get("crdt_lend_rate_type_nm")),
            "crdt_grad_avg": _clean_text(option.get("crdt_grad_avg")),
        }
    )
    for grade in range(1, 11):
        metadata[f"crdt_grad_{grade}"] = _clean_text(option.get(f"crdt_grad_{grade}"))
    return metadata


def products_to_chunks(products: List[Dict[str, object]]) -> Tuple[List[str], List[dict]]:
    docs: List[str] = []
    metadatas: List[dict] = []

    for product in products:
        docs.append(_build_master_doc(product))
        metadatas.append(_build_master_metadata(product))

        options: List[Dict[str, object]] = product.get("options", [])  # type: ignore[assignment]
        for option_index, option in enumerate(options, start=1):
            if product["loan_type"] == "sinyoung":
                docs.append(_build_credit_option_doc(product, option, option_index))
                metadatas.append(_build_credit_option_metadata(product, option, option_index))
            else:
                docs.append(_build_mortgage_option_doc(product, option, option_index))
                metadatas.append(_build_mortgage_option_metadata(product, option, option_index))

    return docs, metadatas


async def crawl_all() -> Tuple[List[str], List[dict]]:
    if not FSS_API_KEY:
        raise ValueError("FSS_API_KEY environment variable is not set.")

    all_docs: List[str] = []
    all_metas: List[dict] = []

    for loan_type, endpoint in LOAN_ENDPOINTS.items():
        print(f"[{LOAN_TYPE_LABELS[loan_type]}] collecting from FSS API...")
        try:
            base_list, option_list = await _fetch_all_pages(endpoint)
            products = _merge_products(base_list, option_list, loan_type)
            docs, metas = products_to_chunks(products)
            all_docs.extend(docs)
            all_metas.extend(metas)
            print(
                f"  loaded {len(products)} products, {len(option_list)} options, "
                f"{len(docs)} chunks"
            )
        except Exception as exc:
            print(f"  failed to collect [{loan_type}]: {exc}")

    print(f"\nfinished collection: {len(all_docs)} chunks")
    return all_docs, all_metas
