# 울리지 않는 알림이 낫다 — 알림을 무엇을 기준으로 줄이는가

> 이 문서가 답할 질문: **알림이 울려도 아무도 보지 않는 상태는 왜 생기고, 무엇을 기준으로 줄여야 하는가?**
>
> 분류: 문제해결형. "알림을 어떻게 설계하는가"가 아니라 **이미 망가진 알림 체계에서 증상 → 원인 → 해법을 찾는** 문제입니다. 그래서 여러 출처가 공통으로 보고하는 증상과 그 처방을 찾는 관점으로 조사했습니다.
>
> 기준: Prometheus 3.x · Alertmanager 0.28 계열 문서 (2026년 10월 확인). 무엇을 지표로 잴지는 `day54-golden-signals.md`에서 다뤘습니다. 이 문서는 **그 지표로 언제 사람을 부를지**만 다룹니다. SLO 자체를 정하는 법은 범위 밖입니다.

## 1. 핵심 개념 — 알림의 비용은 "사람의 주의"입니다

알림 하나를 추가하는 비용은 0처럼 보입니다. YAML 다섯 줄입니다. 그래서 장애를 겪을 때마다 한 줄씩 늘어납니다. 디스크 80%, CPU 85%, 재시작 감지, GC 급증, 큐 길이, 특정 로그 패턴. 1년 뒤 규칙 파일은 300줄이 됩니다.

> 그때 벌어지는 일은 이렇습니다. Slack 알림 채널은 하루에 400건이 쌓이고, 아무도 스크롤하지 않습니다. 새벽에 울린 페이지를 보고 "또 그거겠지" 하면서 스누즈합니다. 그리고 진짜 장애가 났을 때, 그 알림도 400건 중 하나로 섞여서 **40분 뒤에 고객 문의로 알게 됩니다.** 알림이 없어서 생긴 장애가 아니라, 알림이 너무 많아서 생긴 장애입니다.

이게 알림 피로(alert fatigue)입니다. 그리고 이건 팀의 성숙도 문제가 아니라 업계 평균입니다. Grafana Labs가 76개국 1,363명을 조사한 2026년 설문에서 **알림 피로가 장애 대응 속도를 늦추는 가장 큰 단일 장애물로 꼽혔고(응답자 30%), 2위와 거의 두 배 차이**였습니다([Grafana Labs — 4th Annual Observability Survey, 2026-03](https://grafana.com/press/2026/03/18/grafana-labs-4th-annual-observability-survey-reveals-a-field-at-a-crossroads-ai-economics-complexity-and-the-enduring-power-of-open-source/)). 같은 문제를 다룬 2026년 2월 조사(SRE·DevOps·IT 운영 직군 1,039명)에서는 **44%가 지난 1년간 "무시했거나 억제한 알림"에서 비롯된 장애를 겪었다**고 답했습니다([NeuBird 설문, 2026-04](https://neubird.ai/news-and-press/new-study-finds-alert-fatigue-has-become-a-production-reliability-risk/) — 알림 피로 해소 제품을 판매하는 벤더가 발행한 자료라는 점을 감안해서 읽으세요).

그래서 이 챕터의 제목이 과장이 아닙니다. **조치가 없는 알림은 지우는 쪽이 유지하는 쪽보다 낫습니다.** 유지 비용이 0이 아니라, 진짜 알림이 쓸 주의력을 미리 깎아먹기 때문입니다. Prometheus 공식 권고도 같은 방향입니다. **"알림은 가능한 한 적게 두는 것을 목표로 하고, 조치가 필요 없는 페이지는 만들지 말라"**([Prometheus — Alerting best practices](https://prometheus.io/docs/practices/alerting/)).

## 2. 구조 — 알림은 삭제가 아니라 등급 강하로 줄입니다

"쓸모없는 알림을 지우라"는 말에 사람들이 저항하는 이유는 명확합니다. 그 지표가 쓸모없는 게 아니라, **지금 사람을 깨울 만큼은 아닌** 것이기 때문입니다. 그래서 이분법(알림 있음/없음)이 아니라 세 등급으로 나눕니다. Google SRE 책이 쓰는 구분입니다([Practical Alerting](https://sre.google/sre-book/practical-alerting/)).

| 등급 | 질문 | 전달 경로 | 예 |
|---|---|---|---|
| 페이지(page) | **지금 당장** 사람이 개입해야 하는가 | 온콜 호출 | 주문 API 에러율이 예산을 빠르게 태우고 있음 |
| 티켓(ticket) | 개입은 필요하지만 내일 해도 되는가 | 이슈 큐 | 디스크가 2주 뒤 가득 찰 추세 |
| 정보(info) | 조사할 때 보면 되는가 | 대시보드만 | CPU 사용률, GC 횟수, 캐시 적중률 |

페이지 알림 하나를 티켓으로 내리는 건 "포기"가 아닙니다. 같은 정보를 **사람을 깨우지 않는 경로로** 옮기는 작업입니다. 알림 정리를 시작할 때 "지울까요?"로 물으면 아무것도 못 지웁니다. **"이걸 티켓으로 내려도 되나요?"로 물으면 절반이 내려갑니다.**

등급을 나눌 때 기준은 하나입니다. **알림을 받은 사람이 지금 할 수 있는 조치가 있는가.** 조치가 "일단 지켜본다"면 그건 대시보드입니다.

## 3. 원인 — 알림이 늘어나는 네 가지 경로

### 3-1. 증상이 아니라 원인에 걸었습니다

가장 큰 원인입니다. 장애를 겪고 나면 그 장애의 **직접 원인**에 알림을 걸고 싶어집니다. "지난번에 스레드 풀이 터졌으니 스레드 풀에 알림을 걸자."

문제는 원인이 무한하다는 겁니다. 서비스가 느려지는 경로는 수십 개고, 장애마다 하나씩 추가하면 규칙이 선형으로 늘어납니다. 반대로 증상은 몇 개 안 됩니다. 사용자가 겪는 고통은 결국 "느리다 / 실패한다 / 안 된다" 셋입니다.

Prometheus 권고는 구체적입니다. **지연시간과 에러율에 알림을 걸고, 스택에서 가능한 한 높은 지점에 걸되, 지연시간은 스택의 한 지점에서만 페이지로 건다.** 같은 요청 경로의 ALB·게이트웨이·애플리케이션 세 곳에 지연시간 페이지를 걸면, 한 번 느려질 때 세 번 울립니다. 정보량은 늘지 않습니다.

여기서 흔한 반론이 있습니다. "원인 알림이 있어야 빨리 고치지 않나요?" 아닙니다. 원인은 **알림이 아니라 대시보드로** 찾습니다(`day54-golden-signals.md`). 알림이 할 일은 "지금 봐야 한다"를 알리는 것까지고, "무엇 때문인가"는 들어와서 보는 일입니다. 다만 Google SRE 문서는 예외를 인정합니다. 원인이 **아주 확실하고 아주 임박한** 경우에는 원인 알림이 유효합니다([Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)).

### 3-2. 임계값을 사용률에 걸었습니다

`cpu > 80%`, `memory > 85%` 류입니다. 이 알림은 둘 다 틀립니다. CPU 85%인데 응답시간이 멀쩡한 경우가 흔하고(= 거짓 양성), CPU 50%인데 커넥션 풀이 말라서 장애인 경우도 흔합니다(= 거짓 음성). 사용률과 포화도의 차이는 `day54-golden-signals.md`에서 다뤘습니다. 알림 관점의 결론은 이것입니다. **사용률 알림은 대시보드로 내립니다.**

### 3-3. 한 사건이 N개 알림으로 쪼개집니다

인스턴스 12대가 돌고 있고, 공통 의존하는 데이터베이스가 죽습니다. 인스턴스별 에러율 알림 12개 + 헬스체크 실패 12개 + DB 연결 실패 12개 = 36건이 2분 안에 도착합니다. 사건은 하나입니다.

Google SRE 책은 단일 머신 수준 알림에 대해 **"그런 데이터는 너무 노이즈가 많아 조치 가능하지 않으므로 받아들일 수 없다"**고 못을 박습니다. 머신 하나가 죽는 걸 사람이 알 필요가 없게 시스템을 설계하고, 신호는 합산해서 보라는 겁니다.

### 3-4. 심각도가 고정입니다

`error_rate > 1%`로 걸어두면 1.1%도, 100%도 같은 알림입니다. 1.1%는 하루쯤 지켜봐도 되고, 100%는 지금 당장 봐야 합니다. 두 사건의 긴급도가 100배 차이인데 전달 경로가 같습니다.

이걸 임계값 하나로 해결할 수는 없습니다. 임계값을 낮추면 노이즈가 늘고, 올리면 느린 장애를 놓칩니다. 여기서 소진율(burn rate)이 등장합니다.

## 4. 해법의 핵은 소진율 — `for`를 길게 주는 건 해법이 아닙니다

알림이 시끄러우면 보통 두 가지를 합니다. 임계값을 올리거나, `for`를 길게 줍니다. 둘 다 조용해지긴 합니다. 재현율(놓치지 않는 비율)을 깎아서 조용해집니다.

Google SRE Workbook은 알림 규칙을 네 축으로 평가합니다([Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)).

| 축 | 뜻 | 나빠지면 |
|---|---|---|
| 정밀도(precision) | 울린 알림 중 실제 사건의 비율 | 노이즈 → 알림 피로 |
| 재현율(recall) | 실제 사건 중 울린 비율 | 장애를 놓침 |
| 탐지 시간 | 울리기까지 걸리는 시간 | 늦게 알게 됨 |
| 복구 시간(reset time) | 해소 후에도 계속 울리는 시간 | 끝난 장애로 계속 깨움 |

이 네 축으로 보면 `for`를 길게 주는 방식이 왜 나쁜지가 드러납니다. 같은 문서는 `for` 기반 접근을 **권장하지 않는다**고 명시하고, 이유를 둘 듭니다.

1. **지속 시간이 심각도에 비례하지 않습니다.** 에러율 10%와 100%가 똑같이 10분을 기다립니다.
2. **짧은 회복이 타이머를 리셋합니다.** 10분 중 1분만 조건이 풀려도 처음부터 다시 셉니다. 그래서 **톱니 모양으로 오르내리는 장애는 예산을 크게 태우면서도 한 번도 울리지 않을 수 있습니다.**

대안이 소진율입니다. 정의는 간단합니다.

```
소진율 = 현재 에러율 / 허용 에러율(1 - SLO)
```

SLO가 99.9%면 허용 에러율은 0.1%입니다. 소진율 1은 "30일 예산을 정확히 30일에 다 쓰는 속도"입니다. 소진율 10이면 3일에 다 씁니다. 소진율 1,000이면 **약 43분에 한 달 예산을 태웁니다**(같은 문서).

핵심은 이 숫자가 **긴급도를 그대로 표현한다**는 점입니다. 임계값 하나로 두 긴급도를 구분할 수 없었던 문제(§3-4)가 사라집니다. 빠른 소진은 페이지, 느린 소진은 티켓으로 보내면 됩니다.

### 4-1. 멀티윈도 · 멀티번레이트

소진율만으로는 복구 시간 문제가 남습니다. 1시간 창으로 재면 장애가 끝나고도 **약 58분간 알림이 계속 울립니다**(같은 문서). 장애가 1분 만에 끝났는데 한 시간을 더 깨우는 셈입니다.

그래서 권장안은 **긴 창과 짧은 창을 AND로 묶는** 형태입니다. 긴 창은 "유의미한 양을 태웠는가"를 보고, 짧은 창은 "지금도 태우고 있는가"를 봅니다. 짧은 창은 긴 창의 **1/12**로 둡니다.

Workbook이 제시하는 99.9% SLO · 30일 기준 권장값입니다(Table 5-8).

| 등급 | 긴 창 | 짧은 창 | 소진율 | 그 시간에 태우는 예산 |
|---|---|---|---|---|
| 페이지 | 1시간 | 5분 | 14.4 | 2% |
| 페이지 | 6시간 | 30분 | 6 | 5% |
| 티켓 | 3일 | 6시간 | 1 | 10% |

규칙 세 개로 빠른 장애와 느린 장애를 모두 덮습니다. 그리고 알림 개수가 **엔드포인트 수가 아니라 서비스 수에 비례**하게 됩니다.

### 4-2. 코드 — 기록 규칙과 알림 규칙

창마다 비율을 매번 계산하면 쿼리가 길어지고 느려집니다. 기록 규칙으로 먼저 줄여둡니다.

```yaml
# prometheus/rules/order-api-slo.yml
groups:
  - name: order-api-slo-ratios
    interval: 30s
    rules:
      - record: order_api:slo_errors:ratio_rate5m
        expr: |
          sum(rate(http_server_requests_seconds_count{job="order-api",status=~"5.."}[5m]))
            / sum(rate(http_server_requests_seconds_count{job="order-api"}[5m]))
      - record: order_api:slo_errors:ratio_rate1h
        expr: |
          sum(rate(http_server_requests_seconds_count{job="order-api",status=~"5.."}[1h]))
            / sum(rate(http_server_requests_seconds_count{job="order-api"}[1h]))
      - record: order_api:slo_errors:ratio_rate30m
        expr: |
          sum(rate(http_server_requests_seconds_count{job="order-api",status=~"5.."}[30m]))
            / sum(rate(http_server_requests_seconds_count{job="order-api"}[30m]))
      - record: order_api:slo_errors:ratio_rate6h
        expr: |
          sum(rate(http_server_requests_seconds_count{job="order-api",status=~"5.."}[6h]))
            / sum(rate(http_server_requests_seconds_count{job="order-api"}[6h]))

  - name: order-api-slo-alerts
    rules:
      # 빠른 소진 — 1시간에 예산 2%
      - alert: OrderApiErrorBudgetBurnFast
        expr: |
          order_api:slo_errors:ratio_rate1h > (14.4 * 0.001)
          and
          order_api:slo_errors:ratio_rate5m > (14.4 * 0.001)
        labels:
          severity: page
          service: order-api
        annotations:
          summary: "order-api 에러 예산을 1시간에 2% 이상 소진 중"
          description: "최근 1시간 5xx 비율 {{ $value | humanizePercentage }}. 5분 창에서도 초과 중이라 진행 중인 장애입니다."
          runbook_url: "https://wiki.example.com/runbooks/order-api-error-budget"

      # 느린 소진 — 3일에 예산 10%. 깨우지 않고 티켓으로
      - alert: OrderApiErrorBudgetBurnSlow
        expr: |
          order_api:slo_errors:ratio_rate3d > (1 * 0.001)
          and
          order_api:slo_errors:ratio_rate6h > (1 * 0.001)
        labels:
          severity: ticket
          service: order-api
        annotations:
          summary: "order-api 에러 예산이 느리게 새고 있습니다 (3일 기준 10%)"
          runbook_url: "https://wiki.example.com/runbooks/order-api-error-budget"
```

`0.001`이 허용 에러율(1 - 0.999)입니다. SLO를 바꾸면 이 숫자만 바꿉니다. `ratio_rate3d`는 지면상 생략했지만 같은 형태로 추가합니다.

`for`를 아예 쓰지 말라는 뜻은 아닙니다. 짧은 창이 이미 "지금 진행 중"을 검증하므로 여기서는 필요가 없을 뿐입니다. 데이터 공백으로 알림이 깜빡이는 게 문제라면 `keep_firing_for`가 더 맞는 도구입니다. 조건이 마지막으로 충족된 뒤 지정 시간만큼 **발화 상태를 유지**해서 플래핑과 거짓 해소를 막습니다([Prometheus — Alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)).

## 5. 줄일 수 없는 알림은 "전달"을 줄입니다

규칙을 다 정리해도 장애 한 번에 알림 수십 개가 생기는 구조(§3-3)는 남습니다. 이건 규칙이 아니라 Alertmanager 쪽에서 처리합니다.

- **그룹화(grouping)** — 성질이 비슷한 알림을 하나의 알림으로 묶습니다. 수백 개가 동시에 발화하는 대규모 장애에서 가장 유용합니다.
- **억제(inhibition)** — 특정 알림이 이미 발화 중이면 다른 알림의 통지를 **억누릅니다**. "클러스터 전체가 도달 불가"가 울리는 동안 그 클러스터의 개별 알림을 음소거하는 용도입니다.
- **침묵(silence)** — 매처로 일정 기간 음소거합니다. 계획된 배포·점검용입니다.

([Alertmanager 개요](https://prometheus.io/docs/alerting/latest/alertmanager/))

```yaml
# alertmanager.yml
route:
  group_by: ['service', 'alertname']   # 인스턴스 단위로 묶지 않습니다
  group_wait: 30s                      # 첫 통지 전 대기 (기본 30s)
  group_interval: 5m                   # 그룹 변화 통지 주기 (기본 5m)
  repeat_interval: 4h                  # 같은 내용 재통지 간격 (기본 4h)
  receiver: dashboard-only
  routes:
    - matchers: ['severity="page"']
      receiver: oncall-pager
      repeat_interval: 1h              # 미해결 페이지는 더 자주
    - matchers: ['severity="ticket"']
      receiver: issue-queue
      group_wait: 5m
      repeat_interval: 24h             # 티켓은 하루 한 번으로 충분

inhibit_rules:
  # 서비스 자체가 내려갔으면 그 서비스의 다른 알림은 음소거
  - source_matchers: ['alertname="OrderApiDown"']
    target_matchers: ['service="order-api"']
    equal: ['service']

receivers:
  - name: oncall-pager
    webhook_configs:
      - url: 'https://alerts.example.com/hooks/pager'
  - name: issue-queue
    webhook_configs:
      - url: 'https://alerts.example.com/hooks/issues'
        send_resolved: false           # 티켓 큐에 해소 알림까지 보내지 않습니다
  - name: dashboard-only
    webhook_configs:
      - url: 'https://alerts.example.com/hooks/sink'
```

`group_by`에 `instance`를 넣으면 그룹화가 사실상 무력화됩니다. 인스턴스마다 그룹이 하나씩 생기기 때문입니다. 반대로 `group_by: ['...']`는 집계를 완전히 끄고 모든 알림을 그대로 흘려보냅니다(기본값이 아니라 명시적 선택입니다).

## 6. 함정

### 6-1. 소진율로 바꿨더니 저트래픽 서비스가 계속 울립니다

- **증상**: 하루 요청이 수백 건인 내부 API에서 페이지가 매일 울립니다. 들어가 보면 요청 1건이 실패했습니다.
- **원인**: 분모가 작습니다. 10분에 요청 3건 중 1건이 실패하면 에러율 33%, 소진율 333입니다. 비율 기반 알림은 트래픽이 적으면 통계가 되지 않습니다.
- **해법**: Workbook이 드는 선택지는 합성 트래픽을 흘려보내기, 관련 서비스를 묶어서 하나의 SLO로 보기, 클라이언트에 재시도를 두기, SLO를 낮추기, 창을 길게 하기입니다. 실무에서 제일 자주 쓰는 건 **창을 늘리고 등급을 티켓으로 내리는 것**입니다. 저트래픽 서비스는 애초에 깨울 만한 대상이 아닌 경우가 많습니다.

### 6-2. 임계값만 올려서 조용해졌습니다

- **증상**: 알림 채널이 깨끗해졌는데, 장애를 고객 문의로 먼저 알게 됩니다.
- **원인**: 정밀도를 올린 게 아니라 재현율을 버렸습니다. `error_rate > 1%`를 `> 10%`로 바꾸면 노이즈는 사라지지만, 부분 장애 전체가 보이지 않게 됩니다.
- **해법**: 임계값을 올리는 대신 **창을 늘리고 긴 창·짧은 창을 AND로 묶습니다**(§4-1). 조용해지는 방향이 아니라 "같은 민감도로 노이즈만 줄이는" 방향이어야 합니다. 바꾼 뒤에는 지난 장애 몇 건에 대입해서 그때 울렸을지 확인합니다.

### 6-3. 억제 규칙을 걸었다가 진짜 알림이 묻힙니다

- **증상**: 장애 후 회고에서 "그 알림은 발화했는데 통지가 안 갔다"가 나옵니다.
- **원인**: `inhibit_rules`의 범위가 너무 넓습니다. `equal`에 공통 라벨을 넣지 않으면 **다른 서비스의 알림까지 음소거됩니다.** 문서도 `equal` 라벨이 양쪽 모두에 없으면 규칙이 그대로 적용된다고 명시합니다.
- **해법**: `equal`에 반드시 범위를 한정하는 라벨(`service`, `cluster`)을 넣습니다. 그리고 억제는 **인과가 명확한 한 쌍**에만 씁니다. "A가 죽으면 B 알림은 반드시 의미가 없다"가 참이 아니면 쓰지 않습니다. 억제 대신 그룹화로 해결되는 경우가 더 많습니다.

### 6-4. 모든 알림이 Slack 채널 하나로 갑니다

- **증상**: 채널에 하루 수백 건이 쌓이고, 아무도 읽지 않습니다. 해소(resolved) 알림이 절반입니다.
- **원인**: 등급은 라벨에만 있고 **전달 경로가 분리되지 않았습니다**. 라벨에 `severity: page`를 붙여도 라우팅이 하나면 의미가 없습니다.
- **해법**: §5처럼 라우팅을 등급별로 쪼갭니다. 티켓·정보 등급 리시버의 `send_resolved`를 끄고, `repeat_interval`을 등급별로 다르게 둡니다. 페이지 등급 채널은 **하루에 몇 건인지 셀 수 있는 수준**이어야 합니다.

### 6-5. 알림 메시지에 조치가 없습니다

- **증상**: 새벽에 `HighCpu — CPU 사용률이 높습니다`를 받고, 뭘 해야 할지 모른 채로 대시보드를 뒤집니다.
- **원인**: 알림이 "무엇이 일어났는가"만 담고 "무엇을 해야 하는가"를 담지 않았습니다.
- **해법**: `annotations`에 `runbook_url`을 필수로 넣습니다. 런북이 없는 알림은 **만들 때부터 조치가 정의되지 않은 알림**이므로, 런북을 쓸 수 없으면 그 알림은 티켓이나 대시보드로 내립니다. 이건 좋은 습관이 아니라 등급 판정 기준입니다.

## 7. 예제 — 나쁜 알림과 고친 알림

### 7-1. 흔한 형태 ❌

```yaml
- alert: HighCpu
  expr: instance:node_cpu_utilisation:rate5m > 0.8
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "CPU 사용률이 높습니다"
```

문제가 다섯 개 겹쳐 있습니다. 원인 지표에 걸었고(§3-1), 사용률을 포화도로 오해했고(§3-2), 인스턴스마다 하나씩 울리고(§3-3), 10%든 100% 초과든 같은 등급이고(§3-4), 받은 사람이 할 일이 없습니다(§6-5).

### 7-2. 고친 형태 ✔️

```yaml
# 증상 — 사람을 깨웁니다
- alert: OrderApiErrorBudgetBurnFast
  expr: |
    order_api:slo_errors:ratio_rate1h > (14.4 * 0.001)
    and
    order_api:slo_errors:ratio_rate5m > (14.4 * 0.001)
  labels:
    severity: page
    service: order-api
  annotations:
    summary: "order-api 에러 예산을 1시간에 2% 이상 소진 중"
    runbook_url: "https://wiki.example.com/runbooks/order-api-error-budget"

# 포화 추세 — 깨우지 않고 티켓으로. 6시간 뒤 고갈 예측
- alert: OrderApiDiskFillingUp
  expr: predict_linear(node_filesystem_avail_bytes{job="order-api"}[6h], 6 * 3600) < 0
  for: 30m
  labels:
    severity: ticket
    service: order-api
  annotations:
    summary: "order-api 디스크가 6시간 내 고갈될 추세입니다"
    runbook_url: "https://wiki.example.com/runbooks/disk-cleanup"
```

CPU 사용률은 사라지지 않았습니다. **대시보드로 내려갔습니다.** 그리고 디스크는 "80% 넘음"이 아니라 "추세대로면 고갈까지 6시간"으로 바뀌었습니다. 후자는 티켓으로 처리할 수 있는 정보고, 전자는 아닙니다.

## 8. 알림 자체를 측정합니다

알림 정리는 한 번 하는 일이 아니라 계속 하는 일이고, 그러려면 숫자가 필요합니다. Google SRE 책이 제시하는 기준이 출발점으로 쓸 만합니다([Being On-Call](https://sre.google/sre-book/being-on-call/)).

- 온콜 인시던트 1건을 근본 원인 분석·조치·후속까지 제대로 처리하는 데 **평균 6시간**이 든다고 봅니다.
- 그래서 **12시간 교대당 인시던트는 최대 2건**입니다. 이게 운영 부하의 상한입니다.
- 페이지 발생은 시간에 대해 매우 평탄해야 하고, **중위값은 0에 가까워야** 합니다. 매일 페이지를 내는 컴포넌트는 상한을 넘기는 원인입니다.
- 목표는 **알림 1건 : 인시던트 1건** 비율에 가까워지는 것입니다.

실무에서 볼 지표는 둘이면 충분합니다. **교대당 페이지 수**와 **페이지 중 실제로 조치한 비율**입니다. 두 번째가 낮으면 정밀도 문제고, 장애를 알림 없이 겪은 건수가 있으면 재현율 문제입니다. 회고(`postmortem`)에서 "이 알림이 울렸는가 / 울렸는데 묻혔는가 / 울리지 않았는가" 셋 중 무엇이었는지 매번 기록하면 이 숫자가 자연히 쌓입니다.

## 9. 정리

알림 피로는 알림이 많아서 생기는 게 아니라, **사람을 깨우는 알림과 그렇지 않은 알림을 구분하지 않아서** 생깁니다.

- 알림의 비용은 사람의 주의입니다. 조치가 없는 알림은 지우는 쪽이 낫습니다
- 지우기 어려우면 **등급을 내립니다.** 페이지 → 티켓 → 대시보드
- 증상에 걸고, 지연시간은 스택의 한 지점에서만 페이지로 겁니다. 원인은 대시보드로 찾습니다
- 시끄러울 때 임계값을 올리거나 `for`를 늘리는 건 재현율을 버리는 것입니다. **소진율 + 긴 창·짧은 창 AND**로 바꿉니다
- 장애 한 번이 N개 알림이 되는 문제는 규칙이 아니라 그룹화·억제·라우팅으로 풉니다
- 런북을 쓸 수 없는 알림은 페이지가 아닙니다
- 교대당 페이지 수와 조치율을 재지 않으면 정리는 다시 무너집니다

정리의 성공 기준은 알림 수가 줄어든 게 아닙니다. **새벽에 울린 알림을 보고 바로 일어나게 되는 것**입니다.

## 10. 참고자료

- [Google SRE Book — Monitoring Distributed Systems (증상 대 원인)](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Google SRE Book — Practical Alerting (페이지·티켓·대시보드 구분, 단일 머신 알림)](https://sre.google/sre-book/practical-alerting/)
- [Google SRE Book — Being On-Call (교대당 인시던트 상한)](https://sre.google/sre-book/being-on-call/)
- [Google SRE Workbook — Alerting on SLOs (네 평가축, 소진율, 멀티윈도 권장값)](https://sre.google/workbook/alerting-on-slos/)
- [Prometheus — Alerting best practices](https://prometheus.io/docs/practices/alerting/)
- [Prometheus — Alerting rules (`for`, `keep_firing_for`)](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Alertmanager — 개요 (grouping·inhibition·silence)](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [Alertmanager — Configuration (`group_wait`·`group_interval`·`repeat_interval`·`inhibit_rules`)](https://prometheus.io/docs/alerting/latest/configuration/)
- [Grafana Labs — 4th Annual Observability Survey (2026-03)](https://grafana.com/press/2026/03/18/grafana-labs-4th-annual-observability-survey-reveals-a-field-at-a-crossroads-ai-economics-complexity-and-the-enduring-power-of-open-source/)
- 관련 문서: `day54-golden-signals.md`, `day48-log-level.md`, `day42-structured-log-trace-id.md`, `day30-application-healthcheck.md`
