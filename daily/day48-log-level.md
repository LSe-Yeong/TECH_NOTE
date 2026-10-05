# INFO와 DEBUG의 경계는 무엇이 정하는가

> 이 문서가 답할 질문: **어떤 기록을 INFO로 남기고 어떤 기록을 DEBUG로 내릴 것인가 — 그 경계는 무엇이 정하는가?**
>
> 분류: 선택형(A vs B). 두 레벨 중 하나를 고르는 문제라서, 여러 출처가 공통으로 드는 비교 기준과 트레이드오프를 찾는 관점으로 조사했습니다.
>
> 기준: Spring Boot 4.1 · Logback 1.5 · SLF4J 2.x (2026년 10월 확인). 로깅 프레임워크를 왜 쓰는지는 `day25-logging-basics.md`, 무엇을 남길지는 `day36-log-design.md`에서 다뤘습니다. 이 문서는 **남기기로 한 기록에 어떤 레벨을 붙이는가**만 다룹니다. 수집 파이프라인과 알림 설계는 범위 밖입니다.

## 1. 핵심 개념 — 레벨은 중요도 등급이 아니라 "평소에 켜둘 것인가"의 스위치입니다

레벨을 "얼마나 중요한가"로 고르면 기준이 사람마다 달라집니다. 내가 방금 디버깅한 코드는 나에게 제일 중요하니까요. 그래서 레벨 선택은 중요도가 아니라 **운영 중에 상시로 켜둘 수 있는 기록인가**로 갈라야 합니다.

Spring Boot는 기본적으로 ERROR·WARN·INFO만 출력하고 DEBUG와 TRACE는 끕니다([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)). 즉 레벨을 붙이는 행위는 사실상 **"이 줄을 프로덕션에서 볼 것인가"에 대한 투표**입니다.

> 레벨이 취향으로 정해진 코드베이스는 두 증상이 같이 옵니다. 하나는 INFO에 `사용자 조회 진입`, `파라미터 검증 통과` 같은 줄이 섞여서 하루 수백만 줄이 쌓이는 겁니다. 보관 기간이 짧아지고 검색이 느려집니다. 다른 하나는 정작 장애 때 필요한 **외부 결제사 응답 코드**가 DEBUG에 들어 있어서 프로덕션에서 안 보이는 겁니다. 로그를 적게 남긴 것도 많이 남긴 것도 아닌데, 양쪽 비용만 다 냅니다.

경계를 정하는 질문은 하나로 줄어듭니다. **이 줄이 없으면 장애 대응 중에 판단이 막히는가.** 막히면 INFO, 안 막히면 DEBUG입니다.

## 2. 구조 — 레벨은 등급이 아니라 순서입니다

### 2-1. 설정값은 임계값이고, 비교는 한 줄로 끝납니다

Logback은 레벨을 `TRACE < DEBUG < INFO < WARN < ERROR` 순서로 정의합니다. 그리고 출력 여부는 기본 선택 규칙 하나로 결정됩니다. **레벨 p의 요청은 해당 로거의 유효 레벨(effective level) q에 대해 p ≥ q일 때만 통과합니다**([Logback — Architecture](https://logback.qos.ch/manual/architecture.html)).

유효 레벨은 로거에 직접 설정한 값이 아닐 수 있습니다. 같은 문서가 정의하는 규칙은 이렇습니다. 로거 L의 유효 레벨은 **L 자신에서 시작해 루트 로거 방향으로 올라가면서 처음 만나는 null이 아닌 레벨**입니다. 로거 이름이 `com.example.order.PaymentService`라면 `com.example.order` → `com.example` → `com` → root 순으로 거슬러 올라갑니다.

여기서 실무 감각 하나가 나옵니다. 레벨은 **로거 단위로 켜고 끌 수 있고, 로거 이름은 패키지 구조를 따른다**는 점입니다. 그래서 "DEBUG를 켠다"는 결정은 전체가 아니라 특정 패키지에만 적용할 수 있습니다. 이게 §6의 트레이드오프를 완화하는 핵심 수단입니다.

### 2-2. 레벨 이름은 제각각이라 숫자로 비교합니다

여러 언어·프레임워크 로그를 한 저장소에 모으면 레벨 이름이 안 맞습니다. OpenTelemetry 로그 데이터 모델은 이 문제를 레벨당 4칸의 숫자 구간으로 해결합니다.

| SeverityText | SeverityNumber | 규약이 붙인 설명 |
|---|---:|---|
| TRACE | 1–4 | 세밀한 디버깅 이벤트. 기본 설정에서는 보통 비활성 |
| DEBUG | 5–8 | 디버깅 이벤트 |
| INFO | 9–12 | 정보성 이벤트. 어떤 일이 일어났음을 나타냄 |
| WARN | 13–16 | 오류는 아니지만 정보성 이벤트보다는 중요할 가능성이 높음 |
| ERROR | 17–20 | 오류 이벤트. 뭔가 잘못됨 |
| FATAL | 21–24 | 애플리케이션·시스템 크래시 같은 치명적 오류 |

대소 비교가 필요한 맥락에서는 텍스트가 아니라 `SeverityNumber`를 써야 한다고 규약이 명시합니다([OTel — Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)). TRACE 설명에 "기본 설정에서는 보통 비활성"이라는 문구가 규약 수준에 들어가 있다는 점을 보세요. **꺼진 상태가 정상인 레벨이 따로 있다**는 뜻입니다.

### 2-3. 꺼둔 로그의 비용은 거의 0입니다 — 단, 조건이 붙습니다

DEBUG를 많이 심어도 되는 근거가 여기 있습니다. SLF4J는 비활성 상태의 로그 요청 판정 비용이 **수 나노초 수준**이라고 설명합니다. 그리고 파라미터화된 형식과 문자열 연결 형식을 비교하면서, 로그가 꺼져 있을 때 **파라미터화 쪽이 최소 30배 빠르다**고 말합니다([SLF4J — FAQ](https://www.slf4j.org/faq.html)).

```java
// ❌ 꺼져 있어도 문자열 연결과 toString()이 매번 실행됩니다
log.debug("쿠폰 후보 = " + candidates + ", 사용자 = " + user);

// ✅ 꺼져 있으면 포매팅 자체가 일어나지 않습니다
log.debug("쿠폰 후보 {}건 userId={}", candidates.size(), user.getId());
```

`isDebugEnabled()`로 감싸는 패턴에 대해서도 같은 문서가 입장을 냅니다. 로거가 활성일 때 판정을 두 번 하게 되지만, 로거 판정 비용은 실제 로깅 비용의 **1% 미만**이라 무의미한 오버헤드라는 겁니다. 그래서 가드보다 파라미터화를 권합니다.

가드가 여전히 필요한 경우는 하나 남습니다. **인자를 만드는 것 자체가 비싼 경우**입니다.

```java
if (log.isDebugEnabled()) {
    // 직렬화 비용이 큰 인자는 가드 안에서 만듭니다
    log.debug("요청 스냅샷 {}", objectMapper.writeValueAsString(command));
}
```

## 3. 경계를 정하는 기준

### 3-1. 두 독자를 구분합니다

가장 실용적인 구분선은 "누가 읽는가"입니다.

- **INFO는 운영자가 읽습니다.** 운영자는 코드를 모릅니다. 시스템이 무슨 일을 했는지, 어떤 상태가 바뀌었는지만 압니다.
- **DEBUG는 그 코드를 아는 개발자가 읽습니다.** 분기를 어떻게 탔는지, 중간 계산값이 뭐였는지를 봅니다.

그래서 메서드 이름이나 내부 변수가 등장하는 줄은 거의 전부 DEBUG입니다. 반대로 **도메인 상태가 바뀐 사실**은 거의 전부 INFO입니다.

### 3-2. 세 문항으로 판정합니다

| 질문 | 예 | 아니오 |
|---|---|---|
| 프로덕션에서 이게 안 보이면 장애 원인 판정이 막히는가 | INFO | 다음 질문 |
| 상시로 켜둘 수 있는 양인가 (요청당 한 자리 수 이하) | 다음 질문 | DEBUG |
| 운영자가 코드를 몰라도 의미를 아는가 | INFO | DEBUG |

두 번째 문항이 1순위 탈락 사유입니다. "있으면 좋겠다"는 줄은 대부분 양에서 걸립니다. 요청당 수십 줄이 나오는 기록은 내용이 유용해도 INFO가 될 수 없습니다. 유용함과 상시 수집 가능성은 다른 축입니다.

### 3-3. 실제 배치

**INFO로 남기는 것**

- 애플리케이션 기동·종료, 활성 프로파일, 바인딩한 포트 (`day18-graceful-shutdown.md` 참고)
- 요청 요약 한 줄 — 엔드포인트·상태 코드·소요시간 (`day36-log-design.md`의 canonical log line)
- 도메인 상태 전이 — 주문 생성, 결제 승인, 환불 완료
- 외부 시스템 호출의 결과 식별자 — PG 거래번호, 메시지 발행 오프셋
- 스케줄러·배치의 시작과 끝, 처리 건수

**DEBUG로 내리는 것**

- 분기 근거와 중간 계산 — 적용 가능한 쿠폰 후보 목록, 할인 계산 단계
- 외부 요청·응답 본문 (마스킹 후)
- 캐시 적중·미스, 재시도 중간 시도
- 리포지토리 호출 파라미터, 생성된 SQL

**경계에서 자주 틀리는 것**

- 설정 로딩 상세 → DEBUG. 단 **최종 적용값 요약**은 INFO (`day06-env-variable.md` 참고)
- 재시도 → 중간 시도는 DEBUG, **최종 실패**는 WARN 또는 ERROR
- 입력 검증 실패 → 호출자 잘못이므로 ERROR가 아닙니다. 응답 코드로 이미 드러나니 DEBUG, 급증을 봐야 한다면 메트릭

### 3-4. 위쪽 경계도 같은 기준입니다

INFO 위의 두 레벨은 **사람의 행동**으로 갈립니다. WARN은 시스템이 문제를 흡수하고 서비스를 계속한 경우, ERROR는 사람이 개입해야 하는 실패입니다. OpenTelemetry 예외 규약도 같은 선을 긋습니다. 애플리케이션이 처리할 것으로 예상한 예외는 WARN, 처리되지 않은 예외는 ERROR입니다([OTel — Exceptions in logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/)).

이 선이 중요한 이유는 ERROR 건수를 알림 기준으로 쓸 수 있는지가 여기서 결정되기 때문입니다. 흡수된 실패를 ERROR로 올리면 ERROR 수가 "사람이 봐야 할 건수"와 무관해집니다(`day36-log-design.md`).

## 4. 흐름

### 4-1. 코드로 보는 경계

같은 메서드 안에서 두 독자를 나눕니다.

```java
package com.example.order.payment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.List;

@Service
public class PaymentService {

    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);

    private final PaymentGatewayClient gatewayClient;
    private final CouponFinder couponFinder;

    public PaymentService(PaymentGatewayClient gatewayClient, CouponFinder couponFinder) {
        this.gatewayClient = gatewayClient;
        this.couponFinder = couponFinder;
    }

    @Transactional
    public PaymentResult pay(PayCommand command) {
        List<Coupon> candidates = couponFinder.findApplicable(command.userId(), command.amount());
        // 개발자용 — 왜 이 쿠폰이 골라졌는지는 코드를 아는 사람만 필요합니다
        log.debug("쿠폰 후보 {}건 userId={} amount={}",
                  candidates.size(), command.userId(), command.amount());

        Coupon chosen = candidates.stream().max(Comparator.comparing(Coupon::discount)).orElse(null);
        log.debug("쿠폰 선택 couponId={} rule={}",
                  chosen == null ? "none" : chosen.getId(), "MAX_DISCOUNT");

        PaymentResult result = gatewayClient.approve(command, chosen);

        // 운영자용 — 결제가 승인됐다는 사실과 추적 가능한 식별자
        log.atInfo()
           .addKeyValue("orderId", command.orderId())
           .addKeyValue("amount", result.approvedAmount())
           .addKeyValue("couponId", chosen == null ? null : chosen.getId())
           .addKeyValue("pgTid", result.tid())
           .setMessage("payment.approved")
           .log();

        return result;
    }
}
```

쿠폰 후보가 50건이면 DEBUG 줄은 금액까지 포함해 한 줄로 유지됩니다. 목록 전체를 찍고 싶으면 §2-3의 가드 안에 넣습니다. INFO는 **결과 한 줄**만 남습니다.

### 4-2. 설정으로 보는 경계

경계는 코드에만 있지 않습니다. 내 코드와 라이브러리의 기준선을 다르게 둡니다.

```yaml
# application.yml — 프로덕션 기준선
logging:
  level:
    root: info
    com.example.order: info
    org.hibernate.SQL: warn      # 평소엔 끄고, 필요할 때만 올립니다
    org.apache.http: warn        # 라이브러리는 한 칸 위로
  group:
    payment: "com.example.order.payment,com.example.order.settlement"
```

Spring Boot는 여러 로거를 한 이름으로 묶는 **로그 그룹**을 제공하고, `web`과 `sql`은 미리 정의돼 있습니다. `logging.level.sql=debug` 한 줄이 `org.springframework.jdbc.core`와 `org.hibernate.SQL`을 함께 올립니다([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)).

라이브러리를 한 칸 위로 올리는 이유는 품질 문제가 아니라 **양**입니다. 내 코드의 INFO는 요청당 몇 줄이지만, HTTP 클라이언트나 커넥션 풀의 INFO는 내가 통제할 수 없는 빈도로 나옵니다.

### 4-3. 장애 중에 DEBUG를 켜는 절차

여기가 이 주제의 실전 가치입니다. 레벨 경계를 제대로 그어 뒀다면 **재배포 없이** 필요한 로거만 올릴 수 있습니다. Actuator의 `loggers` 엔드포인트가 그 창구입니다.

```bash
# 1. 현재 상태 확인 — configuredLevel이 null이면 상속받고 있다는 뜻입니다
curl -s http://localhost:8080/actuator/loggers/com.example.order.payment

# 2. 해당 패키지만 DEBUG로 (전체가 아닙니다)
curl -s -X POST http://localhost:8080/actuator/loggers/com.example.order.payment \
     -H 'Content-Type: application/json' \
     -d '{"configuredLevel":"debug"}'

# 3. 조사 끝났으면 빈 객체로 원복 — 상속 상태로 되돌아갑니다
curl -s -X POST http://localhost:8080/actuator/loggers/com.example.order.payment \
     -H 'Content-Type: application/json' \
     -d '{}'
```

`configuredLevel`은 그 로거에 직접 설정된 값, `effectiveLevel`은 §2-1의 상속 규칙을 거친 실제 적용값입니다. 원복은 레벨을 `info`로 다시 쓰는 게 아니라 **빈 JSON `{}`을 보내 설정을 지우는 것**입니다([Spring Boot — Loggers 엔드포인트](https://docs.spring.io/spring-boot/api/rest/actuator/loggers.html)). `info`로 덮어쓰면 나중에 기준선을 바꿔도 이 로거만 안 따라옵니다.

이 엔드포인트는 쓰기 작업이므로 아무에게나 열면 안 됩니다. 노출 설정과 인증은 별도로 잠가야 합니다.

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,loggers
```

## 5. 예제 — 같은 메서드, 다른 경계

### 5-1. 레벨이 취향으로 붙은 코드 ❌

```java
@Transactional
public void cancel(long orderId, String reason) {
    log.info("cancel 진입 orderId={}", orderId);
    Order order = orderRepository.findById(orderId).orElseThrow();
    log.info("주문 조회 완료 {}", order);                 // 엔티티 전체
    if (!order.isCancellable()) {
        log.error("취소 불가 상태 orderId={}", orderId);    // 호출자 잘못인데 ERROR
        throw new IllegalStateException("취소 불가");
    }
    for (OrderLine line : order.getLines()) {
        log.info("재고 복구 sku={} qty={}", line.sku(), line.qty());  // 라인 수만큼
    }
    order.cancel(reason);
    log.debug("주문 취소 완료 orderId={}", orderId);        // 정작 이게 DEBUG
}
```

문제가 네 개 겹쳐 있습니다. 진입 로그와 라인별 로그가 INFO라서 **주문 하나에 INFO가 10줄 넘게** 나갑니다. 엔티티를 그대로 찍어서 개인정보가 섞일 수 있고 `day14-dto-vs-entity.md`의 경계도 무너집니다. 취소 불가는 정상 흐름의 거절인데 ERROR라서 알림 기준을 오염시킵니다. 그리고 **정말 남아야 할 상태 전이만 DEBUG**라서 프로덕션에서는 "주문이 취소됐다"는 사실 자체가 안 보입니다.

### 5-2. 경계를 그은 코드 ✔️

```java
@Transactional
public void cancel(long orderId, String reason) {
    Order order = orderRepository.findById(orderId).orElseThrow();
    log.debug("취소 검증 orderId={} status={} lines={}",
              orderId, order.getStatus(), order.getLines().size());

    if (!order.isCancellable()) {
        // 거절은 정상 흐름입니다. 급증 여부는 메트릭으로 봅니다
        log.debug("취소 거절 orderId={} status={}", orderId, order.getStatus());
        throw new OrderNotCancellableException(orderId, order.getStatus());
    }

    order.cancel(reason);
    inventoryRestorer.restore(order);   // 라인별 로그는 이 안에서 DEBUG로

    log.atInfo()
       .addKeyValue("orderId", orderId)
       .addKeyValue("reasonCode", reason)
       .addKeyValue("restoredLines", order.getLines().size())
       .setMessage("order.cancelled")
       .log();
}
```

INFO가 **주문당 정확히 한 줄**로 줄고, 그 한 줄이 "무엇이 어떻게 바뀌었는가"에 답합니다. 라인별 상세는 DEBUG로 내려가 필요할 때 §4-3으로 켭니다. 메시지를 `order.cancelled` 같은 고정 문자열로 둔 이유는 집계 키로 쓰기 위해서입니다.

## 6. 트레이드오프 — DEBUG를 켜는 비용과 범위를 좁히는 방법

DEBUG는 공짜로 켤 수 있는 게 아닙니다. 비용은 세 갈래입니다.

1. **I/O와 수집 비용** — 디스크 쓰기와 수집 파이프라인 처리량. 장애 중에 올리면 이미 부하가 걸린 시스템에 더 얹습니다.
2. **보관 기간 침식** — 용량이 고정이라면 DEBUG가 차지한 만큼 과거 로그가 먼저 지워집니다.
3. **노출** — DEBUG에는 요청 본문이나 SQL 파라미터가 들어 있기 쉽습니다. 켜는 순간 민감정보가 평문으로 나갈 수 있습니다.

그래서 "DEBUG를 켠다"를 전역 결정으로 두지 않습니다. 범위를 좁히는 축이 세 개 있습니다.

- **로거 이름으로 좁히기** — §4-3처럼 패키지 하나만 올립니다. 가장 먼저 쓸 수단입니다.
- **시간으로 좁히기** — 올리고, 사례 몇 건을 확보하고, 바로 내립니다. 켜 놓은 채 잊는 것이 실제로 가장 흔한 사고입니다.
- **대상으로 좁히기** — Logback의 `TurboFilter`는 LoggingEvent 객체가 만들어지기 전에 동작하며, 그중 `MDCFilter`는 MDC의 특정 키·값이 일치할 때만 통과시킵니다([Logback — Filters](https://logback.qos.ch/manual/filters.html)).

```xml
<!-- 특정 사용자의 요청에서만 통과시킵니다. MDC에 값을 심는 쪽은 day42 참고 -->
<turboFilter class="ch.qos.logback.classic.turbo.MDCFilter">
  <MDCKey>username</MDCKey>
  <Value>sebastien</Value>
  <OnMatch>ACCEPT</OnMatch>
</turboFilter>
```

같은 문서가 MDC 키와 레벨 임계값을 연결하는 `DynamicThresholdFilter`도 소개합니다. <!-- TODO: 확인 필요 — DynamicThresholdFilter의 정확한 설정 요소(MDCKey/DefaultThreshold/MDCValueLevelPair)는 공식 문서에 예시가 없어 검증하지 못했습니다. 쓰기 전에 소스나 릴리스 노트로 확인하세요. -->

반복 로그를 줄이는 `DuplicateMessageFilter`도 있습니다. 같은 메시지가 일정 횟수를 넘으면 버리고, 기본 허용 반복은 5회, 캐시 크기는 100입니다. 다만 이 필터는 **기본 선택 규칙보다 먼저** 평가되므로 레벨과 무관하게 작동한다는 점을 알고 써야 합니다.

## 7. 함정

### 7-1. DEBUG를 켰는데 아무것도 안 나옵니다

- **증상**: `logging.level.com.example=debug`를 넣었는데 로그가 그대로입니다. 또는 Actuator로 올렸는데 변화가 없습니다.
- **원인**: 로거 레벨과 **appender 레벨**은 다른 관문입니다. appender에 `ThresholdFilter`가 INFO로 걸려 있으면 로거를 DEBUG로 올려도 appender에서 막힙니다. 또는 올린 로거 이름이 실제 로거의 조상이 아닙니다. 클래스가 `com.example.order...`인데 `com.example.api`를 올린 식입니다.
- **해법**: `/actuator/loggers/<이름>`으로 `effectiveLevel`을 먼저 확인합니다. DEBUG로 보이는데도 안 나오면 범인은 appender 쪽 필터입니다. 로거 이름은 추측하지 말고 기존 로그 한 줄의 로거 필드를 그대로 복사해 씁니다.

### 7-2. 환경변수로 클래스 하나만 올리려는데 안 됩니다

- **증상**: `LOGGING_LEVEL_COM_EXAMPLE_ORDER_PAYMENTSERVICE=DEBUG`가 무시됩니다.
- **원인**: Spring Boot 문서가 명시합니다. 완화된 바인딩(relaxed binding)이 환경변수 이름을 소문자로 변환하기 때문에 **클래스 단위 지정은 환경변수로 지원되지 않습니다**([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)). 패키지는 되지만 클래스는 안 됩니다.
- **해법**: 패키지 단위로 올리거나, 같은 문서가 안내하는 대로 `SPRING_APPLICATION_JSON`을 씁니다. 운영 중이라면 §4-3의 Actuator가 더 빠릅니다.

### 7-3. `--debug`를 줬는데 내 코드 로그가 안 나옵니다

- **증상**: `java -jar app.jar --debug`로 띄웠더니 Tomcat과 Hibernate 로그만 쏟아집니다.
- **원인**: `--debug`는 전체 로거를 DEBUG로 만드는 스위치가 아닙니다. 내장 컨테이너·Hibernate·Spring Boot 등 **선별된 코어 로거만** DEBUG로 올립니다(같은 문서).
- **해법**: 내 패키지는 `logging.level.com.example=debug`로 따로 지정합니다. 그리고 `--debug`를 프로덕션 조사 수단으로 쓰지 않습니다. 범위를 좁히는 수단이 아니라 넓히는 수단입니다.

### 7-4. 레벨만 고치면 자동 반영될 줄 알았는데 에러가 납니다

- **증상**: `logback-spring.xml`에 `scan="true"`를 넣고 파일을 수정했더니 `no applicable action for [springProfile]` 같은 에러가 뜹니다.
- **원인**: Spring Boot 문서가 명확히 제한을 둡니다. `<springProfile>`·`<springProperty>` 확장은 **Logback의 설정 스캔과 함께 쓸 수 없습니다**(같은 문서). 확장을 쓰면서 자동 재적용까지 기대할 수 없습니다.
- **해법**: 둘 중 하나를 고릅니다. 확장을 쓰고 레벨 변경은 Actuator로 하거나, 스캔이 꼭 필요하면 확장을 포기하고 `logging.config`로 순수 Logback 설정을 지정합니다. 참고로 `logback.xml`은 너무 일찍 로딩돼서 애초에 확장을 쓸 수 없습니다.

### 7-5. 꺼둔 DEBUG가 CPU를 먹습니다

- **증상**: DEBUG는 꺼져 있는데 프로파일러에 `toString()`과 `StringBuilder.append`가 올라옵니다.
- **원인**: §2-3의 문자열 연결 형식입니다. 레벨 판정 전에 인자가 이미 만들어집니다. 루프 안이면 호출 횟수만큼 반복됩니다.
- **해법**: 전부 `{}` 파라미터화로 바꿉니다. 인자 생성 자체가 비싼 경우에만 `isDebugEnabled()` 가드를 씁니다. 반대로 **가드를 남발하면** 코드가 읽기 어려워지고 얻는 게 1% 미만입니다(SLF4J FAQ).

### 7-6. DEBUG를 켜자 장애가 더 커졌습니다

- **증상**: 원인을 찾으려고 SQL 로그를 켰더니 응답시간이 더 늘고 디스크가 찼습니다.
- **원인**: `org.hibernate.SQL`이나 HTTP 클라이언트 DEBUG는 **요청당 수십~수백 줄**을 만듭니다. 이미 부하가 걸린 상태에서 동기 appender로 디스크에 쓰면 요청 스레드가 I/O를 기다립니다.
- **해법**: 범위를 패키지 하나로 좁히고, 켠 즉시 시계를 봅니다. 사례 몇 건을 확보하면 바로 내립니다. 상시로 봐야 하는 정보라면 DEBUG 상주가 아니라 **INFO 요약 한 줄로 설계를 바꾸는 것**이 답입니다(`day36-log-design.md`). 덧붙여 민감정보가 섞일 수 있으니 켜는 범위에 요청 본문 로깅이 포함되는지 먼저 확인합니다.

## 8. 정리

INFO와 DEBUG의 경계는 중요도가 아니라 **상시 가동 가능성**이 정합니다.

- INFO는 운영자의 질문에 답하고, 요청당 한 자리 수로 유지됩니다
- DEBUG는 코드를 아는 사람의 질문에 답하고, 꺼진 상태가 정상입니다
- 꺼둔 DEBUG는 수 나노초라서 많이 심어도 됩니다 — **파라미터화했을 때만**
- 그래서 조사 수단은 "로그를 추가하고 배포하기"가 아니라 "로거 범위를 좁혀 올리고 바로 내리기"가 됩니다

마지막 줄이 이 경계를 긋는 실제 보상입니다. 레벨을 제대로 붙여 두면 장애 중에 재배포가 필요 없어집니다.

## 9. 참고자료

- [Spring Boot Reference — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)
- [Spring Boot Actuator API — Loggers](https://docs.spring.io/spring-boot/api/rest/actuator/loggers.html)
- [Logback Manual — Architecture (유효 레벨·기본 선택 규칙)](https://logback.qos.ch/manual/architecture.html)
- [Logback Manual — Filters (TurboFilter·MDCFilter)](https://logback.qos.ch/manual/filters.html)
- [SLF4J — FAQ (파라미터화 로깅과 비용)](https://www.slf4j.org/faq.html)
- [OpenTelemetry — Logs Data Model (SeverityNumber)](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OpenTelemetry — Semantic conventions for exceptions in logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/)
- 관련 문서: `day25-logging-basics.md`, `day36-log-design.md`, `day42-structured-log-trace-id.md`, `day06-env-variable.md`
