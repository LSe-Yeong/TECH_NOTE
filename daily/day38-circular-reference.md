# 순환 참조가 알려주는 설계 문제

> 이 문서가 답할 질문: **두 빈이 서로를 주입받고 있다는 사실은 내 설계에 대해 무엇을 말해주고, 무엇을 고쳐야 그 사이클이 사라지는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처에서 공통으로 보고되는 증상은 "잘 돌던 앱이 버전을 올리니 기동에서 죽는다"이고, 공통으로 제시되는 해법이 전부 회피책이라 그 회피책의 비용까지 같이 다룹니다.
>
> 기준: 본문의 모든 실행 결과는 **Spring Boot 4.1.1(Spring Framework 7.0 계열) / Temurin JDK 17**에서 직접 실행해 얻은 것입니다. 컨테이너 내부 동작 확인에는 `spring-beans` 6.2.13 소스를 함께 읽었습니다. 빈이 어떻게 등록되고 언제 초기화되는지는 `daily/day32-bean-lifecycle.md`에서 다뤘고, 여기서는 "의존 그래프에 고리가 생겼을 때" 이야기만 합니다.

## 1. 핵심 개념 — 순환 참조는 기동 실패가 아니라 책임 배치의 결과입니다

순환 참조는 빈 의존 그래프에 고리가 생긴 상태입니다. `OrderService`가 `CouponService`를 주입받고, `CouponService`가 다시 `OrderService`를 주입받으면 고리가 하나 생깁니다. 셋 이상을 거쳐 돌아오는 고리도 똑같습니다.

컨테이너 입장에서 이게 왜 곤란한지는 뒤에서 보겠습니다. 먼저 짚을 것은 **기동 실패가 문제의 본체가 아니라는 점**입니다.

> 기동 실패는 오히려 친절한 쪽입니다. 진짜 문제는 그 고리가 남긴 상태입니다. 두 클래스 중 어느 쪽이 상위인지 코드가 대답하지 못하고, 한쪽만 떼어내 테스트할 수 없고, 한쪽을 고칠 때 반드시 다른 쪽을 같이 열어봐야 합니다. 나중에 모듈이나 서비스를 쪼갤 때 이 둘은 통째로 붙어서 따라옵니다. Spring Boot 2.6이 기본값을 "금지"로 바꾼 이유도 이겁니다 — 런타임에 어떻게든 풀어주면 이 상태가 영원히 안 드러납니다.

그래서 이 문서의 절반은 "어떻게 통과시키는가"가 아니라 "고리가 어디를 가리키고 있는가"입니다.

## 2. 컨테이너는 고리 앞에서 무엇을 하는가

### 2-1. 생성자 주입은 원리적으로 풀 수 없습니다

생성자 주입은 "완성된 협력자를 받아서 나를 만든다"는 계약입니다. `OrderService`를 만들려면 완성된 `CouponService`가 필요하고, `CouponService`를 만들려면 완성된 `OrderService`가 필요합니다. 양쪽 다 상대가 먼저여야 하니 시작점이 없습니다.

```java
@Service
class OrderService {
    private final CouponService couponService;
    OrderService(CouponService couponService) { this.couponService = couponService; }
}

@Service
class CouponService {
    private final OrderService orderService;
    CouponService(OrderService orderService) { this.orderService = orderService; }
}
```

Spring Boot 4.1.1에서 이 두 빈만 두고 띄우면 이렇게 끝납니다.

```
***************************
APPLICATION FAILED TO START
***************************

Description:

The dependencies of some of the beans in the application context form a cycle:

┌─────┐
|  app.CouponService defined in URL [...App$CouponService.class]
↑     ↓
|  app.OrderService defined in URL [...App$OrderService.class]
└─────┘

Action:

Relying upon circular references is discouraged and they are prohibited by default.
Update your application to remove the dependency cycle between beans. As a last resort,
it may be possible to break the cycle automatically by setting
spring.main.allow-circular-references to true.
```

로그 위쪽에는 원인 예외가 따로 찍힙니다. `BeanCurrentlyInCreationException: Error creating bean with name 'app.CouponService': Requested bean is currently in creation`. **이 예외 이름이 보이면 사이클을 의심하는 게 맞습니다.**

Spring Framework 레퍼런스도 생성자 주입만 쓰면 풀 수 없는 순환이 만들어질 수 있다고 명시하고, 그 경우 세터 주입으로 바꾸는 방법을 언급합니다. 다만 같은 문서가 바로 앞 문단에서 필수 의존성은 생성자 주입을 권장합니다. 즉 "세터로 바꾸라"는 건 권장 설계가 아니라 탈출구입니다.

### 2-2. 세터·필드 주입은 3단계 캐시로 풀립니다

필드 주입은 순서가 다릅니다. 객체를 먼저 만들고(생성자 호출) 그다음에 필드를 채웁니다. 그래서 "아직 필드가 안 채워진 나"를 상대에게 먼저 건네줄 수 있습니다. 이걸 이른 참조(early reference)라고 부르고, 컨테이너는 세 단계 맵으로 관리합니다.

| 단계 | 이름 | 담기는 것 |
|---|---|---|
| 1 | `singletonObjects` | 초기화까지 끝난 완성 빈 |
| 2 | `earlySingletonObjects` | 이미 한 번 노출한 미완성 빈 |
| 3 | `singletonFactories` | 미완성 빈의 참조를 만들어낼 팩토리 |

`OrderService`가 먼저 생성된다고 하면 흐름은 이렇습니다.

1. `OrderService` 인스턴스화 → 3단계에 팩토리 등록
2. `OrderService` 필드 주입 시작 → `CouponService` 요청
3. `CouponService` 인스턴스화 → 3단계에 팩토리 등록
4. `CouponService` 필드 주입 시작 → `OrderService` 요청
5. 1단계 없음 → 2단계 없음 → **3단계 팩토리 실행** → 미완성 `OrderService` 반환, 2단계로 옮김
6. `CouponService` 완성 → 1단계 등록
7. 2번으로 돌아와 `OrderService` 필드에 완성된 `CouponService` 주입 → `OrderService` 완성

여기서 의문이 하나 남습니다. 미완성 객체를 그냥 2단계에 넣어두면 될 텐데 왜 팩토리를 한 번 거치냐는 겁니다. **AOP 때문입니다.** `@Transactional`이나 `@Async`가 붙은 빈은 최종적으로 프록시로 바꿔치기됩니다. 이른 참조를 원본으로 넘겨버리면 상대 빈만 프록시가 아닌 원본을 들고 있게 됩니다. 그래서 팩토리 안에서 `getEarlyBeanReference()`를 호출해 "지금 프록시가 필요하면 프록시를 만들어 반환"합니다. 2단계가 따로 있는 이유는 그 팩토리를 두 번 실행하면 프록시가 두 개 생기기 때문입니다. 한 번 실행한 결과를 2단계에 캐시해 둡니다.

### 2-3. 그런데 Spring Boot는 풀 수 있는 것까지 막습니다

Spring Boot 2.6 릴리스 노트는 빈 사이의 순환 참조를 기본 금지로 바꾸고, `spring.main.allow-circular-references`를 `true`로 두면 2.5의 동작을 되돌릴 수 있다고 적고 있습니다. 이 속성은 4.1.1에서도 그대로 동작합니다. 직접 확인한 조합은 이렇습니다.

| 주입 방식 | 기본 설정 | `allow-circular-references=true` |
|---|---|---|
| 필드·세터 주입 사이클 | 기동 실패 | 기동 성공 (양쪽 참조 정상) |
| 생성자 주입 사이클 | 기동 실패 | **여전히 기동 실패** |

두 번째 줄이 중요합니다. 속성을 켜도 생성자 사이클은 살아나지 않습니다. 켜서 해결됐다면 원래 필드·세터 주입이었다는 뜻입니다.

## 3. 자동 해결의 청구서

2.5까지의 기본 동작은 "알아서 끊어주기"였습니다. 편해 보이지만 대가가 있습니다.

**초기화 순서가 클래스 스캔 순서에 묶입니다.** 위 흐름에서 `OrderService`가 먼저 생성되면 미완성 상태로 노출되는 쪽은 `OrderService`이고, 반대로 스캔되면 노출되는 쪽이 바뀝니다. 클래스 이름을 바꾸거나 패키지를 옮기는 것만으로 "누가 반쯤 만들어진 객체를 보느냐"가 뒤집힙니다.

**그래서 `@PostConstruct`에서 상대 빈의 메서드를 부르면 조용히 깨집니다.** 미완성 참조를 들고 있는 쪽은 상대의 필드가 아직 `null`입니다. 컴파일도 되고 기동도 되고, 그 메서드가 실제로 불리는 첫 요청에서 `NullPointerException`이 납니다.

이 두 가지가 "기동은 되는데 원인을 못 찾는" 부류의 버그를 만듭니다. 기본값을 뒤집은 건 이 부류를 기동 시점으로 끌어올린 결정입니다.

## 4. 진통제 세 개와 각각의 가격

검색하면 거의 항상 이 셋 중 하나가 나옵니다. 셋 다 사이클을 없애지 않고 **주입 시점을 미루기만** 합니다.

### 4-1. `@Lazy` — 프록시를 대신 꽂습니다

```java
@Service
class OrderService {
    private final CouponService couponService;
    OrderService(@Lazy CouponService couponService) { this.couponService = couponService; }
}
```

기본 설정 그대로 기동에 성공합니다. 다만 실제로 꽂힌 객체를 찍어보면 이렇습니다.

```
RESULT @Lazy injected type   : App$CouponService$$SpringCGLIB$$0
```

`CouponService`가 아니라 CGLIB 프록시입니다. 첫 메서드 호출 때 진짜 빈을 찾아옵니다. 가격은 세 가지입니다. 대상 클래스가 `final`이면 프록시를 못 만들고, `final` 메서드는 가로채지 못하며, 디버거와 로그에 찍히는 타입이 실제 타입과 달라집니다.

### 4-2. `ObjectProvider` — 주입 대신 조회로 바꿉니다

```java
@Service
class PointService {
    private final ObjectProvider<CouponService> couponServiceProvider;
    PointService(ObjectProvider<CouponService> provider) { this.couponServiceProvider = provider; }

    public Money discountFor(Long couponId, Money amount) {
        return couponServiceProvider.getObject().discount(couponId, amount);
    }
}
```

```
RESULT provider lookup type  : CouponService
```

`@Lazy`와 달리 실제 타입이 그대로 나옵니다. 프록시가 아니라 호출 시점 조회이기 때문입니다. 가격은 **의존이 생성자 시그니처에서 사라진다**는 점입니다. `OrderService`가 무엇에 의존하는지 생성자만 봐서는 알 수 없고, 필드 타입을 열어봐야 합니다. 의존 관계를 드러내라고 생성자 주입을 쓰는 건데 그 효과를 스스로 지웁니다.

### 4-3. `spring.main.allow-circular-references=true` — 전역 스위치

가장 빨리 통과되고 가장 나중까지 남습니다. 사이클 하나 때문에 애플리케이션 전체의 안전장치를 끄는 선택이고, 한 번 켜두면 그 뒤에 생기는 사이클은 아무도 모릅니다. 릴리스 노트 자체가 "최후의 수단"이라고 적고 있습니다. 마이그레이션 중 임시로 켠다면, 끄는 티켓을 같이 만들어두는 게 맞습니다.

### 4-4. 자기 주입은 Boot 기본 설정에서 기동을 막습니다

`@Transactional`이 같은 클래스 내부 호출에서 안 먹는 문제를 우회하려고 자기 자신을 주입받는 코드가 종종 있습니다.

```java
@Service
public class OrderService {
    @Autowired private OrderService self;   // 길이 1짜리 사이클
}
```

빈이 이것 하나뿐이어도 Spring Boot 4.1.1 기본 설정에서 기동이 실패합니다. 직접 확인했습니다. 길이 1짜리 사이클도 사이클이기 때문입니다.

`@Lazy`를 붙이면 뜹니다. 대신 이렇게 됩니다.

```
RESULT started, self==bean : false
```

주입된 `self`는 컨테이너가 관리하는 그 빈이 **아닙니다.** 프록시입니다. 트랜잭션을 걸겠다는 목적에는 맞지만, `self`와 `this`를 동일시하는 코드를 쓰면 그때부터 틀립니다. 애초에 이 패턴은 "트랜잭션 경계를 가진 메서드가 다른 클래스로 나가야 한다"는 신호에 가깝습니다.

## 5. 사이클은 셋 중 하나를 가리킵니다

여기부터가 본론입니다. 실무에서 만나는 사이클은 대개 세 유형 중 하나입니다.

**유형 1 — 하나의 책임이 두 빈에 걸쳐 있습니다.** 두 서비스가 같은 판단을 나눠 들고 있어서 서로를 계속 불러야 합니다. 해법은 그 판단을 제3의 빈으로 뽑아내는 것입니다. 두 빈이 모두 새 빈을 향하면 고리가 열립니다.

**유형 2 — 의존 방향이 거꾸로 박혀 있습니다.** 아래 계층이 위 계층을 부르고 있는 경우입니다. 대개 "저쪽 데이터가 필요해서" 서비스를 주입받은 것이고, 실제로 필요한 건 서비스가 아니라 조회입니다. 저장소나 조회 전용 컴포넌트에 의존하도록 낮추면 방향이 한쪽으로 정리됩니다.

**유형 3 — 부수효과가 본류에 박혀 있습니다.** 주문이 끝나면 쿠폰·포인트·알림이 뒤따르는데 이것들이 서로를 직접 부르는 경우입니다. 해법은 `ApplicationEventPublisher`로 이벤트를 발행하고 각 관심사가 구독하는 것입니다. 발행자는 구독자를 모르므로 고리가 생길 수 없습니다. 다만 흐름이 코드에서 안 보이게 되는 대가가 있어서, 트랜잭션 경계와 실패 처리를 같이 설계해야 합니다.

## 6. 예제 — 주문과 쿠폰

### 6-1. 사이클이 있는 코드 ❌

```java
@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final CouponService couponService;

    public OrderService(OrderRepository orderRepository, CouponService couponService) {
        this.orderRepository = orderRepository;
        this.couponService = couponService;
    }

    @Transactional
    public Long place(Long userId, List<OrderLine> lines, Long couponId) {
        Order order = Order.of(userId, lines);
        if (couponId != null) {
            order.applyDiscount(couponService.use(couponId, userId, order.totalAmount()));
        }
        return orderRepository.save(order).getId();
    }

    public boolean hasOrderWithCoupon(Long userId, Long couponId) {
        return orderRepository.existsByUserIdAndCouponId(userId, couponId);
    }
}

@Service
public class CouponService {

    private final CouponRepository couponRepository;
    private final OrderService orderService;   // ← 여기서 고리가 닫힙니다

    public CouponService(CouponRepository couponRepository, OrderService orderService) {
        this.couponRepository = couponRepository;
        this.orderService = orderService;
    }

    @Transactional
    public Money use(Long couponId, Long userId, Money amount) {
        Coupon coupon = couponRepository.findById(couponId)
                .orElseThrow(() -> new CouponNotFoundException(couponId));
        if (orderService.hasOrderWithCoupon(userId, couponId)) {
            throw new CouponAlreadyUsedException(couponId);
        }
        return coupon.discountFor(amount);
    }
}
```

`CouponService`는 `OrderService`의 기능이 필요한 게 아닙니다. **"이 사용자가 이 쿠폰을 이미 썼는가"라는 사실 하나가 필요할 뿐입니다.** 그런데 그 사실이 주문 테이블에만 있어서 주문 서비스를 통째로 끌어왔습니다. 유형 2입니다.

### 6-2. 방향을 낮춘 코드 ✔️

```java
@Service
public class CouponService {

    private final CouponRepository couponRepository;
    private final OrderQueryRepository orderQueryRepository;   // 서비스가 아니라 조회에 의존

    public CouponService(CouponRepository couponRepository,
                         OrderQueryRepository orderQueryRepository) {
        this.couponRepository = couponRepository;
        this.orderQueryRepository = orderQueryRepository;
    }

    @Transactional
    public Money use(Long couponId, Long userId, Money amount) {
        Coupon coupon = couponRepository.findById(couponId)
                .orElseThrow(() -> new CouponNotFoundException(couponId));
        if (orderQueryRepository.existsByUserIdAndCouponId(userId, couponId)) {
            throw new CouponAlreadyUsedException(couponId);
        }
        return coupon.discountFor(amount);
    }
}
```

고리가 열렸습니다. 두 서비스가 서로를 모르고, 둘 다 자기보다 아래 계층만 봅니다. 5분이면 끝나고 대부분의 경우 이걸로 충분합니다.

### 6-3. 상태의 주인을 정한 코드 ✔️✔️

그래도 남는 질문이 있습니다. 쿠폰 사용 여부를 왜 주문 테이블에 물어봐야 할까요. **사이클이 가리키고 있던 건 이 지점입니다.** 쿠폰의 사용 이력이 쿠폰 쪽에 없습니다.

```java
@Entity
@Table(uniqueConstraints = @UniqueConstraint(columnNames = {"coupon_id", "user_id"}))
public class CouponRedemption {
    @Id @GeneratedValue private Long id;
    private Long couponId;
    private Long userId;
    private Long orderId;
    private Instant redeemedAt;
    // ... 생략
}
```

```java
@Transactional
public Money use(Long couponId, Long userId, Money amount) {
    Coupon coupon = couponRepository.findById(couponId)
            .orElseThrow(() -> new CouponNotFoundException(couponId));
    try {
        redemptionRepository.saveAndFlush(CouponRedemption.of(couponId, userId));
    } catch (DataIntegrityViolationException e) {
        throw new CouponAlreadyUsedException(couponId);
    }
    return coupon.discountFor(amount);
}
```

`OrderQueryRepository` 의존도 사라졌고, 조회 후 삽입 사이의 경합도 유니크 제약이 막아줍니다. 동시 요청 두 개가 같은 쿠폰을 쓰는 문제를 애플리케이션이 아니라 DB 제약으로 판정하는 이유는 `daily/day21-idempotency.md`에서 다뤘습니다.

## 7. 함정

**사이클이 세 개 이상에 걸쳐 있으면 어디를 끊을지 안 보입니다**
- **증상**: 실패 메시지의 화살표 그림에 빈이 네댓 개 나열되고, 전부 정상적인 의존처럼 보입니다.
- **원인**: 그림에 찍힌 순서는 컨테이너가 생성을 시도한 순서지 잘못된 지점의 순서가 아닙니다. 첫 줄이 범인이라는 보장이 없습니다.
- **해법**: 그림에 나온 빈들의 의존 중 **계층을 거슬러 올라가는 간선 하나**를 찾습니다. 아래 계층이 위 계층을 향하는 화살표가 거의 항상 있습니다. 하나도 없다면 유형 1이니 공통 판단을 제3의 빈으로 뽑습니다.

**속성을 켰는데도 기동이 안 됩니다**
- **증상**: `spring.main.allow-circular-references=true`를 넣었는데 `BeanCurrentlyInCreationException`이 그대로 납니다.
- **원인**: 그 사이클이 생성자 주입으로 닫혀 있습니다. 이 속성은 이른 참조를 허용할 뿐이고, 생성자 인자는 이른 참조로 채울 수 없습니다. 4.1.1에서 직접 확인했습니다.
- **해법**: 속성으로 해결하려 하지 말고 고리를 끊습니다. 정 급하면 한쪽 생성자 인자에 `@Lazy`를 붙이면 속성 없이도 뜨지만, 4-1의 가격을 떠안습니다.

**`@Lazy`로 뚫은 사이클은 첫 요청에서 터집니다**
- **증상**: 기동은 성공했는데 배포 후 특정 API의 첫 호출만 실패합니다.
- **원인**: `@Lazy` 프록시는 첫 메서드 호출 시점에 대상 빈을 찾습니다. 기동 시점 검증을 통째로 건너뛴 셈입니다. 같은 타입 빈이 둘인 상태로 `@Lazy` 주입을 하고 띄워보면 이렇게 나옵니다.

  ```
  RESULT context started
  RESULT lazy call FAILED: NoUniqueBeanDefinitionException
  ```

  주입 지점이 모호한데도 기동은 성공합니다. `@Lazy`가 없었다면 이건 기동에서 잡혔을 문제입니다.
- **해법**: `@Lazy`를 쓴 지점은 목록으로 관리하고, 그 경로를 태우는 통합 테스트를 둡니다. 기동만 확인하는 테스트로는 절대 안 잡힙니다.

**`@PostConstruct`에서 상대 빈을 부르면 `null`입니다**
- **증상**: 속성을 켜서 필드 주입 사이클로 기동했는데, 초기화 훅 안에서 `NullPointerException`이 납니다.
- **원인**: 이른 참조로 받은 상대 빈은 아직 필드 주입이 끝나지 않은 상태입니다. 양쪽 `@PostConstruct`에서 상대의 필드를 찍어보면 한쪽만 `null`입니다.

  ```
  RESULT OrderService @PostConstruct, coupon.orderService = null
  RESULT CouponService @PostConstruct, order.couponService = set
  ```

  먼저 생성된 쪽(여기서는 `CouponService`)이 미완성으로 노출되고, 나중에 생성된 쪽의 훅이 그 미완성 객체를 봅니다. 그리고 **생성 순서는 클래스 이름이나 패키지 구조에 따라 바뀝니다.** 클래스 이름 하나 바꾸면 `null`이 나는 쪽이 반대가 됩니다.
- **해법**: 초기화 훅에서 상대 빈의 상태에 의존하지 않습니다. 모든 싱글톤이 준비된 뒤여야 한다면 `SmartInitializingSingleton`이나 `ApplicationReadyEvent`로 옮깁니다. 근본 해법은 역시 고리를 끊는 것입니다.

## 8. 참고자료

- [Spring Boot 2.6 Release Notes — Circular References Prohibited by Default](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-2.6-Release-Notes)
- [Spring Framework Reference — Dependency Injection / Circular Dependencies](https://docs.spring.io/spring-framework/reference/core/beans/dependencies/factory-collaborators.html)
- `daily/day32-bean-lifecycle.md` — 빈이 만들어지고 초기화되는 순서
- `daily/day08-di-why.md` — 의존성 주입이 푸는 문제
- `daily/day21-idempotency.md` — 유니크 제약으로 경합을 판정하는 이유
