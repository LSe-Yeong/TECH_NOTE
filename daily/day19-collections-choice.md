# List·Set·Map, 무엇을 기준으로 고르는가

> 이 문서가 답할 질문: **컬렉션을 고를 때 실제로 판단해야 하는 기준은 무엇인가?**
>
> 분류: 선택형(A vs B). 여러 선택지의 공통 비교 기준과 트레이드오프를 찾는 관점으로 조사했습니다.
>
> 기준: Java 25(LTS, 2025-09-16 GA) API 명세를 기준으로 서술합니다. 본문의 측정값은 Temurin JDK 17.0.20.1+1 / Linux x64에서 직접 재현했고, 조건을 그때마다 밝힙니다. Java 21에서 추가된 `SequencedCollection`은 이 환경에서 실행 확인이 불가능해 명세만 인용합니다.

## 1. 핵심 개념 — 무엇을 담느냐가 아니라 무엇을 물어보느냐

컬렉션을 고를 때 대부분 "주문 목록이니까 `List`"처럼 **담기는 데이터의 이름**으로 고릅니다. 이 기준은 절반만 맞습니다. 자료구조가 결정하는 건 담는 방식이 아니라 **어떤 질문에 빨리 답할 수 있느냐**입니다.

- `List` — "n번째가 뭔가?" "순서대로 뭐가 있나?"
- `Set` — "이거 있나?" (중복은 없다)
- `Map` — "이 키에 대응하는 값이 뭔가?"

> 주문 20만 건을 처리하면서 `처리완료_ID목록.contains(id)`로 중복을 거르는 코드를 봅니다. 로컬 테스트 데이터 100건에서는 즉시 끝납니다. 운영에서 20만 건이 되자 배치가 몇 시간씩 돕니다. 아래 §4-1에서 직접 측정한 값으로는 **같은 코드가 20만 건에서 14초, `HashSet`으로 바꾸면 4.7밀리초**입니다. 3,000배 차이인데 코드 diff는 한 줄입니다. 자료구조를 잘못 고르면 알고리즘 복잡도 자체가 바뀌고, 이건 서버를 늘려서 해결되지 않습니다.

## 2. 구조 — 세 인터페이스가 서로 다른 계약을 갖는다

### 2-1. 인터페이스는 "질문"을, 구현체는 "접근 패턴"을 따라간다

선택은 두 단계입니다. 이 둘을 섞으면 판단이 꼬입니다.

```text
1단계 — 인터페이스 선택 (설계 결정)
   인덱스/순서가 의미 있나?          → List
   "존재 여부"만 필요하고 중복은 무의미? → Set
   키로 찾아야 하나?                 → Map

2단계 — 구현체 선택 (성능·순서 결정)
   반복 순서를 보장해야 하나?
   정렬이 필요한가?
   어디에 넣고 어디서 빼는가? (앞/뒤/중간)
```

메서드 시그니처에는 **인터페이스**를 씁니다. `ArrayList<Order>`를 반환 타입으로 박아두면 나중에 구현체를 못 바꿉니다.

### 2-2. Java 21이 메운 구멍 — SequencedCollection

Java 21 이전에는 "첫 번째 원소"를 꺼내는 방법이 컬렉션마다 달랐습니다. `List`는 `get(0)`, `Deque`는 `peekFirst()`, `SortedSet`은 `first()`, `LinkedHashSet`은 **방법이 아예 없어서** `iterator().next()`를 써야 했습니다.

Java 21의 `SequencedCollection`이 이걸 통일합니다. `getFirst()`, `getLast()`, `addFirst()`, `addLast()`, `removeFirst()`, `removeLast()`, `reversed()` 일곱 개를 정의하고, `List`·`Deque`·`SortedSet`·`LinkedHashSet` 등이 이 인터페이스를 구현하도록 개조했습니다([SequencedCollection javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/SequencedCollection.html)). 비어 있으면 `NoSuchElementException`을 던집니다.

```java
List<Order> orders = orderRepository.findRecent();
Order latest = orders.getLast();          // Java 21+. 이전에는 orders.get(orders.size() - 1)
```

`orders.get(orders.size() - 1)`은 빈 리스트에서 `get(-1)`이 되어 `IndexOutOfBoundsException`이 납니다. `getLast()`는 의도가 드러나는 예외를 던집니다. **"순서가 있는 컬렉션"이라는 개념에 드디어 타입이 생긴 것**이 핵심입니다.

## 3. 흐름 — 고르는 절차

### 3-1. 결정 순서

```text
Q1. 키 → 값 매핑인가?
      예 → Map 계열 (§4-3)
Q2. 중복을 허용해야 하나?
      아니오, 존재 여부만 → Set 계열 (§4-2)
      예                  → 다음
Q3. 인덱스로 접근하나, 아니면 앞뒤로만 넣고 빼나?
      인덱스 접근 → ArrayList
      앞뒤 전용   → ArrayDeque
```

Q3이 갈리는 지점이 실무에서 가장 많이 틀립니다. "리스트니까 `List`"가 아니라 **접근 위치**를 봅니다.

### 3-2. 코드로 보는 차이

같은 데이터, 다른 질문입니다.

```java
List<Order> orders = orderRepository.findByShopId(shopId);

// 질문 A: 이 사용자가 주문한 적 있나? → 존재 확인이므로 Set
Set<Long> buyerIds = orders.stream()
        .map(Order::getBuyerId)
        .collect(Collectors.toSet());
boolean isRepeatBuyer = buyerIds.contains(userId);

// 질문 B: 주문 ID로 주문을 찾아야 한다 → 키 조회이므로 Map
Map<Long, Order> byId = orders.stream()
        .collect(Collectors.toMap(Order::getId, Function.identity()));

// 질문 C: 화면에 최신순으로 뿌린다 → 순서가 의미 있으므로 List 유지
```

## 4. 구현체 선택 — 측정으로 보는 트레이드오프

### 4-1. Set·Map을 쓰는 이유는 "존재 확인" 하나

`List.contains()`는 처음부터 끝까지 훑습니다. O(n)입니다. `HashSet.contains()`는 해시로 버킷을 한 번에 찾습니다. 평균 O(1)입니다.

n개짜리 컬렉션에 `contains()`를 n번 호출한 시간입니다(워밍업 3회 후 측정, Temurin 17.0.20.1+1, `System.nanoTime()` 단순 측정이므로 절대값보다 **증가 추세**를 봐 주세요).

| n | `ArrayList.contains` × n | `HashSet.contains` × n |
|---:|---:|---:|
| 10,000 | 29.0 ms | 0.21 ms |
| 50,000 | 766.2 ms | 0.68 ms |
| 200,000 | 14,374.2 ms | 4.72 ms |

리스트 쪽은 n이 5배가 될 때 26배, 4배가 될 때 19배가 됩니다. O(n²)입니다. **1만 건에서 29ms면 개발 중에는 아무도 눈치채지 못합니다.**

### 4-2. ArrayList vs LinkedList — 링크드리스트는 거의 답이 아니다

"중간 삽입이 많으면 LinkedList"라는 말을 자주 듣습니다. 실제로는 그 조건이 성립하는 경우가 드뭅니다.

같은 환경에서 원소 10만 개 리스트에 무작위 인덱스로 10만 번 `get()`한 시간, 그리고 인덱스 0에 10만 번 삽입한 시간입니다.

| 작업 | `ArrayList` | `LinkedList` | `ArrayDeque` |
|---|---:|---:|---:|
| 무작위 `get()` × 100,000 | 1 ms 미만 | 3,769 ms | (인덱스 접근 없음) |
| 앞에 삽입 × 100,000 | 539 ms | 6 ms | 7 ms (`addFirst`) |
| 전체 순회 × 20 | 12 ms | 18 ms | — |

`LinkedList`가 이기는 칸은 하나뿐이고, 그 칸에서는 `ArrayDeque`가 같은 성능을 냅니다. 그런데 `LinkedList`는 원소마다 노드 객체를 하나씩 더 만들고, 순회할 때 메모리를 건너뛰며 읽습니다.

**"중간 삽입이 빠르다"도 반쪽입니다.** `LinkedList`에서 링크를 바꾸는 건 O(1)이지만, **그 위치까지 가는 게 O(n)**입니다. 위치를 미리 잡은 `ListIterator`로 순회하며 삽입하는 경우가 아니면 이득이 없습니다.

정리하면 이렇습니다.

- 인덱스 접근이 있다 → `ArrayList`
- 앞뒤로만 넣고 뺀다(큐·스택·BFS) → `ArrayDeque`. javadoc도 "스택으로 쓸 때 `Stack`보다, 큐로 쓸 때 `LinkedList`보다 빠를 것"이라고 명시합니다([ArrayDeque javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ArrayDeque.html))
- `Stack`·`Vector`는 새 코드에 쓰지 않습니다. 모든 메서드가 `synchronized`인데 그걸로 동시성 문제가 풀리지도 않습니다

### 4-3. 순서가 필요할 때 — Linked·Tree·Enum

`HashSet`/`HashMap`의 반복 순서는 **보장되지 않습니다.** 직접 확인한 결과입니다.

```text
// 넣은 순서: delta, alpha, charlie, bravo
new HashMap<>()       → [bravo, alpha, delta, charlie]   // 해시값 순. 예측 불가
new LinkedHashMap<>() → [delta, alpha, charlie, bravo]   // 삽입 순
new TreeMap<>()       → [alpha, bravo, charlie, delta]   // 키 정렬 순
```

| 구현체 | 반복 순서 | 조회 | 비용 |
|---|---|---|---|
| `HashSet` / `HashMap` | 없음 | O(1) 평균 | 기본 선택 |
| `LinkedHashSet` / `LinkedHashMap` | 삽입 순 | O(1) 평균 | 링크 유지 비용 |
| `TreeSet` / `TreeMap` | 정렬 순 | O(log n) | 비교 비용, `null` 키 불가 |
| `EnumSet` / `EnumMap` | enum 선언 순 | O(1) | 키가 enum일 때만 |

`EnumMap`은 내부가 그냥 배열입니다. enum의 `ordinal()`을 인덱스로 쓰므로 해싱조차 하지 않습니다. **키가 enum이면 `HashMap`을 쓸 이유가 없습니다.**

```java
EnumMap<OrderStatus, Integer> counts = new EnumMap<>(OrderStatus.class);
counts.put(OrderStatus.SHIPPED, 1);
counts.put(OrderStatus.NEW, 2);
// 결과: [NEW, SHIPPED] — 넣은 순서가 아니라 enum 선언 순서

EnumSet<OrderStatus> active = EnumSet.complementOf(EnumSet.of(OrderStatus.CANCELLED));
```

`LinkedHashMap`은 접근 순서 모드가 있어 LRU 캐시가 됩니다. 세 번째 생성자 인자를 `true`로 주면 `get()`할 때마다 그 항목이 맨 뒤로 갑니다.

```java
Map<String, Rate> lru = new LinkedHashMap<>(16, 0.75f, true) {
    @Override protected boolean removeEldestEntry(Map.Entry<String, Rate> eldest) {
        return size() > 1000;
    }
};
```

직접 돌려본 결과 `a, b, c`를 넣고 `a`를 조회한 뒤 `d`를 넣으면 `b`가 밀려나고 `[c, a, d]`가 남습니다.

## 5. HashSet은 왜 빠른가 — 그리고 언제 안 빠른가

`HashSet`은 내부적으로 `HashMap`입니다. 그래서 둘의 특성이 같습니다.

`HashMap`은 버킷 배열을 두고 키의 해시로 버킷을 고릅니다. 기본 버킷 수는 16, 기본 로드 팩터는 0.75입니다([HashMap javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/HashMap.html)). 항목 수가 `버킷 수 × 0.75`를 넘으면 버킷을 2배로 늘리고 전부 재배치합니다.

한 버킷에 여러 키가 몰리면 그 안에서는 리스트를 훑습니다. 그래서 해시가 나쁘면 O(n)으로 떨어집니다. JDK는 이걸 방어합니다. **한 버킷의 노드가 8개 이상이 되고 전체 버킷 수가 64 이상이면 그 버킷을 붉은검정트리로 바꿉니다**(`TREEIFY_THRESHOLD = 8`, `MIN_TREEIFY_CAPACITY = 64`, [OpenJDK HashMap.java](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/util/HashMap.java)). 최악이 O(n)에서 O(log n)이 됩니다. 버킷 수가 64 미만이면 트리화 대신 리사이즈를 택합니다. 작은 테이블의 충돌은 버킷을 늘리는 쪽이 싸기 때문입니다.

여기서 두 가지가 따라옵니다.

**`hashCode()`가 성능 계약의 일부입니다.** 모든 객체가 같은 해시를 내면 해시맵은 그냥 리스트입니다. `equals()`만 재정의하고 `hashCode()`를 빼먹으면 조회가 아예 실패합니다.

**초기 용량 인자는 "담을 개수"가 아니라 "버킷 수 요청"입니다.** 직접 확인한 값입니다.

```text
new HashMap<>(1000)  →  버킷 1024개, 임계치 768
                        769번째 항목에서 버킷 2048개로 리사이즈
```

1000개를 담으려고 1000을 넘겼는데 리사이즈가 일어납니다. Java 19부터 `HashMap.newHashMap(1000)`이 이 계산을 대신해 줍니다("예상 매핑 수만큼 리사이즈 없이 담을 수 있는 초기 용량", [javadoc](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/HashMap.html)). Java 17 이하라면 `new HashMap<>((int) (expected / 0.75f) + 1)`로 씁니다.

## 6. 예제

### 6-1. 클린하지 않은 코드 ❌

```java
public List<OrderResponse> attachCoupons(List<Order> orders, List<Coupon> coupons) {
    List<OrderResponse> responses = new ArrayList<>();
    for (Order order : orders) {
        Coupon matched = null;
        for (Coupon coupon : coupons) {                 // 주문마다 쿠폰 전체 순회
            if (coupon.getOrderId().equals(order.getId())) {
                matched = coupon;
                break;
            }
        }
        responses.add(OrderResponse.of(order, matched));
    }
    return responses;
}
```

주문 5,000건 × 쿠폰 5,000건이면 비교가 2,500만 번입니다. 쿼리는 두 번뿐이라 슬로우 쿼리 로그에도 안 잡힙니다. CPU만 한 코어가 100%로 붙어 있습니다.

### 6-2. 개선한 코드 ✔️

```java
public List<OrderResponse> attachCoupons(List<Order> orders, List<Coupon> coupons) {
    Map<Long, Coupon> couponByOrderId = coupons.stream()
            .collect(Collectors.toMap(Coupon::getOrderId, Function.identity(),
                                      (existing, replacement) -> existing));   // 중복 키 정책 명시
    return orders.stream()
            .map(order -> OrderResponse.of(order, couponByOrderId.get(order.getId())))
            .toList();
}
```

**바깥 루프의 "찾기"를 미리 `Map`으로 뒤집는 것**이 이 패턴의 전부입니다. 비교 2,500만 번이 해시 조회 5,000번이 됩니다.

병합 함수를 준 이유는 §7-2에 있습니다.

## 7. 함정

### 7-1. for-each 안에서 `remove()` — 예외가 안 나는 게 더 나쁩니다

- **증상**: 반복 중 삭제하면 `ConcurrentModificationException`이 납니다. 그런데 **어떤 경우엔 예외 없이 조용히 통과합니다.**
- **원인**: 직접 확인한 결과입니다. `[a, b, c, d]`에서 `b`를 지우면 CME가 나지만, **뒤에서 두 번째인 `c`를 지우면 예외 없이 끝납니다.** 삭제 후 크기가 줄어 `hasNext()`가 곧바로 `false`가 되고, 수정 횟수를 검사하는 `next()`가 호출되지 않기 때문입니다. 마지막 원소를 건너뛴 채 루프가 끝납니다.
- **해법**: `removeIf()` 또는 `Iterator.remove()`를 씁니다. `removeIf`는 조건도 같이 드러나서 읽기 좋습니다.

```java
orders.removeIf(order -> order.getStatus() == OrderStatus.CANCELLED);   // ✔️
```

### 7-2. `Collectors.toMap`이 런타임에 터집니다

- **증상**: 잘 돌던 API가 특정 데이터에서만 `IllegalStateException: Duplicate key ...`로 죽습니다.
- **원인**: 두 개짜리 `toMap`은 키가 겹치면 예외를 던집니다. 확인한 메시지는 `Duplicate key A (attempted merging values NEW and PAID)`입니다. `null` 값도 NPE를 냅니다.
- **해법**: **병합 함수를 받는 3인자 버전을 기본으로 씁니다.** 중복이 정말 없다고 믿는다면 그 믿음을 병합 함수 자리에 예외로 적어 두는 편이 낫습니다. 어느 쪽이든 정책이 코드에 남습니다.

### 7-3. `Set`에 넣은 뒤 객체를 바꿉니다

- **증상**: 방금 넣은 객체를 `contains()`로 찾는데 `false`가 나옵니다. 반복하면 분명히 들어 있습니다.
- **원인**: 해시는 **넣을 때** 계산해서 버킷을 정합니다. 넣은 뒤 필드를 바꾸면 해시가 달라지고, 조회는 엉뚱한 버킷을 봅니다. 실제로 리스트를 `HashSet`에 넣고 원소를 추가하니 `contains()`가 `false`, 반복은 그 객체를 찾아냈습니다.
- **해법**: `Set`의 원소와 `Map`의 키는 **불변 객체이거나, 최소한 `hashCode()`에 쓰이는 필드가 변하지 않아야** 합니다. JPA 엔티티를 `Set`에 넣을 때 특히 조심합니다.

### 7-4. `List.remove(int)`와 `remove(Object)`

- **증상**: `List<Integer>`에서 값 1을 지우려 했는데 1번 인덱스가 지워집니다.
- **원인**: 오버로드입니다. 확인 결과 `[10, 20, 30]`에서 `remove(1)`은 `[10, 30]`, `remove(Integer.valueOf(10))`은 `[20, 30]`입니다. 컴파일 에러가 아니라 조용히 다른 메서드가 선택됩니다.
- **해법**: `List<Integer>`에서 값으로 지울 때는 `remove(Integer.valueOf(id))`를 명시합니다.

### 7-5. "불변"이라고 생각한 것이 불변이 아닙니다

- **증상**: 상수로 선언한 리스트의 내용이 런타임에 바뀌어 있습니다.
- **원인**: 네 가지가 전부 다릅니다. 직접 확인한 동작입니다.

| 생성 | 추가/삭제 | 원본 변경 반영 | `null` 원소 |
|---|---|---|---|
| `new ArrayList<>(src)` | 가능 | 안 됨(복사) | 허용 |
| `Arrays.asList(...)` | `UnsupportedOperationException` | — | 허용 |
| `Collections.unmodifiableList(src)` | `UnsupportedOperationException` | **반영됨(뷰)** | 허용 |
| `List.copyOf(src)` / `List.of(...)` | `UnsupportedOperationException` | 안 됨(복사) | **NPE** |

`Collections.unmodifiableList`는 **원본을 감싼 뷰**입니다. 원본에 `add`하면 뷰에도 나타납니다. 확인 결과 원본에 `"y"`를 추가하니 뷰는 `[x, y]`, `List.copyOf` 쪽은 `[x]`였습니다.

- **해법**: 방어 복사가 목적이면 `List.copyOf()`를 씁니다. 단 `null` 원소가 섞일 수 있으면 NPE가 납니다. `Arrays.asList()`는 크기 고정이지 불변이 아닙니다 — `set()`은 됩니다.

### 7-6. `subList()`는 복사본이 아닙니다

- **증상**: 부분 리스트를 수정했는데 원본이 바뀝니다. 또는 원본을 건드린 뒤 부분 리스트를 쓰면 CME가 납니다.
- **원인**: `subList()`는 뷰입니다. 확인 결과 `[1,2,3,4,5].subList(1,3)`에서 `set(0, 99)`를 하면 원본이 `[1, 99, 3, 4, 5]`가 되고, 원본에 `add` 후 `sub.size()`를 호출하면 `ConcurrentModificationException`이 납니다.
- **해법**: 잘라서 따로 쓸 거면 `new ArrayList<>(list.subList(a, b))`로 복사합니다.

### 7-7. `TreeSet`의 중복 판정은 `equals`가 아닙니다

- **증상**: `HashSet`에서는 2건인데 `TreeSet`에서는 1건입니다.
- **원인**: 정렬 컬렉션은 `compareTo`/`Comparator`가 `0`을 반환하면 같은 원소로 봅니다. `String.CASE_INSENSITIVE_ORDER`로 만든 `TreeSet`에 `"Order"`와 `"ORDER"`를 넣으면 크기가 1, 같은 값으로 만든 `HashSet`은 2입니다.
- **해법**: 정렬 컬렉션에 커스텀 `Comparator`를 넘길 때는 **그게 곧 동등성 정의**가 된다는 걸 의식합니다. `equals`와 어긋나는 비교자는 `Set`/`Map` 계약 위반입니다.

### 7-8. `ArrayDeque`에 `null`을 넣습니다

- **증상**: 큐에 `null`을 넣자 `NullPointerException`이 납니다.
- **원인**: `ArrayDeque`는 `null`을 금지합니다. `poll()`이 `null`을 "비었음" 신호로 쓰기 때문에 원소로 허용하면 구분이 안 됩니다. `LinkedList`는 허용합니다(확인함).
- **해법**: 큐에 "값 없음"을 흘려보내야 한다면 그 자체가 설계 신호입니다. 빈 객체나 `Optional`을 담습니다.

## 8. 참고자료

- [SequencedCollection (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/SequencedCollection.html) — Java 21에서 추가된 순서 있는 컬렉션 계약
- [HashMap (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/HashMap.html) — 초기 용량·로드 팩터·fail-fast 반복자
- [ArrayList (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ArrayList.html) — 상수 상각 시간 `add`, 나머지는 선형
- [ArrayDeque (Java SE 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/ArrayDeque.html)
- [OpenJDK HashMap.java](https://github.com/openjdk/jdk/blob/master/src/java.base/share/classes/java/util/HashMap.java) — 트리화 임계치와 그 근거 주석
- 관련 문서: [day07-jvm-memory.md](day07-jvm-memory.md) — 컬렉션이 힙 어디에 앉는가

<!-- TODO: 확인 필요 — §2-2의 SequencedCollection 예제는 Java 21+ 문법이라 이 환경(JDK 17)에서 실행 검증하지 못했습니다. javadoc 명세만 근거로 서술했습니다. -->
<!-- TODO: 확인 필요 — §4-2의 "무작위 get() 0 ms 미만"은 단순 nanoTime 측정에서 JIT가 루프를 최적화했을 가능성이 있습니다. ArrayList가 O(1), LinkedList가 O(n)이라는 결론 자체는 javadoc과 자료구조상 성립하지만, 정확한 배수는 JMH로 다시 재야 합니다. -->
