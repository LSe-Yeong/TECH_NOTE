# DTO와 Entity를 분리해야 하는 이유

## 1. 핵심 개념

- **Entity**: JPA가 테이블과 매핑하는 객체입니다. 영속성 컨텍스트가 생명주기를 관리하고, 연관관계와 지연 로딩을 갖습니다.
- **DTO**(Data Transfer Object): 계층 사이에서 데이터를 주고받기 위한 객체입니다. 테이블 구조와는 무관하고, API 계약만 표현합니다.

> Entity 하나로 DB 저장과 API 응답을 동시에 해결하면 편해 보입니다. 그런데 Entity는 "테이블과 어떻게 매핑되는가"에 최적화된 객체이고, API 응답은 "클라이언트에게 무엇을 보여줄 것인가"에 최적화된 계약입니다. 이 둘을 하나로 묶으면, `orders` 테이블에 컬럼 하나를 추가했을 뿐인데 API 응답 스펙이 같이 바뀌거나, 반대로 API 응답에 필드 하나를 추가하려다 연관관계 매핑까지 건드리게 됩니다.

## 2. 구조

- **Entity의 책임**: 테이블 매핑, 연관관계 관리, 영속성 컨텍스트 생명주기(더티 체킹 대상)
- **DTO의 책임**: 계층 경계 밖으로 나갈 필드만 선택적으로 노출, 검증 어노테이션(`@NotNull`, `@Size` 등)을 붙일 자리, API 계약의 독립적인 버전 관리

두 책임이 다르기 때문에, 한쪽을 바꿔도 다른 쪽이 흔들리지 않게 하려면 객체 자체를 분리해야 합니다.

### 2-1. 선택적 확장 지점

DTO ↔ Entity 매핑은 직접 생성자·정적 팩토리 메서드로 짤 수도 있고, [MapStruct](https://mapstruct.org/) 같은 라이브러리로 컴파일 타임에 매핑 코드를 자동 생성할 수도 있습니다. 필드가 몇 개 안 되면 수동 매핑이 오히려 명확하고, 필드가 많고 매핑 규칙이 반복되면 MapStruct가 보일러플레이트를 줄여줍니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
// 요청 계약 — 클라이언트가 보낼 수 있는 필드만 정의
public record OrderCreateRequest(
    Long productId,
    int quantity
) {}

// 응답 계약 — 클라이언트에게 보여줄 필드만 정의
public record OrderResponse(
    Long id,
    String productName,
    int quantity,
    String status
) {
    public static OrderResponse from(Order order) {
        return new OrderResponse(
            order.getId(),
            order.getProduct().getName(),
            order.getQuantity(),
            order.getStatus().name()
        );
    }
}

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    @PostMapping
    public OrderResponse createOrder(@RequestBody OrderCreateRequest request) {
        Order order = orderService.createOrder(request.productId(), request.quantity());
        return OrderResponse.from(order);
    }
}
```

### 3-2. 실행 흐름

```
Client --(RequestDto, JSON)--> Controller
Controller --(검증된 값 전달)--> Service
Service --(Entity 저장/조회)--> Repository
Repository --(Entity)--> Service
Service --(Entity → ResponseDto 변환)--> Controller
Controller --(ResponseDto, JSON)--> Client
```

Entity는 Service와 Repository 사이에서만 돌아다닙니다. Controller 바깥, 즉 클라이언트와 마주치는 지점에는 DTO만 노출됩니다.

## 4. 특징

### 4-1. 사용 시기

외부에 노출되는 모든 API 경계에서 씁니다. 내부적으로만 쓰는 배치 작업이나 단일 모듈 안의 헬퍼 메서드까지 DTO로 감쌀 필요는 없습니다.

### 4-2. 장점

- API 계약과 테이블 구조가 서로 독립적으로 바뀔 수 있습니다.
- 클라이언트에게 노출할 필드를 명시적으로 고를 수 있습니다(보안).
- 연관관계·지연 로딩과 무관한 순수 값 객체라서, 뒤에서 다룰 무한 재귀·`LazyInitializationException` 문제 자체가 발생하지 않습니다.

### 4-3. 단점 / 트레이드오프

- Entity 필드를 하나 추가하면 DTO도 같이 늘어나야 하는 이중 관리 비용이 생깁니다.
- 매핑 코드(`from()`, `toEntity()` 등)가 계속 쌓입니다. 규모가 커지면 이 매핑 코드 자체가 유지보수 대상이 됩니다.
- 단순 조회-그대로-반환 API에서는 DTO가 Entity 필드를 1:1로 복사하는 것처럼 보여서 "왜 굳이 나누나" 싶은 순간이 옵니다. 그래도 계약을 Entity에 묶지 않는다는 이유만으로 분리할 가치가 있습니다.

## 5. 예제

### 5-1. 클린하지 않은 코드 ❌

```java
@Entity
public class Order {
    @Id @GeneratedValue
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    private Product product;

    private int quantity;

    private boolean isAdminApproved;   // 내부 운영용 필드 — 클라이언트가 건드리면 안 됨

    // getter, setter 생략
}

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderRepository orderRepository;

    public OrderController(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    // ❌ Entity를 요청 바디로 직접 받는다
    // → 클라이언트가 isAdminApproved 같은 필드까지 채워서 보낼 수 있다 (Mass Assignment)
    @PostMapping
    public Order createOrder(@RequestBody Order order) {
        return orderRepository.save(order);
    }

    // ❌ Entity를 그대로 응답으로 반환한다
    // → product가 지연 로딩이면 트랜잭션 밖에서 접근 시 LazyInitializationException
    // → Order와 Product가 서로를 참조하는 양방향 관계면 무한 재귀로 StackOverflowError
    @GetMapping("/{id}")
    public Order getOrder(@PathVariable Long id) {
        return orderRepository.findById(id).orElseThrow();
    }
}
```

### 5-2. 개선한 코드 ✔️

```java
public record OrderCreateRequest(Long productId, int quantity) {}

public record OrderResponse(Long id, String productName, int quantity) {
    public static OrderResponse from(Order order) {
        return new OrderResponse(order.getId(), order.getProduct().getName(), order.getQuantity());
    }
}

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    // ✅ 클라이언트가 채울 수 있는 필드가 DTO에 정의된 것으로 제한된다
    @PostMapping
    public OrderResponse createOrder(@RequestBody OrderCreateRequest request) {
        Order order = orderService.createOrder(request.productId(), request.quantity());
        return OrderResponse.from(order);
    }

    // ✅ 트랜잭션 안에서 필요한 필드만 미리 꺼내 DTO로 변환 후 반환한다
    @GetMapping("/{id}")
    public OrderResponse getOrder(@PathVariable Long id) {
        return OrderResponse.from(orderService.getOrder(id));
    }
}
```

## 6. 단일 책임 원칙(SRP)

Entity와 DTO를 나누는 건 "객체가 바뀌는 이유는 하나여야 한다"는 단일 책임 원칙의 적용입니다. Entity가 바뀌는 이유는 테이블 구조 변경이고, DTO가 바뀌는 이유는 API 계약 변경입니다. 이 둘을 한 객체에 합치면, 서로 다른 이유로 같은 클래스를 계속 고치게 됩니다.

### 6-1. 원칙을 어긴 코드 ❌

```java
// ❌ 하나의 클래스가 "테이블 매핑"과 "API 응답 형태" 두 가지 이유로 바뀐다
@Entity
public class Product {
    @Id @GeneratedValue
    private Long id;
    private String name;
    private int stock;          // 내부 재고 — API에는 노출하고 싶지 않음
    private BigDecimal costPrice; // 원가 — 절대 노출하면 안 됨
    private BigDecimal sellPrice;
}
```

### 6-2. 원칙을 지킨 코드 ✔️

```java
// ✅ Product는 테이블 매핑 이유로만 바뀐다
@Entity
public class Product {
    @Id @GeneratedValue
    private Long id;
    private String name;
    private int stock;
    private BigDecimal costPrice;
    private BigDecimal sellPrice;
}

// ✅ ProductResponse는 API 계약 이유로만 바뀐다 — 원가·재고는 애초에 필드가 없다
public record ProductResponse(Long id, String name, BigDecimal sellPrice) {
    public static ProductResponse from(Product product) {
        return new ProductResponse(product.getId(), product.getName(), product.getSellPrice());
    }
}
```

## 7. 확장 지점 응용하기 — MapStruct

### 7-1. 클린하지 않은 코드 ❌

```java
// ❌ 필드가 늘어날 때마다 이런 변환 메서드를 손으로 계속 늘려야 한다
public class OrderMapper {
    public static OrderResponse toResponse(Order order) {
        return new OrderResponse(
            order.getId(),
            order.getProduct().getName(),
            order.getQuantity(),
            order.getStatus().name()
        );
    }
}
```

### 7-2. MapStruct를 적용한 코드 ✔️

```java
@Mapper(componentModel = "spring")
public interface OrderMapper {

    @Mapping(source = "product.name", target = "productName")
    @Mapping(source = "status", target = "status", qualifiedByName = "statusToString")
    OrderResponse toResponse(Order order);

    @Named("statusToString")
    static String statusToString(OrderStatus status) {
        return status.name();
    }
}
```

MapStruct는 어노테이션 프로세서가 컴파일 타임에 구현체를 생성합니다. 리플렉션을 쓰지 않아서 런타임 비용이 없고, 매핑 누락은 컴파일 경고로 드러납니다.

## 8. 실무에서 찾아보는 DTO

Spring Data REST는 **Projections and Excerpts**라는 이름으로 DTO 패턴을 프레임워크 차원에서 지원합니다. 인터페이스 기반 프로젝션 외에, 값 타입 DTO로도 프로젝션을 정의할 수 있다고 공식 문서가 명시합니다. 이때 Java `record`가 DTO 타입으로 적합하다고 안내합니다. 모든 필드가 `private final`이고 `equals()`/`hashCode()`/`toString()`을 자동 생성해 값 객체로서의 의미를 그대로 지키기 때문입니다. ([Spring Data REST — Projections and Excerpts](https://docs.spring.io/spring-data/rest/reference/projections-excerpts.html))

## 9. 관련된 개념과 비교

### 9-1. DTO vs VO(Value Object)

**유사점**

- 둘 다 불변으로 만드는 경우가 많고, 데이터를 담는 게 주 목적입니다.

**차이점**

- DTO는 "계층 간 전달"이 목적이라 여러 도메인 개념을 조합해서 담아도 됩니다(예: 주문과 상품 정보를 함께 담은 `OrderResponse`).
- VO는 도메인 모델 내부에서 "값 자체의 의미"를 표현합니다(예: `Money`, `Email`). 도메인 로직을 가질 수 있다는 점도 다릅니다.

### 9-2. DTO vs Domain Model(Entity)

- Entity는 식별자(`id`)로 동일성을 판단하고 상태 변화(생명주기)를 갖습니다.
- DTO는 식별자 유무와 무관하게 필드 값이 같으면 같다고 취급해도 되는, 상태 변화가 없는 스냅샷입니다.

## 10. 함정

**Entity를 요청 바디로 직접 받았더니 클라이언트가 의도치 않은 필드를 채워 보낸다 (Mass Assignment)**

- **증상**: `@RequestBody`로 Entity를 그대로 받는 API에, 원래 없어야 할 `role`, `isAdmin`, `isAdminApproved` 같은 필드까지 JSON에 실어 보내면 그대로 저장됩니다.
- **원인**: Spring MVC의 자동 바인딩은 요청 JSON의 키와 객체 필드 이름이 일치하면 값을 채웁니다. Entity가 내부 운영용 필드까지 갖고 있으면, 그 필드도 바인딩 대상이 됩니다. OWASP는 이를 API 취약점으로 분류합니다(2019년판 API6:2019 Mass Assignment, 2023년판에서는 API3:2023 Broken Object Property Level Authorization으로 통합). ([OWASP API Security Top 10](https://owasp.org/API-Security/editions/2019/en/0xa6-mass-assignment/))
- **해법**: 요청 전용 DTO를 만들어 클라이언트가 채울 수 있는 필드만 명시적으로 열어둡니다(allow-list).

**Entity를 응답으로 그대로 반환했더니 무한 재귀로 `StackOverflowError`가 난다**

- **증상**: 양방향 연관관계(`Order` ↔ `Product`, `Product` ↔ `Order`)를 가진 Entity를 Jackson이 직렬화하면 서로를 계속 참조하며 무한히 순회하다 스택이 터집니다.
- **원인**: Jackson은 필드에 접근 가능한 연관관계 객체를 만나면 그 객체도 직렬화합니다. 양방향 관계에서는 부모가 자식을, 자식이 다시 부모를 참조하는 순환이 생깁니다. `@JsonManagedReference`/`@JsonBackReference`나 `@JsonIgnore`로 한쪽 방향을 끊어 완화할 수는 있지만, Entity 구조 자체에 API 직렬화 관심사가 섞여 들어간다는 근본 문제는 남습니다.
- **해법**: DTO로 필요한 필드만 뽑아서 반환합니다. 애초에 순환 참조가 생길 여지가 없습니다.

**DTO로 변환하려고 하니 `LazyInitializationException`이 난다**

- **증상**: Service 메서드가 끝나고 트랜잭션이 닫힌 뒤, Controller나 별도 변환 로직에서 지연 로딩 필드(`order.getProduct().getName()`)에 접근하면 예외가 발생합니다.
- **원인**: 지연 로딩 필드는 영속성 컨텍스트(트랜잭션)가 열려 있을 때만 프록시를 통해 값을 채울 수 있습니다. 트랜잭션이 끝난 뒤에는 프록시가 초기화를 할 수 없습니다.
- **해법**: Entity → DTO 변환을 트랜잭션이 열려 있는 Service 메서드 안에서 끝냅니다. Controller까지 Entity를 들고 나가지 않는 것 자체가 이 문제를 막는 방법입니다.

## 11. 참고자료

- [Spring Data REST — Projections and Excerpts](https://docs.spring.io/spring-data/rest/reference/projections-excerpts.html)
- [OWASP API Security Top 10 — API6:2019 Mass Assignment](https://owasp.org/API-Security/editions/2019/en/0xa6-mass-assignment/)
- [OWASP Mass Assignment Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html)
- [Baeldung — Jackson Bidirectional Relationships and Infinite Recursion](https://www.baeldung.com/jackson-bidirectional-relationships-and-infinite-recursion)
- [MapStruct 공식 사이트](https://mapstruct.org/)
- `daily/day06-service-layer-design.md` — 서비스 계층의 책임은 어디까지인가
