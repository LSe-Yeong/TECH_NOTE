# 실무 REST의 현실 — 무엇을 지키고 무엇을 버리는가

> 이 문서가 답할 질문: **원칙대로 만든 REST API가 실무에 거의 없다면, 우리는 대체 무엇을 기준으로 API를 설계해야 하는가?**
>
> 기준: RFC 9110(HTTP Semantics, 2022) · RFC 5789(PATCH) · RFC 7396(JSON Merge Patch) · RFC 6902(JSON Patch)

## 1. 핵심 개념 — REST는 규칙집이 아니라 제약의 이름입니다

REST는 Roy Fielding이 정의한 **아키텍처 스타일**입니다. 규격서가 아니라 몇 가지 제약(클라이언트-서버, 무상태, 캐시, 계층화, 균일한 인터페이스)의 묶음입니다. 그중 가장 강한 제약이 하이퍼미디어입니다. Fielding은 이걸 못 박아 뒀습니다.

> "if the engine of application state (and hence the API) is not being driven by hypertext, then it cannot be RESTful and cannot be a REST API. Period." ([REST APIs must be hypertext-driven](https://roy.gbiv.com/untangled/2008/rest-apis-must-be-hypertext-driven))

이 기준을 곧이곧대로 적용하면 **여러분이 지금까지 만든 API는 대부분 REST가 아닙니다.** 그리고 그건 대체로 문제가 아닙니다.

문제는 다른 데서 생깁니다. 코드 리뷰에서 "이건 RESTful하지 않은데요"라는 말이 나오고, 30분 동안 `POST /orders/{id}/cancel`이냐 `PATCH /orders/{id}`냐를 놓고 논쟁합니다. 그러는 동안 정작 클라이언트가 실제로 겪는 고통은 아무도 안 다룹니다.

> 클라이언트가 진짜 겪는 고통은 이런 것들입니다. **타임아웃 난 결제 요청을 다시 보내도 되는지 모른다. 400이 떨어졌는데 내 잘못인지 서버 잘못인지 모른다. 필드 하나 추가됐다고 앱이 죽는다.** REST 순수성 논쟁은 이 중 무엇도 풀어주지 않습니다. 이 문서는 이름 붙이기 대신 **재시도 안전성·오류 판별 가능성·변경 내성** 세 가지를 설계 기준으로 놓습니다.

## 2. 실무는 Level 2에서 멈췄습니다

Leonard Richardson이 만들고 Martin Fowler가 정리한 성숙도 모델이 현재 위치를 보여줍니다 ([Richardson Maturity Model](https://martinfowler.com/articles/richardsonMaturityModel.html)).

| 레벨 | 이름 | 실제 모습 |
|---|---|---|
| 0 | The Swamp of POX | 엔드포인트 하나에 POST만. HTTP는 터널 |
| 1 | Resources | URI가 자원별로 나뉨. 메서드는 여전히 POST |
| 2 | HTTP Verbs | 메서드와 상태 코드를 의미대로 사용 |
| 3 | Hypermedia Controls | 응답에 다음 행동 링크(HATEOAS) 포함 |

실무에서 "REST API"라고 부르는 것은 거의 전부 Level 2입니다. Level 3은 왜 안 갔을까요. 비난할 일이 아니라 이유가 있습니다.

- **클라이언트가 링크를 안 따라갑니다.** 앱 개발자는 응답의 `_links.cancel`을 보고 분기하지 않습니다. OpenAPI 문서를 보고 URL을 하드코딩합니다. 서버가 링크를 아무리 잘 넣어도 소비하는 쪽이 없으면 순수 비용입니다.
- **코드 생성 도구가 기준이 됐습니다.** 스키마에서 클라이언트를 생성하는 방식이 표준이 되면서, 런타임 탐색이 아니라 **빌드 타임 계약**이 결합을 관리하는 수단이 됐습니다.
- **모바일 앱은 강제 업데이트가 안 됩니다.** 서버가 URI를 바꿔도 구버전 앱은 그대로 남습니다. Fielding이 말한 "서버가 네임스페이스를 통제한다"가 성립하지 않습니다.

**결론:** Level 3은 목표가 아닙니다. 다만 Level 2를 제대로 하는 것과 Level 2인 척하는 것은 완전히 다릅니다. 아래부터가 그 차이입니다.

## 3. 기준 1 — 메서드는 취향이 아니라 계약입니다

### 3-1. 안전성과 멱등성

RFC 9110은 두 성질을 정의합니다 ([RFC 9110 §9.2](https://www.rfc-editor.org/rfc/rfc9110.html#name-common-method-properties)).

- **안전(safe)**: "요청이 정보 조회만을 의도하며 원 서버의 상태를 바꾸지 않는" 메서드. GET·HEAD·OPTIONS.
- **멱등(idempotent)**: "같은 요청을 여러 번 보냈을 때 서버에 대한 의도된 효과가 한 번 보낸 것과 같은" 메서드. GET·HEAD·PUT·DELETE.

| 메서드 | 안전 | 멱등 | 자동 재시도 |
|---|:---:|:---:|---|
| GET / HEAD | ✔️ | ✔️ | 가능 |
| PUT | ❌ | ✔️ | 가능 |
| DELETE | ❌ | ✔️ | 가능 |
| POST | ❌ | ❌ | **불가** |
| PATCH | ❌ | ❌ | **불가** |

이 표가 왜 중요한가. RFC 9110은 연결 실패 시 **클라이언트가 멱등 요청을 자동으로 재시도할 수 있다**고 규정합니다. 즉 이건 문서상의 분류가 아니라 **HTTP 클라이언트 라이브러리·로드밸런서·서비스 메시가 실제로 따르는 동작**입니다. `POST`를 멱등하게 만들지 않은 채 재시도 정책을 켜면 주문이 두 번 들어갑니다.

PATCH가 멱등이 아닌 이유는 명확합니다. RFC 5789는 PATCH 본문을 "리소스를 어떻게 수정할지 기술한 명령의 집합"으로 정의합니다. `{"op":"add","path":"/tags/-","value":"urgent"}`를 두 번 보내면 태그가 두 개 붙습니다.

### 3-2. 표준 메서드로 안 되는 동작

주문 취소, 결제 승인, 비밀번호 재설정. 이런 건 CRUD로 안 떨어집니다. 억지로 `PATCH /orders/{id}` 에 `{"status":"CANCELLED"}`를 밀어 넣으면 이런 일이 생깁니다.

- 취소는 재고 복구·환불·알림을 동반하는데, 필드 하나 바꾸는 것처럼 보입니다.
- 클라이언트가 `{"status":"DELIVERED"}`를 보내면 어떻게 됩니까. 상태 필드를 쓰기 가능하게 열어둔 순간 **모든 상태 전이가 API 표면이 됩니다.**

Google의 API 설계 가이드는 이 경우 커스텀 메서드를 허용하되 조건을 답니다. "커스텀 메서드는 표준 메서드로 쉽게 표현할 수 없는 기능에만 써야 하며, 일관된 의미론 때문에 가능하면 표준 메서드를 선호한다"입니다. URI 문법은 콜론입니다 ([AIP-136 Custom methods](https://google.aip.dev/136)).

```
POST /v1/publishers/{publisher}/books/{book}:archive
```

콜론이 낯설면 서브리소스 형태(`POST /orders/{orderId}/cancellation`)도 괜찮습니다. **중요한 건 표기법이 아니라 "이 동작이 별도의 권한·검증·감사 대상"이라는 사실이 URI에 드러나는 것**입니다. 팀 안에서 하나만 고르고 끝까지 밀면 됩니다.

## 4. 기준 2 — 재시도가 안전한 API

POST는 멱등이 아닙니다. 그런데 네트워크는 응답을 잃어버립니다. 클라이언트는 "요청이 도착 못 한 건지, 처리는 됐는데 응답만 유실된 건지" 구분할 수 없습니다. 여기서 중복 주문이 태어납니다.

업계 표준 해법은 **클라이언트가 만든 키로 요청을 식별하는 것**입니다. Stripe의 구현이 사실상의 레퍼런스입니다 ([Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)).

- `Idempotency-Key` 헤더에 클라이언트가 생성한 고유 키(V4 UUID 권장, 최대 255자)를 담습니다.
- 서버는 **첫 요청의 상태 코드와 응답 본문을 저장합니다.** 성공이든 실패든 저장합니다. 같은 키로 다시 오면 저장된 결과를 그대로 돌려줍니다. `500`도 그대로 재현됩니다.
- 같은 키인데 파라미터가 다르면 **오류를 반환합니다.** 실수로 키를 재사용하는 걸 막기 위해서입니다.
- 키는 최소 24시간 뒤 삭제될 수 있습니다. 그 뒤 재사용하면 새 요청으로 처리됩니다.
- `GET`·`DELETE`에는 보내지 않습니다. 이미 멱등입니다.

⚠️ **`Idempotency-Key`는 IETF 표준이 아닙니다.** httpapi 워킹그룹의 인터넷 드래프트로 진행되다 07판(2025-10-15)을 끝으로 만료됐고, RFC가 되지 않았습니다 ([draft-ietf-httpapi-idempotency-key-header](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)). 널리 쓰이는 관행일 뿐이므로, 문서에 "표준 헤더"라고 쓰지 말고 동작을 직접 명세해야 합니다.

```java
@PostMapping("/orders")
public ResponseEntity<OrderResponse> place(
        @RequestHeader("Idempotency-Key") String idempotencyKey,
        @Valid @RequestBody PlaceOrderRequest request) {

    // 키 + 요청 지문을 유니크 제약으로 건 테이블에 먼저 선점 INSERT.
    // 이미 있으면 저장된 응답을 그대로 반환합니다.
    return idempotencyStore.findResponse(idempotencyKey)
            .map(saved -> ResponseEntity.status(saved.statusCode())
                                        .body(saved.body(OrderResponse.class)))
            .orElseGet(() -> {
                OrderResponse created = orderService.place(request);
                idempotencyStore.save(idempotencyKey, request.fingerprint(), 201, created);
                return ResponseEntity.created(URI.create("/orders/" + created.id()))
                                     .body(created);
            });
}
```

**핵심은 저장소를 비즈니스 트랜잭션과 같은 DB에 두는 것**입니다. Redis에 키를 두고 주문은 RDB에 쓰면, 둘 사이에서 프로세스가 죽는 순간 보장이 깨집니다. 유니크 제약 위반을 "이미 처리됨"으로 해석하는 방식이 가장 단순하고 안전합니다.

## 5. 기준 3 — 상태 코드는 클라이언트의 분기문입니다

상태 코드는 장식이 아닙니다. 클라이언트의 재시도·로깅·알림이 여기서 갈립니다. 실무에서 실제로 필요한 것만 추리면 이 정도입니다.

| 코드 | 쓰는 순간 | 클라이언트가 할 일 |
|---|---|---|
| 200 | 조회·수정 성공, 본문 있음 | 본문 사용 |
| 201 | 생성됨. `Location` 헤더로 위치를 알림 | 새 리소스 참조 |
| 202 | 접수만 함. 처리는 나중 | 상태 폴링 |
| 204 | 성공, 돌려줄 본문 없음 | 아무것도 파싱하지 않음 |
| 400 | 문법이 깨진 요청(JSON 파싱 실패 등) | 고쳐서 보내야 함. 재시도 무의미 |
| 401 / 403 | 인증 없음 / 권한 없음 | 재인증 vs 포기 |
| 404 | 리소스 없음 | 포기 |
| 405 | 이 리소스가 그 메서드를 지원 안 함 | 코드 버그 |
| 409 | 현재 상태와 충돌(이미 취소된 주문) | 상태 재조회 |
| 422 | 문법은 맞는데 의미가 틀림(수량이 음수) | 입력 수정 |
| 429 / 503 | 과부하 | `Retry-After` 보고 백오프 |

두 가지만 짚습니다.

**400과 422를 구분합니다.** RFC 9110은 422를 "요청 본문의 콘텐츠 타입은 이해했지만 담긴 지시를 처리할 수 없음"으로 정의합니다. 파싱 실패는 400, 검증 실패는 422입니다. 프레임워크 기본값을 따라 전부 400으로 내보내도 동작은 합니다. 다만 **모든 걸 400으로 만들면 클라이언트는 어떤 400이 재시도 가능한지 판단할 수 없습니다.**

**409는 "다시 읽어라"라는 신호입니다.** 이미 취소된 주문을 또 취소하면 404도 400도 아닙니다. 리소스는 있고 요청도 올바른데 현재 상태가 안 맞는 것입니다. RFC 5789도 PATCH를 현재 상태에 적용할 수 없을 때 409를 지목합니다.

응답 **본문**의 포맷은 별도 주제입니다. RFC 9457 Problem Details와 안정적인 오류 코드 설계는 `daily/day03-api-error-format.md`에서 다룹니다.

## 6. 기준 4 — 전체 교체(PUT)와 부분 수정(PATCH)

RFC 5789의 구분이 정확합니다. PUT 본문은 "리소스의 수정된 전체 버전"이고, PATCH 본문은 "어떻게 수정할지 기술한 명령의 집합"입니다.

실무에서 사고가 나는 지점은 **PATCH를 흉내 낸 PUT**입니다.

```java
// ❌ PUT인데 전달된 필드만 반영한다
@PutMapping("/members/{id}")
public MemberResponse update(@PathVariable Long id, @RequestBody MemberRequest request) {
    Member member = memberRepository.findById(id).orElseThrow();
    if (request.nickname() != null) {
        member.changeNickname(request.nickname());   // null이면 건너뛴다
    }
    return MemberResponse.from(member);
}
```

두 가지가 동시에 망가집니다. 첫째, PUT의 의미(전체 교체)를 어겼으니 **멱등성 보장도 근거를 잃습니다.** 둘째, `null`을 "안 보냄"으로 해석했기 때문에 **필드를 의도적으로 비우는 방법이 사라집니다.** 닉네임을 지우고 싶은 사용자는 방법이 없습니다.

부분 수정이 필요하면 PATCH를 쓰되, **본문 형식을 정하고 문서에 씁니다.** 표준화된 선택지가 둘 있습니다.

| 형식 | 미디어 타입 | 삭제 표현 | 특징 |
|---|---|---|---|
| JSON Merge Patch ([RFC 7396](https://www.rfc-editor.org/rfc/rfc7396.html)) | `application/merge-patch+json` | `null` | 단순. 배열은 통째 교체만 가능 |
| JSON Patch ([RFC 6902](https://www.rfc-editor.org/rfc/rfc6902.html)) | `application/json-patch+json` | `remove` 연산 | `add`·`remove`·`replace`·`move`·`copy`·`test` 6개 연산. 배열 원소 조작 가능 |

```json
// merge-patch: 닉네임 변경 + 소개글 삭제
{ "nickname": "코드짜는곰", "bio": null }
```

```json
// json-patch: 낙관적 검사 후 변경
[
  { "op": "test",    "path": "/version",  "value": 7 },
  { "op": "replace", "path": "/nickname", "value": "코드짜는곰" },
  { "op": "remove",  "path": "/bio" }
]
```

JSON Patch의 `test` 연산은 낙관적 동시성 제어를 본문 안에서 표현할 수 있게 해줍니다. 다만 클라이언트가 쓰기 번거롭고, 서버 검증 로직도 복잡해집니다. **대부분의 내부 API는 merge-patch로 충분합니다.**

어느 쪽이든 RFC 5789의 원자성 규칙은 지켜야 합니다. 패치를 적용할 수 없으면 **서버는 어떤 변경도 적용하면 안 됩니다.** 절반만 반영된 리소스가 가장 나쁩니다.

## 7. 기준 5 — 버전은 URI에 붙이는 순간 끝이 아닙니다

`/v1/orders`는 편합니다. 캐시·라우팅·로그가 전부 URI를 보니까요. Fielding은 이걸 명시적으로 반대하지만, 현실에서 URI 버전은 가장 널리 쓰이는 방식입니다.

**진짜 문제는 표기법이 아니라 "무엇을 깨지는 변경으로 볼 것인가"입니다.** 여기가 정해져 있지 않으면 `/v1`이든 헤더든 소용없습니다. 실제 사례 두 개가 답을 보여줍니다.

- **GitHub**: `X-GitHub-Api-Version: 2022-11-28` 같은 날짜 기반 버전을 헤더로 받습니다. **깨지는 변경만 새 버전으로 나가고, 추가적(additive) 변경은 지원 중인 모든 버전에 반영됩니다.** 새 버전 출시 후 이전 버전을 최소 24개월 지원하며, 지원 종료된 버전을 지정하면 400을 돌려줍니다 ([GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)).
- **Stripe**: `Stripe-Version` 헤더로 날짜 기반 버전을 받습니다. 월간 릴리스는 하위 호환 변경만 담고, 하위 호환이 깨지는 변경은 이름 붙은 메이저 릴리스로만 나갑니다. 2026년 8월 기준 현재 버전은 `2026-07-29.dahlia`입니다 ([Stripe API versioning](https://docs.stripe.com/api/versioning)).

두 회사의 공통점은 **"필드 추가는 깨지는 변경이 아니다"를 계약으로 못 박았다**는 점입니다. 그래야 서버가 움직일 수 있습니다. 대신 클라이언트에 의무가 생깁니다. **모르는 필드를 만나면 무시해야 합니다.** Jackson 기준으로는 `FAIL_ON_UNKNOWN_PROPERTIES`를 끄는 것이고, 이건 서버가 아니라 **API를 소비하는 쪽에 적용할 설정**입니다.

버전을 걷어낼 때는 헤더로 예고합니다. `Deprecation` 헤더는 RFC 9745, `Sunset` 헤더는 RFC 8594로 표준화돼 있습니다. Deprecation은 "이 시점부터 폐기 예정", Sunset은 "이 시점에 응답을 멈춤"이고, **Sunset 시각은 Deprecation 시각보다 앞설 수 없습니다** ([RFC 9745](https://www.rfc-editor.org/info/rfc9745/)).

## 8. 예제 — 주문 취소 API를 다시 설계하기

### 8-1. 클린하지 않은 설계 ❌

```java
@PostMapping("/api/orderCancel")
public Map<String, Object> cancelOrder(@RequestBody Map<String, Object> body) {
    Long orderId = Long.valueOf(body.get("orderId").toString());
    try {
        orderService.cancel(orderId);
        return Map.of("result", "OK");
    } catch (Exception e) {
        return Map.of("result", "FAIL", "message", e.getMessage());  // 항상 200
    }
}
```

한 화면씩 보면 큰 문제가 없어 보입니다. 실제로는 다섯 가지가 깨져 있습니다.

1. URI가 자원이 아니라 **동작 이름**입니다. Level 1도 못 갔습니다.
2. 재시도가 안전한지 알 방법이 없습니다. 네트워크가 끊기면 클라이언트는 보낼지 말지를 찍어야 합니다.
3. 모든 응답이 200입니다. 모니터링이 실패를 못 봅니다(함정 1).
4. `Map`이 응답 타입이라 **스키마가 없습니다.** 필드 이름을 바꿔도 컴파일이 통과합니다.
5. 예외 메시지를 그대로 내보냅니다. 클라이언트가 문자열 비교로 분기하기 시작하고, 그 순간 메시지가 API 계약이 됩니다. 스택트레이스가 새어 나가면 보안 문제이기도 합니다.

### 8-2. 개선한 설계 ✔️

```java
@PostMapping("/v1/orders/{orderId}/cancellation")
public ResponseEntity<CancellationResponse> cancel(
        @PathVariable Long orderId,
        @RequestHeader("Idempotency-Key") String idempotencyKey,
        @Valid @RequestBody CancelOrderRequest request) {

    CancellationResult result = orderCancelService.cancel(orderId, idempotencyKey, request.reason());
    return ResponseEntity.ok(CancellationResponse.from(result));
}
```

```java
@RestControllerAdvice
public class OrderExceptionHandler {

    // 이미 취소됐거나 배송이 시작된 주문 → 현재 상태와의 충돌
    @ExceptionHandler(OrderStateConflictException.class)
    public ProblemDetail handleConflict(OrderStateConflictException e) {
        ProblemDetail problem = ProblemDetail.forStatus(HttpStatus.CONFLICT);
        problem.setType(URI.create("https://example.com/problems/order-state-conflict"));
        problem.setTitle("주문 상태가 취소를 허용하지 않습니다");
        problem.setProperty("currentStatus", e.currentStatus());   // 클라이언트가 분기할 값
        return problem;
    }
}
```

바뀐 것은 URI 모양이 아닙니다. **클라이언트가 판단할 수 있는 정보가 생겼습니다.**

- 취소는 주문의 서브리소스로 표현되어, 별도 권한·감사 대상임이 URI에 드러납니다.
- `Idempotency-Key`가 필수라서 타임아웃 후 재전송이 안전합니다.
- 409를 받으면 "다시 조회하라", 422를 받으면 "입력을 고쳐라"로 자동 분기됩니다.
- `currentStatus`가 함께 오므로 클라이언트가 메시지 문자열을 파싱할 이유가 없습니다.

## 9. 함정

**함정 1 — 200 안에 실패를 담는다**

- **증상**: 모든 응답이 `200 OK`인데 본문에 `{"success": false, "code": "OUT_OF_STOCK"}`이 들어 있습니다. 모니터링 대시보드의 에러율이 0%인데 CS 문의는 계속 들어옵니다.
- **원인**: 상태 코드를 "HTTP 통신이 성공했는가"로 해석했습니다. HTTP는 애플리케이션 프로토콜이지 전송 계층이 아닙니다. 프록시·APM·로드밸런서는 전부 상태 코드로 판단합니다.
- **해법**: 실패는 4xx/5xx로 냅니다. 관측 도구가 공짜로 붙습니다. 클라이언트 코드도 `if (response.success)` 대신 언어의 예외 처리에 올라탑니다.

**함정 2 — 재시도 정책을 켜놓고 POST를 방치한다**

- **증상**: 결제가 간헐적으로 두 번 잡힙니다. 재현이 안 되고, 로그를 보면 요청이 실제로 두 번 들어와 있습니다.
- **원인**: HTTP 클라이언트나 게이트웨이의 재시도가 켜져 있는데 POST 엔드포인트에 멱등 보장이 없습니다. 서버는 응답을 만들었지만 네트워크에서 유실됐고, 클라이언트는 실패로 판단해 다시 보냈습니다.
- **해법**: 상태를 바꾸는 POST에 `Idempotency-Key`를 요구합니다. 당장 어렵다면 **최소한 재시도 정책을 메서드별로 분리**해 POST/PATCH를 자동 재시도 대상에서 빼야 합니다.

**함정 3 — DB 테이블이 그대로 URI가 된다**

- **증상**: 화면 하나 그리는 데 API를 6번 호출합니다. 모바일에서 유독 느립니다.
- **원인**: 리소스를 "도메인 개념"이 아니라 "테이블"로 잡았습니다. REST는 테이블을 노출하라는 뜻이 아닙니다.
- **해법**: 리소스는 클라이언트가 다루는 개념 단위로 잡습니다. 주문 상세 화면이 항상 주문·배송·결제를 함께 쓴다면 그건 세 리소스가 아니라 하나입니다. 반대로 무한정 키우면 응답이 비대해지니, **화면이 아니라 유스케이스 단위**가 기준입니다.

**함정 4 — 페이지네이션을 offset으로만 만든다**

- **증상**: 뒷페이지로 갈수록 느려지고, 사용자가 목록을 보는 사이 새 글이 등록되면 항목이 중복되거나 건너뛰어 보입니다.
- **원인**: `?page=N&size=20`은 요청 시점마다 기준점이 달라집니다. 데이터가 계속 들어오는 목록에서는 안정적인 순서가 없습니다.
- **해법**: 정렬 키 기준의 커서 방식으로 바꿉니다. 다만 **응답에 `nextCursor`를 넣는 습관부터 들이는 게 먼저입니다.** 클라이언트가 커서를 받아 쓰는 구조여야 나중에 내부 구현을 바꿀 수 있습니다. 상세 비교는 `08-system-design/20-pagination-api`에서 다룹니다.

**함정 5 — 예제 응답이 곧 명세라고 믿는다**

- **증상**: 서버가 `null`이던 필드를 빈 배열로 바꿨는데 앱이 크래시합니다. "우린 아무것도 안 깼는데요"라는 말이 나옵니다.
- **원인**: 명세에 "이 필드가 null이 될 수 있는가", "이 배열이 비어 있을 수 있는가"가 안 적혀 있었습니다. 클라이언트는 예제 응답 한 개를 보고 타입을 추론했습니다.
- **해법**: OpenAPI 스키마에 `required`와 `nullable`을 실제로 채웁니다. 그리고 **깨지는 변경의 정의를 팀 문서에 한 문단으로 못 박습니다.** "필드 추가는 비파괴, 필드 삭제·타입 변경·enum 값 추가는 파괴" 수준이면 충분합니다. enum 값 추가가 왜 파괴적인지는, 모르는 값을 만나면 죽는 클라이언트 파서를 한 번 보면 압니다.

## 10. 정리

- REST의 진짜 정의를 만족하는 실무 API는 거의 없습니다. Level 2가 사실상의 표준이고, **그걸 인정하고 시작하는 편이 논쟁보다 생산적입니다.**
- 메서드 선택은 취향이 아닙니다. 멱등성은 **클라이언트 라이브러리와 인프라가 실제로 재시도 여부를 결정하는 근거**입니다.
- POST를 멱등하게 만드는 표준은 없습니다. `Idempotency-Key`는 관행이며 드래프트는 만료됐습니다. 그래서 **직접 명세하고 직접 저장해야 합니다.**
- 상태 코드는 클라이언트의 분기문입니다. 400/409/422를 구분하는 이유는 정확성이 아니라 **재시도 가능 여부를 알려주기 위해서**입니다.
- PUT은 전체 교체입니다. 부분 수정이 필요하면 PATCH를 쓰고 본문 형식(merge-patch / json-patch)을 문서에 명시합니다.
- 버전 관리의 본질은 URI냐 헤더냐가 아니라 **"무엇이 깨지는 변경인가"를 계약으로 정하는 것**입니다.

## 11. 참고자료

- [RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)
- [RFC 5789 — PATCH Method for HTTP](https://www.rfc-editor.org/rfc/rfc5789.html)
- [RFC 7396 — JSON Merge Patch](https://www.rfc-editor.org/rfc/rfc7396.html)
- [RFC 6902 — JSON Patch](https://www.rfc-editor.org/rfc/rfc6902.html)
- [RFC 9745 — The Deprecation HTTP Response Header Field](https://www.rfc-editor.org/info/rfc9745/)
- [Roy Fielding — REST APIs must be hypertext-driven](https://roy.gbiv.com/untangled/2008/rest-apis-must-be-hypertext-driven)
- [Martin Fowler — Richardson Maturity Model](https://martinfowler.com/articles/richardsonMaturityModel.html)
- [Google AIP-136 — Custom methods](https://google.aip.dev/136)
- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [GitHub REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- 오류 응답 본문 설계는 `daily/day03-api-error-format.md`에서 다룹니다.
