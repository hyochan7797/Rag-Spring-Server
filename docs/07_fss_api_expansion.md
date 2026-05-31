# FSS API 수집 확장

## 목적

기존 수집 대상은 대출 중심이었다. 현재는 금융감독원 금융상품 API에서 다음 상품군을 함께 수집한다.

| product_type | endpoint | 설명 |
|---|---|---|
| `sinyoung` | `creditLoanProductsSearch` | 개인신용대출 |
| `dambo_mortgage` | `mortgageLoanProductsSearch` | 주택담보대출 |
| `dambo_jeonse` | `rentHouseLoanProductsSearch` | 전세자금대출 |
| `deposit` | `depositProductsSearch` | 정기예금 |
| `saving` | `savingProductsSearch` | 적금 |
| `annuity_saving` | `annuitySavingProductsSearch` | 연금저축 |
| `company` | `companySearch` | 금융회사 |

## 그룹코드 처리

은행권 상품 API는 기본적으로 `topFinGrpNo=020000`으로 조회한다.

다만 `annuitySavingProductsSearch`와 `companySearch`는 은행권 그룹코드만 넣으면 일부 권역 데이터가 누락된다. 이 두 API는 권역코드를 순회해서 수집한다.

```text
대출/예금/적금: topFinGrpNo=020000
연금저축/금융회사: 020000, 030200, 030300, 050000, 060000 순회
```

## 옵션 필드 보존

정기예금 옵션:

```text
save_trm
intr_rate_type
intr_rate_type_nm
intr_rate
intr_rate2
```

적금 옵션:

```text
save_trm
rsrv_type
rsrv_type_nm
intr_rate_type
intr_rate_type_nm
intr_rate
intr_rate2
```

연금저축 옵션:

```text
pnsn_recp_trm
pnsn_recp_trm_nm
pnsn_entr_age
pnsn_entr_age_nm
mon_paym_atm
mon_paym_atm_nm
paym_prd
paym_prd_nm
pnsn_strt_age
pnsn_strt_age_nm
pnsn_recp_amt
```

연금저축 기본정보도 청크에 저장한다.

```text
pnsn_kind / pnsn_kind_nm
sale_strt_day
mntn_cnt
prdt_type / prdt_type_nm
avg_prft_rate
dcls_rate
guar_rate
btrm_prft_rate_1
btrm_prft_rate_2
btrm_prft_rate_3
etc
sale_co
fin_co_subm_day
```

## 확인 명령

새 코드 반영 후 컨테이너를 다시 빌드하고 벡터를 갱신한다.

```powershell
docker compose up -d --build fastapi
```

730개 이상 청크를 한 번에 임베딩하면 OpenAI embedding API의 request token limit을 넘을 수 있다. 현재 `rag_pipeline.py`는 `EMBEDDING_CHUNK_SIZE`와 `QDRANT_BATCH_SIZE` 기본값 8로 임베딩/업서트 요청을 나눠 보낸다.

연금저축 옵션이 많아서 refresh 중 OpenAI TPM(rate limit)에 걸릴 수도 있다. 기본값은 임베딩 재시도를 20회까지 수행한다.

필요하면 `.env`에 아래처럼 더 작은 배치와 더 많은 재시도를 둘 수 있다.

```text
EMBEDDING_CHUNK_SIZE=4
QDRANT_BATCH_SIZE=4
EMBEDDING_MAX_RETRIES=30
```

연금저축 API가 실제로 수집되는지 확인한다. 금융투자 권역 `060000`에서 연금저축펀드가 조회된다.

```powershell
docker compose exec fastapi python -c "import asyncio; from fss_crawler import _fetch_all_pages; base,opt=asyncio.run(_fetch_all_pages('annuitySavingProductsSearch', '060000')); print('base', len(base)); print('option', len(opt)); print(base[:1]); print(opt[:1])"
```

벡터 갱신 후 Qdrant payload 개수를 확인한다.

```powershell
docker compose exec fastapi python -c "from collections import Counter; from rag_pipeline import client,_get_alias_backing; c=_get_alias_backing(); pts,_=client.scroll(collection_name=c, limit=3000, with_payload=True, with_vectors=False); print(Counter(p.payload.get('metadata',{}).get('loan_type') for p in pts))"
```

정상이라면 `annuity_saving` 카운트가 함께 보여야 한다.
