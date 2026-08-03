# HTTP 요청 한 개가 컨트롤러까지 오는 과정

> 이 문서가 답할 질문: **클라이언트가 보낸 HTTP 요청 한 개는 어떤 단계를 거쳐 내가 만든 `@GetMapping` 메서드에 도착하고, 그 반환값은 어떻게 JSON 응답이 되는가?**
>
> 기준 버전: Spring Boot 4.1.0 / Spring Framework 7.0.x / Jakarta EE 11(Servlet 6.1). Spring Boot 3.2 이상에서 동작이 갈리는 지점은 본문에 따로 표시했습니다.

## 1. 핵심 개념

Spring MVC는 **프론트 컨트롤러(Front Controller) 패턴**으로 설계돼 있습니다. 모든 HTTP 요청을 서블릿 하나가 받고, 실제 일은 교체 가능한 위임 컴포넌트들이 나눠 합니다. 그 서블릿이 `DispatcherServlet`입니다. ([Spring Framework Reference — DispatcherServlet](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet.html))

`@RestController`는 서블릿이 아닙니다. 애플리케이션에 등록된 서블릿은 사실상 `DispatcherServlet` 하나뿐이고, 컨트롤러 클래스는 그 서블릿이 리플렉션으로 호출하는 **평범한 스프링 빈**입니다.

> 이 구조를 모르면 디버깅이 통째로 막힙니다. 필터의 예외가 `@RestControllerAdvice`에 안 잡히는 이유, 브레이크포인트가 안 걸리고 404가 나는 이유, traceId가 에러 응답에서만 비어 있는 이유 모두 "그 코드가 요청 경로의 어느 지점에서 도는가"로 결정됩니다.

## 2. 구조

요청은 성격이 다른 두 층을 차례로 지납니다. 이 경계가 이 챕터의 전부라고 해도 과언이 아닙니다.

**서블릿 컨테이너 층** (Tomcat) — Spring을 모릅니다.

| 구성요소 | 역할 |
|---|---|
| 커넥터(Connector) | 소켓에서 바이트를 읽어 HTTP 메시지로 파싱 |
| 요청 처리 스레드 | 파싱된 요청 하나를 담당할 스레드 배정 |
| 필터 체인(`Filter`) | 서블릿 호출 전후를 감쌈. Servlet 표준 스펙 |
| 서블릿(`DispatcherServlet`) | 필터를 다 통과한 요청의 최종 도착지 |

**Spring MVC 층** — `DispatcherServlet` 안쪽입니다. 여기서부터는 전부 스프링 빈입니다.

| 특별 빈 | 역할 |
|---|---|
| `HandlerMapping` | 요청을 핸들러 + 인터셉터 목록으로 매핑. `@RequestMapping`은 `RequestMappingHandlerMapping`이 담당 |
| `HandlerAdapter` | 핸들러가 어떤 모양이든 `DispatcherServlet`이 동일하게 호출하도록 감쌈 |
| `HandlerExceptionResolver` | 처리 중 발생한 예외를 응답으로 변환 |
| `ViewResolver` | 논리 뷰 이름을 실제 `View` 객체로 해석 |
| `LocaleResolver` | 클라이언트 `Locale`·타임존 결정 |
| `MultipartResolver` | `multipart/form-data` 파싱 |
| `FlashMapManager` | 리다이렉트 사이로 속성 전달 |

([Special Bean Types](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/special-bean-types.html))

REST API만 만드는 팀은 `ViewResolver`·`FlashMapManager`를 사실상 안 씁니다. `@ResponseBody`가 붙은 반환값은 뷰를 거치지 않고 `HandlerAdapter` 안에서 응답 본문까지 다 써버리기 때문입니다(3-2에서 다시 봅니다).

### 2-1. 확장 지점

경로 위에 끼어들 수 있는 자리가 층마다 하나씩 있습니다.

- **`Filter`** — 컨테이너 층. `HttpServletRequest`/`Response`를 **감싸서 바꿔치기할 수 있는 유일한 자리**입니다(요청 본문 캐싱, 응답 압축, CORS).
- **`HandlerInterceptor`** — MVC 층. 어느 핸들러가 선택됐는지 **알고 나서** 도는 자리입니다.
- **`HandlerMethodArgumentResolver`** — 컨트롤러 파라미터 하나를 어떻게 채울지 결정합니다. `@Valid`로 바인딩·검증을 위임하는 것도 이 자리입니다(5절).
- **`HttpMessageConverter`** — 본문 바이트 ↔ 객체 변환. `@RequestBody`, `HttpEntity`가 이걸 씁니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

경로를 눈으로 보려면 각 층에 로그를 하나씩 심어보는 게 가장 빠릅니다.

```java
// src/main/java/com/example/order/web/RequestIdFilter.java (OncePerRequestFilter)
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 100)
public class RequestIdFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestIdFilter.class);

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String requestId = UUID.randomUUID().toString().substring(0, 8);
        request.setAttribute("requestId", requestId);
        log.info("[{}] filter in  - {} {}", requestId, request.getMethod(), request.getRequestURI());
        try {
            chain.doFilter(request, response);
        } finally {
            // 응답 상태 코드는 체인이 되돌아온 뒤에야 확정됩니다.
            log.info("[{}] filter out - status={}", requestId, response.getStatus());
        }
    }
}
```

```java
// src/main/java/com/example/order/web/HandlerLoggingInterceptor.java (HandlerInterceptor)
@Component
public class HandlerLoggingInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(HandlerLoggingInterceptor.class);

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // 필터에서는 알 수 없던 정보입니다. 여기서는 어떤 메서드가 뽑혔는지 이미 정해졌습니다.
        if (handler instanceof HandlerMethod handlerMethod) {
            log.info("[{}] handler   - {}#{}",
                    request.getAttribute("requestId"),
                    handlerMethod.getBeanType().getSimpleName(),
                    handlerMethod.getMethod().getName());
        }
        return true;
    }
}
// WebMvcConfigurer.addInterceptors()에서 registry.addInterceptor(this).addPathPatterns("/orders/**")로 등록합니다.
```

```java
// src/main/java/com/example/order/web/OrderController.java
@RestController
public class OrderController {

    public record OrderResponse(Long orderId, String status) {}

    @GetMapping("/orders/{orderId}")
    public ResponseEntity<OrderResponse> find(@PathVariable Long orderId) {
        return ResponseEntity.ok(new OrderResponse(orderId, "PAID"));
    }
}
```

`GET /orders/1001`을 호출하면 로그 순서가 `filter in → handler → filter out`으로 찍힙니다. 필터가 인터셉터를 **감싸고 있다**는 사실이 이 순서로 드러납니다.

### 3-2. 실행 흐름

큰 경로부터 봅니다.

```text
소켓 → Tomcat 커넥터 → 요청 스레드 배정 → Filter 체인 → DispatcherServlet
     → HandlerMapping → Interceptor.preHandle → HandlerAdapter
     → ArgumentResolver → 컨트롤러 메서드 → ReturnValueHandler(+ MessageConverter)
     → Interceptor.postHandle → afterCompletion → Filter 체인 복귀 → 응답 전송
```

`DispatcherServlet` 안쪽은 공식 문서가 순서를 명시하고 있습니다. ([Processing](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/sequence.html))

1. `WebApplicationContext`를 요청 속성으로 바인딩합니다. 컨트롤러가 컨테이너에 접근하는 통로입니다.
2. `LocaleResolver`를 요청에 바인딩합니다. 국제화가 필요 없으면 실질적으로 하는 일이 없습니다.
3. `MultipartResolver`가 있으면 멀티파트 여부를 검사해 요청을 `MultipartHttpServletRequest`로 **감쌉니다.**
4. 핸들러(인터셉터+핸들러)를 실행합니다. **애노테이션 컨트롤러는 뷰 대신 `HandlerAdapter` 안에서 응답을 직접 렌더링할 수 있습니다.**
5. 모델이 반환된 경우에만 뷰를 렌더링합니다.
6. 처리 중 예외는 `HandlerExceptionResolver` 빈들이 해석합니다.

4번의 굵은 부분이 REST API에서 가장 중요합니다. `@ResponseBody`(또는 `ResponseEntity`)를 반환하면 5번으로 가지 않습니다. `RequestResponseBodyMethodProcessor`가 `HttpMessageConverter`로 객체를 JSON 바이트로 써버리고, `ModelAndView`는 `null`로 돌아옵니다. **`ViewResolver`는 아예 호출되지 않습니다.**

파라미터가 채워지는 지점도 짚어둘 만합니다. `@PathVariable Long orderId`에서 `"1001"`이 `Long`이 되는 건 컨트롤러 코드가 아니라 `HandlerAdapter`가 부르는 `HandlerMethodArgumentResolver`가 하는 일입니다. 형변환 실패는 컨트롤러 진입 **전에** 터집니다. 브레이크포인트가 컨트롤러 첫 줄에서 안 걸리는 상황의 절반은 이겁니다.

### 3-3. 로그로 흐름을 직접 보기

추측하지 말고 프레임워크가 말하게 하는 게 빠릅니다.

```yaml
# application.yml
logging:
  level:
    web: debug          # Spring Boot의 web 로깅 그룹
```

Spring Boot 문서는 이 설정으로 **등록된 필터의 순서와 URL 패턴이 기동 시점에 로그로 남는다**고 명시합니다. ([Servlet Web Applications](https://docs.spring.io/spring-boot/reference/web/servlet.html))

요청 처리 중에는 대략 이런 로그가 남습니다(정확한 문구는 버전마다 다릅니다).

```text
DEBUG DispatcherServlet             : GET "/orders/1001", parameters={}
DEBUG RequestMappingHandlerMapping  : Mapped to OrderController#find(Long)
DEBUG DispatcherServlet             : Completed 200 OK
```

`Mapped to`가 안 보이면 요청이 컨트롤러까지 못 온 겁니다. 필터·경로·HTTP 메서드를 의심할 차례이지 컨트롤러 코드를 볼 차례가 아닙니다.

한 가지 주의할 점: **DEBUG/TRACE 레벨에서 요청 파라미터와 헤더는 기본적으로 마스킹됩니다.** 민감 정보 유출을 막기 위한 기본값이라, 다 보려면 `spring.mvc.log-request-details=true`를 켜야 하고 그래서 프로덕션에서는 켜지 않습니다.

매핑 전체를 표로 보고 싶으면 Actuator의 `/actuator/mappings`로 한 번에 확인할 수 있습니다.

## 4. 특징

### 4-1. 이 구조가 실제로 주는 것

**(1) 횡단 관심사를 컨트롤러 밖으로 뺄 수 있습니다.** 인증, 로깅, 트레이스 ID, CORS는 필터나 인터셉터 하나면 끝납니다.

**(2) 컨트롤러가 HTTP를 거의 안 봅니다.** 파라미터 추출·형변환·JSON 파싱이 전부 프레임워크로 넘어가고, 컨트롤러엔 도메인 호출만 남습니다.

**(3) 각 단계가 전부 교체 가능합니다.** `HandlerMapping`, `HandlerAdapter`, `HttpMessageConverter`가 전부 인터페이스라, Spring은 애노테이션 컨트롤러와 함수형 라우팅을 같은 `DispatcherServlet` 아래에서 굴립니다.

### 4-2. 대신 지불하는 비용

| 비용 | 실무에서 나타나는 모습 |
|---|---|
| 스택 깊이 | 예외 스택트레이스가 수십~수백 줄. 내 코드 줄을 찾는 데 시간이 걸림 |
| 층 경계의 비직관성 | 필터·인터셉터·`@ControllerAdvice`의 예외 처리 범위가 다름(6절) |
| 암묵적 동작 | 파라미터 바인딩·컨버터 선택이 코드에 안 보임. 안 되면 왜 안 되는지도 안 보임 |
| 요청 = 스레드 | 요청 하나가 스레드 하나를 점유. 느린 외부 호출이 곧 스레드 고갈 |

마지막 항목은 Spring Boot 3.2부터 선택지가 생겼습니다. `spring.threads.virtual.enabled=true`(Java 21+)를 켜면 Tomcat이 요청마다 가상 스레드를 씁니다. 흐름 자체는 그대로이고, 그 경로를 타는 스레드의 종류만 바뀝니다.

<!-- TODO: 가상 스레드 활성화 시 Tomcat 동작은 2차 자료만 확인했습니다. Spring Boot 4.1 레퍼런스 원문 확인 필요. -->

## 5. 예제 — 컨트롤러가 HTTP 파싱을 떠안을 때

### 5-1. 흐름을 모르고 쓴 코드 ❌

```java
// ❌ 프레임워크가 이미 해주는 일을 컨트롤러에서 손으로 다시 합니다
@RestController
public class OrderController {

    private final OrderService orderService; // 생성자 주입, 이하 생략

    @GetMapping("/orders")
    public ResponseEntity<?> search(HttpServletRequest request) {
        String memberIdParam = request.getParameter("memberId");
        if (memberIdParam == null) {
            return ResponseEntity.badRequest().body("memberId is required");
        }
        Long memberId;
        try {
            memberId = Long.valueOf(memberIdParam);
        } catch (NumberFormatException e) {
            return ResponseEntity.badRequest().body("memberId must be a number");
        }

        String sizeParam = request.getParameter("size");
        int size = (sizeParam == null) ? 20 : Integer.parseInt(sizeParam);  // 여기는 검증이 빠졌습니다

        return ResponseEntity.ok(orderService.search(memberId, size));
    }
}
```

문제가 세 가지입니다. 첫째, 반환 타입이 `?`라서 정상 응답과 에러 응답의 형태가 컨트롤러마다 제각각이 됩니다. 둘째, `size` 쪽 `parseInt`는 예외를 안 잡아서 500이 나갑니다. **같은 종류의 잘못된 입력이 400이 되기도 하고 500이 되기도 합니다.** 셋째, 이 검증 코드가 컨트롤러 수만큼 복제됩니다.

### 5-2. 각 단계에 일을 되돌려준 코드 ✔️

```java
// ✅ 바인딩·검증은 ArgumentResolver에, 에러 응답 형식은 한 곳에 맡깁니다
@GetMapping("/orders")
public ResponseEntity<List<OrderResponse>> search(@Valid OrderSearchRequest request) {
    return ResponseEntity.ok(orderService.search(request.memberId(), request.size()));
}
```

```java
// ✅ 타입 변환 실패와 검증 실패가 한 형식으로 나갑니다
@RestControllerAdvice
public class ApiExceptionHandler extends ResponseEntityExceptionHandler {

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException ex, HttpHeaders headers,
            HttpStatusCode status, WebRequest request) {
        String detail = ex.getBindingResult().getFieldErrors().stream()
                .map(e -> e.getField() + ": " + e.getDefaultMessage())
                .collect(Collectors.joining(", "));
        return ResponseEntity.badRequest()
                .body(ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, detail));
    }
}
```

`OrderSearchRequest`는 `memberId`에 `@NotNull`, `size`에 `@Min`/`@Max`를 붙인 record입니다(`@Valid`로 검증). `memberId=abc`가 들어오면 이제 컨트롤러에 **들어오기 전에** 바인딩 단계에서 걸리고, `ResponseEntityExceptionHandler`가 정해진 형식으로 400을 만듭니다. 컨트롤러는 요청이 이미 유효하다는 전제 위에서만 동작합니다.

## 6. 관련 개념과 비교 — 예외는 어디서 잡히는가

세 지점의 차이를 "예외가 어디로 가는가"로 보면 한 번에 정리됩니다.

| 던진 위치 | `@RestControllerAdvice`가 잡는가 | 실제로 응답을 만드는 것 |
|---|---|---|
| `Filter` (`chain.doFilter` 이전) | ❌ 못 잡음 | 서블릿 컨테이너 → `/error` 포워드 → `BasicErrorController` |
| `HandlerInterceptor.preHandle` | ✅ 잡음 | `HandlerExceptionResolver` |
| `HandlerMethodArgumentResolver` | ✅ 잡음 | `HandlerExceptionResolver` |
| 컨트롤러 메서드 | ✅ 잡음 | `HandlerExceptionResolver` |
| `@ResponseBody` 직렬화 중 | 부분적 | 응답 커밋 이후면 손쓸 수 없음 |

경계는 딱 하나입니다. **`@ControllerAdvice`는 `DispatcherServlet` 안쪽만 봅니다.** 필터는 바깥이라 예외가 컨테이너까지 올라가고, Spring Boot의 글로벌 에러 페이지 `/error`(`BasicErrorController`)로 포워드됩니다.

정리하면: MVC 계층 내부 예외 → `@RestControllerAdvice` + `ResponseEntityExceptionHandler`, 필터 실패·컨테이너 레벨 404 → `ErrorController`/`ErrorAttributes`.

**둘 중 하나만 두면 응답 형식이 갈립니다.** API가 항상 `ProblemDetail`을 반환한다고 문서에 써놓고, 인증 필터가 터졌을 때만 Whitelabel HTML이 나가는 상황이 여기서 생깁니다.

## 7. 함정

### 함정 1 — 필터에서 던진 예외가 `@RestControllerAdvice`에 안 잡힙니다

- **증상**: JWT 검증 필터에서 `InvalidTokenException`을 던졌는데, 정해둔 JSON 에러 포맷 대신 Whitelabel 에러 페이지나 밋밋한 500이 돌아옵니다.
- **원인**: 필터는 `DispatcherServlet` **바깥**입니다. 예외가 컨테이너까지 올라가 `/error`로 포워드되고, `@ControllerAdvice`는 이 경로를 볼 수 없습니다.
- **해법**: (a) 인증 실패를 필터 안에서 직접 응답으로 씁니다(`response.setStatus(401)` 후 `ObjectMapper`로 본문 작성, 예외를 밖으로 안 던짐). (b) `HandlerExceptionResolver`를 필터에 주입해 위임합니다(Spring Security라면 `AuthenticationEntryPoint`). 어느 쪽이든 `/error` 응답 형식도 API 포맷에 맞춰야 안전합니다.

### 함정 2 — 요청 본문을 필터에서 읽었더니 컨트롤러에서 빈 값이 옵니다

- **증상**: 감사 로그를 남기려고 필터에서 `request.getInputStream()`을 읽었습니다. 로그는 잘 남는데 컨트롤러의 `@RequestBody` 객체 필드가 전부 `null`이거나 `HttpMessageNotReadableException`이 납니다.
- **원인**: 서블릿 요청 본문은 **한 번만 읽을 수 있는 스트림**입니다. 필터가 다 읽어버리면 뒤에 오는 `HttpMessageConverter`가 읽을 게 없습니다.
- **해법**: `ContentCachingRequestWrapper`로 요청을 감싸 `chain.doFilter`에 넘기고, 본문은 `chain.doFilter` **이후에** `getContentAsByteArray()`로 꺼냅니다. 요청을 감싸는 필터는 순서 제약도 있습니다. Spring Boot 문서는 **래핑 필터는 `OrderedFilter.REQUEST_WRAPPER_FILTER_MAX_ORDER` 이하로 두라**고 명시합니다.

### 함정 3 — 에러 응답에서만 traceId가 비어 있습니다

- **증상**: 정상 응답 로그에는 요청 ID가 붙는데, 500이 난 요청의 `/error` 처리 로그에는 없습니다. MDC 기반 로깅이라면 에러 로그만 컨텍스트가 비어 보입니다.
- **원인**: `OncePerRequestFilter`는 `shouldNotFilterErrorDispatch()`가 기본 `true`라 **에러 디스패치에서는 필터가 다시 돌지 않습니다.** (Spring Boot 3.2부터 빈은 모든 `DispatcherType`으로 등록되지만, 필터 자신이 ERROR 디스패치를 건너뜁니다.)
- **해법**: `shouldNotFilterErrorDispatch()`를 `false`로 오버라이드합니다. 단, 같은 요청에 필터 본문이 두 번 실행되므로 ID 생성 같은 로직은 이미 값이 있으면 재사용해야 하고, MDC는 `finally`에서 꼭 `clear()`합니다. 요청 스레드가 풀로 재사용돼 남은 값이 **다음 요청 로그에 섞이기 때문입니다.**

### 함정 4 — 없는 URL을 부르면 내 에러 포맷이 아니라 다른 게 나옵니다

- **증상**: `/api/orderss` 같은 오타 경로가 `ProblemDetail`이 아니라 Whitelabel 페이지나 기본 JSON으로 응답됩니다.
- **원인**: 매핑되는 핸들러가 없으면 요청은 정적 리소스 핸들러로 넘어가고, 거기서도 못 찾으면 `NoResourceFoundException`(Spring Framework 6.1+)이 발생합니다. `DefaultHandlerExceptionResolver`가 404로 처리하는 예외라 우리가 만든 핸들러를 안 거칩니다. (예전에 쓰던 `spring.mvc.throw-exception-if-no-handler-found`는 Boot 3.4 이후 제거됐습니다.)
- **해법**: `ResponseEntityExceptionHandler`를 상속한 `@RestControllerAdvice`에서 `NoResourceFoundException`을 오버라이드합니다. `/error`(`BasicErrorController`) 쪽 응답 형식도 맞춰야 필터에서 난 404·401까지 포맷이 통일됩니다. 함정 1과 같은 처방입니다.

## 8. 참고자료

- [DispatcherServlet](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet.html) · [Processing](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/sequence.html) · [Special Bean Types](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-servlet/special-bean-types.html) — 프론트 컨트롤러 구조, 처리 순서, 특별 빈 역할
- [Method Arguments](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-methods/arguments.html) · [Filters](https://docs.spring.io/spring-framework/reference/web/webmvc/filters.html) — 파라미터 해석, 내장 필터
- [Spring Boot Servlet Web Applications](https://docs.spring.io/spring-boot/reference/web/servlet.html) — 필터 순서 규칙, DEBUG 로깅, `/error` 기본 처리
- 관련 챕터: `day01-jvm-why.md` — 이 요청 흐름이 도는 런타임 자체에 대한 이야기
