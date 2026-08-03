# 에러 응답 포맷을 통일해야 하는 이유

> 이 문서가 답할 질문: **API가 실패했을 때 돌려주는 응답 본문의 형태를 왜 하나로 맞춰야 하고, 그 안에 무엇을 담아야 하는가?**
>
> 기준: RFC 9457(2023년 7월) / Spring Framework 7.0.x / Spring Boot 4.1.0. `ProblemDetail`은 Spring Framework 6.0, Spring Boot 3.0부터 있습니다.

## 1. 핵심 개념

에러 응답 포맷은 **실패를 어떻게 표현할지에 대한 서버와 클라이언트 사이의 계약**입니다. 성공 응답의 스키마는 다들 신경 써서 설계합니다. 실패 응답은 그러지 않습니다. 그래서 대부분의 프로젝트에서 에러 포맷은 설계된 적이 없고, 그때그때 생겨납니다.

한 서비스 안에서 이렇게 갈라집니다.

```json
// 컨트롤러가 직접 만든 것
{"success": false, "message": "재고가 부족합니다"}

// @RestControllerAdvice가 만든 것
{"code": "E4091", "msg": "out of stock", "data": null}

// Spring Boot의 /error가 만든 것
{"timestamp": "2026-08-03T04:11:22.415+00:00", "status": 500, "error": "Internal Server Error", "path": "/orders"}

// 앞단 게이트웨이가 만든 것
<html><head><title>502 Bad Gateway</title></head>...
```

> 이 네 가지가 **같은 서버의 같은 엔드포인트에서 상황에 따라 번갈아 나옵니다.** 클라이언트는 결국 네 벌의 방어 코드를 쓰거나, 더 흔하게는 `message` 문자열을 `contains`로 뒤집니다. 그 순간 에러 문구는 UI 텍스트가 아니라 API 스펙이 됩니다. 오타를 고쳤을 뿐인데 결제 화면이 멈추는 장애가 여기서 나옵니다.

포맷 통일은 "보기 좋게 정리하자"는 문제가 아닙니다. **클라이언트가 무엇을 보고 분기할지 정해주는 문제**입니다.

## 2. 구조 — RFC 9457이 정한 다섯 칸

RFC 9457 `Problem Details for HTTP APIs`는 RFC 7807을 대체한 표준입니다. 미디어 타입은 `application/problem+json`, `application/problem+xml`이고 본문 멤버는 다섯 개입니다. ([RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html))

| 멤버 | 정의 | 실무에서 놓치는 점 |
|---|---|---|
| `type` | 문제 **종류**를 식별하는 URI. 없으면 `about:blank` | 클라이언트가 분기해야 하는 값. 한 번 정하면 못 바꿉니다 |
| `title` | 사람이 읽는 짧은 요약 | 같은 `type`이면 **항상 같은 문구**여야 합니다(번역 제외) |
| `status` | HTTP 상태 코드 숫자 | **참고용입니다.** 실제 응답의 상태 코드가 우선합니다 |
| `detail` | 이번 발생 건에 대한 설명 | 디버깅 정보를 담는 칸이 아닙니다. 사용자가 고칠 수 있게 돕는 칸입니다 |
| `instance` | 이 **발생 건 하나**를 식별하는 URI | `type`이 "종류", `instance`가 "사건 번호"입니다 |

여기서 자주 헷갈리는 세 가지를 짚습니다.

**`type`이 URL일 필요는 없습니다.** URI는 식별자이지 주소가 아닙니다. 열어볼 수 있으면 좋지만 필수가 아닙니다. RFC는 IANA에 문제 유형 레지스트리를 새로 만들었고, 최초 등록된 항목은 `about:blank` 하나입니다. `about:blank`는 "HTTP 상태 코드 이상의 의미가 없다"는 뜻이고, 이때 `title`은 상태 코드의 표준 문구(404면 `Not Found`)를 쓰라고 권고합니다.

**`status`는 본문에 있어도 응답 상태 코드를 이기지 못합니다.** 본문에 `"status": 409`를 넣고 실제로는 200으로 내보내면, 표준상으로도 그 응답은 200입니다(8절 함정 3).

**확장 멤버는 쓰라고 열어둔 자리입니다.** 문제 유형을 정의하면서 필드를 추가할 수 있고, 클라이언트는 모르는 필드를 무시해야 합니다. 다만 XML 호환을 위해 이름은 글자로 시작하고 영숫자·언더스코어만 쓰며 **세 글자 이상**이어야 합니다.

한 가지 더. **여러 문제가 동시에 발생했을 때** RFC는 "가장 관련 있거나 급한 문제 하나"를 담으라고 권고하고, 배치 응답용 범용 타입을 새로 만들지 말라고 합니다. 이 권고를 폼 검증에 그대로 적용하면 사용자가 폼을 다섯 번 제출하게 됩니다. 검증처럼 **모든 오류를 한 번에 알려주는 게 본질인 경우는 확장 멤버로 배열을 실어 보내는 게 맞습니다**(8절 함정 4).

RFC의 보안 고려사항도 한 줄이지만 중요합니다. 에러 상세는 **시스템·접근 권한·사용자 프라이버시를 위협할 수 있는 정보를 흘리지 않도록 걸러야 하고, 스택 덤프를 HTTP로 노출하지 말라**고 명시합니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

Spring Framework 6.0부터 `ProblemDetail`, `ErrorResponse`, `ErrorResponseException`, `ResponseEntityExceptionHandler`가 표준 구현으로 들어와 있습니다. ([Error Responses](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html))

```java
// src/main/java/com/example/order/web/OrderExceptionHandler.java
@RestControllerAdvice
public class OrderExceptionHandler extends ResponseEntityExceptionHandler {

    private static final URI OUT_OF_STOCK =
            URI.create("https://api.example.com/problems/out-of-stock");

    @ExceptionHandler(OutOfStockException.class)
    public ProblemDetail handleOutOfStock(OutOfStockException ex) {
        // status는 여기 지정한 값이 그대로 응답 상태 코드가 됩니다.
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.CONFLICT,
                "요청한 %d개 중 %d개만 남아 있습니다.".formatted(ex.getRequested(), ex.getAvailable()));
        problem.setType(OUT_OF_STOCK);
        problem.setTitle("재고 부족");          // 이 type이면 항상 이 문구
        problem.setProperty("errorCode", "OUT_OF_STOCK");   // 확장 멤버
        problem.setProperty("productId", ex.getProductId());
        return problem;
    }
}
```

응답은 이렇게 나갑니다.

```json
HTTP/1.1 409 Conflict
Content-Type: application/problem+json

{
  "type": "https://api.example.com/problems/out-of-stock",
  "title": "재고 부족",
  "status": 409,
  "detail": "요청한 3개 중 1개만 남아 있습니다.",
  "instance": "/orders",
  "errorCode": "OUT_OF_STOCK",
  "productId": 4821
}
```

`errorCode`와 `productId`가 중첩 객체가 아니라 **최상위 필드로 펼쳐진 것**에 주목합니다. `setProperty()`로 넣은 값은 `ProblemDetail`의 `properties` Map에 들어가는데, Spring이 등록하는 `ProblemDetailJacksonMixin`이 직렬화 시점에 이 Map을 풀어서 최상위에 올립니다. 역직렬화도 같은 방식으로 돌아갑니다.

검증 오류는 부모 클래스의 메서드를 오버라이드해 형태를 맞춥니다.

```java
@Override
protected ResponseEntity<Object> handleMethodArgumentNotValid(
        MethodArgumentNotValidException ex, HttpHeaders headers,
        HttpStatusCode status, WebRequest request) {

    List<Map<String, String>> fieldErrors = ex.getBindingResult().getFieldErrors().stream()
            .map(error -> Map.of(
                    "field", error.getField(),
                    // getDefaultMessage()는 null이 될 수 있어 Map.of에 그대로 넣으면 NPE가 납니다.
                    "reason", Objects.requireNonNullElse(error.getDefaultMessage(), "유효하지 않은 값")))
            .toList();

    ProblemDetail problem = ProblemDetail.forStatusAndDetail(
            HttpStatus.BAD_REQUEST, "%d개 항목이 올바르지 않습니다.".formatted(fieldErrors.size()));
    problem.setType(URI.create("https://api.example.com/problems/validation-failed"));
    problem.setTitle("입력값 검증 실패");
    problem.setProperty("errorCode", "VALIDATION_FAILED");
    problem.setProperty("errors", fieldErrors);   // 확장 멤버, 3글자 이상
    return ResponseEntity.badRequest().body(problem);
}
```

### 3-2. 실행 흐름

응답 본문이 만들어지는 경로는 **두 개**이고, 이 둘이 갈라지는 게 이 주제의 핵심입니다.

```text
[경로 A] 컨트롤러/바인딩에서 예외
  DispatcherServlet → HandlerExceptionResolver
    → ExceptionHandlerExceptionResolver → @RestControllerAdvice
    → ProblemDetail 반환 → instance 미설정 시 현재 URL 경로로 자동 설정
    → HttpMessageConverter → application/problem+json

[경로 B] 필터에서 터진 예외 / 매핑 없는 404 / 컨테이너 레벨 오류
  서블릿 컨테이너 → /error 포워드 → BasicErrorController
    → DefaultErrorAttributes → application/json
    → {"timestamp": ..., "status": ..., "error": ..., "path": ...}
```

경로 A는 `@ControllerAdvice`가 관장하고, 경로 B는 Spring Boot의 전역 에러 처리(`ErrorController`/`ErrorAttributes`)가 관장합니다. **두 경로는 서로를 모릅니다.** 요청이 `DispatcherServlet` 안까지 들어왔는지 여부로 갈립니다(`day02-spring-request-flow.md` 6절).

Spring Boot에서 RFC 9457 지원은 **기본으로 꺼져 있습니다.** 켜려면 이렇게 씁니다.

```yaml
# application.yml
spring:
  mvc:
    problemdetails:
      enabled: true   # Spring Boot 4.1 기준 기본값 false
```

이 설정은 내장 예외를 처리하는 `ResponseEntityExceptionHandler`를 자동 등록합니다. 즉 **경로 A만 바꿉니다.** 경로 B는 그대로입니다. ([Spring Boot 4.1 — Servlet Web Applications](https://docs.spring.io/spring-boot/reference/web/servlet.html))

직접 만든 `@ControllerAdvice`를 함께 쓸 거면 Spring Boot가 등록하는 것(order 0)보다 앞선 순서를 줘야 합니다.

## 4. 특징

### 4-1. 이 표준을 쓸 때와 안 쓸 때

**쓰는 게 유리한 경우** — 외부에 공개하는 API, 팀이 여럿인 마이크로서비스, 클라이언트가 웹·앱·서버로 여러 종류인 경우입니다. 포맷 협상 회의를 없애주는 게 표준의 가장 큰 가치입니다.

**굳이 안 써도 되는 경우** — 클라이언트가 우리 팀 프론트엔드 하나뿐이고 이미 사내 표준 포맷이 굳어 있다면, RFC로 바꾸는 비용이 이득보다 큽니다. **중요한 건 RFC 9457을 쓰는 것이 아니라 포맷이 하나인 것입니다.**

### 4-2. 얻는 것

- 클라이언트가 `type`(또는 확장 `errorCode`) 하나로 분기합니다. 메시지 파싱이 사라집니다.
- `ProblemDetail`을 그대로 역직렬화할 수 있습니다. 서버 간 호출에서 `RestClientResponseException.getResponseBodyAs(ProblemDetail.class)`로 바로 꺼냅니다.
- `type` URI가 곧 에러 문서의 주소가 되므로 문서와 코드가 같은 식별자를 공유합니다.
- 다국어를 프레임워크에 맡길 수 있습니다. Spring은 `problemDetail.title.<예외 FQCN>`, `problemDetail.<예외 FQCN>` 형태의 메시지 코드를 `MessageSource`로 해석합니다.

### 4-3. 대신 지불하는 비용

| 비용 | 실제로 겪는 모습 |
|---|---|
| `type` URI 관리 | 에러 종류마다 URI를 정하고 문서를 유지해야 합니다. 안 하면 전부 `about:blank`가 되어 표준을 쓴 의미가 없어집니다 |
| 기존 클라이언트 호환 | 이미 배포된 앱이 `{"code","msg"}`를 파싱 중이면 포맷 교체는 깨지는 변경입니다. 버전 협상이나 병행 기간이 필요합니다 |
| 표준 5칸의 부족 | 필드별 검증 오류, 재시도 가능 여부, 추적 ID는 전부 확장 멤버 설계가 따로 필요합니다 |
| `Content-Type` 변경 | `application/json`이 아니라 `application/problem+json`이 나갑니다. 응답 타입을 문자열로 비교하던 클라이언트·테스트가 깨집니다 |
| 경로 B와의 불일치 | 설정 하나로 전부 통일되지 않습니다(8절 함정 1) |

세 번째가 실무에서 제일 자주 오해받는 지점입니다. **표준을 채택해도 설계는 남습니다.** RFC는 봉투를 정해줄 뿐 내용물을 정해주지 않습니다.

## 5. 예제

### 5-1. 흔한 코드 ❌

```java
// ❌ 성공/실패를 본문 플래그로 표현하고, 상태 코드는 늘 200
@PostMapping("/orders")
public ResponseEntity<Map<String, Object>> create(@RequestBody OrderRequest request) {
    try {
        Order order = orderService.place(request);
        return ResponseEntity.ok(Map.of("success", true, "data", order.getId()));
    } catch (OutOfStockException e) {
        return ResponseEntity.ok(Map.of("success", false, "message", "재고가 부족합니다"));
    } catch (Exception e) {
        // 원인을 그대로 노출합니다
        return ResponseEntity.ok(Map.of("success", false, "message", e.getMessage()));
    }
}
```

문제가 네 겹입니다.

1. **모든 응답이 200입니다.** 모니터링의 5xx 비율, 로드밸런서, 클라이언트 HTTP 라이브러리의 에러 처리, 캐시가 전부 이 응답을 "성공"으로 봅니다. 장애가 그래프에 안 나타납니다.
2. **클라이언트가 분기할 안정적인 값이 없습니다.** 남은 건 한글 메시지뿐이라 `message.contains("재고")`를 쓰게 됩니다.
3. **마지막 `catch`가 내부 정보를 그대로 뱉습니다.** `e.getMessage()`에는 SQL 조각이나 내부 호스트명이 실려 나옵니다.
4. **이 컨트롤러 밖에서 터진 예외는 이 포맷을 안 따릅니다.** 인증 필터가 실패하면 완전히 다른 응답이 나갑니다.

### 5-2. 개선한 코드 ✔️

```java
// ✅ 컨트롤러는 성공 경로만 씁니다. 실패 표현은 한 곳에 모읍니다.
@PostMapping("/orders")
public ResponseEntity<OrderResponse> create(@RequestBody @Valid OrderRequest request) {
    Order order = orderService.place(request);
    return ResponseEntity
            .created(URI.create("/orders/" + order.getId()))
            .body(OrderResponse.from(order));
}
```

실패는 3-1의 `OrderExceptionHandler` 하나가 담당합니다. 예상 못 한 예외는 이렇게 받습니다.

```java
@ExceptionHandler(Exception.class)
public ProblemDetail handleUnexpected(Exception ex, HttpServletRequest request) {
    String traceId = MDC.get("traceId");
    // 상세 원인은 로그에만 남깁니다.
    log.error("[{}] 처리되지 않은 예외 - {} {}", traceId, request.getMethod(), request.getRequestURI(), ex);

    ProblemDetail problem = ProblemDetail.forStatusAndDetail(
            HttpStatus.INTERNAL_SERVER_ERROR,
            "요청을 처리하지 못했습니다. 문의 시 traceId를 알려주세요.");
    problem.setTitle("서버 오류");
    problem.setProperty("errorCode", "INTERNAL_ERROR");
    problem.setProperty("traceId", traceId);
    return problem;
}
```

**`detail`에 예외 메시지를 넣지 않고 `traceId`를 넣은 것**이 이 코드의 전부입니다. 사용자에게는 문의 수단을 주고, 개발자에게는 로그를 검색할 키를 줍니다. 원인은 로그에만 있습니다.

호출하는 쪽은 이렇게 받습니다.

```java
try {
    return restClient.post().uri("/orders").body(request).retrieve().body(OrderResponse.class);
} catch (RestClientResponseException e) {
    ProblemDetail problem = e.getResponseBodyAs(ProblemDetail.class);
    if (problem != null && "OUT_OF_STOCK".equals(problem.getProperties().get("errorCode"))) {
        throw new StockUnavailableException(problem.getDetail());   // 메시지는 표시용으로만
    }
    throw e;
}
```

## 6. 이 설계가 지키는 원칙 — 분기하는 값은 안정적이어야 한다

에러 응답에는 성격이 다른 두 종류의 정보가 섞여 있습니다.

- **기계가 읽는 것**: 상태 코드, `type`, `errorCode` → **절대 바뀌면 안 됩니다.** 이건 API 스펙입니다.
- **사람이 읽는 것**: `title`, `detail` → **언제든 바뀝니다.** 문구 개선, 번역, A/B 테스트 대상입니다.

이 구분이 무너지면 문구 수정이 클라이언트 장애가 됩니다.

같은 결론을 다른 표준에서도 확인할 수 있습니다. Google의 API 설계 가이드(AIP-193)는 상태 코드가 20여 개뿐이라 그것만으로는 상황을 구분할 수 없다고 보고, **모든 에러 응답에 `ErrorInfo`를 넣어 `reason`·`domain`이라는 기계용 식별자를 제공하라**고 요구합니다. `reason`은 `ERROR` 같은 게 아니라 `CPU_AVAILABILITY`처럼 구체적이어야 합니다. 그리고 클라이언트가 메시지를 파싱하고 있을 가능성 때문에 **기존 API의 메시지 문자열은 안정적으로 유지해야 한다**고 못 박습니다. 메시지 파싱이 얼마나 흔한 실수인지를 표준이 인정하고 있는 셈입니다. ([AIP-193 Errors](https://google.aip.dev/193))

RFC 9457의 `type`과 AIP-193의 `reason`은 이름만 다를 뿐 같은 자리를 차지합니다. **상태 코드는 분류이고, 그 아래 한 칸이 더 필요하다**는 것이 두 표준의 공통 결론입니다.

```java
// ❌ 메시지를 파싱합니다. 서버가 문구를 다듬으면 조용히 깨집니다.
if (response.getMessage().contains("재고")) { showRestockButton(); }

// ✅ 계약된 식별자로 분기합니다. 문구는 화면에 그대로 뿌리기만 합니다.
if ("OUT_OF_STOCK".equals(problem.getProperties().get("errorCode"))) { showRestockButton(); }
```

## 7. 실무에서 찾아보는 사례 — Spring Boot의 기본 에러 응답

Spring Boot의 기본 응답(`DefaultErrorAttributes`)은 `timestamp`, `status`, `error`, `path`를 담습니다. `message`, `errors`, `trace`, `exception`은 **기본적으로 빠져 있습니다.**

기본값은 소스에서 바로 확인됩니다(`ErrorProperties`).

| 속성 | 기본값 |
|---|---|
| `server.error.path` | `/error` |
| `server.error.include-message` | `NEVER` |
| `server.error.include-stacktrace` | `NEVER` |
| `server.error.include-binding-errors` | `NEVER` |
| `server.error.include-exception` | `false` |
| `server.error.whitelabel.enabled` | `true` |

`NEVER`/`ALWAYS`/`ON_PARAM` 세 가지 중 셋 다 `NEVER`가 기본입니다. **프레임워크가 기본적으로 아무것도 안 알려주는 쪽을 택한 것**이고, 이유는 2절의 보안 고려사항 그대로입니다. 로컬에서 원인이 안 보인다고 `include-stacktrace: always`를 켠 다음 그 설정이 운영까지 따라가는 일이 자주 생깁니다. 켜야 한다면 프로파일별 설정 파일에 넣어 운영에는 안 가게 막습니다.

## 8. 함정

### 함정 1 — `problemdetails.enabled=true`를 켰는데 어떤 에러만 옛날 포맷입니다

- **증상**: 컨트롤러에서 난 예외는 `application/problem+json`으로 잘 나옵니다. 그런데 존재하지 않는 URL을 부르거나 인증 필터가 실패하면 `{"timestamp","status","error","path"}` 형태의 응답이 돌아옵니다. API 문서에는 모든 에러가 Problem Details라고 써놨는데 실제로는 두 포맷이 섞입니다.
- **원인**: 3-2의 경로 B입니다. `spring.mvc.problemdetails.enabled`는 `ResponseEntityExceptionHandler`를 등록할 뿐이고, `BasicErrorController`/`DefaultErrorAttributes`는 이 설정과 무관하게 기존 포맷을 유지합니다. Spring Boot 이슈 [#43850 "Render global errors as Problem Details"](https://github.com/spring-projects/spring-boot/issues/43850)로 **현재 열려 있는(4.x 마일스톤) 미해결 항목**입니다.
- **해법**: `ErrorAttributes` 빈을 직접 등록해 `/error` 응답도 같은 형태로 맞춥니다(Spring Boot 4.1 기준 `org.springframework.boot.webmvc.error.ErrorAttributes`). `DefaultErrorAttributes`를 상속해 `getErrorAttributes()` 결과를 `type`/`title`/`status`/`detail`/`instance` + `errorCode` 키로 재조립하는 게 가장 손이 적게 갑니다. **포맷 통일을 선언하기 전에 없는 URL을 한 번 호출해 보는 것**이 확인 절차입니다.

### 함정 2 — `detail`에 내부 정보가 실려 나갑니다

- **증상**: 운영 로그를 보다가 클라이언트에 나간 응답에서 `could not execute statement; SQL [insert into orders ...]`나 내부 호스트명, 컬럼명을 발견합니다. 보안 점검에서 지적받습니다.
- **원인**: `ProblemDetail.forStatusAndDetail(status, ex.getMessage())` 같은 코드입니다. JPA·JDBC 예외 메시지에는 SQL과 스키마가 그대로 들어 있습니다. `server.error.include-message: always`를 개발 편의로 켜두고 운영에 그대로 나간 경우도 같습니다.
- **해법**: `detail`은 **사용자가 무엇을 고쳐야 하는지**만 씁니다. 원인은 로그에 남기고 응답에는 `traceId`만 실어 보냅니다(5-2). `Exception.class`를 받는 최종 핸들러를 반드시 두고, 그 핸들러가 예외 메시지를 응답에 넣지 않는지 코드 리뷰 항목으로 고정합니다. RFC 9457의 보안 고려사항이 정확히 이 얘기입니다.

### 함정 3 — 에러인데 200을 돌려줍니다

- **증상**: 결제 실패율이 올라갔는데 대시보드의 5xx·4xx 그래프는 평평합니다. 알림도 안 울립니다. CDN이 실패 응답을 캐시해서 다른 사용자에게도 같은 에러가 나갑니다.
- **원인**: `{"success": false}` 패턴입니다. HTTP는 상태 코드를 보고 동작하는 미들웨어(로드밸런서, 캐시, 재시도 라이브러리, APM)로 둘러싸여 있는데, 본문 플래그는 그 어느 것도 읽지 않습니다. RFC 9457이 본문 `status`를 참고용으로만 규정하고 실제 상태 코드를 우선하는 것도 같은 이유입니다.
- **해법**: 실패는 4xx/5xx로 내보냅니다. 클라이언트 입력 문제면 4xx, 서버 문제면 5xx입니다. 애매하면 **"클라이언트가 요청을 고치면 성공하는가"**로 나눕니다. 예외적으로 배치 API처럼 부분 성공이 정상인 경우는 200 + 항목별 결과가 맞지만, 그건 **의도적으로 설계한 성공 응답**이지 에러 응답이 아닙니다.

### 함정 4 — 검증 오류를 하나씩만 알려줍니다

- **증상**: 회원가입 폼에서 사용자가 제출 → 이메일 형식 오류 → 고치고 제출 → 비밀번호 길이 오류 → 고치고 제출 → 약관 미동의. 이탈률이 오릅니다.
- **원인**: `ProblemDetail`의 표준 다섯 칸에는 "어느 필드가 왜 틀렸는지"를 담을 자리가 없습니다. RFC의 "가장 급한 문제 하나만" 권고를 검증에까지 그대로 적용하면 이렇게 됩니다. 게다가 `server.error.include-binding-errors` 기본값도 `NEVER`라, 아무것도 안 하면 필드 정보가 응답에 아예 없습니다.
- **해법**: 확장 멤버로 배열을 실어 보냅니다(3-1의 `errors`). 필드명은 클라이언트의 폼 필드명과 매칭되는 값이어야 하고, 이름은 세 글자 이상이어야 합니다. 그리고 이 배열의 구조를 **한 번 정하면 스키마로 고정합니다.** 화면마다 `errors`, `fieldErrors`, `violations`가 다르게 나가면 포맷을 통일한 의미가 사라집니다.

<!-- TODO: Spring Boot 3.x는 ErrorAttributes 패키지가 org.springframework.boot.web.servlet.error 입니다. 4.0에서 모듈이 재편되며 경로가 바뀌었는데, 3.x → 4.x 정확한 이동 경로는 마이그레이션 가이드 원문으로 재확인이 필요합니다. -->

## 9. 참고자료

- [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html) — 다섯 멤버의 정의, 확장 멤버 규칙, 복수 문제 처리 권고, 보안 고려사항
- [Spring Framework — Error Responses](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html) — `ProblemDetail`, `ErrorResponse`, `ResponseEntityExceptionHandler`, 메시지 코드 규칙, `ProblemDetailJacksonMixin`
- [Spring Boot 4.1 — Servlet Web Applications](https://docs.spring.io/spring-boot/reference/web/servlet.html) — `/error` 기본 처리, `spring.mvc.problemdetails.enabled`, `ErrorAttributes` 커스터마이징
- [spring-boot#43850 — Render global errors as Problem Details](https://github.com/spring-projects/spring-boot/issues/43850) — 함정 1의 미해결 이슈
- [Google AIP-193 — Errors](https://google.aip.dev/193) — 기계용 식별자와 사람용 메시지의 분리
- 관련 챕터: `day02-spring-request-flow.md` — 경로 A와 경로 B가 갈리는 지점
