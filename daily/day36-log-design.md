# 장애 났을 때 필요한 로그는 무엇인가

> 이 문서가 답할 질문: **장애 대응 중에 실제로 쓸모가 있었던 로그와, 쌓여만 있던 로그는 무엇이 달랐는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). "로그는 있는데 원인을 못 찾는다"는 증상에서 출발해, 여러 출처가 공통으로 지목하는 원인과 해법을 찾는 관점으로 조사했습니다.
>
> 기준: Spring Boot 4.1 · SLF4J 2.x (2026년 9월 확인). 로깅 프레임워크를 왜 쓰는지는 `day25-logging-basics.md`에서 다뤘습니다. 이 문서는 그 위에서 **무엇을 남길 것인가**만 다룹니다. 로그 레벨 기준선, 수집 파이프라인, 트레이스 ID 전파 구현은 범위 밖입니다.

## 1. 핵심 개념 — 로그 설계는 "무엇을 찍을까"가 아니라 "무엇으로 검색할까"입니다

로그를 남기는 시점과 읽는 시점은 다릅니다. 그래서 설계의 기준점도 쓰는 쪽이 아니라 **읽는 쪽**에 있어야 합니다.

장애 대응을 시작할 때 손에 쥐고 있는 건 보통 세 가지뿐입니다. **증상**(에러율이 올랐다, CS가 들어왔다), **대략적인 시각**, 그리고 운이 좋으면 **식별자 하나**(주문번호, 사용자 ID). 이 셋에서 출발해 도달할 수 없는 기록은, 아무리 자세해도 그날 아무도 못 찾습니다.

> 새벽 2시에 결제 실패 알림이 옵니다. 로그를 엽니다. `ERROR 결제 실패`가 4천 줄 있습니다. 어느 주문인지, 어떤 결제 수단인지, 결제사가 뭐라고 답했는지, 4천 건이 한 원인인지 네 가지 원인인지 **한 줄도 알려주지 않습니다.** 그런데 바로 옆에는 `INFO 주문 조회 요청 들어옴`이 200만 줄 찍혀 있어서, 검색은 검색대로 느립니다. 로그가 없어서가 아니라 **읽는 사람의 질문에 답하도록 설계되지 않아서** 대응이 늦어집니다.

로그 설계는 문장을 예쁘게 쓰는 일이 아닙니다. 장애 중에 던질 질문을 미리 정하고, **그 질문의 검색 키를 평소에 심어두는 일**입니다.

## 2. 구조 — 장애 대응이 로그에 던지는 네 개의 질문

실제 대응에서 나오는 질문은 대체로 이 넷으로 수렴합니다. 로그의 필드 목록은 여기서 역산해서 나옵니다.

### 2-1. 어디까지 갔나 — 경계

요청이 들어오긴 했는가, 외부 API를 부르긴 했는가, DB에 커밋은 됐는가. 실패 지점이 **내 앞인지 내 안인지 내 뒤인지**를 가르는 질문입니다.

그래서 로그는 함수마다가 아니라 **경계마다** 남깁니다. 요청 수신, 외부 호출, 메시지 발행, 커밋. 경계를 넘을 때는 들어간 기록과 나온 기록이 짝을 이뤄야 합니다. 나간 기록이 없으면 그게 바로 "여기서 멈췄다"는 정보입니다.

### 2-2. 무엇을 가지고 그랬나 — 입력과 결정 근거

같은 코드가 어떤 요청에서는 되고 어떤 요청에서는 안 됩니다. 차이는 입력에 있습니다. 식별자와, **분기를 결정한 값**을 남깁니다.

`할인 적용됨`이 아니라 `할인 적용 orderId=10293 couponId=88 rate=0.1 reason=FIRST_ORDER`입니다. 결과만 있는 로그는 "그래서 왜?"에서 멈추지만, 근거가 있는 로그는 거기서 다음 질문으로 넘어갑니다.

### 2-3. 왜 실패했나 — 원인 체인

실패 로그의 가치는 메시지가 아니라 **원인**에 있습니다. OpenTelemetry 시맨틱 규약은 예외를 로그에 기록할 때 `exception.type`, `exception.message`, `exception.stacktrace` 세 속성을 정의합니다. 앞의 두 개는 하나가 없으면 다른 하나가 필수이고, 스택트레이스는 권장입니다([OTel — Exceptions in logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/)).

같은 문서가 심각도 기준도 정해 둡니다. **애플리케이션이 처리할 것으로 예상한 예외는 WARN, 처리되지 않은 예외는 ERROR**입니다. 이 구분이 중요한 이유는, 둘을 섞으면 ERROR 개수가 알림 기준으로 못 쓰게 되기 때문입니다.

외부 호출 실패라면 예외 타입만으로는 부족합니다. 상대가 뭐라고 답했는지 — 상태 코드, 에러 코드, 응답 본문의 식별 가능한 일부 — 가 있어야 "우리 문제인가 저쪽 문제인가"가 갈립니다.

### 2-4. 나만 그런가 — 범위

장애의 크기를 재는 질문입니다. 특정 인스턴스만인가, 특정 버전만인가, 특정 고객만인가, 특정 엔드포인트만인가.

이건 메시지에 쓸 내용이 아니라 **모든 로그에 자동으로 붙어야 하는 공통 필드**입니다. 서비스 이름, 버전, 인스턴스, 환경. Spring Boot 4.1의 구조화 로깅에서는 `logging.structured.json.add`로 고정 필드를 전체 로그에 붙일 수 있습니다([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)).

```yaml
logging:
  structured:
    format:
      console: ecs
    json:
      add:
        service.version: "${APP_VERSION:unknown}"
        deployment.environment: "${APP_ENV:local}"
```

## 3. 흐름

### 3-1. 세 층으로 나눠 남깁니다

네 질문에 답하려고 모든 메서드에 로그를 박으면 200만 줄이 됩니다. 실제로 필요한 건 층이 다른 세 종류입니다.

| 층 | 언제 | 무엇을 | 양 |
|---|---|---|---|
| 요청 요약 | 요청이 끝날 때 **항상** | 요청 식별자·엔드포인트·상태·소요시간·주요 입력 | 요청당 1줄 |
| 상태 전이 | 도메인 상태가 바뀔 때 | 무엇이 어떤 상태에서 어떤 상태로, 왜 | 드물게 |
| 실패 | 예외·외부 실패 | 원인 체인 + 그때의 입력 | 실패할 때만 |

첫 번째 층이 이 설계의 중심입니다. Stripe는 이걸 **canonical log line**이라고 부릅니다. 요청 하나가 끝날 때 그 요청의 핵심 정보를 **한 줄에 모아서** 찍는 방식입니다. 정보가 여러 줄에 흩어져 있으면 아무리 좋은 검색 시스템이 있어도 조합하는 데 시간이 걸린다는 게 이유입니다([Stripe — Canonical log lines](https://stripe.com/blog/canonical-log-lines)).

한 줄로 모으면 성질이 바뀝니다. 흩어진 로그는 `grep`한 다음 사람이 눈으로 맞춰야 하지만, 한 줄에 모인 로그는 **그 자체가 질의 가능한 레코드**가 됩니다. "지난 10분간 500으로 끝난 요청을 고객별로 묶어줘"가 한 번의 질의로 끝납니다.

### 3-2. 코드로 보는 구성

요청 요약 한 줄과, 모든 로그에 붙을 요청 식별자를 필터에서 함께 처리합니다.

```java
package com.example.order.logging;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

@Component
public class RequestSummaryFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger("request.summary");

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String requestId = UUID.randomUUID().toString();
        MDC.put("requestId", requestId);
        long startedAt = System.nanoTime();
        try {
            chain.doFilter(request, response);
        } finally {
            // requestId 등 MDC에 담긴 값은 구조화 출력에 자동으로 포함됩니다
            log.atInfo()
               .addKeyValue("method", request.getMethod())
               .addKeyValue("path", request.getRequestURI())
               .addKeyValue("status", response.getStatus())
               .addKeyValue("durationMs", (System.nanoTime() - startedAt) / 1_000_000)
               .setMessage("request.completed")
               .log();
            MDC.clear();
        }
    }
}
```

세 가지가 의도적입니다.

1. **`finally`에서 찍습니다.** 예외로 빠져나가는 요청이야말로 요약이 필요한 요청입니다. `try` 안에서 찍으면 정작 장애 때 안 남습니다.
2. **`addKeyValue`로 넘깁니다.** SLF4J 2.x의 fluent API이고, Spring Boot의 구조화 로깅은 이 키-값과 MDC의 항목을 JSON 필드로 그대로 내보냅니다([Spring Boot — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)). 문자열로 이어붙이면 나중에 파싱해야 합니다. 텍스트 패턴으로 출력할 때 MDC 값을 같이 보려면 패턴에 `%X{requestId}`를 넣습니다.
3. **`MDC.clear()`를 `finally`에 둡니다.** 이유는 §6-2에 있습니다.

실패 지점에서는 요약이 아니라 원인을 남깁니다.

```java
try {
    PaymentResult result = paymentClient.approve(command);
    log.info("결제 승인 orderId={} pgTid={} amount={}",
             order.getId(), result.tid(), order.getAmount());
} catch (PaymentDeclinedException e) {
    // 예상한 실패 — 상대가 준 판단 근거를 남긴다
    log.warn("결제 거절 orderId={} amount={} pgCode={} pgMessage={}",
             order.getId(), order.getAmount(), e.getCode(), e.getMessage());
    throw e;
} catch (PaymentGatewayTimeoutException e) {
    // 예상 못 한 실패 — 원인 체인 전체를 남긴다
    log.error("결제 게이트웨이 응답 없음 orderId={} amount={} elapsedMs={}",
              order.getId(), order.getAmount(), e.getElapsedMillis(), e);
    throw e;
}
```

예외 객체는 **마지막 인자**로 넘깁니다. `{}` 개수보다 인자가 하나 많으면 SLF4J가 그것을 스택트레이스로 처리합니다. 스택트레이스를 읽는 순서는 `day31-stacktrace-reading.md`에서 다룹니다.

### 3-3. 장애가 났을 때 로그를 읽는 순서

설계가 맞는지 확인하는 가장 빠른 방법은 이 순서를 실제로 따라가 보는 것입니다.

```text
1. 시각 창 좁히기      status>=500 인 request.completed 를 시간별로 집계
2. 범위 판정           같은 결과를 path / version / instance 로 다시 묶기
3. 대표 사례 하나 고르기  실패한 요청의 requestId 를 하나 확보
4. 그 요청만 재생하기    requestId 로 전체 로그를 시간순 정렬
5. 원인 확정           마지막 경계 로그 + 그 직후 실패 로그의 예외 체인
```

1번과 2번이 요약 한 줄로 끝나고, 4번이 요청 식별자로 끝납니다. **이 두 개가 없으면 3번에서 막힙니다.** 로그를 늘려서는 해결되지 않고, 식별자를 심어야 해결됩니다.

## 4. 무엇을 남기지 않을 것인가

로그 설계에서 더 어려운 쪽은 빼는 결정입니다. 공짜가 아니기 때문입니다.

### 4-1. 로그는 바이트당 돈이고, 노이즈당 시간입니다

보관 비용도 비용이지만 더 비싼 건 검색 시간입니다. 성공 경로의 `조회 요청 들어옴` 같은 줄은 정상일 때만 대량으로 생기고 장애 때는 아무것도 알려주지 않습니다. 그런데 보관 기간을 갉아먹어서, 사흘 전 장애를 보려고 할 때 정작 원인 로그가 이미 지워져 있게 만듭니다.

기준은 단순합니다. **그 줄만 따로 봤을 때 대응 중 판단이 하나라도 바뀌는가.** 안 바뀌면 요약 한 줄에 필드로 접어 넣거나 DEBUG로 내립니다.

### 4-2. 카디널리티가 높은 값은 로그로, 낮은 값은 메트릭으로

주문번호, 사용자 ID, 요청 ID처럼 값의 종류가 무한한 데이터는 로그가 감당할 수 있는 영역입니다. 반대로 "초당 에러 수" 같은 건 로그를 세어서 만들 게 아니라 메트릭으로 뽑아야 합니다. 알림은 메트릭이 울리고, **울린 다음 파고드는 건 로그**입니다.

### 4-3. 절대 남기면 안 되는 것

OWASP Logging Cheat Sheet는 로그에 직접 기록하면 안 되는 항목을 명시합니다. 세션 식별자, 액세스 토큰, 인증 비밀번호, DB 접속 문자열, 암호화 키, 카드·계좌 정보, 그리고 동의받지 않은 개인정보입니다([OWASP — Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)).

같은 문서가 각 로그 항목이 담아야 할 것을 **언제·어디서·누가·무엇을**로 정리하는데, §2의 네 질문과 거의 겹칩니다. 요청 객체를 통째로 찍으면 앞의 넷은 다 담기지만 금지 목록도 같이 담깁니다. **필드를 골라서 찍는 것**이 유일한 해법입니다.

## 5. 예제 — 같은 장애, 두 가지 로그

결제 API가 간헐적으로 실패하는 상황입니다.

### 5-1. 이런 로그 ❌

```java
public void pay(PayCommand command) {
    log.info("결제 시작");
    try {
        paymentClient.approve(command);
        log.info("결제 완료");
    } catch (Exception e) {
        log.error("결제 실패: " + e.getMessage());
        throw new PaymentException("결제에 실패했습니다");
    }
}
```

```text
2026-09-17T02:14:03.221Z ERROR c.e.p.PaymentService : 결제 실패: Read timed out
```

여기서 알 수 있는 건 "누군가의 결제가 타임아웃으로 실패했다"뿐입니다. 어느 주문인지 모르니 CS와 대조할 수 없고, 얼마짜리인지 모르니 영향도를 못 냅니다. `e.getMessage()`만 이어붙여서 원인 체인이 통째로 사라졌고, 새 예외를 던지면서 원래 예외를 `cause`로 넘기지도 않았습니다. `catch (Exception e)`로 묶어서 **예상한 거절과 예상 못 한 장애가 같은 줄로 나옵니다.**

### 5-2. 이렇게 ✔️

```java
public void pay(PayCommand command) {
    try {
        PaymentResult result = paymentClient.approve(command);
        log.atInfo()
           .addKeyValue("orderId", command.orderId())
           .addKeyValue("amount", command.amount())
           .addKeyValue("method", command.method())
           .addKeyValue("pgTid", result.tid())
           .setMessage("payment.approved")
           .log();
    } catch (PaymentDeclinedException e) {
        log.atWarn()
           .addKeyValue("orderId", command.orderId())
           .addKeyValue("amount", command.amount())
           .addKeyValue("pgCode", e.getCode())
           .setMessage("payment.declined")
           .log();
        throw e;
    } catch (PaymentGatewayException e) {
        log.atError()
           .addKeyValue("orderId", command.orderId())
           .addKeyValue("amount", command.amount())
           .addKeyValue("attempt", command.attempt())
           .setCause(e)
           .setMessage("payment.gateway_error")
           .log();
        throw new PaymentException("결제에 실패했습니다", e);
    }
}
```

바뀐 것은 네 가지입니다.

1. **메시지가 이벤트 이름입니다.** `payment.gateway_error`는 문장과 달리 값이 고정이라 집계 키로 쓸 수 있습니다. 한글 문장을 쓰더라도 문장 안에 변수를 섞지 않는 원칙은 같습니다.
2. **식별자와 금액이 필드로 남습니다.** `orderId`로 한 건을 추적하고, `amount` 합으로 영향 규모를 냅니다.
3. **거절은 WARN, 게이트웨이 장애는 ERROR입니다.** OTel 규약의 구분과 같고, 덕분에 ERROR 건수가 곧 "사람이 봐야 할 건수"가 됩니다.
4. **`setCause(e)`와 `new PaymentException(..., e)`로 원인 체인을 둘 다 유지합니다.** 감싸면서 원인을 빠뜨리는 게 원인 추적이 끊기는 가장 흔한 지점입니다.

## 6. 함정

### 6-1. 모든 계층이 같은 예외를 로그로 남깁니다

- **증상**: 실패 한 건인데 ERROR가 네 줄 찍힙니다. 스택트레이스가 거의 같고 조금씩 다릅니다. 에러 건수 기반 알림이 실제의 몇 배로 울립니다.
- **원인**: 계층마다 `catch` → `log.error` → `rethrow`를 하고, 마지막에 글로벌 예외 핸들러가 한 번 더 찍습니다.
- **해법**: **원인을 가장 잘 아는 한 곳에서만 남깁니다.** 보통 외부 호출·DB 같은 경계, 즉 실패 원인을 실제로 알고 있는 지점입니다(§3-2, §5-2가 그 자리입니다). 그 위 계층은 로그 대신 예외를 감싸면서 맥락을 넣고, 어디서도 안 남긴 예외만 `@ControllerAdvice`가 최종 안전망으로 ERROR에 남깁니다(응답 포맷은 `day03-api-error-format.md` 참고).

### 6-2. MDC가 비어 있거나, 남의 요청 값이 들어 있습니다

- **증상**: 비동기 처리나 `@Async` 작업의 로그에서 `requestId`가 사라집니다. 더 나쁜 경우, **다른 사용자의 ID가 붙은 채로** 로그가 남습니다.
- **원인**: MDC는 스레드 로컬입니다. Logback 문서는 자식 스레드가 부모의 MDC를 자동으로 물려받지 않으며, `Executors`로 스레드를 관리하면 복사가 항상 이뤄지지는 않는다고 명시합니다. 또 스레드를 재사용하는 서버에서는 **MDC에 잘못된 정보가 남을 수 있다**고 경고합니다([Logback — MDC](https://logback.qos.ch/manual/mdc.html)).
- **해법**: `put()`마다 대응하는 `remove()` 또는 `clear()`를 두되 반드시 `finally`에 둡니다. 스레드를 넘길 때는 제출 전에 `MDC.getCopyOfContextMap()`으로 복사해 작업 스레드에서 `MDC.setContextMap()`으로 심습니다.

### 6-3. 요약 로그가 정상 요청에만 남습니다

- **증상**: 에러율은 올라갔는데 요약 로그를 아무리 뒤져도 실패 요청이 안 보입니다.
- **원인**: 요약을 컨트롤러 끝이나 인터셉터의 `postHandle`에서 찍었습니다. 예외가 나면 그 지점에 도달하지 못합니다. 필터 순서가 뒤라서 앞단 필터(인증 등)에서 끊긴 요청도 안 남습니다.
- **해법**: 요약은 `finally`에서, 그리고 **필터 체인의 가장 바깥**에서 찍습니다. 인증 실패로 401이 난 요청도 요약에는 남아야 합니다.

### 6-4. 실패가 폭주하면서 원인 로그가 밀려납니다

- **증상**: 장애 직후 로그가 폭증했고, 정작 **처음 몇 분**의 로그가 검색되지 않거나 유실됩니다.
- **원인**: 재시도 루프 안에서 시도마다 ERROR를 찍습니다. 초당 수만 줄이 나가면서 수집 파이프라인의 처리량 한계에 걸리거나, 보관 용량이 먼저 차서 오래된 쪽부터 사라집니다. 비동기 appender를 쓰면 큐가 넘치면서 조용히 버려지기도 합니다(`day25-logging-basics.md` 참고).
- **해법**: 재시도는 **마지막 시도에서만 ERROR**로 남기고 중간 시도는 DEBUG로 내립니다. 장애 시점의 첫 로그가 가장 비싸다는 전제로, 같은 원인이 반복될 때 요약해서 남기는 방식을 씁니다.

### 6-5. 시각이 서로 안 맞습니다

- **증상**: 앱 로그와 프록시 로그를 나란히 놓으면 순서가 뒤집혀 보입니다. 로그 도구에서 시간 범위를 잡으면 아무것도 안 나옵니다.
- **원인**: 컨테이너 기본 타임존은 대개 UTC인데 어디선가 로컬 시각으로 찍습니다. 타임존 표기가 없는 포맷이면 되돌릴 방법도 없습니다.
- **해법**: 오프셋을 포함한 ISO-8601로 통일합니다. 구조화 로깅 포맷(ECS 등)을 쓰면 `@timestamp`가 이 형식으로 나갑니다. 사람이 보기 좋은 변환은 저장할 때가 아니라 **볼 때** 합니다.

### 6-6. 마스킹을 수집기에서만 합니다

- **증상**: 로그 도구의 화면에는 마스킹돼 보이는데, 서버의 파일이나 컨테이너 표준 출력에는 원문이 그대로 있습니다.
- **원인**: 마스킹 규칙을 수집 파이프라인에만 걸었습니다. 애플리케이션이 이미 평문으로 뱉은 뒤라서, 파이프라인 이전 단계에는 전부 남습니다.
- **해법**: **찍기 전에** 거릅니다. 민감 필드를 가진 객체를 통째로 넘기지 않고, `toString()`에서 제외하며, 필요한 필드만 골라 남깁니다. 수집기 쪽 규칙은 마지막 방어선이지 1차 방어선이 아닙니다.

## 7. 정리

장애 때 쓸모 있던 로그의 공통점은 자세함이 아니었습니다. **읽는 사람의 질문에 검색 키로 답한다는 점**이었습니다.

- 요청 하나를 끝까지 이어 붙일 **식별자**가 있는가
- 요청당 한 줄, 집계와 범위 판정이 가능한 **요약**이 있는가
- 실패 로그에 결과 말고 **원인 체인과 그때의 입력**이 있는가
- 이 넷을 위해, 나머지를 **덜 남기기로** 했는가

마지막 항목이 제일 어렵고 제일 효과가 큽니다. 로그를 늘려서 관측성이 좋아지는 구간은 생각보다 빨리 끝납니다.

## 8. 참고자료

- [OWASP — Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [OpenTelemetry — Semantic conventions for exceptions in logs](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/)
- [OpenTelemetry — General log attributes](https://opentelemetry.io/docs/specs/semconv/general/logs/)
- [Stripe Engineering — Canonical log lines](https://stripe.com/blog/canonical-log-lines)
- [Spring Boot Reference — Logging](https://docs.spring.io/spring-boot/reference/features/logging.html)
- [Logback Manual — Mapped Diagnostic Context](https://logback.qos.ch/manual/mdc.html)
- 관련 문서: `day25-logging-basics.md`, `day31-stacktrace-reading.md`, `day03-api-error-format.md`
