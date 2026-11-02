# 예외 처리를 어디에 둘 것인가 — `@ControllerAdvice`가 잡는 것과 못 잡는 것

> 이 문서가 답할 질문: **예외를 응답으로 바꾸는 지점을 어디에 두어야 하고, `@ControllerAdvice`의 경계는 어디까지인가?**
>
> 기준: Spring Framework 7.0.x / Spring Boot 4.1 (4.1.0 GA 2026년 6월). 버전이 갈리는 부분은 본문에 따로 표시합니다.
>
> 에러 응답의 **본문 포맷**은 day03-api-error-format.md에서 다뤘습니다. 이 문서는 **누가 어디서 잡는가**만 다룹니다.

## 1. 핵심 개념

`@ControllerAdvice`는 여러 컨트롤러에 공통으로 적용되는 `@ExceptionHandler`·`@InitBinder`·`@ModelAttribute` 메서드를 모아두는 자리입니다. `@RestControllerAdvice`는 여기에 `@ResponseBody`를 더한 것이고, 둘 다 `@Component`가 메타 애너테이션으로 붙어 있어 컴포넌트 스캔으로 등록됩니다.

문제는 이름이 주는 기대와 실제 범위가 다르다는 점입니다. advice 클래스 하나에 `@ExceptionHandler(Exception.class)`를 달면 "이 애플리케이션의 모든 예외"가 거기로 온다고 읽힙니다. 실제로 오는 것은 **`DispatcherServlet`이 핸들러를 찾아 실행하는 구간에서 던져진 예외**뿐입니다.

> 인증 실패, 서블릿 필터에서 터진 `NullPointerException`, `@Async` 스레드의 예외, 응답 본문이 이미 나가기 시작한 뒤의 직렬화 실패는 advice를 **거치지 않습니다.** 이것들은 Spring Boot의 `/error`로 빠지고, 거기서 Boot 기본 포맷이 나갑니다. 그래서 포맷을 통일했다고 믿는 서비스가 상황에 따라 두 가지 응답을 번갈아 내보냅니다. 클라이언트는 두 벌의 파싱 코드를 쓰게 되고, 그 두 벌 중 하나는 장애 때만 실행되므로 평소에 검증되지 않습니다.

예외 처리 전략을 정하는 일은 "advice를 만들 것인가"가 아니라 **경계가 몇 개이고 각 경계에서 누가 응답을 만드는가**를 정하는 일입니다.

## 2. 구조 — 예외가 응답이 되는 네 단계

요청 하나가 컨트롤러까지 오는 경로는 day02-spring-request-flow.md에서 다뤘습니다. 예외는 그 경로를 거꾸로 올라가면서 네 번 처리 기회를 만납니다.

```
① 컨트롤러/서비스에서 throw
   → ② HandlerExceptionResolver 체인 (여기가 @ControllerAdvice)
      → 해결되면 종료
   → ③ 해결 안 되면 서블릿 컨테이너로 전파
      → ④ 컨테이너가 에러 페이지로 ERROR 디스패치 → Spring Boot의 /error
```

`DispatcherServlet`은 핸들러 실행 중 예외가 나면 `HandlerExceptionResolver` 빈들의 체인에 위임합니다. 각 리졸버는 세 가지 중 하나를 반환합니다. 에러 뷰를 가리키는 `ModelAndView`, 자기가 처리를 끝냈다는 뜻의 빈 `ModelAndView`, 그리고 **`null` — "나는 못 처리했으니 다음 리졸버가 해보라"**. 끝까지 `null`이면 예외는 컨테이너로 올라갑니다. ([Exceptions](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/exceptionhandlers.html))

MVC Config가 기본으로 등록하는 리졸버는 세 개이고, `WebMvcConfigurationSupport#addDefaultHandlerExceptionResolvers`에 등록된 순서가 곧 시도 순서입니다.

| 순서 | 리졸버 | 담당 |
|---:|---|---|
| 1 | `ExceptionHandlerExceptionResolver` | `@Controller`·`@ControllerAdvice`의 `@ExceptionHandler` 메서드 호출 |
| 2 | `ResponseStatusExceptionResolver` | `@ResponseStatus`가 붙은 예외를 상태 코드로 변환 |
| 3 | `DefaultHandlerExceptionResolver` | Spring MVC가 던지는 예외(`HttpMessageNotReadableException` 등)를 상태 코드로 변환 |

순서가 중요한 이유는 **앞에서 처리되면 뒤는 호출되지 않는다**는 점입니다. 내 예외 클래스에 `@ResponseStatus(HttpStatus.CONFLICT)`를 붙여 놓고 advice에 `@ExceptionHandler(Exception.class)`를 두면, 1번이 먼저 먹으므로 `@ResponseStatus`는 영향을 주지 못합니다. 애너테이션이 무시된 게 아니라 2번 리졸버까지 가지 않은 것입니다.

### 2-1. 적용 범위를 좁히는 지점

advice는 기본적으로 모든 컨트롤러에 적용되지만 세 가지 방법으로 대상을 좁힐 수 있습니다. ([Controller Advice](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-advice.html))

```java
@ControllerAdvice(annotations = RestController.class)   // 애너테이션으로
@ControllerAdvice("com.example.order.api")              // 패키지로
@ControllerAdvice(assignableTypes = AdminController.class)  // 타입으로
```

JSON API와 서버 사이드 렌더링 뷰가 한 애플리케이션에 섞여 있을 때 가장 자주 쓰는 지점입니다. 다만 공식 문서는 이 선택자들이 **런타임에 평가되므로 과하게 쓰면 성능에 영향을 줄 수 있다**고 명시합니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
// src/main/java/com/example/order/api/OrderExceptionHandler.java
@Order(10)                       // 뒤에서 설명합니다. 생략하면 가장 낮은 우선순위가 됩니다
@RestControllerAdvice(annotations = RestController.class)
public class OrderExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(OrderExceptionHandler.class);

    @ExceptionHandler(OutOfStockException.class)
    public ProblemDetail handleOutOfStock(OutOfStockException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.CONFLICT, "재고가 부족합니다.");
        problem.setType(URI.create("https://api.example.com/problems/out-of-stock"));
        problem.setProperty("productId", ex.getProductId());
        return problem;   // 여기 담긴 status가 응답 상태 코드가 됩니다
    }

    // 최종 방어선. 여기까지 왔다는 건 예상 못 한 예외라는 뜻이므로 ERROR로 남깁니다
    @ExceptionHandler(Exception.class)
    public ProblemDetail handleUnexpected(Exception ex, HandlerMethod handlerMethod) {
        log.error("처리되지 않은 예외: handler={}", handlerMethod.getShortLogMessage(), ex);
        return ProblemDetail.forStatusAndDetail(
                HttpStatus.INTERNAL_SERVER_ERROR, "요청을 처리할 수 없습니다.");
    }
}
```

`ResponseEntityExceptionHandler`를 상속하면 Spring MVC가 던지는 예외들(검증 실패, 잘못된 JSON, 지원하지 않는 메서드 등)이 RFC 9457 본문으로 나갑니다. 상속하지 않으면 그 예외들은 3번 리졸버로 내려가 본문 없는 상태 코드만 남습니다.

`@ExceptionHandler` 메서드가 받을 수 있는 인자는 예외 말고도 여럿입니다. 위에서 쓴 `HandlerMethod`는 **예외를 던진 컨트롤러 메서드**라서, 로그에 "어느 API에서 터졌는지"를 남길 때 유용합니다(day36-log-design.md).

### 3-2. 실행 흐름

`OrderService`가 `OutOfStockException`을 던졌을 때:

1. `ha.handle()` 안에서 예외 발생 → `DispatcherServlet`이 `dispatchException`에 보관
2. `ExceptionHandlerExceptionResolver`가 컨트롤러 지역 핸들러 → advice 순으로 매칭 메서드 탐색
3. `handleOutOfStock` 호출, 반환된 `ProblemDetail`을 `HttpMessageConverter`가 직렬화
4. 리졸버가 빈 `ModelAndView` 반환 → 체인 종료. 2·3번 리졸버는 호출되지 않음
5. `HandlerInterceptor.afterCompletion`이 예외 객체를 인자로 받으며 호출

## 4. 어느 핸들러가 이기는가 — 규칙 네 개

`Exception` 하나만 받는 advice가 생각대로 동작하지 않는 대부분의 이유가 이 규칙들입니다.

**① 컨트롤러 지역 핸들러가 advice보다 먼저입니다.** 공식 문서의 표현은 "advice의 전역 `@ExceptionHandler`는 컨트롤러의 지역 핸들러 **다음에** 적용된다"입니다. 참고로 `@ModelAttribute`와 `@InitBinder`는 반대로 전역이 먼저입니다.

**② 한 클래스 안에서는 "거리"로 정합니다.** `@ExceptionHandler`는 최상위 예외뿐 아니라 **감싸인 원인(cause)에도 매칭**되고, 5.3부터는 임의 깊이의 cause까지 봅니다. 여러 메서드가 매칭되면 `ExceptionDepthComparator`가 던져진 예외 타입으로부터의 깊이를 재서 가까운 쪽을 고릅니다. 일반적으로 최상위 매칭이 cause 매칭보다 우선합니다.

**③ advice 사이에서는 우선순위가 깊이를 이깁니다.** 이게 가장 안 알려진 규칙입니다. 깊이 비교는 **한 클래스 안에서만** 적용되므로, 우선순위가 높은 advice의 `Exception` 매칭이 낮은 advice의 정확한 매칭을 이깁니다. 도메인별 advice를 여러 개 두면서 그중 하나에 `@ExceptionHandler(Exception.class)`를 넣으면, 그 advice가 다른 advice의 구체적인 핸들러들을 전부 가립니다.

**④ `@Order`를 안 주면 가장 낮은 우선순위입니다.** `ControllerAdviceBean#getOrder()`는 빈이 `Ordered`를 구현하지도, `@Order`가 붙어 있지도 않으면 `Ordered.LOWEST_PRECEDENCE`를 씁니다. advice가 두 개 이상이고 둘 다 순서를 안 줬으면 순서가 빈 탐색 순서에 의존하게 되므로, **advice가 둘 이상이면 전부 `@Order`를 명시합니다.**

여기서 문서와 코드가 어긋나는 지점이 하나 있습니다. 공식 레퍼런스는 `spring.mvc.problemdetails.enabled`로 자동 구성되는 Boot의 핸들러를 "order가 0"이라고 설명하면서 그보다 앞서게 하라고 안내합니다. 그런데 Spring Boot 4.1.x와 3.5.x의 `ProblemDetailsExceptionHandler` 소스에는 `@Order`가 없고 `ResponseEntityExceptionHandler`도 `Ordered`를 구현하지 않습니다. 즉 실제로는 `LOWEST_PRECEDENCE`로 보입니다.

<!-- TODO: 확인 필요 — 레퍼런스의 "order 0" 기술이 구버전 잔재인지, 자동 구성 어딘가에서 order를 주는지 확정하지 못했습니다. 어느 쪽이든 내 advice에 0보다 작은 @Order를 주면 안전하므로 그렇게 쓰길 권합니다. -->

참고로 `spring.mvc.problemdetails.enabled`의 기본값은 `false`입니다(Boot 4.1.x `WebMvcProperties.Problemdetails`의 `private boolean enabled;`). 켜 두고 직접 `ResponseEntityExceptionHandler`를 상속한 advice까지 만들면 같은 역할의 advice가 두 개 공존합니다.

## 5. 예제 — catch-all 하나에서 경계 분리로

### 5-1. 클린하지 않은 코드 ❌

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

    // ❌ 모든 걸 한 메서드로. 어떤 예외인지 문자열로 분기한다
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handle(Exception ex) {
        HttpStatus status = ex.getMessage() != null && ex.getMessage().contains("없습니다")
                ? HttpStatus.NOT_FOUND
                : HttpStatus.INTERNAL_SERVER_ERROR;
        return ResponseEntity.status(status)
                .body(Map.of("message", ex.getMessage()));   // ❌ NPE 가능, 내부 메시지 노출
    }
}
```

문제는 세 겹입니다. 메시지 문자열이 사실상 API 스펙이 되고, `ex.getMessage()`가 `null`이면 `Map.of`가 `NullPointerException`을 던지며, 내부 예외 메시지(테이블명, 쿼리 조각)가 그대로 클라이언트로 나갑니다.

### 5-2. 개선한 코드 ✔️

```java
// 1) 도메인 예외는 자신의 의미만 들고 있습니다. HTTP를 모릅니다
public class OrderNotFoundException extends RuntimeException {
    private final long orderId;
    public OrderNotFoundException(long orderId) {
        super("주문을 찾을 수 없습니다: " + orderId);
        this.orderId = orderId;
    }
    public long getOrderId() { return this.orderId; }
}
```

```java
// 2) 변환은 advice에서. 예외 타입마다 메서드를 나눕니다
@Order(10)
@RestControllerAdvice(annotations = RestController.class)
public class OrderExceptionHandler extends ResponseEntityExceptionHandler {

    @ExceptionHandler(OrderNotFoundException.class)
    public ProblemDetail handleNotFound(OrderNotFoundException ex) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.NOT_FOUND, "주문을 찾을 수 없습니다.");
        problem.setProperty("orderId", ex.getOrderId());
        return problem;
    }
}
```

```java
// 3) 최종 방어선은 별도 advice로 분리하고 가장 낮은 순위를 줍니다
@Order(Ordered.LOWEST_PRECEDENCE)
@RestControllerAdvice
public class FallbackExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(FallbackExceptionHandler.class);

    @ExceptionHandler(Exception.class)
    public ProblemDetail handle(Exception ex, HttpServletRequest request) {
        log.error("처리되지 않은 예외: {} {}", request.getMethod(), request.getRequestURI(), ex);
        // 내부 메시지를 쓰지 않습니다. 상세는 로그에만 남깁니다
        return ProblemDetail.forStatusAndDetail(
                HttpStatus.INTERNAL_SERVER_ERROR, "요청을 처리할 수 없습니다.");
    }
}
```

catch-all을 **별도 클래스로 분리하는 것**이 핵심입니다. 규칙 ③ 때문에, 같은 클래스가 아니라 다른 advice에 있는 `Exception` 핸들러는 순위를 낮추는 것만으로 다른 advice를 가리지 않게 만들 수 있습니다.

## 6. 경계 밖 — advice에 안 들어오는 예외들

| 예외가 터진 위치 | advice 도달 | 실제 처리 주체 |
|---|:---:|---|
| 컨트롤러·서비스·리포지토리 | ○ | `@ExceptionHandler` |
| `HandlerInterceptor.preHandle` / `postHandle` | ○ | `@ExceptionHandler` |
| `HandlerInterceptor.afterCompletion` | ✗ | 없음. `logger.error`로 남기고 삼킵니다 |
| 서블릿 `Filter`, Spring Security 필터 체인 | ✗ | `ExceptionTranslationFilter`, `AuthenticationEntryPoint`, `AccessDeniedHandler` |
| `@Async`·`@Scheduled` 스레드 | ✗ | `AsyncUncaughtExceptionHandler`, `ErrorHandler` |
| 핸들러 메서드가 던진 `Error`(OOM 등) | ○ | `ServletException`으로 감싸여 전달됩니다 |
| 본문 직렬화가 시작된 뒤 | △ | 핸들러는 호출되지만 이미 나간 응답은 되돌릴 수 없습니다 |

세 줄만 덧붙입니다.

**인증·인가 예외는 구조적으로 못 잡습니다.** Spring Security는 `DispatcherServlet` **앞단의 필터 체인**이고, `AuthenticationException`과 `AccessDeniedException`은 그 안의 `ExceptionTranslationFilter`가 처리합니다. advice는 아직 실행된 적도 없습니다. 401/403 응답 포맷을 맞추려면 `AuthenticationEntryPoint`와 `AccessDeniedHandler`를 직접 등록해야 합니다.

**`Error`는 `ServletException`에 감싸여 전달됩니다.** `DispatcherServlet`은 핸들러에서 올라온 `Throwable`을 `ServletException("Handler dispatch failed: ...")`로 감싸 리졸버에 넘깁니다(4.3부터). 그래서 `@ExceptionHandler(Exception.class)`는 `OutOfMemoryError` 뒤에도 평온하게 500 JSON을 만듭니다. JVM이 이미 불안정한 상태에서 응답을 성형하는 셈이라, 최종 방어선 로그만큼은 반드시 `ERROR`로 남겨야 합니다.

**advice를 여러 개 만들면 "어디에도 없는" 예외가 생깁니다.** `assignableTypes`나 패키지 선택자로 좁힌 advice만 있고 전역 폴백이 없으면, 선택자에 안 걸리는 컨트롤러의 예외는 `/error`로 빠집니다.

## 7. 전략 — 세 경계에 같은 포맷을 놓는 일

포맷 통일은 advice 하나로 끝나지 않습니다. 응답을 만드는 자리가 최소 세 곳이기 때문입니다.

1. **필터 경계** — `AuthenticationEntryPoint` / `AccessDeniedHandler` / 필터 내부 `try-catch`
2. **핸들러 경계** — `@ControllerAdvice` (대부분의 예외)
3. **폴백** — Spring Boot의 `/error`. `ErrorAttributes` 빈을 등록해 내용을 바꾸거나 `ErrorController`를 구현해 완전히 대체합니다

세 곳이 같은 스키마를 내보내는지 **실제로 호출해서 확인**하는 것까지가 작업 범위입니다. 2번만 맞춰 놓고 끝내면 장애 때 1번과 3번이 다른 모양을 냅니다.

트레이드오프도 분명합니다.

- **얻는 것**: 컨트롤러에서 `try-catch`가 사라집니다. 예외 → 상태 코드 매핑이 한 파일에 모여서 리뷰할 수 있습니다.
- **잃는 것**: 전역이라 한 줄 고치면 모든 API에 영향이 갑니다. 그리고 `@ExceptionHandler(Exception.class)`는 **버그를 숨기는 장치**로도 작동합니다. 로그를 `WARN`으로 남기면 터지는 걸 아무도 모릅니다.
- **테스트 비용**: 지역 `try-catch`는 단위 테스트로 검증되지만 advice는 요청을 흘려봐야 검증됩니다. `MockMvcBuilders.standaloneSetup()`은 `setControllerAdvice()`로 직접 등록하지 않으면 advice를 적용하지 않고, 서블릿 컨테이너가 없으므로 `/error` ERROR 디스패치도 일어나지 않습니다. 3번 폴백은 MockMvc로는 검증되지 않습니다.

`try-catch`로 지역에서 처리할지, advice로 올릴지는 day61-checked-unchecked.md의 기준과 같습니다. **대안이 있어서 분기할 수 있으면** 그 자리에서 잡고, **응답으로 바꾸는 일밖에 남지 않았으면** advice로 올립니다.

## 8. 함정

**함정 1 — `@ExceptionHandler` 자체가 터지면 원래 예외로 되돌아갑니다**

- **증상**: advice를 붙였는데 Boot 기본 500 응답(또는 whitelabel 페이지)이 나옵니다. 내 advice가 등록은 되어 있고 다른 예외에서는 잘 동작합니다.
- **원인**: `ExceptionHandlerExceptionResolver`는 핸들러 메서드 호출을 `try`로 감싸고, 거기서 **원래 예외도 그 cause도 아닌** 예외가 나오면 `logger.warn("Failure in @ExceptionHandler ...")`만 남기고 `null`을 반환합니다. 체인은 원래 예외로 처리를 계속합니다. 즉 advice가 매칭되지 않은 것처럼 동작합니다.
- **해법**: advice 로거 레벨을 확인해 `WARN`이 보이게 합니다(`org.springframework.web.servlet.mvc.method.annotation`). 그리고 핸들러 안에서 `ex.getMessage()`를 그대로 `Map.of`에 넣는 식의 NPE 유발 코드를 없앱니다. 참고로 **원래 예외를 그대로 다시 던지는 것은 공식 기능**이고, 이때는 남은 리졸버 체인으로 넘어갑니다.

**함정 2 — 응답이 이미 나가기 시작한 뒤에는 바꿀 수 없습니다**

- **증상**: 200 OK인데 JSON이 중간에서 끊겨 있습니다. 클라이언트는 파싱 에러를 봅니다. 서버 로그에는 예외가 찍혀 있습니다.
- **원인**: 상태 코드와 헤더는 본문 첫 바이트가 나갈 때 확정됩니다. 지연 로딩 실패나 `@JsonProperty` getter의 예외처럼 **직렬화 도중** 터지는 예외는 그 시점이 이미 지난 경우가 많습니다. advice가 호출돼도 덮어쓸 응답이 없습니다.
- **해법**: 엔티티를 그대로 직렬화하지 않고 DTO로 변환해서 반환합니다(day14-dto-vs-entity.md). 변환 과정에서 터지면 그건 핸들러 실행 중이므로 advice가 정상적으로 잡습니다.

**함정 3 — 로컬에서는 메시지가 보이는데 운영에서는 빈 응답입니다**

- **증상**: 똑같은 에러인데 운영 응답 본문에 `message`가 없습니다.
- **원인**: advice를 안 거치고 `/error`로 빠진 경우입니다. Boot의 에러 속성은 `include-message` 같은 설정으로 제어되고, Spring Boot 3.5 기준 `include-message`·`include-stacktrace`·`include-binding-errors`의 기본값은 모두 `never`입니다(`ErrorProperties`). 로컬에서는 누군가 `always`로 켜 뒀을 뿐입니다.
- **해법**: 메시지가 비었다는 건 설정 문제가 아니라 **경로 문제**라는 신호로 읽습니다. `/error`로 빠진 이유(6절 표)를 먼저 찾습니다. ⚠️ `include-stacktrace=always`로 가리지 마세요. 스택트레이스를 HTTP로 노출하는 것은 RFC 9457도 금지하는 사항입니다.
- **버전 주의**: Spring Boot 4.0부터 이 속성들의 접두사가 `server.error.*` → `spring.web.error.*`로 바뀌었고, 옛 키는 조용히 바인딩되지 않습니다. 4.x로 올린 뒤 `message`가 사라졌다면 이것이 원인입니다.

<!-- TODO: 확인 필요 — Boot 4.x에서 include-* 기본값이 그대로 never인지는 소스로 재확인하지 못했습니다. 위 기본값은 3.5 기준입니다. -->

**함정 4 — 브라우저에는 HTML, API에는 JSON을 주려는데 하나만 나옵니다**

- **증상**: 같은 예외에 대해 `@ExceptionHandler`를 두 개 만들면 중복 등록으로 기동이 실패합니다.
- **원인**: 예외 타입만으로는 핸들러를 구분할 수 없습니다.
- **해법**: `@ExceptionHandler(produces = "application/json")`과 `produces = "text/html"`로 나눕니다. 중복으로 거부되지 않고, 에러 처리 단계의 콘텐츠 협상이 어느 쪽을 쓸지 정합니다.

## 9. 참고자료

- [Spring Framework — Exceptions (HandlerExceptionResolver)](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/exceptionhandlers.html)
- [Spring Framework — @ExceptionHandler](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-exceptionhandler.html)
- [Spring Framework — Controller Advice](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-advice.html)
- [Spring Framework — Error Responses (ProblemDetail)](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html)
- [Spring Boot — Error Handling](https://docs.spring.io/spring-boot/reference/web/servlet.html#web.servlet.spring-mvc.error-handling)
- [Spring Security — ExceptionTranslationFilter](https://docs.spring.io/spring-security/site/apidocs/org/springframework/security/web/access/ExceptionTranslationFilter.html)
- [OpenRewrite — Migrate Spring Boot properties to 4.0 (`server.error` → `spring.web.error`)](https://docs.openrewrite.org/recipes/java/spring/boot4/springbootproperties_4_0)
- 관련 챕터: day02-spring-request-flow.md, day03-api-error-format.md, day14-dto-vs-entity.md, day61-checked-unchecked.md
