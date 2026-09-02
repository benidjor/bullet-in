# GCP 요금을 웹 가격표 대신 과금 원장에서 읽는다 (2026-09-02)

안건 2θ 를 착수하며 Lakehouse Iceberg REST 카탈로그의 비용을 확인해야 했다.
그런데 공식 가격표 페이지가 답을 주지 않았다.

- `cloud.google.com/bigquery/pricing` 에는 카탈로그 항목이 아예 없다.
- `cloud.google.com/biglake/pricing` 은 404 다.
- Lakehouse 문서에도 전용 가격 페이지 링크가 없고 일반 `cloud.google.com/pricing` 만 걸려 있다.

**Cloud Billing Catalog API 를 부르면 SKU 원문이 그대로 온다.**
무료 구간도 SKU 안에 단가 0인 첫 구간으로 박혀 있어서 검색 요약을 믿지 않고 값을 직접 읽을 수 있다.

이 절차는 안건 ξ (Gemini 비용 증가) 처럼 다른 축의 비용을 따질 때도 그대로 쓴다.

## 1. 준비

로컬 `gcloud` 가 인증돼 있으면 된다.
확인은 한 줄이다.

```bash
gcloud auth list
```

2026-09-02 기준으로 맥에 SDK 577.0.0 이 깔려 있고 `benidjor@gmail.com` 으로 인증돼 있었다.
**「브라우저 인증이 필요하니 사용자 몫」 이라고 전제하지 말고 이 명령으로 먼저 재라.**

## 2. 서비스 목록에서 대상을 찾는다

서비스가 1,779개라 이름으로 걸러야 한다.

```bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://cloudbilling.googleapis.com/v1/services?pageSize=5000" -o services.json
```

받은 JSON 에서 `displayName` 으로 찾는다.

```python
import json
d = json.load(open("services.json"))
for s in d["services"]:
    if "BigLake" in s["displayName"]:
        print(s["name"], s["displayName"])
```

**제품 이름이 바뀌어도 서비스 이름은 옛 이름으로 남아 있을 수 있다.**
2026-04-20 에 BigLake 가 Lakehouse 로 바뀌었지만 과금 서비스는 여전히 `BigLake` 다.
찾는 이름으로 안 나오면 옛 이름으로도 찾아 본다.

이렇게 얻은 값이다.

| 서비스 | ID |
| --- | --- |
| BigLake | `A6C3-245D-D767` |
| Cloud Storage | `95FF-2EF5-5EA1` |
| BigQuery | `24E6-581D-38E5` |

## 3. 그 서비스의 SKU 를 받는다

통화를 지정하면 원화로 온다.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://cloudbilling.googleapis.com/v1/services/A6C3-245D-D767/skus?pageSize=5000&currencyCode=KRW" \
  -o skus.json
```

## 4. 무료 구간을 읽는 법

**`tieredRates` 의 첫 구간 단가가 0이면 그 SKU 에 무료 티어가 있다.**
다음 구간의 `startUsageAmount` 가 무료 한도다.

```python
import json
d = json.load(open("skus.json"))
for s in d["skus"]:
    for pi in s.get("pricingInfo", []):
        pe = pi.get("pricingExpression", {})
        for t in pe.get("tieredRates", []):
            u = t.get("unitPrice", {})
            krw = int(u.get("units", "0")) + u.get("nanos", 0) / 1e9
            print(f"{s['description']:<60} {int(t.get('startUsageAmount', 0)):>8,} 부터  {krw:.9f} KRW")
```

단가는 `units` (정수부) 와 `nanos` (10억분의 1) 로 나뉘어 오므로 둘을 더해야 한다.
`nanos` 만 보면 0원으로 읽고, `units` 만 보면 소수점 아래를 버린다.

## 5. 이 절차로 확인한 값 (2026-09-02)

| SKU | 무료 구간 | 초과 단가 |
| --- | --- | --- |
| `Class A API call usage of the Lakehouse runtime catalog service` | 월 5,000회 | 0.0083 KRW/회 |
| `Class B API call usage of the Lakehouse runtime catalog service` | 월 50,000회 | 0.00124 KRW/회 |
| `Regional Standard Class A Operations` (GCS) | 월 5,000회 | 0.0069 KRW/회 |
| `Regional Standard Class B Operations` (GCS) | 월 50,000회 | 0.00055 KRW/회 |
| `Standard Storage US Regional` | 5 GiB-월 | 27.67 KRW/GiB |
| `BigLake Table Management` (`us-central1`) | **없음** | **165.99 KRW/시간** |

마지막 줄이 이 조회의 값어치다.
검색 요약만 보고 「무료 구간 안」 이라고 넘겼으면, 시간당 과금되는 SKU 하나를 못 보고 지나쳤을 것이다.

## 6. 함정 넷

- **무료 한도는 프로젝트가 아니라 결제 계정 단위다.**
   프로젝트를 나눠도 한도가 늘지 않고 반대로 나눈다고 손해도 없다.
- **같은 이름의 예산이 여러 개일 수 있다.**
   GCS 의 Class A 5,000회와 Lakehouse 카탈로그의 Class A 5,000회는 **서로 다른 SKU** 이고 각자 무료 구간을 갖는다.
   하나로 합쳐 세면 예산을 절반으로 잘못 잡는다.
- **리전 필터를 `serviceRegions` 로 걸면 `global` SKU 가 빠진다.**
   연산 계열은 대부분 `global` 로 등록돼 있어서 리전으로만 거르면 정작 필요한 항목이 안 나온다.
- **SKU 에 없는 요금이 있을 수 있다.**
   조회 결과가 곧 청구서는 아니다.
   첫 달에는 결제 보고서를 **서비스와 프로젝트 두 기준으로 각각** 보고 대조한다 (`CLAUDE.md` 의 Gemini 비용 절차와 같은 규율).

## 7. 관련 문서

- 이 절차로 세운 설계 = `docs/superpowers/specs/2026-09-02-history-lakehouse-design.md` 2절
- 백업 축의 GCS 사용 = `docs/runbook/2026-09-01-backup-and-restore.md`
