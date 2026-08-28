# 재시도가 안전하려면 — 멱등성(Idempotency)

> 이 문서가 답할 질문: **응답을 못 받아 같은 요청이 두 번 도착했을 때, 결제가 두 번 되지 않게 하려면 무엇을 보장해야 하는가?**
>
> 분류: 기술이해형(왜 존재하는가). "멱등성이 없으면 무슨 일이 벌어지는가"에서 출발해, 실무에서 실제로 멱등성을 만드는 세 가지 층까지 내려갑니다.
>
> 기준: HTTP 의미론은 [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html), 락 동작은 MySQL 8.4 InnoDB, 코드는 Spring Boot 3.x·4.x에서 모두 동작하는 API만 씁니다.

## 1. 핵심 개념 — 멱등성은 "횟수"가 아니라 "의도한 효과"에 대한 약속입니다

RFC 9110 §9.2.2는 멱등성을 이렇게 정의합니다. **같은 메서드로 동일한 요청을 여러 번 보냈을 때 서버에 의도된 효과가, 한 번 보냈을 때의 효과와 같으면 그 메서드는 멱등하다.** 이 명세가 정의하는 메서드 중에서는 PUT, DELETE, 그리고 안전한(safe) 메서드가 멱등합니다.

여기서 자주 오해하는 지점이 있습니다. **응답은 달라도 됩니다.** DELETE를 두 번 보내면 첫 번째는 `204`, 두 번째는 `404`가 나올 수 있습니다. 그래도 DELETE는 멱등합니다. 판단 기준이 응답이 아니라 서버에 남는 상태이기 때문입니다.

> 멱등성이 왜 필요한지는 타임아웃을 한 번 겪어보면 압니다. 결제 API를 호출했는데 3초 뒤 read timeout이 났습니다. 이때 서버 상태는 셋 중 하나입니다. **요청이 도착도 안 했거나, 처리 중이거나, 이미 처리가 끝났는데 응답만 못 돌아온 것입니다.** 클라이언트는 셋을 구별할 방법이 없습니다.
>
> 여기서 재시도하지 않으면 성공한 결제가 사용자에게 실패로 보입니다. 재시도하면 두 번 결제될 수 있습니다. 그리고 재시도를 안 하기로 정해도 소용없습니다. **사용자가 결제 버튼을 다시 누릅니다.** 로드밸런서도 누릅니다. 배치 스케줄러도 누릅니다.
>
> 즉 "재시도를 할까 말까"는 선택지가 아닙니다. 재시도는 이미 일어나고 있고, 우리가 정할 수 있는 건 **재시도가 안전한지 여부**뿐입니다.

멱등성은 그래서 성능 최적화나 부가 기능이 아니라, 분산 시스템에서 **"모름" 상태를 복구 가능하게 만드는 유일한 수단**입니다.

## 2. 구조 — 멱등성은 세 개의 층에서 만들어집니다

멱등성을 "Idempotency-Key 헤더"와 동일시하기 쉬운데, 그건 세 번째 층입니다. 앞의 두 층으로 해결되면 키 테이블을 만들 필요가 없습니다.

| 층 | 무엇으로 보장하는가 | 비용 |
|---|---|---|
| 1. 메서드 | 메서드 의미론 자체 (PUT/DELETE) | 없음 |
| 2. 자원 설계 | 식별자·상태 전이·조건부 요청 | 스키마 설계 |
| 3. 요청 식별자 | 클라이언트가 만든 키 + 서버 저장소 | 테이블, 만료 관리, 지연 |

### 2-1. 메서드 층 — 인프라가 이미 이 계약을 따르고 있습니다

이건 문서상의 약속이 아니라 실제로 동작에 반영되는 계약입니다. RFC 9110은 **프록시가 멱등하지 않은 요청을 자동 재시도해서는 안 된다(MUST NOT)** 고 못박습니다.

nginx가 정확히 그렇게 구현되어 있습니다. `proxy_next_upstream`의 기본값은 `error timeout`인데, 요청이 이미 업스트림으로 전송된 상태라면 POST·PATCH·LOCK은 다음 서버로 넘기지 않습니다. 넘기게 하려면 `non_idempotent` 파라미터를 명시적으로 켜야 합니다([nginx 문서](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_next_upstream), 1.9.13부터).

```nginx
# 이 한 줄을 켜면 nginx가 POST도 다른 업스트림으로 재전송합니다.
proxy_next_upstream error timeout non_idempotent;
```

반대로 내가 GET을 멱등하게 만들지 않았다면(예: 조회 API가 조회수를 올린다면) 이 계약을 이미 어긴 겁니다. 프록시와 클라이언트 라이브러리는 GET을 마음대로 재시도합니다.

### 2-2. 자원 설계 층 — POST를 PUT으로 바꾸면 키가 필요 없습니다

가장 값싼 멱등성은 **식별자를 클라이언트가 정하게 하는 것**입니다.

```
POST /orders                 → 서버가 ID 생성. 두 번 부르면 주문 2개
PUT  /orders/{clientOrderId} → 클라이언트가 ID 결정. 두 번 불러도 주문 1개
```

두 번째 방식은 별도 저장소가 필요 없습니다. 주문 테이블의 `client_order_id` 유니크 인덱스가 곧 멱등성 저장소입니다.

상태 전이를 조건에 넣는 방법도 있습니다. **"바꿔라"가 아니라 "이 상태였으면 바꿔라"로 쓰면** 두 번째 실행은 0건 갱신으로 끝납니다.

```sql
-- 두 번 실행해도 결과가 같습니다. 두 번째는 갱신 0건입니다.
UPDATE orders
   SET status = 'CANCELED', canceled_at = NOW(6)
 WHERE order_id = ? AND status = 'PAID';
```

갱신 건수가 0이면 "이미 취소됨"이므로 성공으로 처리할지 판단할 수 있습니다. 값을 누적하는 연산(`balance = balance - 100`)만이 이 방법으로 안 되고, 그때 3번 층이 필요합니다.

### 2-3. 요청 식별자 층 — Idempotency-Key

누적 연산이거나 외부 결제 게이트웨이를 호출하는 경우처럼 **재실행 자체가 부작용인 작업**에는 요청마다 고유한 키를 받습니다.

Stripe가 사실상 표준을 만들었습니다. `Idempotency-Key` 요청 헤더로 클라이언트가 만든 키를 받고, **첫 요청의 상태 코드와 응답 본문을 저장했다가 이후 같은 키의 요청에 그대로 돌려줍니다. 500 에러였어도 그 500을 돌려줍니다.** 키는 최대 255자이며 V4 UUID를 권장하고, 최소 24시간이 지난 키는 삭제될 수 있습니다. 같은 키에 다른 파라미터가 오면 오류로 처리합니다. POST만 지원하며 GET·DELETE에는 의미가 없습니다([Stripe API 문서](https://docs.stripe.com/api/idempotent_requests)).

IETF에서 표준화 작업도 진행 중입니다. `draft-ietf-httpapi-idempotency-key-header-07`(2025-10-15, Standards Track)은 키가 처리 중일 때 `409`, 같은 키에 다른 페이로드가 오면 `422`, 키가 필수인데 없으면 `400`을 제안합니다([IETF 초안](https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-07.html)). 다만 **아직 RFC가 아닙니다.** 상태 코드는 참고하되 표준으로 인용하면 안 됩니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

키 저장소부터 봅니다. 핵심은 딱 하나, **유니크 제약**입니다.

```sql
CREATE TABLE idempotency_record (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    user_id         BIGINT       NOT NULL,
    idem_key        VARCHAR(255) NOT NULL,
    fingerprint     CHAR(64)     NOT NULL,   -- 요청 본문 SHA-256
    status          VARCHAR(20)  NOT NULL,   -- IN_PROGRESS / COMPLETED
    response_status SMALLINT     NULL,
    response_body   JSON         NULL,
    created_at      DATETIME(6)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_key (user_id, idem_key),
    KEY idx_created_at (created_at)
) ENGINE = InnoDB;
```

`user_id`를 유니크 키에 넣은 이유는 §10 함정에서 다룹니다.

```java
@Component
@RequiredArgsConstructor
public class IdempotencyStore {

    private final JdbcTemplate jdbc;

    /** 처음 보는 키면 true, 이미 있으면 false. 비즈니스 트랜잭션과 분리해 즉시 커밋합니다. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean tryBegin(long userId, String idemKey, String fingerprint) {
        try {
            jdbc.update("""
                    INSERT INTO idempotency_record
                        (user_id, idem_key, fingerprint, status, created_at)
                    VALUES (?, ?, ?, 'IN_PROGRESS', NOW(6))
                    """, userId, idemKey, fingerprint);
            return true;
        } catch (DuplicateKeyException e) {
            return false;
        }
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void complete(long userId, String idemKey, int httpStatus, String body) {
        jdbc.update("""
                UPDATE idempotency_record
                   SET status = 'COMPLETED', response_status = ?, response_body = ?
                 WHERE user_id = ? AND idem_key = ?
                """, httpStatus, body, userId, idemKey);
    }

    /** 결과를 확정할 수 없을 때 키를 지워 재시도를 허용합니다. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void abandon(long userId, String idemKey) {
        jdbc.update("DELETE FROM idempotency_record WHERE user_id = ? AND idem_key = ?",
                userId, idemKey);
    }

    // Optional<IdempotencyRecord> find(long userId, String idemKey) { ... 생략 }
}
```

`REQUIRES_NEW`로 별도 트랜잭션을 쓰는 이유가 중요합니다. 키 기록이 비즈니스 트랜잭션에 묶여 있으면 **커밋 전까지는 중복 요청이 이 키를 볼 수 없습니다.** 두 번째 요청의 INSERT는 락을 기다리며 커넥션과 스레드를 붙잡고, 첫 트랜잭션이 5초짜리라면 5초를 통째로 대기합니다.

이제 조율하는 쪽입니다.

```java
@Service
@RequiredArgsConstructor
public class PaymentFacade {

    private final IdempotencyStore store;
    private final PaymentService paymentService;  // @Transactional이 걸린 실제 결제 로직
    private final ObjectMapper objectMapper;

    public PaymentResponse pay(long userId, String idemKey, PaymentRequest request) {
        String fingerprint = sha256(request);

        if (!store.tryBegin(userId, idemKey, fingerprint)) {
            IdempotencyRecord found = store.find(userId, idemKey)
                    .orElseThrow(() -> new IllegalStateException("키가 방금 회수되었습니다"));

            if (!found.fingerprint().equals(fingerprint)) {
                throw new KeyReusedException();      // 같은 키, 다른 요청 → 422
            }
            if (found.status() == Status.IN_PROGRESS) {
                throw new RequestInFlightException(); // 아직 처리 중 → 409
            }
            return read(found.responseBody());        // 저장된 결과를 그대로 재생
        }

        try {
            PaymentResponse response = paymentService.pay(userId, request);
            store.complete(userId, idemKey, 200, write(response));
            return response;
        } catch (BusinessException e) {
            // 잔액 부족 같은 확정된 실패도 "결과"입니다. 재시도해도 같은 답이 나와야 합니다.
            store.complete(userId, idemKey, e.status(), write(e.body()));
            throw e;
        } catch (RuntimeException e) {
            // 원인을 확정할 수 없는 실패 — 키를 지워 재시도를 허용합니다.
            store.abandon(userId, idemKey);
            throw e;
        }
    }

    // String sha256(PaymentRequest r), String write(Object o), PaymentResponse read(String s)
    // ... 생략 (ObjectMapper + MessageDigest)
}
```

여기서 갈리는 판단이 하나 있습니다. **비즈니스 실패는 결과로 저장하고, 원인 불명 실패는 키를 지웁니다.** 잔액 부족은 몇 번을 다시 물어도 잔액 부족이므로 저장해서 재생하는 게 맞습니다. 반대로 DB 커넥션 타임아웃은 결제가 됐는지 안 됐는지 우리도 모르므로 저장하면 안 됩니다.

### 3-2. 실행 흐름

```
[정상 첫 요청]
요청(key=K) → INSERT K (IN_PROGRESS) 커밋 → 결제 실행 → UPDATE K (COMPLETED, 응답 저장) → 200

[응답을 못 받은 클라이언트가 같은 K로 재시도]
요청(key=K) → INSERT 실패(DuplicateKey) → 조회 → COMPLETED → 저장된 200 재생
                                                └ IN_PROGRESS → 409 (잠시 후 다시 시도하라)
                                                └ fingerprint 불일치 → 422

[결제 중 서버가 죽음]
K는 IN_PROGRESS로 남음 → 재시도는 계속 409 → 회수 배치가 오래된 IN_PROGRESS를 정리해야 함
```

마지막 줄이 이 구조의 가장 약한 고리입니다.

## 4. 특징

### 4-1. 어느 층을 쓸지 고르는 기준

| 상황 | 선택 |
|---|---|
| 조회, 삭제, 전체 교체 | 1층. 메서드 의미론대로 구현만 하면 끝 |
| 생성인데 클라이언트가 ID를 만들 수 있음 | 2층. `PUT /orders/{id}` + 유니크 인덱스 |
| 상태 전이 (취소, 승인, 발송) | 2층. `WHERE status = ...` 조건부 갱신 |
| 잔액 증감, 포인트 적립, 외부 결제 호출 | 3층. Idempotency-Key |
| 클라이언트가 우리 통제 밖 (외부 파트너) | 3층. 계약으로 키를 요구 |

### 4-2. 3층의 대가

- **쓰기가 두 번 늘어납니다.** 요청당 INSERT 1회 + UPDATE 1회가 추가됩니다.
- **저장소가 무한히 자랍니다.** 만료 정책이 없으면 이 테이블이 제일 큰 테이블이 됩니다.
- **응답을 통째로 저장합니다.** 응답에 개인정보가 들어 있으면 보관 기간이 곧 개인정보 보관 기간이 됩니다.
- **서버 혼자서는 완성할 수 없습니다.** 키는 클라이언트가 만듭니다. 3층 멱등성은 서버 기능이 아니라 **클라이언트와 맺는 계약**이고, 이게 본질적인 한계입니다.

## 5. 예제 — 조회 후 삽입은 왜 틀렸는가

### 5-1. 클린하지 않은 코드 ❌

```java
// ❌ 조회 → 없으면 삽입. 단일 스레드 테스트에서는 완벽하게 동작합니다.
@Transactional
public PaymentResponse pay(long userId, String idemKey, PaymentRequest request) {
    Optional<IdempotencyRecord> found = store.find(userId, idemKey);
    if (found.isPresent()) {
        return read(found.get().responseBody());
    }
    store.insert(userId, idemKey);          // (A)
    PaymentResponse response = paymentService.pay(userId, request);
    store.complete(userId, idemKey, 200, write(response));
    return response;
}
```

문제는 조회와 삽입 사이의 틈입니다. 두 요청이 거의 동시에 오면 **둘 다 `find`에서 빈 결과를 받고, 둘 다 (A)를 통과하고, 둘 다 결제합니다.** 사용자가 버튼을 빠르게 두 번 누르는 상황이 정확히 그 조건입니다.

유니크 제약이 없으면 (A)의 INSERT 두 개가 모두 성공하므로 코드로는 막을 수 없습니다. `synchronized`를 걸어도 서버가 두 대면 소용없습니다.

### 5-2. 개선한 코드 ✔️

```java
// ✔️ 먼저 삽입하고, 성공한 쪽만 진짜 처리를 진행합니다.
//    "누가 처음인가"의 판정을 애플리케이션이 아니라 DB 유니크 제약에 맡깁니다.
if (!store.tryBegin(userId, idemKey, fingerprint)) {
    return replayOrReject(userId, idemKey, fingerprint);
}
PaymentResponse response = paymentService.pay(userId, request);
store.complete(userId, idemKey, 200, write(response));
return response;
```

바뀐 건 순서 하나입니다. **확인하고 실행하는 대신, 실행 권한을 먼저 따냅니다.** 서버가 몇 대든 DB 인덱스는 하나이므로 승자는 반드시 한 명입니다.

## 6. 멱등성 키가 지키는 계약 — 키는 요청이 아니라 "결과"를 소유합니다

키를 "이미 처리했는지 표시하는 플래그"로 이해하면 절반만 구현하게 됩니다. 키가 소유해야 하는 건 **그 요청이 만들어낸 결과 전체**입니다.

### 6-1. 계약을 어긴 코드 ❌

```java
// ❌ 중복이면 200 OK와 빈 본문을 돌려줍니다.
if (!store.tryBegin(userId, idemKey, fingerprint)) {
    return ResponseEntity.ok().build();
}
```

클라이언트 입장에서 이건 재앙입니다. 재시도한 클라이언트는 `paymentId`를 못 받으므로, 결제가 됐는지 확인할 방법이 없습니다. **재시도를 안전하게 만들려던 기능이 재시도한 클라이언트만 결과를 모르게 만들었습니다.**

### 6-2. 계약을 지킨 코드 ✔️

```java
// ✔️ 원래 응답을 그대로 재생하고, 재생임을 헤더로 알립니다.
IdempotencyRecord found = store.find(userId, idemKey).orElseThrow();

if (!found.fingerprint().equals(fingerprint)) {
    // 같은 키로 다른 요청을 보냈다 — 클라이언트의 키 생성 로직이 잘못된 것입니다.
    return ResponseEntity.unprocessableEntity().body(problem("idempotency-key-reused"));
}
if (found.status() == Status.IN_PROGRESS) {
    return ResponseEntity.status(409).body(problem("request-in-flight"));
}
return ResponseEntity.status(found.responseStatus())
        .header("Idempotent-Replayed", "true")
        .body(found.responseBody());
```

지문(fingerprint) 검증이 왜 필요한지가 핵심입니다. 키가 같은데 요청 본문이 다르다면 둘 중 하나가 반드시 사고입니다. 클라이언트가 키를 재사용했거나, 키가 충돌했거나. **여기서 조용히 이전 결과를 돌려주면 "1만 원 결제 요청에 100원 결제 결과가 돌아오는" 일이 생깁니다.** 에러 응답 포맷은 `day03-api-error-format.md`의 규칙을 그대로 씁니다.

## 8. 실무에서 찾아보는 멱등성

같은 개념이 계층마다 다른 이름으로 이미 들어가 있습니다.

| 시스템 | 이름 | 동작 | 유효 범위 |
|---|---|---|---|
| Stripe | `Idempotency-Key` 헤더 | 첫 응답(에러 포함)을 저장 후 재생 | 최소 24시간 |
| Kafka Producer | `enable.idempotence` | 브로커가 시퀀스 번호로 중복 배치 제거 | 프로듀서 세션 |
| SQS FIFO | `MessageDeduplicationId` | 같은 ID의 후속 메시지를 받되 전달하지 않음 | 5분 |
| nginx | `proxy_next_upstream` | 멱등하지 않은 메서드는 기본적으로 재전송 안 함 | 요청 단위 |

Kafka는 3.0부터 `enable.idempotence` 기본값이 `true`입니다. 켜면 `acks=all`, `retries > 0`, `max.in.flight.requests.per.connection <= 5`가 강제되고, 충돌하는 설정을 명시하면서 멱등성도 명시하면 `ConfigException`이 납니다([Kafka 프로듀서 설정 문서](https://kafka.apache.org/41/configuration/producer-configs/)). **프로듀서 재시도로 인한 중복은 기본적으로 막혀 있다**는 뜻인데, 이게 컨슈머까지의 exactly-once를 의미하지는 않습니다.

SQS FIFO의 중복 제거 창은 **5분**이며, 메시지를 수신하고 삭제한 뒤에도 그 ID는 계속 추적됩니다([AWS 문서](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/using-messagededuplicationid-property.html)). 6분 뒤에 온 재시도는 새 메시지입니다. **인프라의 중복 제거는 언제나 시간 창이 있고, 그 창 밖에서는 애플리케이션이 책임집니다.**

## 9. 관련 개념과 비교

| 개념 | 무엇을 보장하나 | 멱등성과의 관계 |
|---|---|---|
| 안전(safe) | 서버 상태를 바꾸지 않음 | 안전하면 반드시 멱등. 역은 아님 (PUT은 멱등하지만 안전하지 않음) |
| 중복 제거(dedup) | 일정 시간 창 안의 동일 메시지 1회 처리 | 시간 제한이 있는 멱등성. 창을 벗어나면 깨짐 |
| exactly-once | 정확히 한 번 처리 | 전달은 at-least-once로 두고 **처리를 멱등하게** 만들어 흉내 내는 것 |
| 낙관적 락 | 내가 읽은 버전이 그대로일 때만 갱신 | 서로 다른 요청의 충돌을 막음. 같은 요청의 중복은 못 막음 |

네 번째 줄이 헷갈리기 쉽습니다. 낙관적 락(`@Version`, HTTP의 `If-Match`)은 **다른 사람의 동시 수정**을 막는 장치입니다. 같은 요청을 두 번 보내는 상황은 버전이 이미 올라간 뒤이므로 두 번째가 거부되긴 하지만, 클라이언트는 "충돌"인지 "내 재시도"인지 구별할 수 없습니다. 목적이 다릅니다.

## 10. 함정

**함정 1 — 유니크 제약 없는 키 테이블**

- **증상**: 로컬과 스테이징에서는 완벽한데, 프로덕션 트래픽에서 하루에 몇 건씩 중복 결제가 생깁니다.
- **원인**: 키 컬럼에 유니크 인덱스가 없습니다. 조회-후-삽입은 동시 요청에서 항상 깨집니다.
- **해법**: 유니크 제약을 걸고 삽입 실패(`DuplicateKeyException`)를 판정 신호로 씁니다. 판정을 애플리케이션이 하면 안 됩니다.

**함정 2 — 같은 키로 세 개 이상이 동시에 몰리면 데드락 ⚠️**

- **증상**: 중복 방지는 되는데 `Deadlock found when trying to get lock` 로그가 간헐적으로 찍힙니다.
- **원인**: InnoDB에서 INSERT는 삽입한 행에 배타 락을 겁니다. 중복 키 오류가 나면 **그 인덱스 레코드에 공유 락**이 걸립니다. 세션 1이 삽입하고 커밋 전인 상태에서 세션 2·3이 같은 키를 삽입하면 둘 다 공유 락 대기에 들어가고, 세션 1이 롤백하는 순간 둘 다 공유 락을 얻지만 서로 때문에 배타 락으로 승격하지 못해 데드락이 납니다([MySQL 8.4 문서](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html)).
- **해법**: 키 삽입 트랜잭션을 최대한 짧게 잡습니다(`REQUIRES_NEW`로 분리해 즉시 커밋). 롤백 경로를 줄이는 것도 같은 효과입니다. 그래도 발생하므로 데드락 예외를 잡아 "중복 요청"으로 처리하는 경로를 둡니다.

**함정 3 — 키에 사용자 스코프가 없음**

- **증상**: 드물게 다른 사용자의 결제 결과가 응답으로 나갑니다.
- **원인**: 키를 전역 유니크로 잡았습니다. 클라이언트가 UUID 대신 `order-1` 같은 값을 보내면 다른 사용자와 충돌합니다. 그리고 우리는 클라이언트의 키 생성 로직을 통제할 수 없습니다.
- **해법**: 유니크 키를 `(user_id, idem_key)`로 잡습니다. 키를 인증 주체에 종속시키면 남의 키를 추측해도 남의 결과가 나가지 않습니다.

**함정 4 — 죽은 IN_PROGRESS가 영원히 남음**

- **증상**: 배포 직후 특정 사용자가 몇 번을 시도해도 계속 `409`를 받습니다.
- **원인**: 결제 처리 도중 파드가 종료되어 `IN_PROGRESS` 레코드가 완료로 바뀌지 못했습니다. 이후 모든 재시도가 "처리 중"으로 판정됩니다. 종료 처리는 `day18-graceful-shutdown.md`의 문제와 이어집니다.
- **해법**: `created_at`이 일정 시간(예: 처리 타임아웃의 2배)을 넘긴 `IN_PROGRESS`를 회수하는 배치를 둡니다. 회수 전에 실제 처리 결과를 확인할 수 있으면 확인 후 확정하고, 확인할 수 없으면 삭제해 재시도를 허용합니다. **회수 배치가 없으면 이 설계는 미완성입니다.**

**함정 5 — 클라이언트가 재시도할 때마다 새 키를 만듦**

- **증상**: 서버는 완벽하게 구현했는데 중복이 계속 생깁니다.
- **원인**: 클라이언트가 요청을 보낼 때마다 `UUID.randomUUID()`를 호출합니다. 재시도인데 키가 다르면 서버 입장에서는 새 요청입니다.
- **해법**: 키는 **재시도 루프 바깥에서 한 번만** 생성합니다. 화면에서 시작하는 요청이라면 사용자가 결제 화면에 진입한 시점에 발급해 두는 편이 안전합니다. 이건 서버 코드로 강제할 수 없으므로 API 문서에 명시해야 합니다.

**함정 6 — 만료 정책 없음**

- **증상**: 키 테이블이 수억 행이 되고, 유니크 인덱스가 메모리에서 밀려나면서 INSERT가 느려집니다.
- **원인**: 삭제 정책 없이 계속 쌓았습니다.
- **해법**: 보관 기간을 정하고(Stripe는 최소 24시간 기준) `created_at` 인덱스로 나눠서 삭제합니다. 보관 기간은 곧 **재시도가 안전한 기간**이므로, 클라이언트 재시도 정책보다 넉넉해야 합니다. 응답 본문에 개인정보가 있다면 보관 기간을 짧게 잡을 이유가 하나 더 생깁니다.

## 11. 참고자료

- [RFC 9110 §9.2.2 Idempotent Methods](https://www.rfc-editor.org/rfc/rfc9110.html#name-idempotent-methods)
- [Stripe API — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [draft-ietf-httpapi-idempotency-key-header-07 (IETF 초안, RFC 아님)](https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-07.html)
- [MySQL 8.4 — Locks Set by Different SQL Statements in InnoDB](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html)
- [Apache Kafka Producer Configs — enable.idempotence](https://kafka.apache.org/41/configuration/producer-configs/)
- [Amazon SQS — Using the message deduplication ID](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/using-messagededuplicationid-property.html)
- [nginx — proxy_next_upstream](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_next_upstream)
- 관련 문서: `day09-rest-api-design.md`(재시도 안전성 관점의 API 설계), `day03-api-error-format.md`(409·422 응답 포맷), `day20-service-layer-design.md`(트랜잭션 경계)
