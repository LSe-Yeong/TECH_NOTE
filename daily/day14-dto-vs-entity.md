# DTO와 Entity를 분리해야 하는 이유

> 이 문서가 답할 질문: **Entity를 그대로 API 요청·응답에 쓰면 무엇이 무너지고, DTO는 그걸 어떻게 막는가?**
>
> 분류: 기술이해형(왜 존재하는가). "DTO를 안 쓰면 실제로 무슨 일이 벌어지는가"에서 시작해 분리의 근거까지 내려갑니다.
>
> 기준: Spring Boot 4.1(2026-06-10 GA, [릴리스 공지](https://spring.io/blog/2026/06/10/spring-boot-4/)) · Hibernate ORM 7 · Jackson 3 기준으로 서술합니다.

## 1. 핵심 개념 — 두 객체는 사는 세계가 다릅니다

`@Entity`가 붙은 객체는 **DB 행의 대리인**입니다. 영속성 컨텍스트가 관리하고, 필드를 바꾸면 트랜잭션 커밋 시점에 UPDATE가 나갑니다. 식별자(`@Id`)로 동일성이 결정됩니다.

DTO(Data Transfer Object)는 **경계를 넘는 데이터 한 덩어리**입니다. 관리하는 주체가 없고, 상태 변화가 어디에도 반영되지 않습니다. 필드 구성은 오직 "받는 쪽이 뭘 필요로 하는가"가 결정합니다.

> `OrderController`가 `Order` 엔티티를 그대로 반환합니다. 잘 돕니다. 그러다 어느 날 개인정보 보호 요구로 `Order`에 `customerPhone` 필드를 추가하자, **아무도 코드를 고치지 않았는데 공개 API 응답에 전화번호가 실려 나갑니다.** 반대 방향도 같습니다. 회원 수정 API가 `@RequestBody Member`를 받으면, 클라이언트가 JSON에 `"role": "ADMIN"`을 끼워 넣는 순간 권한이 올라갑니다. **엔티티를 경계에 두면 DB 스키마를 바꾸는 행위가 곧 API 계약을 바꾸는 행위가 됩니다.** 그리고 그 사실을 아무도 리뷰에서 못 봅니다.

## 2. 구조 — 분리의 진짜 근거는 "변경 이유"입니다

DTO를 옹호할 때 흔히 "계층 분리"라고만 말합니다. 추상적이라 설득이 안 됩니다. 구체적으로 보면 두 객체는 **바뀌는 이유와 시점이 다릅니다.**

| | 바뀌는 이유 | 바뀌는 주기 | 깨지면 |
|---|---|---|---|
| Entity | DB 스키마, 인덱스, 정규화 | 마이그레이션할 때 | 애플리케이션이 못 뜬다 |
| 요청 DTO | 클라이언트가 보낼 수 있는 것 | API 버전 올릴 때 | 클라이언트가 400을 받는다 |
| 응답 DTO | 화면이 필요로 하는 것 | 화면 바뀔 때 | 화면이 깨진다 |

세 축이 하나로 묶여 있으면 **한 축의 변경이 나머지 둘을 인질로 잡습니다.** 컬럼 하나 이름을 바꾸려는데 안드로이드 앱 배포 주기를 기다려야 하는 상황이 여기서 나옵니다.

여기에 하나가 더 있습니다. **엔티티에는 "영속성 상태"라는 눈에 안 보이는 속성이 있습니다.** 같은 `Order` 객체라도 영속 상태냐 준영속 상태냐에 따라 setter 한 줄의 결과가 완전히 달라집니다. DTO에는 이 축이 아예 없습니다. 그래서 안전합니다.

## 3. 흐름 — 엔티티를 경계에 두면 실제로 벌어지는 일

### 3-1. 응답 방향: 직렬화가 트랜잭션 밖에서 일어납니다

Spring MVC에서 JSON 직렬화는 **컨트롤러가 리턴한 다음**에 일어납니다. 서비스의 `@Transactional`은 이미 끝났습니다.

```
요청 → 컨트롤러 → 서비스(@Transactional 시작~종료) → 컨트롤러 리턴
     → HttpMessageConverter가 Jackson으로 직렬화   ← 여기는 트랜잭션 밖
     → 응답
```

이 상태에서 Jackson이 `order.getItems()`를 호출하면 지연 로딩 프록시가 초기화를 시도하고, 세션이 닫혀 있으면 `LazyInitializationException`이 납니다. 응답은 500이 아니라 **JSON이 반쯤 쓰이다 잘린 상태로** 나가기도 합니다. 헤더는 이미 200으로 전송됐기 때문입니다.

여기서 Spring Boot의 기본 설정이 상황을 헷갈리게 만듭니다. `spring.jpa.open-in-view`는 **기본값이 `true`**이고, `OpenEntityManagerInViewInterceptor`가 요청 전체 구간에서 EntityManager를 열어 둡니다([Spring Boot 레퍼런스](https://docs.spring.io/spring-boot/reference/data/sql.html)). 그래서 직렬화 중 지연 로딩이 그냥 됩니다.

문제는 **"된다"가 아니라 "언제 어떤 쿼리가 나가는지 아무도 모르게 된다"**는 점입니다.

- 커넥션을 응답이 다 나갈 때까지 붙들고 있습니다. 트래픽이 오르면 커넥션 풀이 먼저 마릅니다.
- 같은 서비스 코드를 `@KafkaListener`나 배치에서 호출하면 OSIV가 없으니 그때 처음 터집니다. 웹에서는 되고 비동기에서는 안 되는 코드가 만들어집니다.
- 컬렉션을 순회하는 순간 N+1이 직렬화 단계에서 발생합니다. 서비스 코드만 봐서는 안 보입니다.

참고로 Spring Boot 4.0에서 이 기본값을 `false`로 바꾸자는 제안이 올라왔지만 **채택되지 않았습니다**([spring-boot#47547](https://github.com/spring-projects/spring-boot/issues/47547)). 여전히 기본은 `true`입니다.

<!-- TODO: 확인 필요 — Spring Boot 4.x에서 open-in-view 기본값 true일 때 출력되는 시작 로그 경고문의 정확한 전체 문구를 소스에서 직접 확인하지 못했습니다(GitHub raw 경로 404). 본문에서는 문구를 인용하지 않고 동작만 서술했습니다. -->

### 3-2. 요청 방향: 바인딩이 곧 수정입니다

응답보다 요청 쪽이 더 위험합니다.

```java
// ❌ 수정 API가 엔티티를 그대로 받습니다
@PatchMapping("/members/{id}")
public void update(@PathVariable Long id, @RequestBody Member member) {
    memberService.update(id, member);
}
```

두 가지가 동시에 무너집니다.

**대량 할당(Mass Assignment).** Jackson은 JSON에 있는 필드를 이름만 맞으면 채웁니다. 클라이언트가 `{"nickname":"kim","role":"ADMIN","point":999999}`를 보내면 `role`과 `point`도 채워집니다. 화면에 그 입력창이 없다는 건 방어가 아닙니다. **API는 화면과 무관하게 호출됩니다.**

**부분 수정이 전체 덮어쓰기가 됩니다.** JSON에 없던 필드는 `null`로 남습니다. 이 객체를 그대로 `save()`하면 멀쩡하던 컬럼이 전부 `null`이 됩니다. 특히 `merge()` 계열 동작에서 조용히 데이터가 날아갑니다.

DTO는 이 둘을 **필드를 선언하지 않는 것만으로** 막습니다. `MemberUpdateRequest`에 `role` 필드가 없으면 클라이언트가 뭘 보내든 들어올 자리가 없습니다. 화이트리스트가 타입 시스템에 박히는 셈입니다.

## 4. 트레이드오프 — 공짜가 아닙니다

DTO 분리를 팔면서 비용을 안 말하면 사기입니다.

- **클래스가 늘어납니다.** 도메인 하나에 요청 DTO·응답 DTO·엔티티까지 최소 3개입니다.
- **매핑 코드가 늘어납니다.** 필드를 추가할 때 고칠 곳이 늘고, 빠뜨리면 값이 `null`로 나갑니다. 그런데 이건 컴파일러가 안 잡아줍니다.
- **DTO가 엔티티를 그대로 복사한 쌍둥이면 비용만 남습니다.** 필드 구성이 100% 같은 DTO는 계약을 고정하는 효과는 있지만, 이 이득이 유지비보다 큰지는 프로젝트마다 다릅니다.

**언제 분리를 안 해도 되는가**도 정해둡시다.

- 사내 관리 도구, 사용자가 개발팀뿐인 API — 스키마와 계약을 같은 사람이 같은 날 바꿉니다.
- 프로토타입 — 다음 주에 버릴 코드입니다.

기준은 **"이 API를 쓰는 쪽과 스키마를 바꾸는 쪽이 다른 사람인가"**입니다. 다르면 분리합니다.

## 5. 예제

### 5-1. 클린하지 않은 코드 ❌

```java
@RestController
@RequiredArgsConstructor
public class OrderController {

    private final OrderRepository orderRepository;

    @GetMapping("/orders/{id}")
    public Order getOrder(@PathVariable Long id) {
        return orderRepository.findById(id)
                .orElseThrow(() -> new OrderNotFoundException(id));
    }
}
```

- `Order`에 추가되는 모든 컬럼이 자동으로 공개됩니다.
- `items`, `member` 같은 연관관계가 직렬화 시점에 초기화되며 N+1을 만듭니다.
- 양방향 연관관계가 있으면 `Order → Member → orders → Order`로 순환하며 무한 재귀에 빠집니다.

이 마지막 문제를 `@JsonIgnore`로 막는 게 흔한 대응인데, **엔티티에 직렬화 관심사를 심는 것**이라 다른 API에서 그 필드가 필요해지는 순간 막힙니다.

### 5-2. 개선한 코드 ✔️

```java
public record OrderResponse(
        Long orderId,
        String status,
        BigDecimal totalAmount,
        List<OrderLine> lines
) {
    public record OrderLine(String productName, int quantity, BigDecimal price) {}

    public static OrderResponse from(Order order) {
        List<OrderLine> lines = order.getItems().stream()
                .map(item -> new OrderLine(
                        item.getProductName(), item.getQuantity(), item.getPrice()))
                .toList();
        return new OrderResponse(
                order.getId(), order.getStatus().name(), order.getTotalAmount(), lines);
    }
}
```

```java
@Transactional(readOnly = true)
public OrderResponse getOrder(Long id) {
    Order order = orderRepository.findWithItemsById(id)   // fetch join으로 한 번에
            .orElseThrow(() -> new OrderNotFoundException(id));
    return OrderResponse.from(order);   // 트랜잭션 안에서 변환이 끝납니다
}
```

핵심은 필드를 골랐다는 게 아니라 **변환이 트랜잭션 안에서 끝난다**는 점입니다. 컨트롤러가 리턴하는 시점에 DTO는 이미 값만 든 평범한 객체입니다. 프록시도, 세션 의존성도 없습니다. 그래서 OSIV를 꺼도 그대로 돕니다.

레코드(record)는 DTO에 잘 맞습니다. 모든 필드가 `private final`이고 `equals`/`hashCode`/`toString`이 자동으로 생기며, Spring Data JPA 문서도 DTO 타입으로 레코드를 권장합니다([Spring Data JPA Projections](https://docs.spring.io/spring-data/jpa/reference/repositories/projections.html)).

### 5-3. 요청 DTO는 검증까지 데려옵니다 ✔️

```java
public record MemberUpdateRequest(
        @NotBlank @Size(max = 20) String nickname,
        @Email String email
) {}
```

```java
@PatchMapping("/members/{id}")
public void update(@PathVariable Long id, @Valid @RequestBody MemberUpdateRequest request) {
    memberService.updateProfile(id, request.nickname(), request.email());
}
```

`role`은 필드 자체가 없으니 들어올 수 없습니다. 그리고 검증 애너테이션이 **엔티티가 아니라 요청 DTO에** 붙었습니다. 이게 중요합니다. "가입할 때는 필수, 수정할 때는 선택"인 필드를 엔티티 하나에 표현하려면 Bean Validation 그룹까지 동원해야 하는데, DTO를 나누면 그냥 두 클래스입니다.

## 6. DTO를 만드는 세 가지 방법

엔티티를 통째로 조회한 뒤 매핑하는 게 유일한 방법은 아닙니다. 목록 조회처럼 필드 일부만 필요한 경우엔 **DB에서부터 필요한 컬럼만** 가져올 수 있습니다.

```java
public interface OrderRepository extends JpaRepository<Order, Long> {

    // 1. 생성자 표현식 — JPQL에서 바로 DTO를 만듭니다
    @Query("""
        select new com.example.order.dto.OrderSummary(o.id, o.status, o.totalAmount)
        from Order o where o.member.id = :memberId
    """)
    List<OrderSummary> findSummaries(@Param("memberId") Long memberId);

    // 2. 클래스 기반 프로젝션 — 생성자 파라미터 이름으로 매핑
    List<OrderSummary> findByStatus(OrderStatus status);

    // 3. 인터페이스 기반 프로젝션(closed)
    List<OrderTitleOnly> findByMemberId(Long memberId);
}

public interface OrderTitleOnly {
    Long getId();
    String getStatus();
}
```

닫힌(closed) 인터페이스 프로젝션은 필요한 속성을 전부 알 수 있어서 **Spring Data가 쿼리 자체를 최적화**합니다. 반면 `@Value`로 SpEL을 쓰는 열린(open) 프로젝션은 어떤 속성이 쓰일지 모르므로 이 최적화가 적용되지 않습니다([Spring Data JPA Projections](https://docs.spring.io/spring-data/jpa/reference/repositories/projections.html)).

**언제 무엇을 쓰는가**는 이렇게 갈립니다.

| 상황 | 선택 |
|---|---|
| 도메인 로직을 태운 뒤 응답한다 | 엔티티 조회 → 매핑 |
| 목록·통계처럼 읽기만 한다 | 생성자 표현식 / 프로젝션 |
| 여러 테이블을 조합한 화면 전용 데이터 | 생성자 표현식 또는 네이티브 쿼리 |

읽기 전용 조회에 엔티티를 쓰면 영속성 컨텍스트가 스냅샷까지 떠서 메모리를 두 배로 씁니다. 그럴 필요가 없는 경로입니다.

## 7. 매핑 코드는 어디에 두는가

정답은 하나가 아니지만, 판단 기준은 있습니다.

- **엔티티가 DTO를 몰라야 합니다.** `Order`에 `toResponse()`를 넣으면 도메인이 API 계약을 알게 됩니다. 화면이 늘어날 때마다 엔티티가 부풀어 오릅니다.
- **DTO는 엔티티를 알아도 됩니다.** 위 예제의 `OrderResponse.from(Order)`처럼 정적 팩터리를 DTO 쪽에 두면 의존 방향이 한쪽으로만 갑니다.
- **컨트롤러에서 변환하지 않습니다.** 변환 시점이 트랜잭션 밖으로 나가면서 §3-1 문제가 그대로 돌아옵니다.

MapStruct 같은 매핑 라이브러리는 컴파일 시점에 구현을 생성하므로 리플렉션 기반 매퍼보다 예측 가능합니다. 다만 현재 안정 릴리스는 1.6.3(2024-11-09)이고, 1.7은 2026-06-27 시점에 Beta2 단계입니다([MapStruct News](https://mapstruct.org/news/)). 도입한다면 이 상태를 감안해 결정합니다.

**매퍼를 도입한다고 문제가 사라지지는 않습니다.** 필드를 빠뜨렸을 때 MapStruct는 경고를 낼 수 있지만, 잘못된 필드를 매핑하는 것까지는 못 잡습니다. 매핑 테스트가 필요한 이유입니다.

## 8. 관련된 개념과 비교

| | 정체성 | 가변성 | 목적 |
|---|---|---|---|
| Entity | `@Id` | 가변(더티 체킹) | DB 행의 대리인 |
| DTO | 없음 | 보통 불변 | 경계를 넘는 데이터 운반 |
| VO(값 객체) | 모든 필드 값 | 불변 | 값 자체에 의미와 규칙 부여 |
| 프로젝션 | 없음 | 불변 | 필요한 컬럼만 조회 |

DTO와 VO를 섞어 쓰는 코드를 자주 봅니다. **`Money`, `Address` 같은 VO는 도메인 안에 사는 개념이고 검증 규칙을 갖습니다.** DTO는 도메인 밖으로 나가는 껍데기라 규칙이 없습니다. VO를 DTO 대신 응답에 쓰면 도메인 규칙이 API 계약에 새어 나갑니다.

## 9. 함정

### 9-1. 응답 DTO에 엔티티를 필드로 담습니다

- **증상**: DTO를 만들었는데도 `LazyInitializationException`이 계속 납니다.
- **원인**: `record OrderResponse(Long id, Order order)`처럼 엔티티를 그대로 품었습니다. 껍데기만 DTO입니다.
- **해법**: DTO의 필드는 원시 타입·String·다른 DTO만 허용한다는 규칙을 정합니다. 컬렉션도 `List<OrderLine>`처럼 DTO의 중첩 레코드로 받습니다.

### 9-2. Hibernate 모듈로 덮어서 넘어갑니다

- **증상**: `jackson-datatype-hibernate`를 넣고 `Hibernate6Module`을 등록하니 예외가 사라집니다.
- **원인**: 이 모듈은 초기화되지 않은 프록시를 `null`로 쓰거나 건너뜁니다([jackson-datatype-hibernate](https://github.com/FasterXML/jackson-datatype-hibernate)). **예외가 없어진 것이지 데이터가 채워진 게 아닙니다.**
- **해법**: 클라이언트에 조용히 `null`이 나가는 게 예외보다 나은지 판단합니다. 서버 렌더링 템플릿 같은 특정 상황이 아니면, 필요한 데이터를 명시적으로 조회해 DTO에 담는 쪽이 맞습니다.

### 9-3. `@JsonIgnoreProperties({"hibernateLazyInitializer", "handler"})`를 엔티티에 붙입니다

- **증상**: `getReference()`로 얻은 프록시를 직렬화할 때 `hibernateLazyInitializer` 직렬화 실패가 납니다. 위 애너테이션을 붙이면 사라집니다.
- **원인**: 프록시 객체의 내부 필드를 Jackson이 직렬화하려다 실패한 것입니다. 애너테이션은 그 필드를 가릴 뿐입니다.
- **해법**: 근본 원인은 **프록시가 컨트롤러 밖까지 살아 나간 것**입니다. DTO 변환을 트랜잭션 안으로 넣으면 이 애너테이션 자체가 필요 없어집니다.

### 9-4. DTO에 setter를 다 열어둡니다

- **증상**: DTO 값이 중간에 바뀌어 있는데 어디서 바꿨는지 못 찾습니다.
- **원인**: 운반용 객체에 변경 지점이 열려 있으면 서비스 중간에서 값을 주무르는 코드가 생깁니다.
- **해법**: record나 생성자 + getter만 둡니다. 요청 DTO도 record로 받을 수 있습니다.

### 9-5. Jackson 3 전환에서 커스텀 직렬화가 조용히 빠집니다

- **증상**: Spring Boot 4로 올린 뒤 DTO 응답의 날짜 포맷이 달라졌습니다.
- **원인**: Spring Boot 4는 Jackson 3을 기본으로 쓰고, 패키지가 `com.fasterxml.jackson`에서 `tools.jackson`으로 바뀌었습니다. 또 `ObjectMapper` 빈을 정의하는 것만으로는 자동 구성을 대체하지 못하고 `JsonMapper` 빈을 정의해야 합니다([Spring Boot 4.0 마이그레이션 가이드](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)).
- **해법**: 마이그레이션 기간에는 `spring.jackson.use-jackson2-defaults=true`로 Jackson 2 기본값에 맞출 수 있습니다. 다만 임시방편이므로 DTO 직렬화 결과를 검증하는 테스트를 먼저 만들어 두는 편이 낫습니다.

## 10. 참고자료

- [Spring Data JPA — Projections](https://docs.spring.io/spring-data/jpa/reference/repositories/projections.html) — 인터페이스·클래스 기반 프로젝션과 쿼리 최적화 조건
- [Spring Boot Reference — Working with SQL Databases](https://docs.spring.io/spring-boot/reference/data/sql.html) — `spring.jpa.open-in-view` 기본 동작
- [spring-boot#47547](https://github.com/spring-projects/spring-boot/issues/47547) — Spring Boot 4에서 OSIV 기본값 변경 제안이 거절된 논의
- [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide) — Jackson 3 전환
- [jackson-datatype-hibernate](https://github.com/FasterXML/jackson-datatype-hibernate) — 프록시 직렬화 처리 모듈
- 관련 문서: [day02-spring-request-flow.md](day02-spring-request-flow.md) — 직렬화가 어느 단계에서 일어나는가
- 관련 문서: [day03-api-error-format.md](day03-api-error-format.md) — 응답 계약을 고정한다는 것의 의미
- 관련 문서: [day09-rest-api-design.md](day09-rest-api-design.md) — 변경 내성을 갖는 API 설계
