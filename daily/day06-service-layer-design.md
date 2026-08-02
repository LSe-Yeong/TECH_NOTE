# 서비스 계층의 책임은 어디까지인가

## 1. 핵심 개념

**Service Layer**는 Controller(표현 계층)와 Repository(영속성 계층) 사이에서 하나의 유스케이스를 완결시키는 계층입니다. 트랜잭션 경계를 정하고, 여러 Repository·외부 API 호출을 하나의 흐름으로 묶습니다.

> Service 없이 Controller가 Repository를 직접 호출하면 어떻게 될까요. 주문 생성이라는 하나의 유스케이스 안에 재고 확인, 결제 요청, 포인트 차감이 얽혀 있다고 하면, 이 흐름을 어디서 트랜잭션으로 묶을지 애매해집니다. 또 같은 "주문 생성" 로직이 REST API와 배치 작업 양쪽에서 필요하면, Controller에 있던 로직을 그대로 복사하게 됩니다. Service는 이 유스케이스 단위 로직을 한 군데 모아서, 트랜잭션 경계를 명확히 하고 재사용 가능하게 만듭니다.

## 2. 구조

- **Controller**: HTTP 요청·응답 변환, 입력 검증 트리거. 비즈니스 로직을 갖지 않습니다.
- **Service**: 유스케이스 단위 오케스트레이션과 트랜잭션 경계. 여러 Repository·도메인 객체·외부 클라이언트를 조합합니다.
- **Domain(Entity/도메인 객체)**: 상태와, 그 상태를 스스로 지키는 규칙(불변식, 상태 전이 조건).
- **Repository**: 영속성 접근만 담당합니다.

Service의 핵심 책임은 "무엇을 할지 결정하는 로직"이 아니라 "누구에게 시키고 어떤 순서로 묶을지 조율하는 로직"입니다. 개별 규칙(할인율 계산, 상태 전이 가능 여부 판단 등)은 가능한 한 도메인 객체에 남겨둡니다.

### 2-1. 선택적 확장 지점

Service가 커지면 역할을 둘로 나눌 수 있습니다. **Application Service**는 트랜잭션 경계와 조율만 담당하고, **Domain Service**는 하나의 Entity에 넣기 애매한 도메인 규칙(여러 Entity를 조합해야 계산되는 정책 등)을 담당합니다. Spring의 `@Service`는 이 둘을 구분하지 않지만, 클래스를 나눠서 역할을 분리할 수 있습니다(7장 참고).

## 3. 흐름

### 3-1. 코드로 보는 구성

```java
@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final ProductRepository productRepository;
    private final PaymentClient paymentClient;

    public OrderService(OrderRepository orderRepository,
                         ProductRepository productRepository,
                         PaymentClient paymentClient) {
        this.orderRepository = orderRepository;
        this.productRepository = productRepository;
        this.paymentClient = paymentClient;
    }

    @Transactional
    public Order placeOrder(Long productId, int quantity, String paymentToken) {
        Product product = productRepository.findById(productId)
            .orElseThrow(() -> new ProductNotFoundException(productId));

        product.decreaseStock(quantity);          // 규칙 판단은 도메인 객체가 한다
        paymentClient.charge(paymentToken, product.calculatePrice(quantity));

        Order order = Order.place(product, quantity);
        return orderRepository.save(order);
    }
}
```

### 3-2. 실행 흐름

```
Controller --(유스케이스 호출)--> Service
Service --(트랜잭션 경계 안에서 조회/저장)--> Repository --> DB
Service --(규칙 판단 위임)--> Domain --(상태 변경 결과)--> Service
```

Service는 Repository에서 데이터를 가져와 Domain 객체에 판단을 맡기고, 그 결과를 다시 Repository로 저장합니다. "판단"이 Domain에 있다는 게 핵심입니다.

## 4. 특징

### 4-1. 사용 시기

트랜잭션이 필요하거나, 하나의 유스케이스가 여러 Repository·외부 API를 조합해야 할 때 Service를 둡니다. 단순 조회 하나를 그대로 반환하는 경우까지 억지로 Service를 거칠 필요는 없지만, 팀 컨벤션상 일관성을 위해 얇게라도 두는 경우가 많습니다.

### 4-2. 장점

- 트랜잭션 경계가 명확해집니다. `@Transactional`을 어디에 붙일지 고민할 필요 없이 Service 메서드 단위로 정해집니다.
- 같은 유스케이스를 여러 진입점(REST API, 배치, 메시지 컨슈머)에서 재사용할 수 있습니다.
- Repository를 목(mock)으로 대체해 Controller 레이어 없이 유스케이스 단위 테스트가 가능합니다.

### 4-3. 단점 / 트레이드오프

- 계층이 하나 늘어나므로, 단순 CRUD만 하는 기능에는 Controller → Repository로 바로 가는 것보다 코드가 늘어납니다.
- Service에 모든 로직을 몰아넣는 습관이 들면, Entity는 getter/setter만 남고 로직은 전부 Service에 쌓이는 **빈약한 도메인 모델(Anemic Domain Model)**로 흐르기 쉽습니다(10장 함정 참고).

## 5. 예제

### 5-1. 클린하지 않은 코드 ❌

```java
// ❌ 하나의 메서드가 검증, 재고 차감, 결제, 이메일 발송을 전부 처리한다
// ❌ Entity 필드를 직접 꺼내서 계산한다 (캡슐화 위반)
@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final ProductRepository productRepository;
    private final PaymentClient paymentClient;
    private final EmailClient emailClient;

    // 생성자 생략

    @Transactional
    public Order placeOrder(Long productId, int quantity, String paymentToken, String email) {
        Product product = productRepository.findById(productId).orElseThrow();

        if (product.getStock() < quantity) {
            throw new IllegalStateException("재고 부족");
        }
        product.setStock(product.getStock() - quantity);

        BigDecimal price = product.getPrice().multiply(BigDecimal.valueOf(quantity));
        if (quantity >= 10) {
            price = price.multiply(BigDecimal.valueOf(0.9)); // 대량 구매 할인 10%
        }
        paymentClient.charge(paymentToken, price);

        Order order = new Order();
        order.setProduct(product);
        order.setQuantity(quantity);
        order.setStatus(OrderStatus.PLACED);
        Order saved = orderRepository.save(order);

        emailClient.send(email, "주문이 완료되었습니다. 주문번호: " + saved.getId());

        return saved;
    }
}
```

### 5-2. 개선한 코드 ✔️

```java
@Entity
public class Product {
    // 필드 생략

    public void decreaseStock(int quantity) {
        if (this.stock < quantity) {
            throw new InsufficientStockException(this.id, quantity);
        }
        this.stock -= quantity;
    }

    public BigDecimal calculatePrice(int quantity) {
        BigDecimal base = this.price.multiply(BigDecimal.valueOf(quantity));
        return quantity >= 10 ? base.multiply(BigDecimal.valueOf(0.9)) : base;
    }
}

@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final ProductRepository productRepository;
    private final PaymentClient paymentClient;
    private final OrderNotifier orderNotifier;   // 알림 발송을 별도 협력자로 분리

    // 생성자 생략

    @Transactional
    public Order placeOrder(Long productId, int quantity, String paymentToken, String email) {
        Product product = productRepository.findById(productId)
            .orElseThrow(() -> new ProductNotFoundException(productId));

        product.decreaseStock(quantity);
        paymentClient.charge(paymentToken, product.calculatePrice(quantity));

        Order order = orderRepository.save(Order.place(product, quantity));
        orderNotifier.notifyOrderPlaced(email, order.getId());

        return order;
    }
}
```

Service는 "재고를 줄여라", "가격을 계산해라", "알림을 보내라"라고 시킬 뿐, 재고가 얼마나 있는지·할인율이 몇 퍼센트인지는 직접 판단하지 않습니다.

## 6. Tell, Don't Ask 원칙

Service가 Entity의 값을 꺼내서(`getStock()`) 직접 조건을 판단하고 다시 값을 넣는(`setStock()`) 방식은 **Tell, Don't Ask** 원칙을 어깁니다. 객체에게 상태를 물어보고 호출자가 판단하는 대신, 객체에게 "이렇게 해라"라고 시키고 판단은 객체 안에서 하게 하는 원칙입니다.

### 6-1. 원칙을 어긴 코드 ❌

```java
// ❌ Service가 Product의 내부 상태를 꺼내서 직접 판단한다
if (product.getStock() < quantity) {
    throw new IllegalStateException("재고 부족");
}
product.setStock(product.getStock() - quantity);
```

### 6-2. 원칙을 지킨 코드 ✔️

```java
// ✅ Product에게 "재고를 줄여라"라고 시키고, 가능한지 여부는 Product가 판단한다
product.decreaseStock(quantity);
```

`decreaseStock()` 안에서 재고 부족 여부를 판단하므로, 같은 검증 로직이 다른 Service 메서드에서 또 중복될 일이 없습니다.

## 7. 확장 지점 응용하기 — Application Service와 Domain Service 분리

### 7-1. 클린하지 않은 코드 ❌

```java
// ❌ 배송비 계산 정책(여러 조건 조합)까지 OrderService가 직접 갖고 있다
@Service
public class OrderService {

    @Transactional
    public Order placeOrder(Long productId, int quantity, Address address) {
        Product product = productRepository.findById(productId).orElseThrow();

        BigDecimal shippingFee = BigDecimal.valueOf(3000);
        if (product.calculatePrice(quantity).compareTo(BigDecimal.valueOf(50000)) >= 0) {
            shippingFee = BigDecimal.ZERO; // 5만원 이상 무료 배송
        }
        if (address.isRemoteArea()) {
            shippingFee = shippingFee.add(BigDecimal.valueOf(5000)); // 도서산간 추가 요금
        }

        // ... 주문 생성 로직
        return orderRepository.save(Order.place(product, quantity, shippingFee));
    }
}
```

### 7-2. Domain Service로 분리한 코드 ✔️

```java
// ✅ 배송비 정책은 특정 Entity 하나에 속한 규칙이 아니므로 Domain Service로 분리한다
@Component
public class ShippingFeePolicy {

    private static final BigDecimal FREE_SHIPPING_THRESHOLD = BigDecimal.valueOf(50000);
    private static final BigDecimal BASE_FEE = BigDecimal.valueOf(3000);
    private static final BigDecimal REMOTE_AREA_SURCHARGE = BigDecimal.valueOf(5000);

    public BigDecimal calculate(BigDecimal orderAmount, Address address) {
        BigDecimal fee = orderAmount.compareTo(FREE_SHIPPING_THRESHOLD) >= 0 ? BigDecimal.ZERO : BASE_FEE;
        return address.isRemoteArea() ? fee.add(REMOTE_AREA_SURCHARGE) : fee;
    }
}

@Service
public class OrderService {

    private final ShippingFeePolicy shippingFeePolicy;
    // 나머지 필드 생략

    @Transactional
    public Order placeOrder(Long productId, int quantity, Address address) {
        Product product = productRepository.findById(productId).orElseThrow();
        BigDecimal orderAmount = product.calculatePrice(quantity);
        BigDecimal shippingFee = shippingFeePolicy.calculate(orderAmount, address);

        return orderRepository.save(Order.place(product, quantity, shippingFee));
    }
}
```

`ShippingFeePolicy`는 상태를 갖지 않는 순수 계산 객체입니다. `OrderService`(Application Service)는 여전히 트랜잭션과 조율만 담당하고, 배송비 정책이라는 도메인 규칙은 별도 Domain Service로 빠졌습니다.

## 8. 실무에서 찾아보는 서비스 계층

Spring Framework 공식 Javadoc은 `@Service` 어노테이션을 설명하면서, "Service"라는 용어를 Domain-Driven Design(Evans, 2003)에서 가져온 정의로 소개합니다. **"모델 안에서 독립적으로 존재하는, 캡슐화된 상태가 없는 인터페이스로 제공되는 연산"**이라는 정의입니다. Spring 자체는 `@Service`에 `@Component`와 다른 부가 기능을 주지는 않지만(둘 다 컴포넌트 스캔 대상이라는 점은 동일), 클래스의 의도를 드러내기 위한 스테레오타입으로 이 정의를 명시하고 있습니다. ([Spring Framework Javadoc — `@Service`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/stereotype/Service.html))

## 9. 관련된 개념과 비교

### 9-1. Service Layer(Domain Model) vs Transaction Script

**유사점**

- 둘 다 하나의 유스케이스(트랜잭션)를 처리하는 진입점이 있다는 점은 같습니다.

**차이점**

- Transaction Script는 Martin Fowler가 정리한 패턴으로, "각 프로시저가 프레젠테이션 계층의 요청 하나를 처리하는 방식으로 비즈니스 로직을 조직화"합니다. 로직이 절차 안에 순서대로 나열됩니다. ([Martin Fowler — Transaction Script](https://martinfowler.com/eaaCatalog/transactionScript.html))
- 이 글에서 다룬 Service Layer + Domain Model 조합은 로직을 객체(Entity, Domain Service)에 분산시키고, Service는 그 객체들을 조율만 합니다.
- 단순한 CRUD 위주 애플리케이션은 Transaction Script로도 충분하지만, 규칙이 복잡해지고 재사용되는 로직이 늘어날수록 Domain Model 쪽이 유리해집니다. 어느 쪽이 항상 옳다는 정답은 없습니다.

## 10. 함정

**Service 하나가 검증·재고·결제·알림을 전부 처리하는 "God Service"가 됐다**

- **증상**: `OrderService` 같은 클래스 하나의 메서드가 100줄을 넘고, 관련 없어 보이는 책임(이메일 발송, 결제, 재고 관리)이 한 메서드 안에 섞여 있습니다. 코드 리뷰에서 "이 메서드가 뭘 하는지" 한 문장으로 설명이 안 됩니다.
- **원인**: 새 요구사항이 생길 때마다 기존 메서드에 코드를 이어 붙이는 게 가장 쉬운 방법이기 때문입니다. 책임을 분리할 타이밍을 놓치면 계속 누적됩니다.
- **해법**: 책임 단위로 협력자를 분리합니다(알림은 `OrderNotifier`, 결제는 `PaymentClient`). Service는 이 협력자들을 순서대로 호출하는 조율자로만 남깁니다(5장, 7장 참고).

**Entity는 getter/setter만 남고, 로직이 전부 Service에 쌓이는 빈약한 도메인 모델(Anemic Domain Model)이 됐다**

- **증상**: Entity 클래스를 열어보면 필드와 getter/setter뿐이고, 실제 판단 로직은 전부 `XxxService`에 있습니다.
- **원인**: Martin Fowler는 이를 안티패턴으로 지적하면서, "데이터와 그 데이터를 다루는 프로세스를 함께 묶는다"는 객체지향의 기본 전제를 어긴 절차형 설계라고 설명합니다. 도메인 모델을 매핑하는 비용(ORM 등)은 그대로 지불하면서, 복잡한 로직을 객체에 담아 얻는 이점은 놓치는 셈입니다. ([Martin Fowler — AnemicDomainModel](https://martinfowler.com/bliki/AnemicDomainModel.html))
- **해법**: 상태를 바꾸는 규칙(재고 차감 가능 여부, 상태 전이 조건 등)을 Entity 메서드로 옮깁니다(6장 Tell, Don't Ask 참고). 다만 여러 Entity를 조합해야 하는 규칙까지 억지로 하나의 Entity에 넣을 필요는 없습니다. 그런 경우는 Domain Service로 분리합니다(7장 참고).

**Service 클래스 전체에 `@Transactional`을 습관적으로 붙였다**

- **증상**: 조회만 하는 메서드에도 쓰기 트랜잭션이 걸리고, 외부 API 호출(`paymentClient.charge()`)까지 트랜잭션 범위 안에 들어가서 DB 커넥션을 필요 이상으로 오래 점유합니다.
- **원인**: 클래스 레벨에 `@Transactional`을 붙이면 모든 public 메서드에 일괄 적용됩니다. 트랜잭션이 실제로 필요한 범위(Repository 접근)와 필요 없는 범위(외부 API 호출, 읽기 전용 조회)를 구분하지 않은 채로 습관적으로 붙이면 이런 문제가 생깁니다.
- **해법**: 트랜잭션이 꼭 필요한 메서드에만 개별적으로 붙이고, 조회 전용 메서드에는 `@Transactional(readOnly = true)`를 씁니다. 외부 API 호출은 가능하면 트랜잭션 경계 밖으로 빼거나, 트랜잭션이 끝난 뒤 실행되도록 순서를 조정합니다.

## 11. 참고자료

- [Spring Framework Javadoc — `@Service`](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/stereotype/Service.html)
- [Martin Fowler — Transaction Script](https://martinfowler.com/eaaCatalog/transactionScript.html)
- [Martin Fowler — AnemicDomainModel](https://martinfowler.com/bliki/AnemicDomainModel.html)
- `daily/day06-dto-vs-entity.md` — DTO와 Entity를 분리해야 하는 이유
- `daily/day01-di-why.md` — 의존성 주입은 무슨 문제를 푸는가
