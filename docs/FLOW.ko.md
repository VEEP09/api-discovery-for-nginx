# NGINX API Discovery — 프로젝트 가이드

> NGINX Access Log를 기반으로 API를 자동 식별하고,  
> 딥러닝(AutoEncoder, LSTM) + OpenAPI Spec 비교로 Shadow API 및 비정상 호출 패턴을 탐지하는 시스템.

---

## 목차

1. [전체 아키텍처](#1-전체-아키텍처)
2. [처리 흐름 (Flow)](#2-처리-흐름-flow)
3. [모듈 구조](#3-모듈-구조)
4. [설치 및 환경 설정](#4-설치-및-환경-설정)
5. [NGINX 설정](#5-nginx-설정)
6. [설정 파일 가이드](#6-설정-파일-가이드)
7. [실행 방법](#7-실행-방법)
8. [대시보드 사용법](#8-대시보드-사용법)
9. [출력 파일 설명](#9-출력-파일-설명)
10. [멀티 서버 배포](#10-멀티-서버-배포)
11. [트러블슈팅](#11-트러블슈팅)

---

## 1. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│  NGINX (1.11.0+)                                                │
│  log_format api_discovery → /var/log/nginx/api_access.log      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  JSON 한 줄 = 요청 1건
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pipeline  (main.py)                                            │
│                                                                 │
│  [1] Collector   로그 파일 읽기 (배치 / 실시간 tail)            │
│       ↓                                                         │
│  [2] Parser      JSON 파싱 → ParsedLog (타입 안전 구조체)       │
│       ↓                                                         │
│  [3] Normalizer  URI 정규화  /users/123 → /users/{id}          │
│       ↓                                                         │
│  [4] Inventory   (method, endpoint) 집계 → API 목록 생성       │
│       ↓                                                         │
│  [5] Extractor   ParsedLog → RawFeatures (26개 의미 feature)   │
│       ↓                                                         │
│  [6] Vectorizer  RawFeatures → 수치 벡터 (MinMax 스케일링)     │
│       ↓                          ↓                             │
│  [7] AutoEncoder          SequenceBuilder                       │
│      비지도 이상 탐지      IP별 시계열 시퀀스 생성              │
│                                  ↓                             │
│                           LSTM AutoEncoder                      │
│                           시퀀스 이상 탐지                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  output/ 저장
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Dashboard  (serve.py)                                          │
│  FastAPI + Chart.js — 5초 자동 갱신                             │
│                                                                 │
│  Overview │ Endpoints │ Anomalies │ Models                      │
│                           ↑                                     │
│              OpenAPI Spec 업로드 (브라우저에서 직접)            │
│              → ML 탐지 + Spec 비교 통합 Shadow 탐지             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 처리 흐름 (Flow)

### Step 1 — 로그 수집

NGINX가 요청마다 JSON 한 줄을 `api_access.log`에 기록한다.  
`LogReader`가 파일을 `batch_size`(기본 10,000줄) 단위로 읽어 넘긴다.

```
api_access.log
{"time":"2026-04-21T13:45:01+09:00","method":"GET","uri":"/api/v1/users/1042",...}
{"time":"2026-04-21T13:45:02+09:00","method":"POST","uri":"/api/v1/orders",...}
...
```

---

### Step 2 — 파싱

`LogParser`가 각 JSON 줄을 `ParsedLog` 구조체로 변환한다.  
파싱 실패 줄은 스킵하고 성공/실패 통계를 기록한다.

파싱 중 자동으로 추출되는 파생 필드:

| 파생 필드 | 설명 |
|-----------|------|
| `query_params` | query_string을 dict로 파싱 |
| `has_auth` | Authorization 헤더 존재 여부 |
| `auth_type` | Bearer / Basic / token 구분 |

---

### Step 3 — URI 정규화

`URINormalizer`가 URI의 각 path segment를 분석해 동적 값을 placeholder로 치환한다.  
패턴은 **설정 파일에서 순서대로** 적용된다 (구체적인 패턴을 앞에 둬야 오탐 방지).

```
/api/v1/users/1042                  →  /api/v1/users/{id}
/api/v1/users/550e8400-...-440000   →  /api/v1/users/{uuid}
/api/v1/reports/2024-03-01          →  /api/v1/reports/{date}
/api/v1/users/1042/orders/99        →  /api/v1/users/{id}/orders/{id}
/static/app.js                      →  (제외 — exclude_prefixes)
```

---

### Step 4 — API Inventory 생성

정규화된 `(method, endpoint)` 쌍을 키로 호출 통계를 집계한다.

수집 항목: 호출 횟수, 2xx/4xx/5xx 분포, 평균 응답시간, 인증 여부, 고유 IP 수, 첫/마지막 호출 시각

---

### Step 5 — Feature Engineering

`FeatureExtractor`가 `ParsedLog` 1건에서 26개 feature를 추출한다.

| 카테고리 | Feature 목록 |
|----------|-------------|
| 시간 | hour, minute, day_of_week, is_weekend |
| 요청 | method, status_class, is_error, body_bytes_sent, request_length, request_time, upstream_response_time |
| URI | uri_length, uri_depth, uri_special_char_ratio, uri_suspicious_char_count, has_path_param |
| Query | query_param_count, query_total_length, query_special_char_ratio, query_suspicious_char_count |
| 인증 | has_auth, auth_type |
| UA | is_bot, is_browser, ua_length |
| IP | is_internal_ip |

`FeatureVectorizer`가 범주형(method, auth_type)은 Label Encoding,  
수치형은 MinMax Scaling으로 모든 값을 `[0, 1]` 범위 벡터로 변환한다.

`SequenceBuilder`가 IP 단위로 요청을 시간순 정렬 후  
`window_size` 길이의 슬라이딩 윈도우로 LSTM 입력 시퀀스를 생성한다.

---

### Step 6 — 딥러닝 학습

#### AutoEncoder (비지도 이상 탐지)

```
입력 벡터 (26차원)
    ↓
Encoder: 26 → 16 → 8  (ReLU)
    ↓
Bottleneck (8차원)
    ↓
Decoder:  8 → 16 → 26  (ReLU + Sigmoid)
    ↓
재구성 벡터 (26차원)

이상 점수 = MSE(입력, 재구성)
임계값    = 정상 데이터 재구성 오차의 95th percentile
```

정상 패턴만 학습하므로 **라벨 없이** 동작한다.  
학습한 적 없는 패턴(Shadow API, 비정상 요청)은 재구성 오차가 높아진다.

#### LSTM AutoEncoder (시퀀스 이상 탐지)

```
입력 시퀀스 (window_size × 26)
    ↓
LSTM Encoder → hidden state (32차원)
    ↓
LSTM Decoder → 시퀀스 복원 (window_size × 26)

이상 점수 = 시퀀스 전체 평균 MSE
```

반복 호출, 스캐닝, 비정상 접근 순서 등 **흐름 기반 공격** 탐지에 특화된다.

---

### Step 7 — Shadow API 탐지 (ML + Spec 통합)

`ShadowDetector`가 두 소스를 결합해 Shadow API를 판정한다.

#### ML 기반 (Spec 없이도 동작)

`call_count = 1` — 단 한 번만 호출된 미식별 엔드포인트.  
스캐닝, 취약점 탐색, 실수로 노출된 내부 API 등이 해당된다.

#### Spec 기반 (OpenAPI 파일 업로드 시 활성화)

API Inventory의 각 엔드포인트를 OpenAPI 스펙과 대조한다.  
**스펙에 정의되지 않았지만 실제 트래픽이 있는 엔드포인트** = Shadow API.

```
traffic endpoint  ──→  match_key 변환  ──→  spec match_keys 와 비교
                        /users/{id}                /users/{}
                        /users/{userId}    →       /users/{}   ← 동일하게 취급
```

path parameter의 **이름은 무시**하고 **구조만 비교**하므로  
OpenAPI의 `{userId}`와 정규화된 `{id}`가 올바르게 매칭된다.

#### source 플래그 3종

| source | 의미 |
|--------|------|
| `ml` | call_count = 1 (ML 단독 탐지) |
| `spec` | Spec 미등록 + 트래픽 있음 (Spec 단독 탐지) |
| `ml+spec` | 두 조건 모두 해당 (가장 위험) |

#### Unused (Spec에만 존재, 트래픽 없음)

Spec에 정의됐지만 실제 호출 기록이 없는 엔드포인트.  
삭제된 API가 문서에 남아 있거나 미배포 기능 확인에 활용한다.

---

## 3. 모듈 구조

```
nginx-api-discovery/
│
├── main.py                        # 파이프라인 실행 진입점
├── serve.py                       # 대시보드 서버 실행 진입점
├── config/
│   └── settings.yaml              # 전체 설정 (서버마다 별도 파일 가능)
│
├── src/
│   ├── collector/
│   │   └── log_reader.py          # 배치 읽기 / 실시간 tail
│   │
│   ├── parser/
│   │   └── log_parser.py          # JSON 파싱 → ParsedLog
│   │
│   ├── discovery/
│   │   ├── normalizer.py          # URI 정규화 (/users/123 → /users/{id})
│   │   ├── inventory.py           # API Inventory 집계 + CSV/JSON 저장
│   │   ├── openapi_parser.py      # OpenAPI 2.0/3.0 YAML·JSON 파싱
│   │   └── shadow_detector.py     # ML + Spec 통합 Shadow 탐지
│   │
│   ├── features/
│   │   ├── extractor.py           # ParsedLog → RawFeatures (26개)
│   │   ├── vectorizer.py          # RawFeatures → 수치 벡터 (save/load)
│   │   ├── sequence_builder.py    # IP별 슬라이딩 윈도우 시퀀스
│   │   └── dataset.py             # flat CSV + sequence JSON 저장
│   │
│   ├── models/
│   │   ├── autoencoder.py         # AutoEncoder 모델 정의
│   │   ├── lstm_model.py          # LSTM AutoEncoder 모델 정의
│   │   ├── trainer.py             # 공통 학습 루프 (Early Stopping)
│   │   ├── detector.py            # 재구성 오차 → 이상 점수 → 판정
│   │   └── model_manager.py       # 학습/저장/로드 일괄 관리
│   │
│   ├── dashboard/
│   │   ├── app.py                 # FastAPI 라우터 (업로드 포함)
│   │   ├── reader.py              # output/ 최신 파일 + OpenAPI 스펙 읽기
│   │   ├── static/
│   │   │   ├── style.css          # NGINX Plus 스타일 다크 테마
│   │   │   └── dashboard.js       # Chart.js + 업로드 UI + 5초 자동 폴링
│   │   └── templates/
│   │       └── index.html         # 4탭 대시보드 레이아웃
│   │
│   └── pipeline.py                # 전체 파이프라인 오케스트레이터
│
├── output/                        # 파이프라인 실행 결과 (자동 생성)
│   ├── openapi/                   # 업로드된 OpenAPI 스펙 저장
│   └── models/                    # 학습된 모델 가중치 및 임계값
├── tests/                         # 단위 테스트 (41개)
└── requirements.txt
```

---

## 4. 설치 및 환경 설정

### 요구 사항

- Python 3.10+
- NGINX 1.11.0+ (request_id 변수 지원)

### 설치

```bash
git clone <repo>
cd nginx-api-discovery
pip3 install -r requirements.txt
```

### requirements.txt

```
pyyaml>=6.0
torch>=2.0
numpy>=1.24
fastapi>=0.110
uvicorn>=0.27
jinja2>=3.1
python-multipart>=0.0.9
pytest>=8.0
```

> PyTorch CPU 전용으로 설치하려면:
> ```bash
> pip3 install torch --index-url https://download.pytorch.org/whl/cpu
> ```

---

## 5. NGINX 설정

`nginx.conf`의 `http` 블록에 아래 내용을 추가한다.

```nginx
http {
    log_format api_discovery escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"method":"$request_method",'
            '"uri":"$uri",'
            '"query_string":"$query_string",'
            '"status":$status,'
            '"body_bytes_sent":$body_bytes_sent,'
            '"request_length":$request_length,'
            '"request_time":$request_time,'
            '"http_user_agent":"$http_user_agent",'
            '"http_referer":"$http_referer",'
            '"http_x_forwarded_for":"$http_x_forwarded_for",'
            '"http_authorization":"$http_authorization",'
            '"http_content_type":"$http_content_type",'
            '"http_accept":"$http_accept",'
            '"upstream_response_time":"$upstream_response_time",'
            '"server_name":"$server_name",'
            '"request_id":"$request_id"'
        '}';

    access_log /var/log/nginx/api_access.log api_discovery;
}
```

설정 적용:

```bash
nginx -t          # 문법 검사
nginx -s reload   # 무중단 재적용
```

---

## 6. 설정 파일 가이드

`config/settings.yaml` 전체 항목 설명:

```yaml
pipeline:
  log_path: "/var/log/nginx/api_access.log"  # NGINX 로그 경로
  output_dir: "./output"                      # 결과 저장 경로
  batch_size: 10000                           # 배치 처리 단위 (줄 수)

discovery:
  normalizers:                  # URI 정규화 패턴 (순서 = 우선순위)
    - name: uuid
      pattern: '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
      placeholder: "{uuid}"     # UUID는 숫자 ID보다 앞에 둬야 오탐 방지
    - name: date
      pattern: '\d{4}-\d{2}-\d{2}'
      placeholder: "{date}"
    - name: numeric_id
      pattern: '\d+'
      placeholder: "{id}"
    - name: hex_hash
      pattern: '[0-9a-f]{24,}'
      placeholder: "{hash}"
  exclude_prefixes:             # 분석 제외할 URI 접두사
    - "/static"
    - "/health"

inventory:
  output_format: "both"        # csv / json / both
  min_call_count: 1            # 이 횟수 미만 호출은 Inventory에서 제외

features:
  window_size: 10              # LSTM 시퀀스 길이 (timestep 수)
  step: 1                      # 슬라이딩 윈도우 이동 간격
                               #   1 = 최대 데이터 생성 (겹침 많음)
                               #   window_size = 겹침 없음
  vectorizer_path: "./output/vectorizer.json"  # 인코더 저장 경로

models:
  output_dir: "./output/models"
  threshold_percentile: 95.0   # 정상 데이터의 상위 5%를 이상으로 판정
                               # 낮출수록 민감도 증가, 높일수록 특이도 증가
  autoencoder:
    hidden_dims: [16, 8]       # 인코더 레이어 크기 (디코더는 자동 역순)
    lr: 0.001
    batch_size: 64
    max_epochs: 100
    patience: 10               # val_loss 개선 없으면 10 epoch 후 조기 종료

  lstm:
    hidden_dim: 32             # LSTM hidden state 차원
    num_layers: 1
    lr: 0.001
    batch_size: 32
    max_epochs: 100
    patience: 10
```

---

## 7. 실행 방법

### 7-1. 파이프라인 실행 (로그 분석 + 학습)

```bash
# 기본 실행
python3 main.py

# 설정 파일 지정
python3 main.py --config config/settings.yaml

# 디버그 로그 출력
python3 main.py --log-level DEBUG
```

실행 시 콘솔 출력 예시:

```
2026-04-21 14:00:01 [INFO] === API Discovery Pipeline 시작 ===
2026-04-21 14:00:03 [INFO] [1/4] 파싱 완료 — 14313건 성공, 2건 실패 (성공률: 99.99%)
2026-04-21 14:00:03 [INFO] [2/4] Inventory 저장 완료 — 42개 Endpoint / 14313회 호출
2026-04-21 14:00:04 [INFO] [3/4] Feature Engineering 완료 — 14313개 벡터, 1180개 시퀀스
2026-04-21 14:00:04 [INFO] [4/4] 딥러닝 모델 학습 시작
2026-04-21 14:00:08 [INFO] Epoch   10/100 | train_loss: 0.024310 | val_loss: 0.026104
2026-04-21 14:00:11 [INFO] Early stopping at epoch 38 (best val_loss: 0.018923)
2026-04-21 14:00:12 [INFO] 임계값 설정: 0.042831 (95.0th percentile)
2026-04-21 14:00:12 [INFO] [4/4] AutoEncoder — 이상 탐지: 716/14313건 (5.0%)
2026-04-21 14:00:14 [INFO] [4/4] LSTM — 이상 시퀀스: 59/1180건 (5.0%)
2026-04-21 14:00:14 [INFO] 처리 시간: 13.4초
2026-04-21 14:00:14 [INFO] === Pipeline 완료 ===
```

### 7-2. 주기적 실행 (cron 등록)

```bash
# crontab -e
# 매 1시간마다 실행
0 * * * * cd /path/to/nginx-api-discovery && python3 main.py >> /var/log/api-discovery.log 2>&1
```

### 7-3. 테스트 실행

```bash
python3 -m pytest tests/ -v
# 41개 테스트 전부 통과 확인
```

---

## 8. 대시보드 사용법

### 실행

```bash
# 기본 (포트 8080)
python3 serve.py

# 포트 / output 경로 지정
python3 serve.py --port 9090 --output /data/api-discovery/output

# 개발 모드 (코드 수정 시 자동 재시작)
python3 serve.py --reload
```

브라우저에서 `http://서버IP:8080` 접속.

> **코드 수정 후에는 반드시 서버를 재시작해야 변경 사항이 반영된다.**
> ```bash
> pkill -f "serve.py"
> python3 serve.py
> ```

---

### 탭별 기능

#### Overview 탭

전체 현황을 한눈에 파악하는 메인 화면.

| 카드 | 설명 |
|------|------|
| Total Endpoints | 발견된 API 엔드포인트 수 |
| Total Requests | 전체 요청 수 |
| Total Errors | 4xx + 5xx 합계 |
| Global Error Rate | 전체 오류율 |
| No-Auth Endpoints | 인증 없이 접근 가능한 엔드포인트 수 |
| Shadow APIs | ML + Spec 통합 Shadow 탐지 수 (Spec 업로드 시 Spec 기반 수도 표시) |
| High Error Endpoints | 오류율 30% 이상 엔드포인트 수 |
| Unique IPs | 접근한 고유 IP 수 |
| Model Status | 딥러닝 모델 학습 완료 여부 |

차트:
- **Top Endpoints by Requests** — 호출 많은 상위 10개 엔드포인트
- **Method Distribution** — GET/POST/PUT/DELETE 비율
- **Status Distribution** — 2xx/4xx/5xx 비율
- **Top Endpoints by Error Rate** — 오류율 높은 상위 10개

---

#### Endpoints 탭

전체 API Inventory 테이블.

- **검색**: endpoint 경로로 필터링
- **메서드 필터**: GET/POST/PUT/DELETE/PATCH 선택
- **컬럼 정렬**: 헤더 클릭으로 오름/내림차순 전환
- **페이지네이션**: 25건씩 표시
- **플래그 표시**:
  - `Shadow?` — 1회 호출 엔드포인트 (문서에 없는 API 가능성)
  - 빨간 Error Rate — 30% 이상
  - `None` 인증 배지 — 인증 없이 접근 가능

---

#### Anomalies 탭

Shadow API 탐지 결과와 기타 이상 항목을 표시.

**OpenAPI Spec 업로드 패널**

탭 상단에 위치한 업로드 패널에서 OpenAPI 스펙 파일을 등록한다.

- YAML (`.yaml`, `.yml`) / JSON (`.json`) 모두 지원
- OpenAPI 2.0 (Swagger) / OpenAPI 3.0 모두 지원
- 드래그 앤 드롭 또는 파일 선택 버튼으로 업로드
- 업로드 후 Title, API Version, Endpoint 수 즉시 표시
- 스펙 제거 버튼으로 언제든 초기화 가능
- **서버를 재시작해도 업로드된 스펙은 `output/openapi/`에 유지**된다

**Shadow API Detection 섹션**

| 컬럼 | 설명 |
|------|------|
| **Shadow APIs** | ML + Spec 통합 탐지 결과. 각 항목에 `ml` / `spec` / `ml+spec` source 배지 표시 |
| **Spec에만 있고 트래픽 없음** | OpenAPI에 정의됐지만 실제 호출 기록 없는 엔드포인트 (Spec 미업로드 시 비활성) |

**Other Anomalies 섹션**

| 컬럼 | 탐지 기준 |
|------|-----------|
| **No Authentication** | has_auth = false (인증 없이 접근 가능) |
| **High Error Rate** | error_rate ≥ 30% (오류율 높은 위험 엔드포인트) |

---

#### Models 탭

딥러닝 학습 결과 확인.

- **Training Loss Curve** — AutoEncoder / LSTM의 학습/검증 loss 곡선
- **AutoEncoder 정보** — 학습 epoch 수, 최종 loss, 이상 판정 임계값
- **LSTM 정보** — 학습 epoch 수, 최종 loss, 이상 판정 임계값

> 모델이 아직 학습되지 않았으면 "No trained model found" 표시.

---

### 대시보드 API 엔드포인트 (직접 조회 가능)

| 경로 | 메서드 | 설명 |
|------|--------|------|
| `GET /api/summary` | GET | 전체 요약 통계 |
| `GET /api/inventory` | GET | API 목록 (`?method=GET&search=user&sort=call_count&order=desc`) |
| `GET /api/charts/top-endpoints` | GET | 상위 호출 엔드포인트 |
| `GET /api/charts/method-dist` | GET | 메서드 분포 |
| `GET /api/charts/status-dist` | GET | 상태코드 분포 |
| `GET /api/charts/error-rate` | GET | 오류율 상위 엔드포인트 |
| `GET /api/charts/training-history` | GET | 모델 학습 곡선 |
| `GET /api/anomalies/shadow` | GET | Shadow API 목록 (ML + Spec 통합) |
| `GET /api/anomalies/unused-spec` | GET | Spec 등록 후 트래픽 없는 엔드포인트 |
| `GET /api/anomalies/no-auth` | GET | 인증 없는 엔드포인트 |
| `GET /api/anomalies/high-error` | GET | 고오류율 엔드포인트 (`?threshold=30.0`) |
| `GET /api/openapi/status` | GET | 현재 업로드된 Spec 정보 |
| `POST /api/openapi/upload` | POST | OpenAPI 스펙 파일 업로드 (multipart/form-data) |
| `DELETE /api/openapi/spec` | DELETE | 업로드된 스펙 제거 |

---

## 9. 출력 파일 설명

파이프라인 실행 및 대시보드 사용 중 `output/` 아래에 생성되는 파일들.

```
output/
├── api_inventory_YYYYMMDD_HHMMSS.json       # API Inventory (JSON)
├── api_inventory_YYYYMMDD_HHMMSS.csv        # API Inventory (CSV)
├── features_flat_YYYYMMDD_HHMMSS.csv        # AutoEncoder 입력 벡터 + 메타
├── features_sequences_YYYYMMDD_HHMMSS.json  # LSTM 입력 시퀀스
├── feature_stats_YYYYMMDD_HHMMSS.json       # Feature Engineering 통계
├── vectorizer.json                           # 인코더/스케일러 (서버 간 공유용)
├── openapi/
│   └── spec.yaml (또는 spec.json)           # 업로드된 OpenAPI 스펙 (서버 재시작 후도 유지)
└── models/
    ├── autoencoder.pt                        # AutoEncoder 가중치
    ├── lstm_autoencoder.pt                   # LSTM 가중치
    ├── ae_threshold.json                     # AutoEncoder 이상 판정 임계값
    ├── lstm_threshold.json                   # LSTM 이상 판정 임계값
    ├── ae_train_history.json                 # AE epoch별 train/val loss
    └── lstm_train_history.json               # LSTM epoch별 train/val loss
```

대시보드는 실행 시마다 **가장 최신 타임스탬프 파일을 자동 선택**한다.

---

## 10. 멀티 서버 배포

여러 NGINX 서버에서 데이터를 수집하는 경우, 서버마다 별도 설정 파일을 사용한다.

### 구조 예시

```
nginx-api-discovery/
├── config/
│   ├── settings_api_server.yaml     # API 서버 전용 설정
│   ├── settings_cdn.yaml            # CDN 서버 전용 설정
│   └── settings_admin.yaml          # 관리자 서버 전용 설정
```

### 서버별 설정 차이점

```yaml
# settings_api_server.yaml
pipeline:
  log_path: "/var/log/nginx/api_access.log"
  output_dir: "./output/api_server"

# settings_admin.yaml
pipeline:
  log_path: "/var/log/nginx/admin_access.log"
  output_dir: "./output/admin"
discovery:
  exclude_prefixes:
    - "/static"
    - "/health"
    - "/metrics"       # 관리자 서버 전용 제외 경로 추가
```

### 실행

```bash
python3 main.py --config config/settings_api_server.yaml
python3 main.py --config config/settings_admin.yaml
```

### 학습된 모델을 다른 서버에서 재사용

서버 A에서 학습 후, 아래 파일들을 서버 B에 복사하면 재학습 없이 즉시 추론 가능하다.

```bash
scp output/vectorizer.json            serverB:/path/output/
scp output/models/autoencoder.pt      serverB:/path/output/models/
scp output/models/ae_threshold.json   serverB:/path/output/models/
# OpenAPI 스펙도 공유 가능
scp output/openapi/spec.yaml          serverB:/path/output/openapi/
```

---

## 11. 트러블슈팅

### 파싱 실패율이 높은 경우

```bash
python3 main.py --log-level DEBUG
# "파싱 실패" 로그에서 원본 줄 확인
```

원인: NGINX 로그 포맷과 파서 기대값 불일치.  
→ `config/settings.yaml`의 `log_path` 확인, NGINX `log_format` 재확인.

---

### URI 정규화가 잘못 되는 경우

```
/api/v1/reports/2024-03-01  →  /api/v1/reports/{id}  (날짜가 id로 잘못 치환)
```

원인: `settings.yaml`의 `normalizers` 순서 오류 — `date`가 `numeric_id`보다 뒤에 있으면 발생.  
→ 항상 **uuid → date → numeric_id** 순서를 유지한다.

---

### OpenAPI 업로드 시 "Not Found" 오류

원인: 코드 수정 후 서버를 재시작하지 않아 구버전이 실행 중인 경우.

```bash
pkill -f "serve.py"
python3 serve.py
```

코드를 변경했다면 항상 서버를 재시작해야 새 라우트가 등록된다.

---

### OpenAPI 업로드 시 422 오류

원인 1: `python-multipart` 패키지 미설치.
```bash
pip3 install python-multipart
```

원인 2: 스펙 파일 형식 오류 (유효한 OpenAPI 2.0 / 3.0이 아닌 경우).  
→ 응답 본문의 `detail` 필드에서 파싱 오류 내용을 확인한다.

---

### 모델 학습이 너무 느린 경우

CPU 환경에서 데이터가 많으면 학습이 오래 걸린다.

```yaml
# settings.yaml 조정
models:
  autoencoder:
    max_epochs: 50      # epoch 수 줄이기
    batch_size: 128     # batch 크기 키우기
  lstm:
    max_epochs: 50
    batch_size: 64
features:
  step: 5               # 시퀀스 겹침 줄여 데이터 수 감소
```

---

### 대시보드에 데이터가 표시되지 않는 경우

파이프라인을 먼저 실행해 `output/` 파일을 생성해야 한다.

```bash
python3 main.py       # 먼저 실행
python3 serve.py      # 그 다음 대시보드 실행
```

---

### 포트 충돌

```bash
# 사용 중인 포트 확인
lsof -i :8080

# 다른 포트 사용
python3 serve.py --port 9090
```
