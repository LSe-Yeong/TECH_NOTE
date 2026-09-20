# 컬렉션에서 객체가 사라지는 이유 — equals와 hashCode의 계약

> 이 문서가 답할 질문: **HashSet에 분명히 넣은 객체가 왜 `contains`에서 `false`로 나오는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처에서 공통으로 보고되는 "컬렉션에서 객체를 못 찾는" 증상을 모아, 계약의 어느 조항이 깨졌을 때 어떤 증상이 나오는지를 되짚는 관점으로 조사했습니다.
>
> 기준: 본문의 모든 실행 결과는 Temurin JDK 17.0.20.1+1 / Linux x64에서 직접 실행해 얻은 것입니다. `equals`를 언제 쓰고 `==`를 언제 쓰는가(동일성 대 동등성의 일반론)는 다루지 않고, **해시 기반 자료구조에서 깨지는 지점**만 봅니다.

## 1. 핵심 개념 — 두 메서드는 따로 있는 게 아니라 하나의 계약입니다

`Object`가 주는 기본 구현은 이렇습니다. `equals`는 `==`와 같고(같은 객체일 때만 참), `hashCode`는 서로 다른 객체에 대해 가능한 한 서로 다른 정수를 돌려줍니다. 즉 **기본값은 "모든 객체는 자기 자신하고만 같다"** 입니다.

문제는 이 둘을 따로 고칠 수 있다는 점입니다. `equals`만 재정의하면 컴파일도 되고 테스트도 통과합니다. 깨지는 건 해시 기반 자료구조에 넣는 순간입니다.

```text
담은 직후  contains = true
수량 변경 후 contains = false
remove        = false
size          = 1
순회 결과      = [SKU-1001 x2]
다시 add 후 size = 2
```

> `size`는 1인데 `contains`는 `false`고, `remove`도 실패합니다. 순회하면 멀쩡히 보입니다. 그리고 같은 객체를 다시 넣으면 **크기가 2가 됩니다.** 장바구니에 같은 상품이 두 줄로 찍히고, 중복 제거한 줄 알았던 `Set`에 중복이 남고, 캐시가 계속 미스가 납니다. 이 증상들의 원인은 전부 하나입니다.

## 2. 구조 — `HashMap`이 키를 찾는 세 단계

`HashSet`은 내부가 `HashMap`이므로 `HashMap` 기준으로 봅니다. `get(key)`는 이 순서로 동작합니다.

1. **해시 계산** — `key.hashCode()`를 부르고 상위 비트를 섞습니다.
2. **버킷 선택** — 섞인 값으로 배열 인덱스를 고릅니다.
3. **버킷 안에서 비교** — 그 칸에 들어 있는 항목들과 `==` 또는 `equals`로 비교합니다.

1번에서 쓰는 함수는 [OpenJDK 17의 `HashMap`](https://github.com/openjdk/jdk17u/blob/master/src/java.base/share/classes/java/util/HashMap.java) 기준 이 한 줄입니다.

```java
static final int hash(Object key) {
    int h;
    return (key == null) ? 0 : (h = key.hashCode()) ^ (h >>> 16);
}
```

테이블 크기가 2의 거듭제곱이라 인덱스를 고를 때 하위 비트만 쓰입니다. 그래서 상위 16비트를 하위로 한 번 접어 넣습니다. **상위 비트만 다른 해시값들이 전부 같은 칸으로 몰리는 것을 막는 장치**입니다.

핵심은 **2번과 3번이 다른 메서드를 쓴다**는 사실입니다. 어느 칸을 볼지는 `hashCode`가 정하고, 그 칸 안에서 같은지는 `equals`가 정합니다. 둘이 어긋나면 **맞는 답이 있는데 그 칸을 아예 안 봅니다.**

### 2-1. 계약 네 줄

[`Object` javadoc](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/Object.html)이 요구하는 것 중 실무에서 깨지는 건 두 조항입니다.

- `equals`가 같다고 한 두 객체는 `hashCode`가 **반드시 같아야** 합니다.
- 같은 객체에 대해 `hashCode`는 **일관되게 같은 값**을 돌려줘야 합니다. 단, "`equals` 비교에 쓰이는 정보가 바뀌지 않는 한"이라는 단서가 붙습니다.

반대 방향은 요구하지 않습니다. `hashCode`가 같다고 `equals`가 같을 필요는 없습니다. javadoc은 다만 다른 객체에 다른 값을 주면 해시 테이블 성능이 좋아진다고만 적어 둡니다. 이 비대칭이 뒤에서 세 번째 증상을 만듭니다.

## 3. 계약이 깨지는 세 가지 방식

### 3-1. `equals`만 재정의한 경우

```java
static class Coupon {
    final String code;
    Coupon(String code) { this.code = code; }
    @Override public boolean equals(Object o) {
        return o instanceof Coupon c && code.equals(c.code);   // hashCode 없음
    }
}
```

```text
equals            = true
hashCode 일치      = false
Set.contains      = false
List.contains     = true
둘 다 넣은 뒤 size  = 2
```

`equals`는 `true`인데 `Set.contains`는 `false`입니다. `List.contains`는 버킷 없이 전부 훑으며 `equals`만 쓰므로 `true`가 나옵니다. **`List`에서는 되는데 `Set`에서만 안 되면 거의 확실히 이 경우입니다.**

### 3-2. 넣은 뒤에 필드를 바꾼 경우 ← 맨 위 실행 결과의 정체

`equals`와 `hashCode`를 둘 다 제대로 만들어도 깨집니다.

```java
static class CartItem {
    String sku;
    int quantity;                                   // 가변 필드가 해시에 들어갔습니다
    @Override public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof CartItem other)) return false;
        return quantity == other.quantity && Objects.equals(sku, other.sku);
    }
    @Override public int hashCode() { return Objects.hash(sku, quantity); }
}

Set<CartItem> cart = new HashSet<>();
CartItem item = new CartItem("SKU-1001", 1);
cart.add(item);        // quantity=1 기준으로 버킷 A에 저장
item.quantity = 2;     // 해시가 바뀝니다. 그런데 객체는 여전히 버킷 A에 있습니다
cart.contains(item);   // 버킷 B를 뒤집니다 → false
```

**객체는 사라지지 않았습니다. 주소가 바뀐 겁니다.** `HashMap`은 필드가 바뀌었다고 항목을 옮겨 주지 않습니다. 옮길 수 있다는 걸 알 방법 자체가 없습니다. 그래서 `size`는 1인데 `contains`는 `false`, `remove`도 실패하고, 순회로는 보이고, 다시 넣으면 2가 됩니다.

계약 위반은 `hashCode` 쪽이 아니라 **사용자 쪽**입니다. javadoc의 단서("`equals` 비교에 쓰이는 정보가 바뀌지 않는 한")를 어긴 것이므로, 해법은 `hashCode`를 고치는 게 아니라 **해시에 들어가는 필드를 불변으로 만드는 것**입니다.

### 3-3. `hashCode`가 상수인 경우 — 틀리진 않지만 느립니다

`return 1;`은 계약을 위반하지 않습니다. 같은 객체는 항상 같은 값을 돌려주고, `equals`가 같으면 해시도 같습니다. 결과도 정확합니다. 대신 전부 한 칸에 쌓입니다.

10,000개를 넣고 10,000번 `get`한 결과입니다(세 번 반복 중 워밍업이 끝난 3회차).

| 키의 `hashCode` | 조회 10,000회 |
|---|---:|
| `id.hashCode()` | 0.72ms |
| 상수 `1` | 753.00ms |
| 상수 `1` + `Comparable` 구현 | 2.71ms |

세 번째 줄이 흥미롭습니다. Java 8부터 한 버킷에 항목이 일정 수 이상 쌓이면 연결 리스트를 레드-블랙 트리로 바꿉니다. `HashMap` 소스 기준 `TREEIFY_THRESHOLD`는 8, 그리고 테이블 용량이 `MIN_TREEIFY_CAPACITY`(64) 이상일 때만 트리로 바꿉니다. 트리 탐색은 키들 사이에 순서가 있어야 제 성능이 나오므로, 키가 `Comparable`이면 O(log n)으로 버티고 아니면 결국 전부 훑습니다. **1000배 차이는 "해시 충돌" 자체가 아니라 그 구제책이 먹히느냐에서 나옵니다.**

실무에서 `return 1;`을 일부러 쓰는 사람은 없습니다. 하지만 **아이디 한 종류만 쓰는 팀 코드에서 상수에 가까운 해시가 나오는 경우**는 있습니다. 예를 들어 `hashCode`를 `getClass().hashCode()`로 만들어 둔 JPA 엔티티가 그렇습니다(7절 참고).

## 4. 그래서 무엇을 필드로 고르는가

기준은 두 가지뿐입니다.

- **불변인가** — 컬렉션에 들어 있는 동안 안 바뀌는 값이어야 합니다(3-2).
- **식별하는가** — 그 값이 같으면 "같은 것"이라고 부를 수 있어야 합니다.

`equals`에 쓴 필드와 `hashCode`에 쓴 필드는 **같은 집합**이어야 합니다. `equals`엔 세 개를 쓰고 `hashCode`엔 두 개만 쓰는 건 허용됩니다(해시가 더 거칠어질 뿐 계약 위반은 아닙니다). 반대는 즉시 위반입니다.

### 4-1. `record`를 쓸 수 있으면 `record`가 답입니다

[`Record` javadoc](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/Record.html)은 컴포넌트가 모두 같으면 `equals`가 참이고, **같은 컴포넌트로 만든 두 레코드는 반드시 같은 해시를 갖는다**고 보장합니다. 구체적 알고리즘은 명시하지 않으며 바뀔 수 있다고 못 박습니다. 값 객체(금액, 좌표, 조회 조건 키)라면 직접 짤 이유가 없습니다.

```java
public record OrderKey(String tenantId, long orderNo) { }
```

레코드 컴포넌트는 `final`이므로 3-2의 함정도 구조적으로 막힙니다. 다만 **컴포넌트가 가변 객체(예: `List`)를 참조하면 그 내부는 여전히 바뀔 수 있습니다.** 레코드는 얕은 불변입니다.

### 4-2. 직접 짤 때

```java
@Override
public boolean equals(Object o) {
    if (this == o) return true;
    if (!(o instanceof OrderKey other)) return false;
    return orderNo == other.orderNo && tenantId.equals(other.tenantId);
}

@Override
public int hashCode() {
    return Objects.hash(tenantId, orderNo);
}
```

`Objects.hash`는 가변인자라 호출마다 배열을 하나 만듭니다. 초당 수백만 번 불리는 키가 아니면 신경 쓸 일이 아니지만, 그런 자리라면 `31 * tenantId.hashCode() + Long.hashCode(orderNo)` 같은 직접 계산이나 해시 캐싱을 고려합니다.

## 5. 예제 — 조회 조건을 캐시 키로 쓰기

상품 목록 조회 결과를 로컬 캐시에 담는 코드입니다. 키는 "검색 조건"입니다.

### 5-1. 클린하지 않은 코드 ❌

```java
public class ProductQuery {
    private String category;
    private List<String> brands;
    private int page;

    public void setPage(int page) { this.page = page; }
    // 게터·세터 생략

    @Override
    public boolean equals(Object o) {
        if (o == null || getClass() != o.getClass()) return false;
        ProductQuery q = (ProductQuery) o;
        return page == q.page && category.equals(q.category) && brands.equals(q.brands);
    }

    @Override
    public int hashCode() {
        return Objects.hash(category, brands, page);
    }
}
```

```java
// 호출부
ProductQuery query = new ProductQuery("SHOES", new ArrayList<>(List.of("A")), 0);
List<Product> first = cache.computeIfAbsent(query, repository::search);

query.setPage(1);                                   // ① 키를 캐시에 넣은 뒤 변경
List<Product> second = cache.computeIfAbsent(query, repository::search);
```

문제가 세 겹입니다.

- **①에서 3-2와 같은 일이 벌어집니다.** `page`를 바꾸는 순간 첫 번째 항목은 잘못된 버킷에 갇혀 영영 안 맞습니다. 캐시는 무한히 커지면서 히트율은 0에 수렴합니다.
- **`brands`가 가변 리스트입니다.** 호출부가 리스트를 들고 있다가 원소를 추가하면 키를 건드리지 않아도 해시가 바뀝니다.
- **`category`가 `null`이면 `equals`에서 `NullPointerException`이 납니다.**

### 5-2. 개선한 코드 ✔️

```java
public record ProductQuery(String category, List<String> brands, int page) {
    public ProductQuery {
        Objects.requireNonNull(category, "category");
        brands = List.copyOf(brands);               // 방어적 복사 → 불변 리스트
    }
}
```

```java
ProductQuery first = new ProductQuery("SHOES", List.of("A"), 0);
ProductQuery second = first.withPage(1);            // 바꾸는 대신 새 키를 만듭니다
```

`record`의 compact 생성자에서 `List.copyOf`로 복사하면, 호출부가 원본 리스트를 나중에 뭘 하든 키의 해시는 변하지 않습니다. **키를 바꾸는 대신 새 키를 만드는 구조**로 바뀌면서 ①과 두 번째 문제가 동시에 사라집니다. `equals`/`hashCode`는 컴파일러가 컴포넌트 전체로 만들어 주므로 어긋날 여지도 없습니다.

`withPage` 같은 변형 메서드는 레코드가 만들어 주지 않으므로 직접 추가합니다.

```java
public ProductQuery withPage(int newPage) {
    return new ProductQuery(category, brands, newPage);
}
```

## 6. 대칭성 — `getClass`와 `instanceof` 중 무엇인가

이 선택은 취향 문제가 아닙니다. 계약의 **대칭성** 조항과 직접 연결됩니다.

`getClass() != o.getClass()`로 막으면, 필드가 완전히 같은 서브클래스 인스턴스와 절대 같아지지 않습니다. 프록시(하이버네이트 지연 로딩, CGLIB, Mockito)는 전부 서브클래스로 만들어지므로 여기에 걸립니다.

```text
real.equals(proxy)  = false
proxy.equals(real)  = false
hashCode 일치        = true
Set.contains(proxy) = false
size                = 2
```

해시는 같아서 **같은 버킷에 나란히 두 개**가 들어갑니다. 조회·삭제는 전부 실패합니다.

반대로 `instanceof`로 열어 두면 서브클래스가 필드를 추가하는 순간 대칭성이 깨집니다. 부모는 "같다"고 하고 자식은 "필드가 하나 더 다르다"며 "다르다"고 합니다. `x.equals(y)`와 `y.equals(x)`가 달라지면 결과는 **비교 순서에 따라 달라지고**, 컬렉션은 그 순서를 보장하지 않습니다.

실무 해법은 두 갈래입니다.

- **상속을 막습니다.** 클래스를 `final`로 하거나 `record`를 씁니다. 이러면 `instanceof`로 열어 둬도 안전합니다.
- **상속이 불가피하면 `canEqual`을 씁니다.** "상대방도 나를 자기와 비교할 의사가 있는가"를 되묻는 방식입니다. Lombok의 `@EqualsAndHashCode`가 생성하는 `canEqual`이 바로 이것이고, [공식 문서](https://projectlombok.org/features/EqualsAndHashCode)는 그 목적을 JPA 프록시가 원본 클래스와 같을 수 있게 하기 위함이라고 밝힙니다.

## 7. JPA 엔티티라는 특수 사례

엔티티는 앞의 기준 두 개를 동시에 만족시키기가 어렵습니다. 자동 생성 식별자는 `persist` 전에는 `null`이고 커밋 시점에 채워집니다. **즉 "불변"이 아닙니다.**

[Hibernate 사용자 가이드](https://docs.hibernate.org/orm/5.2/userguide/html_single/chapters/domain/entity.html)는 이 상황을 명시적으로 다룹니다. 생성된 식별자로 `equals`/`hashCode`를 만들면, 영속화 전에 `Set`에 담긴 엔티티가 영속화 이후 해시가 바뀌면서 `Set`의 계약을 깬다고 지적합니다(3-2와 정확히 같은 증상입니다). 가이드의 권고는 **비즈니스 키 또는 내추럴 아이디**를 쓰라는 것입니다. ISBN, 주문번호, 사업자번호처럼 DB가 만들어 주는 게 아니라 도메인이 이미 갖고 있는 값 말입니다.

내추럴 키가 없을 때 쓰이는 절충안이 `hashCode`를 타입 단위 상수로 고정하고 `equals`만 식별자로 비교하는 방식입니다. 해시가 절대 안 바뀌니 계약은 지켜집니다. 대신 3-3에서 본 대로 **같은 타입 엔티티가 한 버킷에 전부 쌓입니다.** 컬렉션에 수십 개가 들어가는 연관관계 수준이면 괜찮고, 수천 개를 `Set`에 담는 자리라면 재야 합니다.

<!-- TODO: 확인 필요 — 이 "상수 hashCode + 식별자 equals" 절충안은 Hibernate 공식 문서가 아니라 커뮤니티에서 널리 쓰이는 패턴입니다. 공식 권고는 어디까지나 내추럴 키입니다. Hibernate 6.x 사용자 가이드의 해당 절(3.24)을 직접 확인해 권고 문구를 갱신할 것. -->

Lombok을 엔티티에 쓸 때 한 가지 더 있습니다. `@EqualsAndHashCode`는 기본적으로 **모든 non-static, non-transient 필드를 포함하고, getter가 있으면 getter를 호출합니다**(공식 문서). 엔티티에 `@Data`를 붙이면 지연 로딩 연관관계의 getter까지 불립니다. `equals` 한 번에 쿼리가 나가고, 세션이 닫힌 뒤라면 예외가 납니다. `@EqualsAndHashCode(onlyExplicitlyIncluded = true)`로 대상을 좁히는 편이 안전합니다.

## 8. 실무에서 찾아보는 `hashCode`

표준 라이브러리가 같은 문제를 어떻게 다뤘는지 보면 기준이 분명해집니다.

**`String` — 불변이라서 캐싱이 가능합니다.** [OpenJDK 17 `String.java`](https://github.com/openjdk/jdk17u/blob/master/src/java.base/share/classes/java/lang/String.java)는 `private int hash` 필드에 한 번 계산한 해시를 저장해 두고 재사용합니다. 해시가 실제로 0인 문자열 때문에 매번 다시 계산하는 걸 막으려고 `hashIsZero` 불리언까지 따로 둡니다. **이 최적화가 성립하는 전제가 바로 "문자열은 안 바뀐다"** 입니다. 3-2에서 본 규칙의 반대편입니다.

**`List`·`Map` — 내용 기반이라 키로 쓰기 위험합니다.** `List.hashCode`는 원소들의 해시로 계산되도록 인터페이스 차원에서 정의되어 있습니다. 그래서 내용이 바뀌면 해시가 바뀝니다. 가변 컬렉션을 해시 키로 쓰면 안 되는 이유가 여기 있습니다.

**배열 — 재정의가 아예 없습니다.** 배열의 `equals`/`hashCode`는 `Object`의 것 그대로라 참조 비교입니다. 내용 비교는 `Arrays.equals`/`Arrays.hashCode`를 따로 불러야 합니다.

## 9. 함정

**① `Set`에 넣은 뒤 setter를 호출한다**
- **증상**: `size()`는 늘어 있는데 `contains`/`remove`가 실패합니다. 순회하면 보입니다. 같은 객체를 다시 넣으면 크기가 늘어납니다.
- **원인**: 해시에 쓰이는 필드가 바뀌어 항목이 잘못된 버킷에 남았습니다.
- **해법**: 해시에 들어가는 필드를 `final`로 만듭니다. 꼭 바꿔야 한다면 **빼고 → 바꾸고 → 다시 넣습니다.** 컬렉션 안에서 바꾸지 않습니다.

**② `equals`만 만들고 `hashCode`를 안 만든다**
- **증상**: `List.contains`는 `true`인데 `Set.contains`가 `false`. 중복 제거가 안 됩니다.
- **원인**: `hashCode`가 여전히 객체마다 다르므로 버킷이 갈립니다.
- **해법**: IDE 생성 기능이나 `record`를 씁니다. 빌드에서 잡고 싶다면 ErrorProne의 `EqualsHashCode` 같은 검사를 CI에 넣습니다.

**③ 배열을 필드로 쓰고 `Objects.hash`에 그대로 넣는다**
- **증상**: 내용이 같은 두 객체가 계속 다르다고 나옵니다.
- **원인**: 배열의 `hashCode`/`equals`는 재정의되어 있지 않아 참조 기준입니다. `Objects.hash(arr)`는 배열 내용을 보지 않습니다.
- **해법**: `Arrays.hashCode(arr)`와 `Arrays.equals(...)`를 씁니다. 중첩 배열이면 `deepHashCode`/`deepEquals`입니다. 애초에 배열 대신 `List`를 쓰는 쪽이 낫습니다.

**④ `equals`에 `Double`/`Float` 필드를 `==`로 비교한다**
- **증상**: `NaN`을 담은 객체가 자기 자신과 같지 않다고 나옵니다. 재귀형 조회가 무한 루프처럼 보입니다.
- **원인**: `NaN == NaN`은 `false`입니다. 반사성 조항 위반입니다.
- **해법**: `Double.compare(a, b) == 0`을 씁니다. `record`가 하는 방식도 이쪽입니다.

**⑤ 가변 컬렉션을 해시 키로 쓴다**
- **증상**: `Map<List<String>, ?>`에 넣고 리스트에 원소를 추가한 뒤 조회하면 못 찾습니다.
- **원인**: `List`의 `hashCode`는 원소들로 계산되므로 내용이 바뀌면 해시가 바뀝니다. ①과 같은 문제입니다.
- **해법**: 키로 넣기 전에 `List.copyOf`로 불변 복사본을 만듭니다.

## 10. 자가 점검

새로 만든 키 클래스에 대해 이 다섯 줄이 전부 통과하면 대부분의 사고를 막을 수 있습니다.

```java
assertThat(a.equals(a)).isTrue();                          // 반사성
assertThat(a.equals(b)).isEqualTo(b.equals(a));            // 대칭성
assertThat(a.equals(null)).isFalse();                      // null
assertThat(a.hashCode()).isEqualTo(b.hashCode());          // a.equals(b)일 때
assertThat(new HashSet<>(List.of(a, b))).hasSize(1);       // a.equals(b)일 때
```

## 11. 참고자료

- [Object (Java SE 17 API)](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/Object.html) — `equals`/`hashCode` 계약 원문
- [Record (Java SE 17 API)](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/lang/Record.html) — 레코드가 보장하는 것과 보장하지 않는 것
- [OpenJDK 17 `HashMap.java`](https://github.com/openjdk/jdk17u/blob/master/src/java.base/share/classes/java/util/HashMap.java) — `hash()`, `TREEIFY_THRESHOLD`, `MIN_TREEIFY_CAPACITY`
- [Hibernate User Guide — Implementing equals() and hashCode()](https://docs.hibernate.org/orm/5.2/userguide/html_single/chapters/domain/entity.html)
- [Lombok `@EqualsAndHashCode`](https://projectlombok.org/features/EqualsAndHashCode)
- 관련 노트: `daily/day19-collections-choice.md`(어떤 컬렉션을 고를 것인가), `daily/day14-dto-vs-entity.md`(엔티티를 경계 밖으로 내보낼 때)
