import httpx
import asyncio
import os
from typing import List, Dict, Tuple, Optional
from dotenv import load_dotenv

load_dotenv("/app/.env")

FSS_BASE_URL   = "https://finlife.fss.or.kr/finlifeapi"
FSS_API_KEY    = os.getenv("FSS_API_KEY")
BANK_GROUP_CODE = "020000"  # 은행권 (저축은행: 030200)

LOAN_ENDPOINTS = {
    "sinyoung":      "creditLoanProductsSearch",       # 신용대출
    "dambo_mortgage": "mortgageLoanProductsSearch",    # 주택담보대출
    "dambo_jeonse":  "rentHouseLoanProductsSearch",    # 전세자금대출
}

LOAN_TYPE_KO = {
    "sinyoung":       "신용대출",
    "dambo_mortgage": "주택담보대출",
    "dambo_jeonse":   "전세자금대출",
}


# ──────────────────────────────────────────────
# API 호출
# ──────────────────────────────────────────────
async def _fetch_page(client: httpx.AsyncClient, endpoint: str, page_no: int) -> dict:
    url = f"{FSS_BASE_URL}/{endpoint}.json"
    params = {
        "auth":        FSS_API_KEY,
        "topFinGrpNo": BANK_GROUP_CODE,
        "pageNo":      page_no,
    }
    resp = await client.get(url, params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def _fetch_all_pages(endpoint: str) -> Tuple[list, list]:
    all_base, all_options = [], []
    async with httpx.AsyncClient() as client:
        page = 1
        while True:
            try:
                data = await _fetch_page(client, endpoint, page)
            except httpx.HTTPStatusError as e:
                print(f"  ⚠️ HTTP {e.response.status_code} 오류 (page {page})")
                break

            result    = data.get("result", {})
            base_list = result.get("baseList", [])
            opt_list  = result.get("optionList", [])

            if not base_list:
                break

            all_base.extend(base_list)
            all_options.extend(opt_list)

            max_page = int(result.get("max_page_no", 1))
            now_page = int(result.get("now_page_no", page))
            if now_page >= max_page:
                break
            page += 1
            await asyncio.sleep(0.3)

    return all_base, all_options


# ──────────────────────────────────────────────
# 금리 옵션 포맷팅
# ──────────────────────────────────────────────
def _format_options_mortgage(options: list) -> str:
    if not options:
        return "금리 옵션 정보 없음"
    lines = []
    for opt in options:
        mrtg  = opt.get("mrtg_type_nm", "")
        rpay  = opt.get("rpay_type_nm", "")
        rtype = opt.get("lend_rate_type_nm", "")
        r_min = opt.get("lend_rate_min", "")
        r_max = opt.get("lend_rate_max", "")
        r_avg = opt.get("lend_rate_avg", "")
        line  = f"  · {mrtg} / {rpay} / {rtype}: {r_min}%~{r_max}%"
        if r_avg:
            line += f" (평균 {r_avg}%)"
        lines.append(line)
    return "\n".join(lines)


def _format_options_credit(options: list) -> str:
    if not options:
        return "금리 옵션 정보 없음"
    lines = []
    for opt in options:
        prdt_nm  = opt.get("crdt_prdt_type_nm", "")
        rate_nm  = opt.get("crdt_lend_rate_type_nm", "")
        avg      = opt.get("crdt_grad_avg", "")
        # 신용등급 1~10등급 금리
        grades   = []
        for g in range(1, 11):
            val = opt.get(f"crdt_grad_{g}", "")
            if val:
                grades.append(f"{g}등급 {val}%")
        line = f"  · {prdt_nm} / {rate_nm}"
        if avg:
            line += f": 평균 {avg}%"
        if grades:
            line += f"\n    [{', '.join(grades)}]"
        lines.append(line)
    return "\n".join(lines)


# ──────────────────────────────────────────────
# baseList + optionList 병합
# ──────────────────────────────────────────────
def _merge_products(base_list: list, option_list: list, loan_type: str) -> List[Dict]:
    options_by_code: Dict[str, list] = {}
    for opt in option_list:
        key = opt.get("fin_prdt_cd", "")
        options_by_code.setdefault(key, []).append(opt)

    products = []
    for base in base_list:
        prod_cd = base.get("fin_prdt_cd", "")
        opts    = options_by_code.get(prod_cd, [])

        if loan_type == "sinyoung":
            rate_info = _format_options_credit(opts)
        else:
            rate_info = _format_options_mortgage(opts)

        products.append({
            # 기본 식별 정보
            "loan_type":    loan_type,
            "bank_name":    base.get("kor_co_nm", ""),
            "fin_co_no":    base.get("fin_co_no", ""),
            "product_name": base.get("fin_prdt_nm", ""),
            "product_code": prod_cd,
            # 상품 상세 (풍부한 텍스트 그대로 보존)
            "join_way":        base.get("join_way", ""),
            "loan_limit":      base.get("loan_lmt", ""),
            "extra_cost":      base.get("loan_inci_expn", ""),
            "early_repay_fee": base.get("erly_rpay_fee", ""),
            "overdue_rate":    base.get("dly_rate", ""),
            # 금리 옵션 (포맷팅된 문자열)
            "rate_info": rate_info,
            # 공시 기간
            "dcls_month":    base.get("dcls_month", ""),
            "dcls_strt_day": base.get("dcls_strt_day", ""),
            "dcls_end_day":  base.get("dcls_end_day") or "현재",
        })

    return products


# ──────────────────────────────────────────────
# 상품 → 풍부한 단일 청크 변환
# ──────────────────────────────────────────────
def products_to_chunks(products: List[Dict]) -> Tuple[List[str], List[dict]]:
    docs, metadatas = [], []

    for p in products:
        loan_type = p["loan_type"]
        # 필터링용 normalized type (dambo_mortgage, dambo_jeonse → dambo)
        normalized = "dambo" if loan_type.startswith("dambo") else loan_type
        type_ko    = LOAN_TYPE_KO.get(loan_type, loan_type)

        # ── 본문 구성: 모든 필드를 하나의 문서에 ──
        parts = [
            f"[은행명] {p['bank_name']}",
            f"[상품명] {p['product_name']}",
            f"[대출종류] {type_ko}",
        ]

        if p["join_way"]:
            parts.append(f"[가입방법] {p['join_way']}")

        if p["loan_limit"]:
            parts.append(f"[대출한도] {p['loan_limit']}")

        if p["extra_cost"]:
            parts.append(f"[부대비용]\n{p['extra_cost']}")

        if p["early_repay_fee"]:
            parts.append(f"[중도상환수수료]\n{p['early_repay_fee']}")

        if p["overdue_rate"]:
            parts.append(f"[연체이자율]\n{p['overdue_rate']}")

        if p["rate_info"]:
            parts.append(f"[금리 옵션]\n{p['rate_info']}")

        if p["dcls_month"]:
            parts.append(
                f"[공시기간] {p['dcls_strt_day']} ~ {p['dcls_end_day']} (공시월: {p['dcls_month']})"
            )

        doc_text = "\n".join(parts)

        meta = {
            "bank_name":    p["bank_name"],
            "loan_type":    normalized,
            "product_name": p["product_name"],
            "product_code": p["product_code"],
            "dcls_month":   p["dcls_month"],
        }

        docs.append(doc_text)
        metadatas.append(meta)

    return docs, metadatas


# ──────────────────────────────────────────────
# 전체 크롤링 진입점
# ──────────────────────────────────────────────
async def crawl_all() -> Tuple[List[str], List[dict]]:
    if not FSS_API_KEY:
        raise ValueError("FSS_API_KEY 환경변수가 설정되지 않았습니다.")

    all_docs, all_metas = [], []

    for loan_type, endpoint in LOAN_ENDPOINTS.items():
        print(f"📡 [{LOAN_TYPE_KO[loan_type]}] FSS API 수집 중...")
        try:
            base_list, option_list = await _fetch_all_pages(endpoint)
            products = _merge_products(base_list, option_list, loan_type)
            docs, metas = products_to_chunks(products)
            all_docs.extend(docs)
            all_metas.extend(metas)
            print(f"  ✅ {len(products)}개 상품 → {len(docs)}개 청크")
        except Exception as e:
            print(f"  ⚠️ [{loan_type}] 수집 실패: {e}")

    print(f"\n📦 전체 수집 완료: {len(all_docs)}개 청크")
    return all_docs, all_metas
