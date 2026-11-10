# 검증은 어느 계층에서 하는가

> 이 문서가 답할 질문: **"값이 올바른가"라는 검사를 요청 DTO·컨트롤러 파라미터·서비스·엔티티 중 어디에 두어야 하고, 그 선택이 던져지는 예외와 응답 상태 코드를 어떻게 바꾸는가?**
>
> 분류: **선택형.** "어디에 둘 것인가"가 본문이고, 각 지점의 증상은 그 선택의 결과로 다룹니다.
>
> 기준: Spring Framework 7.0.x / Spring Boot 4.1.x / Hibernate Validator 9.1.x(Jakarta Validation 3.1.1). 버전이 갈리는 부분은 본문에 표시합니다.
>
> 에러 응답을 **어디서 잡아 어떤 포맷으로 내보내는가**는 day68-exception-handling.md와 day03-api-error-format.md에서 다뤘습니다. 이 문서는 **검사 자체를 어디에 두는가**만 다룹니다.

## 1. 핵심 개념

검증이라고 한 단어로 부르지만 실무에서 섞여 있는 것은 세 종류입니다.

| 종류 | 판단에 필요한 것 | 예 |
|---|---|---|
| 형식 검증 | 입력값 하나 | 길이 32 이하, 빈 문자열 아님, 미래 날짜 |
| 불변식 | 객체 자신의 상태 | 수량 ≥ 1, 시작일 ≤ 종료일 |
| 업무 규칙 | 다른 데이터 조회 | 이미 쓰인 쿠폰 코드인가, 재고가 남았는가 |

> `@Valid` 하나로 다 되는 것처럼 보이기 때문에 세 종류를 전부 요청 DTO 애너테이션으로 밀어 넣게 됩니다. 그러면 두 가지가 동시에 벌어집니다. 재고 확인처럼 DB를 읽어야 하는 검사는 애너테이션으로 표현이 안 되니 서비스에 또 쓰게 되고, DTO를 거치지 않는 호출 경로(배치, 메시지 컨슈머, 다른 서비스 메서드)에서는 **아무 검증도 걸리지 않습니다.** 반대로 전부 엔티티 애너테이션으로 몰면 위반이 `save()`가 아니라 트랜잭션이 끝나는 flush 시점에 터져서, 스택트레이스가 원인 코드를 가리키지 않습니다.

Bean Validation 애너테이션은 "이 필드가 만족해야 하는 조건"을 선언할 뿐이고, **그걸 실제로 실행하는 주체를 지정하지 않습니다.** 검증 전략을 정한다는 건 애너테이션을 고르는 일이 아니라, 실행 주체 네 개 중 누구에게 무엇을 맡길지 정하는 일입니다.

## 2. 구조 — 제약을 실행하는 네 주체

| 지점 | 무엇이 트리거하는가 | 실패 시 예외 | 기본 상태 코드 |
|---|---|---|---:|
| ① 요청 본문·모델 바인딩 | `@RequestBody`·`@ModelAttribute`·`@RequestPart`에 붙은 `@Valid`/`@Validated` | `MethodArgumentNotValidException` | 400 |
| ② 컨트롤러 메서드 파라미터 | 파라미터에 직접 붙은 제약(`@Min`, `@NotBlank` 등) | `HandlerMethodValidationException` | 400 |
| ③ 일반 빈의 메서드 | 클래스에 붙은 `@Validated` + `MethodValidationPostProcessor` | `ConstraintViolationException` | 500 |
| ④ 엔티티 영속화 | Hibernate의 `BeanValidationEventListener` | `ConstraintViolationException` | 500 |

①과 ②의 상태 코드는 예외 자신이 들고 있습니다. `MethodArgumentNotValidException#getStatusCode()`는 `BAD_REQUEST`를 고정으로 반환하고, `HandlerMethodValidationException`은 **반환값 검증일 때만 500**, 입력 검증이면 400입니다. 반면 ③④가 던지는 `jakarta.validation.ConstraintViolationException`은 `ResponseEntityExceptionHandler`가 다루는 예외 목록에 없습니다.

> 같은 `@Min(1)` 애너테이션인데 ①②에서 깨지면 400이고, ③④에서 깨지면 클라이언트가 500을 받습니다. 이건 버그가 아니라 설계입니다 — ③④까지 내려온 잘못된 값은 "클라이언트가 잘못 보냈다"가 아니라 "앞단에서 걸러내지 못했다", 즉 서버 결함이라는 뜻입니다.

②는 Spring Framework 6.1에서 들어온 내장 메서드 검증입니다. AOP 프록시 없이 `RequestMappingHandlerAdapter`가 직접 수행하므로 컨트롤러에 프록시가 생기지 않습니다. ([Validation](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-validation.html))

### 2-1. 확장 지점

- **그룹(groups)** — 같은 타입을 상황별로 다르게 검증합니다. `@Validated(OnCreate.class)`로 요청합니다.
- **커스텀 제약** — `ConstraintValidator` 구현체는 `SpringConstraintValidatorFactory`로 생성되므로 **다른 빈을 주입받을 수 있습니다.** 즉 커스텀 제약 안에서 리포지터리를 조회하는 것이 기술적으로 가능합니다. 가능하다는 것과 해야 한다는 것은 다릅니다 — §4-1에서 다시 다룹니다. ([Spring Validation](https://docs.spring.io/spring-framework/reference/core/validation/beanvalidation.html))

## 3. 흐름

### 3-1. 코드로 보는 구성

세 종류를 세 군데로 나눈 모습입니다.

```java
// ① 형식 검증 — 요청 DTO. 신뢰 경계에서 한 번만
public record CouponIssueRequest(
        @NotBlank @Size(max = 32) String couponCode,
        @NotNull @Min(1) @Max(10) Integer quantity,
        @NotNull @Future LocalDate expiresOn) {
}
```

```java
@RestController
@RequestMapping("/api/coupons")
class CouponController {

    private final CouponIssueService couponIssueService;

    CouponController(CouponIssueService couponIssueService) {
        this.couponIssueService = couponIssueService;
    }

    @PostMapping
    ResponseEntity<Void> issue(@Valid @RequestBody CouponIssueRequest request) {
        couponIssueService.issue(request.couponCode(), request.quantity(), request.expiresOn());
        return ResponseEntity.noContent().build();
    }
}
```

```java
// 불변식 — 생성자. DTO를 거치지 않아도 깨진 객체가 만들어지지 않습니다
@Entity
class Coupon {

    @Id @GeneratedValue
    private Long id;

    @Column(nullable = false, length = 32)
    private String code;

    @Column(nullable = false)
    private int quantity;

    protected Coupon() {   // JPA 요구사항
    }

    Coupon(String code, int quantity) {
        if (code == null || code.isBlank()) {
            throw new IllegalArgumentException("쿠폰 코드가 비어 있습니다.");
        }
        if (quantity < 1) {
            throw new IllegalArgumentException("발급 수량은 1 이상이어야 합니다: " + quantity);
        }
        this.code = code;
        this.quantity = quantity;
    }
}
```

제약을 `@NotNull`이 아니라 `@Column(nullable = false)` + 생성자 `if`로 쓴 이유는 §8-④에서 설명합니다.

```java
// 업무 규칙 — 서비스. 다른 데이터를 읽어야 판단되는 것만 여기 둡니다
@Service
class CouponIssueService {

    private final CouponRepository couponRepository;

    CouponIssueService(CouponRepository couponRepository) {
        this.couponRepository = couponRepository;
    }

    @Transactional
    void issue(String code, int quantity, LocalDate expiresOn) {
        if (couponRepository.existsByCode(code)) {
            throw new DuplicateCouponCodeException(code);   // advice가 409로 변환
        }
        couponRepository.save(new Coupon(code, quantity));
    }
}
```

### 3-2. 실행 흐름

1. `RequestResponseBodyMethodProcessor`가 요청 본문을 `CouponIssueRequest`로 역직렬화합니다.
2. 파라미터에 `@Valid`가 있으므로 `WebDataBinder#validate`가 돕니다 → 위반 시 `MethodArgumentNotValidException` → 400 + `ProblemDetail`. **컨트롤러 메서드는 호출되지 않습니다.**
3. 통과 → 컨트롤러 진입 → 서비스 호출.
4. 서비스가 `existsByCode`로 DB를 읽습니다 → 업무 규칙 위반이면 도메인 예외 → advice가 409로 변환.
5. `new Coupon(...)` → 불변식 위반이면 즉시 실패. 생성자이므로 스택트레이스의 맨 윗줄이 호출 지점입니다.
6. 커밋 직전 flush → INSERT.

세 검사는 각각 다른 질문에 답합니다. 2번 단계는 "요청이 말이 되는가", 5번 단계는 "객체가 말이 되는가", 4번 단계는 "지금 이 데이터로 해도 되는가". 질문이 다르므로 세 군데에 있는 것은 중복이 아닙니다.

## 4. 특징

### 4-1. 무엇을 어디에 두는가

| 검사 | 둘 곳 | 근거 |
|---|---|---|
| 길이·패턴·null·범위 | 요청 DTO (①) | 입력만 보고 판단되므로 가장 바깥에서 끝내는 게 가장 싸다 |
| `@PathVariable`·`@RequestParam` 범위 | 컨트롤러 파라미터 (②) | DTO가 없는 값이다. 별도 래퍼를 만들 가치가 없다 |
| 객체 자신의 불변식 | 생성자 / 정적 팩토리 | 호출 경로와 무관하게 보장된다. 실패 지점이 생성 지점이다 |
| 조회가 필요한 규칙 | 서비스 (③ 아님, 평범한 `if`) | 트랜잭션 경계 안에서 판단해야 한다 |
| DB 스키마 제약 | `@Column` | 애플리케이션이 죽어도 남는 유일한 방어선 |

**조회가 필요한 규칙을 커스텀 제약으로 만들지 않는 편이 좋습니다.** §2-1처럼 기술적으로는 됩니다. 그런데 "이미 쓰인 코드인가"는 조회한 순간과 INSERT하는 순간 사이에 바뀝니다. 중복 검사는 트랜잭션과 유니크 제약으로 푸는 문제이고, 애너테이션은 그 둘 어느 쪽도 제어하지 못합니다. 더 나쁜 건 실패 응답이 `ConstraintViolationException` 경로를 타면서 400이 되는 것입니다 — 재시도하면 성공할 수 있는 경합을 클라이언트 잘못으로 보고하게 됩니다.

### 4-2. 이 배치가 주는 것

- 상태 코드가 자동으로 갈립니다. 형식 오류 400, 규칙 위반 409, 통과 못 한 값이 안쪽에서 터지면 500.
- 메시지를 번역할 지점이 한 곳(①)으로 모입니다. `MessageSource` 번들만 관리하면 됩니다.
- 서비스 메서드를 배치나 컨슈머에서 직접 호출해도 불변식은 유지됩니다.

### 4-3. 트레이드오프

- **중복처럼 보입니다.** DTO의 `@NotBlank`와 생성자의 `if`는 같은 조건을 두 번 검사합니다. 실제로 두 번 돕니다. 대신 실패 비용이 다릅니다 — 하나는 400 응답이고, 하나는 "이 코드 경로에 버그가 있다"는 신호입니다.
- **그룹을 쓰기 시작하면 DTO를 읽기 어려워집니다.** 생성용·수정용 제약이 한 레코드에 섞이고, 어느 그룹이 어디서 활성화되는지는 컨트롤러를 봐야 알 수 있습니다. 보통은 DTO를 두 개로 쪼개는 쪽이 낫습니다 (day14-dto-vs-entity.md).
- **생성자 검증은 테스트 픽스처 만들기를 번거롭게 합니다.** 테스트 전용 빌더를 하나 두는 비용을 받아들여야 합니다.
- **③의 `@Validated`는 AOP 프록시입니다.** 같은 클래스 내부 호출에서는 동작하지 않습니다 (day44-proxy-aop.md).

## 5. 예제

### 5-1. 모든 걸 애너테이션으로 ❌

```java
@Entity
class Reservation {

    @Id @GeneratedValue
    private Long id;

    @NotNull @Size(min = 2, max = 50)
    private String guestName;

    @NotNull @Min(1)
    private Integer headCount;

    // setter로 조립
    void setGuestName(String guestName) { this.guestName = guestName; }
    void setHeadCount(Integer headCount) { this.headCount = headCount; }
}
```

```java
@PostMapping("/api/reservations")
ResponseEntity<Void> create(@RequestBody ReservationRequest request) {   // @Valid 없음
    reservationService.create(request);
    return ResponseEntity.ok().build();
}
```

`@Valid`가 없으니 ①이 돌지 않고, 엔티티 애너테이션만 남습니다. `headCount = 0`인 요청은 컨트롤러와 서비스를 그대로 통과한 뒤 **커밋 직전 flush에서** 터집니다. 로그에 남는 것은 `ConstraintViolationException: headCount: 1 이상이어야 합니다` 한 줄이고, 스택트레이스는 `EntityManager#flush` 아래로 전부 Hibernate 내부입니다. 어느 엔드포인트의 어떤 요청이었는지 알 수 없고, 클라이언트는 500을 받습니다.

### 5-2. 개선한 코드 ✔️

```java
public record ReservationRequest(
        @NotBlank @Size(min = 2, max = 50) String guestName,
        @NotNull @Min(1) @Max(20) Integer headCount) {
}
```

```java
@PostMapping("/api/reservations")
ResponseEntity<Void> create(@Valid @RequestBody ReservationRequest request) {
    reservationService.create(request.guestName(), request.headCount());
    return ResponseEntity.ok().build();
}
```

```java
@Entity
class Reservation {

    @Id @GeneratedValue
    private Long id;

    @Column(nullable = false, length = 50)
    private String guestName;

    @Column(nullable = false)
    private int headCount;

    protected Reservation() {
    }

    Reservation(String guestName, int headCount) {
        if (guestName == null || guestName.isBlank()) {
            throw new IllegalArgumentException("예약자명이 비어 있습니다.");
        }
        if (headCount < 1) {
            throw new IllegalArgumentException("인원은 1 이상이어야 합니다: " + headCount);
        }
        this.guestName = guestName;
        this.headCount = headCount;
    }
}
```

`headCount`를 `Integer`에서 `int`로 바꾼 것도 검증입니다. null이 들어올 수 없는 필드는 타입으로 막는 게 애너테이션보다 강합니다 (day53-column-type-choice.md).

## 6. 그룹을 쓸 때와 DTO를 쪼갤 때

생성은 `couponCode`가 필수지만 수정에서는 안 보내는 경우입니다. 그룹으로 쓰면 이렇게 됩니다.

```java
interface OnCreate {}

public record CouponRequest(
        @NotBlank(groups = OnCreate.class) @Size(max = 32) String couponCode,
        @NotNull @Min(1) Integer quantity) {
}

@PostMapping
ResponseEntity<Void> create(@Validated(OnCreate.class) @RequestBody CouponRequest request) { ... }

@PutMapping("/{couponId}")
ResponseEntity<Void> update(@PathVariable Long couponId,
                            @Valid @RequestBody CouponRequest request) { ... }
```

그룹을 명시하지 않은 제약은 `jakarta.validation.groups.Default`에 속합니다. 그래서 `update`의 `@Valid`는 `@Size`만 검사하고 `@NotBlank`는 건너뜁니다. 동작은 맞지만, DTO만 봐서는 `couponCode`가 필수인지 알 수 없습니다.

**그룹은 "같은 입력 집합을 다른 강도로 검증할 때"만 씁니다.** 필드 구성 자체가 다르면 `CouponCreateRequest`와 `CouponUpdateRequest`로 쪼갭니다. 쪼갠 쪽이 애너테이션도 단순해지고, API 문서에도 정확히 드러납니다.

## 7. 실무에서 찾아보는 검증 실행 지점

- **Hibernate ORM** — `BeanValidationEventListener`가 `PreInsertEvent`·`PreUpdateEvent`·`PreDeleteEvent`를 받아 엔티티를 검증합니다. 삭제 이벤트는 기본적으로 검증하지 않습니다. 이벤트별 그룹은 `jakarta.persistence.validation.group.pre-persist` 같은 프로퍼티로 지정합니다. ([Hibernate Validator 11.1.2](https://docs.hibernate.org/stable/validator/reference/en-US/html_single/))
- **DDL 생성** — Hibernate는 제약을 매핑 메타데이터로도 씁니다. `@NotNull`은 not null 컬럼, `@Size`는 컬럼 길이를 `max`로, `@Min`/`@Max`는 check 제약을 만듭니다. `hibernate.validator.apply_to_ddl=false`로 끕니다. ([같은 문서 11.1.1](https://docs.hibernate.org/stable/validator/reference/en-US/html_single/))
- **Spring** — `DefaultDataBinderFactory`의 내부 클래스 `MethodValidationInitializer`는 파라미터에 `jakarta.validation.Valid`가 붙어 있으면 바인더에서 Bean Validation 검증기를 **제외**합니다. 메서드 검증에 넘기기 위한 처리이고, §8-①의 원인입니다.
- **Spring Boot** — `ValidationAutoConfiguration`이 `spring.validation.method.adapt-constraint-violations`(기본 `false`)를 읽어 `MethodValidationPostProcessor`에 넘깁니다. `true`로 바꾸면 ③이 `ConstraintViolationException` 대신 `MethodValidationException`을 던지고, 파라미터별로 묶인 결과를 받을 수 있습니다.

## 8. 함정

### ① 파라미터 제약 하나를 추가하면 본문 검증의 예외 타입이 바뀝니다 ⚠️

- **증상**: 잘 돌던 `@ControllerAdvice`의 `MethodArgumentNotValidException` 핸들러가 특정 엔드포인트에서만 먹지 않습니다. 상태 코드는 400 그대로인데 응답 본문 포맷이 다릅니다.
- **원인**: 메서드 파라미터 중 하나라도 제약 애너테이션을 들고 있으면 `HandlerMethod#shouldValidateArguments()`가 `true`가 됩니다. 그러면 `RequestMappingHandlerAdapter`가 바인더 팩토리에 `methodValidationApplicable = true`를 세팅하고, `MethodValidationInitializer`가 `@Valid` 파라미터의 Bean Validation 검증기를 제외합니다. 본문 검증이 ①에서 ②로 넘어가고, 던져지는 예외가 `HandlerMethodValidationException`으로 바뀝니다. `@RequestParam @Min(0) int page` 한 줄 추가가 같은 메서드의 `@RequestBody` 검증 경로를 갈아치웁니다.
- **해법**: 두 예외를 **모두** 처리합니다. 공식 문서도 시그니처에 따라 어느 쪽이든 던져질 수 있으니 둘 다 다루라고 명시합니다. `ResponseEntityExceptionHandler`를 상속하면 둘 다 기본 처리되므로, 직접 `@ExceptionHandler`를 쓸 때만 문제가 됩니다.

### ② 컨트롤러 클래스에 `@Validated`를 붙이면 내장 메서드 검증이 꺼집니다

- **증상**: `@RequestParam @Min(1) int page`에 `0`을 보내면 400이 아니라 500이 나옵니다.
- **원인**: 클래스 레벨 `@Validated`가 있으면 `shouldValidateArguments()`가 `false`를 반환하고, 검증이 AOP 프록시 경로로 넘어갑니다. 프록시가 던지는 것은 `ConstraintViolationException`이고 이건 400으로 매핑되지 않습니다.
- **해법**: 컨트롤러에서 클래스 레벨 `@Validated`를 **제거**합니다. 공식 문서가 6.1 내장 지원을 쓰려면 지우라고 못 박습니다.

### ③ `@NotNull`이 없는 제약은 null을 통과시킵니다

- **증상**: `@Size(min = 1)`이 걸린 리스트 필드에 null이 들어와 그대로 통과하고, 다음 줄에서 NPE가 납니다.
- **원인**: 스펙상 대부분의 제약은 null을 유효로 봅니다. `@Size`의 javadoc에 "null elements are considered valid"가 명시돼 있습니다. `@Email`도 null에 `true`를 반환합니다.
- **해법**: 문자열이면 `@NotBlank`, 컬렉션·맵이면 `@NotEmpty`, 그 외 타입은 `@NotNull`을 병기합니다. 셋의 범위는 다릅니다 — `@NotNull`은 모든 타입, `@NotEmpty`는 `CharSequence`/`Collection`/`Map`/배열, `@NotBlank`는 `CharSequence`만이고 **trim한 길이**를 봅니다.

### ④ 엔티티 제약은 `save()`가 아니라 flush에서 터집니다

- **증상**: `save()`는 통과하는데 트랜잭션 커밋 지점에서 500이 납니다. `@Transactional` 메서드 바깥에서 터지므로 try-catch로 감싸도 안 잡힙니다.
- **원인**: `BeanValidationEventListener`는 pre-insert / pre-update 이벤트에서 돕니다. `save()`는 영속성 컨텍스트에 넣기만 하고, INSERT가 발행되는 시점은 flush입니다.
- **해법**: 입력 검증은 ①에서 끝내고, 엔티티에는 `@Column` 제약과 생성자 불변식만 둡니다. 이벤트 검증을 아예 끄려면 `jakarta.persistence.validation.mode`를 `none`으로 설정합니다(Spring Boot에서는 `spring.jpa.properties.jakarta.persistence.validation.mode=none`). 단 끄면 DDL 생성에 쓰이는 제약 정보는 남지만 런타임 최후 방어선이 사라지므로, 보통은 끄기보다 **의존하지 않는** 쪽을 택합니다.

<!-- TODO: 확인 필요 — `spring.jpa.properties.*` 접두사로 JPA 프로퍼티가 전달되는 것은 Spring Boot의 일반 동작이지만, Boot 4.1 문서에서 이 키의 동작을 명시한 문단은 확인하지 못했습니다. -->

### ⑤ 애너테이션이 조용히 무시됩니다

- **증상**: `@Valid`와 `@NotBlank`를 다 붙였는데 잘못된 요청이 400 없이 그대로 통과합니다. 에러 로그도 없습니다.
- **원인**: `spring-boot-starter-validation`이 클래스패스에 없습니다. Spring Boot 2.3부터 이 스타터는 `spring-boot-starter-web`의 전이 의존성이 아닙니다. 구현체가 없으면 `ValidationAutoConfiguration`의 조건이 성립하지 않아 `Validator` 빈이 등록되지 않고, 애너테이션은 그냥 메타데이터로 남습니다.
- **해법**: `spring-boot-starter-validation`을 직접 추가합니다. 잘못된 입력을 하나 던져보는 테스트를 하나라도 두면 이 상황이 다시 발생해도 CI에서 걸립니다.

## 9. 참고자료

- [Spring MVC — Validation](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-validation.html) — ①②의 적용 조건, 클래스 레벨 `@Validated` 주의사항
- [Spring — Error Responses](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html) — 검증 예외가 `ProblemDetail`로 변환되는 과정
- [Spring — Java Bean Validation](https://docs.spring.io/spring-framework/reference/core/validation/beanvalidation.html) — `LocalValidatorFactoryBean`, 메서드 검증, 커스텀 제약
- [Spring Boot — Validation](https://docs.spring.io/spring-boot/reference/io/validation.html) — `@Validated` 메서드 검증, 메시지 소스 연동
- [Hibernate Validator Reference Guide](https://docs.hibernate.org/stable/validator/reference/en-US/html_single/) — 11.1 ORM 통합, 2.3.1 내장 제약 목록과 DDL 영향
- [Jakarta Validation 3.1 Specification](https://jakarta.ee/specifications/bean-validation/3.1/jakarta-validation-spec-3.1.html) — 그룹, 기본 그룹, 컨테이너 요소 제약
- 관련 챕터: day68-exception-handling.md, day03-api-error-format.md, day14-dto-vs-entity.md, day20-service-layer-design.md, day44-proxy-aop.md
