# API 응답 포맷 통일하기 — 공통 봉투는 무엇을 사고 무엇을 파는가

> 이 문서가 답할 질문: **성공 응답을 공통 봉투(`ApiResponse<T>`)로 감쌀 것인가, 자원을 그대로 돌려줄 것인가?**
>
> 분류: 선택형(A vs B). 여러 출처가 공통으로 드는 비교 기준과 트레이드오프를 찾는 관점으로 조사했습니다.
>
> 기준: Spring Boot 4.1 · Spring Framework 7 (2026년 9월 확인). 에러 응답의 내용 설계는 `day03-api-error-format.md`에서 다루므로 여기서는 **성공 응답의 형태**와 **에러 포맷과의 경계**만 봅니다.

## 1. 핵심 개념 — "포맷 통일"은 봉투 이야기가 아닙니다

팀에서 "응답 포맷 통일하자"는 말이 나오면 대개 이런 클래스가 하나 생깁니다.

```json
{ "success": true, "data": { "orderId": 10293 }, "message": null }
```

그런데 이 봉투(envelope)는 통일해야 할 네 가지 중 **하나**일 뿐입니다. 나머지 셋 — 성공/실패를 어디로 알리는가, 필드를 어떻게 표기하는가, 목록을 어떤 모양으로 주는가 — 이 안 맞으면 봉투가 있어도 클라이언트는 엔드포인트마다 다르게 짜야 합니다.

> 통일이 없는 API를 붙이는 쪽에서 실제로 벌어지는 일입니다. 주문 조회는 `{ "order": {...} }`, 주문 목록은 최상위 배열, 결제 조회는 `{ "data": {...}, "resultCode": "0000" }`. 성공 판정이 세 가지라 클라이언트에 분기가 세 벌 생깁니다. 여기에 어떤 API는 실패해도 200을 주고 `success: false`를 넣습니다. **그 순간 게이트웨이·모니터링·재시도 라이브러리는 전부 그 실패를 성공으로 셉니다.** 응답 포맷은 취향 문제가 아니라, HTTP를 아는 중간 장비들이 읽는 계약입니다.

정리하면 이 문서의 선택지는 두 개입니다.

- **A안 — 봉투 없음**: 자원을 그대로 직렬화하고, 상태는 HTTP 상태 코드로 알립니다.
- **B안 — 공통 봉투**: 모든 성공 응답을 `{ "data": ... }` 한 겹으로 감쌉니다.

## 2. 구조 — 응답에서 실제로 통일해야 하는 네 가지

### 2-1. 성공/실패를 알리는 채널

**HTTP 상태 코드가 1차 채널입니다.** 본문의 `success` 필드는 보조일 수는 있어도 대체는 못 됩니다. 상태 코드를 읽는 주체가 내 클라이언트 코드만이 아니기 때문입니다. 로드밸런서의 5xx 카운트, APM의 에러율, `RestClient`의 예외 발생 여부, CDN의 캐시 여부가 전부 여기에 걸려 있습니다.

최소한 이 정도는 팀에서 합의해 둡니다.

| 상황 | 코드 | 본문 |
|---|---|---|
| 조회 성공 | 200 | 자원 |
| 생성 성공 | 201 + `Location` 헤더 | 생성된 자원 (또는 비움) |
| 삭제·상태변경 성공, 돌려줄 게 없음 | 204 | **없음** |
| 클라이언트 잘못 | 4xx | 에러 표현 |
| 서버 잘못 | 5xx | 에러 표현 |

### 2-2. 최상위는 배열이 아니라 객체

목록 응답을 최상위 JSON 배열로 주면, 나중에 페이지 정보 한 줄을 추가하는 순간 **깨지는 변경**이 됩니다. Zalando의 API 가이드라인은 이를 MUST 규칙으로 못 박습니다("MUST always return JSON objects as top-level data structures", [Rule 110](https://opensource.zalando.com/restful-api-guidelines/#110)).

이 규칙 하나 때문에 A안(봉투 없음)을 택해도 목록만큼은 뭔가로 감싸게 됩니다. 즉 **"봉투를 쓸 것인가"의 진짜 쟁점은 단건 응답입니다.**

### 2-3. 필드 표기 규약

봉투보다 클라이언트를 자주 괴롭히는 쪽입니다. 다음 다섯 개는 문서로 못 박고 전역 설정으로 강제합니다.

1. **네이밍** — `camelCase` 또는 `snake_case` 중 하나. 섞으면 클라이언트 매핑이 엔드포인트마다 달라집니다.
2. **날짜·시각** — ISO-8601 문자열로 통일하고 오프셋을 포함합니다(`2026-09-03T14:03:11+09:00`).
3. **금액** — 부동소수 금지. 정수 최소 단위(원 단위) 또는 문자열로 보냅니다.
4. **식별자** — `Long` ID를 JSON 숫자로 내보내면 JavaScript의 안전 정수 범위(`Number.MAX_SAFE_INTEGER` = 2^53-1, [MDN](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Number/MAX_SAFE_INTEGER)) 밖에서 정밀도가 깨집니다. 큰 ID는 문자열로 보냅니다.
5. **null** — 필드를 통째로 빼는가, `null`로 두는가. 하나로 정합니다.

Spring Boot 4는 Jackson 3를 기본으로 씁니다([Spring Boot — JSON](https://docs.spring.io/spring-boot/reference/features/json.html)). Jackson 3.0은 `WRITE_DATES_AS_TIMESTAMPS` 기본값을 `false`로 바꿨습니다([Migrating to Jackson 3](https://github.com/FasterXML/jackson/blob/main/jackson3/MIGRATING_TO_JACKSON_3.md)). 즉 2.x 시절 숫자 타임스탬프로 나가던 `OffsetDateTime`이 ISO-8601 문자열로 나갑니다. 규약을 코드가 아니라 라이브러리 기본값에 맡겨 뒀다면, 버전을 올리는 날 응답 포맷이 바뀝니다.

### 2-4. 컬렉션과 페이지 메타

목록은 `items`(또는 `data`)와 페이지 메타를 분리합니다. 커서 기반이라면 `nextCursor`와 `hasNext`가 들어갑니다. 이쪽 설계는 `day15-pagination-api.md`에서 다룹니다.

## 3. A안과 B안 — 무엇을 사고 무엇을 파는가

| 기준 | A. 봉투 없음 | B. 공통 봉투 |
|---|---|---|
| 응답 크기·중첩 | 얕음 | `data` 한 겹 추가 |
| 클라이언트 파싱 | 엔드포인트마다 타입이 다름 | `ApiResponse<T>` 하나로 제네릭 처리 |
| HTTP 표준 도구 | 그대로 활용 | 그대로 활용 (상태 코드를 유지한다면) |
| 공통 메타(traceId 등) 추가 | 자리가 없음 → 헤더로 | 봉투에 자리가 있음 |
| 에러 포맷과의 관계 | ProblemDetail과 자연스럽게 공존 | 봉투와 ProblemDetail이 충돌 |
| 실수 유발 | 응답 모양이 제각각이 되기 쉬움 | "항상 200" 안티패턴으로 미끄러지기 쉬움 |

**B안이 실제로 사는 것은 클라이언트의 제네릭 파싱 코드 한 벌입니다.** 안드로이드·iOS·웹이 각각 붙는 상황에서 `Response<ApiResponse<T>>` 하나로 처리되는 값은 작지 않습니다. 반대로 **파는 것은 중첩 한 겹과, 에러 표준(RFC 9457)과의 정합성**입니다.

그래서 실무에서 자주 보이는 절충이 이겁니다.

- 성공은 봉투로 감싼다 (또는 감싸지 않는다) — **팀이 정한다**
- 실패는 봉투에 넣지 않고 `application/problem+json`으로 내보낸다 — **표준을 따른다**

성공/실패 응답의 최상위 모양이 달라지는 게 이상해 보이지만, 클라이언트는 어차피 상태 코드로 먼저 분기합니다. 성공 경로와 실패 경로가 다른 타입인 것이 오히려 정직합니다.

### 3-1. 어느 쪽이든 하면 안 되는 것 — "항상 200"

```json
HTTP/1.1 200 OK
{ "success": false, "code": "ORDER_NOT_FOUND", "data": null }
```

이건 A/B 선택 문제가 아니라 그냥 손해입니다. 잃는 것을 나열하면 이렇습니다.

- APM·대시보드의 에러율이 0으로 보입니다. 장애 중에 그래프가 평온합니다.
- ALB·API Gateway의 5xx 알람이 울리지 않습니다.
- `RestClient`·`WebClient`·Feign이 예외를 던지지 않아 호출부가 정상 흐름으로 진행합니다.
- 중간 캐시가 실패 응답을 정상 응답으로 캐싱할 수 있습니다.

봉투를 쓰더라도 **상태 코드는 반드시 진실을 말해야 합니다.**

## 4. B안을 택했다면 — 손이 아니라 한 곳에서 감쌉니다

### 4-1. 코드로 보는 구성

```java
package com.example.order.api;

public record ApiResponse<T>(T data) {
    public static <T> ApiResponse<T> of(T data) {
        return new ApiResponse<>(data);
    }
}
```

```java
package com.example.order.api;

import org.springframework.core.MethodParameter;
import org.springframework.core.ResolvableType;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;

@RestControllerAdvice(basePackages = "com.example.order.api")   // 범위를 반드시 좁힙니다
public class ApiResponseWrapper implements ResponseBodyAdvice<Object> {

    @Override
    public boolean supports(MethodParameter returnType,
                            Class<? extends HttpMessageConverter<?>> converterType) {
        if (isStringBody(returnType)) {
            return false;                                        // §6-1 참고
        }
        Class<?> type = bodyType(returnType);
        return !ProblemDetail.class.isAssignableFrom(type)
                && !ApiResponse.class.isAssignableFrom(type);
    }

    @Override
    public Object beforeBodyWrite(Object body, MethodParameter returnType,
                                  MediaType selectedContentType,
                                  Class<? extends HttpMessageConverter<?>> converterType,
                                  ServerHttpRequest request, ServerHttpResponse response) {
        if (body == null) {
            return null;                                         // 204 No Content를 지킵니다
        }
        if (body instanceof ProblemDetail) {
            return body;
        }
        return ApiResponse.of(body);
    }

    private static boolean isStringBody(MethodParameter returnType) {
        return String.class.equals(bodyType(returnType));
    }

    private static Class<?> bodyType(MethodParameter returnType) {
        Class<?> type = returnType.getParameterType();
        if (ResponseEntity.class.isAssignableFrom(type)) {
            Class<?> generic = ResolvableType.forMethodParameter(returnType).getGeneric(0).resolve();
            return generic != null ? generic : Object.class;
        }
        return type;
    }
}
```

컨트롤러는 봉투를 모릅니다.

```java
@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping("/{orderId}")
    public OrderResponse get(@PathVariable Long orderId) {
        return OrderResponse.from(orderService.getById(orderId));
    }

    @PostMapping
    public ResponseEntity<OrderResponse> create(@RequestBody @Valid OrderCreateRequest request) {
        Order order = orderService.place(request.buyerId(), request.productId(), request.quantity());
        return ResponseEntity
                .created(URI.create("/orders/" + order.getId()))
                .body(OrderResponse.from(order));
    }
}
```

### 4-2. 실행 흐름

```text
1. 컨트롤러가 OrderResponse 반환
2. RequestResponseBodyMethodProcessor가 반환 타입으로 HttpMessageConverter 선택   ← 여기서 확정
3. 선택된 컨버터를 인자로 ResponseBodyAdvice.supports() 호출
4. true면 beforeBodyWrite()가 body를 ApiResponse로 교체
5. 2에서 고른 컨버터가 교체된 body를 직렬화
```

**2번이 4번보다 먼저**라는 점이 이 구조의 전부입니다. 컨버터는 원래 반환 타입을 보고 이미 정해졌는데, 본문만 나중에 바뀝니다. 여기서 §6-1의 함정이 나옵니다.

## 5. 예제

### 5-1. 컨트롤러가 직접 감싸는 코드 ❌

```java
@GetMapping("/{orderId}")
public ApiResponse<OrderResponse> get(@PathVariable Long orderId) {
    return new ApiResponse<>(true, OrderResponse.from(orderService.getById(orderId)), null);
}

@DeleteMapping("/{orderId}")
public ApiResponse<Void> cancel(@PathVariable Long orderId) {
    orderService.cancel(orderId);
    return new ApiResponse<>(true, null, "취소되었습니다");   // 200 + 의미 없는 본문
}
```

문제는 두 가지입니다. 첫째, 감싸는 걸 **사람이 기억해야 해서** 새로 들어온 엔드포인트 하나가 빠지면 그때부터 포맷이 두 개입니다. 둘째, 반환 타입이 전부 `ApiResponse<...>`로 고정되면서 201·204를 쓸 자리가 사라집니다. `message`에 한글 문구를 담는 것도 좋지 않습니다. 클라이언트가 화면에 그대로 뿌리는 순간 **문구 수정이 서버 배포**가 되고, 다국어가 막힙니다.

### 5-2. 개선한 코드 ✔️

```java
@GetMapping("/{orderId}")
public OrderResponse get(@PathVariable Long orderId) {
    return OrderResponse.from(orderService.getById(orderId));
}

@DeleteMapping("/{orderId}")
@ResponseStatus(HttpStatus.NO_CONTENT)
public void cancel(@PathVariable Long orderId) {
    orderService.cancel(orderId);
}
```

컨트롤러는 자원만 반환하고, 봉투는 §4의 어드바이스가 한 곳에서 붙입니다. 상태 코드는 상태 코드대로 씁니다. 클라이언트에게 보여줄 문구는 `code`로 내려주고 문구 자체는 클라이언트가 관리합니다.

## 6. 함정

### 6-1. `String`을 반환하는 순간 `ClassCastException`이 납니다

- **증상**: 대부분 잘 되는데 특정 엔드포인트만 500이 나고 `com.example.order.api.ApiResponse cannot be cast to java.lang.String`이 찍힙니다.
- **원인**: 반환 타입이 `String`이면 `StringHttpMessageConverter`가 먼저 선택됩니다(§4-2의 2번). 그 뒤 어드바이스가 본문을 `ApiResponse`로 바꾸지만 컨버터는 그대로라, 문자열이 아닌 객체를 받아 캐스팅에서 터집니다. Spring 팀은 이를 프레임워크 결함이 아니라 사용 방식 문제로 보고 이슈를 닫았습니다([spring-framework#25103](https://github.com/spring-projects/spring-framework/issues/25103)).
- **해법**: §4의 `supports()`처럼 `String` 본문을 아예 제외하거나, 감싸야 한다면 `ObjectMapper`로 직접 직렬화해 문자열로 되돌려 줍니다. 근본적으로는 **JSON API에서 `String`을 그대로 반환하지 않는 것**이 답입니다.

### 6-2. 봉투가 Actuator와 API 문서까지 감쌉니다

- **증상**: 봉투를 붙인 뒤 `/actuator/health`가 `{"data":{"status":"UP"}}`로 나오면서 로드밸런서 헬스체크가 실패합니다. springdoc의 `/v3/api-docs`도 감싸져 Swagger UI가 스펙을 못 읽습니다.
- **원인**: `@RestControllerAdvice`는 기본적으로 **모든 컨트롤러에 적용됩니다**. Actuator 엔드포인트와 springdoc 컨트롤러도 여기 포함됩니다([Spring Framework — Controller Advice](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-advice.html)).
- **해법**: `basePackages`·`annotations`·`assignableTypes`로 적용 범위를 내 API 패키지로 좁힙니다. 헬스체크 응답 설계는 그 자체로 별도 주제입니다.

### 6-3. 문서에는 봉투가 없습니다

- **증상**: Swagger UI의 응답 예시는 `{"orderId": 10293}`인데 실제 응답은 `{"data":{"orderId":10293}}`입니다. 이 스펙으로 클라이언트 코드를 생성하면 전부 파싱에 실패합니다.
- **원인**: springdoc은 **컨트롤러 메서드 시그니처**를 읽어 스키마를 만듭니다. 봉투는 그보다 뒤 단계인 `ResponseBodyAdvice`에서 붙으므로 문서에 나타날 방법이 없습니다.
- **해법**: `OpenApiCustomizer`로 모든 응답 스키마를 봉투로 감싸도록 문서 생성 쪽도 함께 손봅니다. 그럴 여력이 없다면 이 비용을 B안의 대가로 계산에 넣어야 합니다. 스펙 파일을 CI에서 검증하는 방법은 `day12-swagger-api-docs.md`를 참고합니다.

### 6-4. 봉투가 `ProblemDetail`을 삼킵니다

- **증상**: `@ExceptionHandler`에서 만든 RFC 9457 응답이 `{"data":{"type":"about:blank","status":404,...}}`로 나갑니다. `Content-Type`은 `application/problem+json`인데 본문 구조는 표준이 아닙니다.
- **원인**: `ResponseBodyAdvice`는 예외 핸들러가 반환한 본문에도 동작합니다. `ResponseEntityExceptionHandler`가 만들어 주는 Spring 기본 예외 응답도 마찬가지로 감싸집니다([Spring Framework — Error Responses](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html)).
- **해법**: `supports()`나 `beforeBodyWrite()`에서 `ProblemDetail`을 명시적으로 통과시킵니다(§4 코드). 에러 본문 설계는 `day03-api-error-format.md`에서 다룹니다.

### 6-5. `NON_NULL`로 필드를 감췄더니 클라이언트가 깨집니다

- **증상**: 서버는 아무것도 안 바꿨다는데 특정 주문에서만 앱이 크래시합니다. 응답을 보면 `canceledAt` 필드 자체가 없습니다.
- **원인**: `spring.jackson.default-property-inclusion=non_null`을 전역으로 켜면 값이 `null`인 필드는 **키까지 사라집니다.** "값이 null"과 "필드가 없음"을 구분하는 클라이언트에서는 다른 상황이 됩니다.
- **해법**: 전역 설정으로 켜지 말고, 응답 크기가 실제로 문제인 DTO에만 `@JsonInclude`를 붙입니다. 어느 쪽을 택하든 **API 문서에 명시**합니다. 어느 필드가 언제 사라지는지는 클라이언트가 추측할 수 없습니다.

## 7. 실무에서 찾아보는 응답 포맷

**Stripe**는 단건 응답에 봉투를 씌우지 않습니다. 자원을 그대로 주되 `object` 필드로 타입을 밝힙니다. 반면 목록은 봉투를 씌워 `object: "list"`, `data`, `has_more`, `url`을 담습니다([Stripe API — Pagination](https://docs.stripe.com/api/pagination)). §2-2에서 말한 "단건은 그대로, 목록은 감싼다"가 실제로 큰 API에서 쓰이는 형태입니다.

여기서 가져갈 점은 "Stripe처럼 하라"가 아니라, **성공 응답 봉투에는 업계 표준이 없다**는 사실입니다. 에러 쪽에는 RFC 9457이라는 표준이 있지만 성공 쪽에는 없습니다. 그러니 이건 표준을 찾아 헤맬 문제가 아니라 **팀이 정하고 문서에 적고 기계로 강제할 문제**입니다.

## 8. 정리 — 결정 순서

1. **상태 코드를 먼저 정합니다.** 이게 안 지켜지면 나머지 논의는 의미가 없습니다.
2. **에러는 RFC 9457을 따릅니다.** 여기는 이미 답이 나와 있습니다.
3. **성공 봉투는 클라이언트 수를 보고 정합니다.** 클라이언트가 여럿이고 제네릭 파싱의 이득이 크면 B안, 공개 API거나 표준 도구 친화성이 중요하면 A안입니다. 어느 쪽이든 목록은 객체로 감쌉니다.
4. **필드 표기 규약을 전역 설정으로 강제합니다.** 규약은 문서가 아니라 코드로 지켜집니다.
5. **B안을 택했으면 사람 손이 아니라 한 곳에서 감쌉니다.** 그리고 그 한 곳이 §6의 함정을 전부 지나간다는 걸 기억합니다.

봉투가 있느냐 없느냐로 API 품질이 갈리지 않습니다. **같은 질문에 항상 같은 모양으로 답하느냐**가 갈립니다.

## 9. 참고자료

- [Zalando RESTful API Guidelines — Rule 110](https://opensource.zalando.com/restful-api-guidelines/#110)
- [Spring Framework — Error Responses (RFC 9457)](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html)
- [Spring Framework — Controller Advice](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-advice.html)
- [spring-framework#25103 — ResponseBodyAdvice cannot change the selected HttpMessageConverter](https://github.com/spring-projects/spring-framework/issues/25103)
- [Spring Boot — JSON](https://docs.spring.io/spring-boot/reference/features/json.html)
- [Migrating to Jackson 3](https://github.com/FasterXML/jackson/blob/main/jackson3/MIGRATING_TO_JACKSON_3.md)
- [Stripe API — Pagination](https://docs.stripe.com/api/pagination)
- 관련 문서: `day03-api-error-format.md`, `day09-rest-api-design.md`, `day12-swagger-api-docs.md`, `day14-dto-vs-entity.md`, `day15-pagination-api.md`
