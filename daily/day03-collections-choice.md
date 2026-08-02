# List, Set, Map — 언제 무엇을 쓰는가

## 1. 핵심 개념: List, Set, Map이란?

- **List**: 순서가 있고 중복을 허용합니다. 인덱스로 접근합니다.
- **Set**: 중복을 허용하지 않습니다. "이미 있는지"가 중요할 때 씁니다.
- **Map**: 키로 값을 찾습니다. 키는 중복될 수 없습니다.

> **"자료구조 선택은 '동작하는가'가 아니라 '얼마나 빠른가'를 결정합니다."** `ArrayList`로 중복 체크를 하면 O(n), `HashSet`이면 O(1)입니다.

## 2. 구조

```
키-값 쌍이 필요한가?
├─ 예       → Map 계열
└─ 아니오 → 중복을 허용하는가?
             ├─ 예       → List 계열
             └─ 아니오 → Set 계열
```

- **List 계열**: `ArrayList`(배열 기반, 인덱스 O(1)), `LinkedList`(노드 기반, 거의 쓸 일 없음)
- **Set 계열**: `HashSet`(O(1) 탐색), `LinkedHashSet`(삽입 순서 유지), `TreeSet`(정렬 유지)
- **Map 계열**: `HashMap`(O(1) 탐색), `LinkedHashMap`(삽입 순서 유지), `TreeMap`(정렬 유지), `ConcurrentHashMap`(스레드 안전)

### 2-1. 선택적 확장 지점

- `ArrayList`, `HashMap` 모두 기본 생성자를 쓰면 작은 기본 용량에서 시작해 필요할 때 자동으로 리사이즈합니다. 이게 기본 동작입니다.
- 최종 크기를 예상할 수 있다면 `new ArrayList<>(initialCapacity)`, `new HashMap<>(initialCapacity)`로 미리 크기를 지정해 리사이즈 횟수를 줄일 수 있습니다. 필수는 아니고 선택적으로 튜닝하는 지점입니다.

## 3. 자료구조 선언 흐름

### 3-1. 클래스 구성

```java
List<OrderId> orderIds = new ArrayList<>();      // 순서 + 중복 허용
Set<OrderId> uniqueIds = new HashSet<>();        // 중복 제거
Map<Long, Order> ordersById = new HashMap<>();   // ID로 조회
```

### 3-2. 탐색 비용 흐름

```
List.contains()  : O(n)  — 처음부터 끝까지 선형 탐색
Set.contains()   : O(1)  — 해시로 바로 위치 계산
Map.get(key)     : O(1)  — 해시로 바로 위치 계산
```

## 4. 특징

### 4-1. 사용 시기

- **List**: 순서가 의미 있거나 중복을 허용해야 할 때. 기본은 `ArrayList`
- **Set**: 중복 체크, 존재 여부 확인이 목적일 때. 기본은 `HashSet`
- **Map**: 키로 값을 찾아야 할 때. 기본은 `HashMap`

### 4-2. 장점

- 목적에 맞는 자료구조를 쓰면 탐색 비용이 O(n)에서 O(1)로 줄어, 데이터가 커져도 응답 시간이 늘지 않습니다.
- `LinkedHashSet`/`LinkedHashMap`처럼 "순서 + 빠른 탐색"을 동시에 만족하는 구현체도 있습니다.

### 4-3. 단점 / 트레이드오프

- `HashSet`/`HashMap`은 순서를 보장하지 않습니다. 순서가 필요한데 이걸 놓치면 버그가 됩니다.
- `TreeSet`/`TreeMap`은 항상 정렬 상태를 유지하는 대신 O(log n)으로, `HashSet`/`HashMap`보다 느립니다.

## 5. 예제: 중복 체크 로직

### 5-1. 클린하지 않은 코드 ❌

```java
// ❌ O(n²) — processedIds가 크면 느립니다
List<Long> processedIds = new ArrayList<>();
for (Order order : orders) {
    if (!processedIds.contains(order.getId())) {
        processedIds.add(order.getId());
        process(order);
    }
}
```

- `ArrayList.contains()`는 선형 탐색입니다. 루프 안에서 부르면 O(n²)이 됩니다.

### 5-2. HashSet을 적용한 코드 ✔️

```java
// ✅ O(n) — contains()가 O(1)
Set<Long> processedIds = new HashSet<>();
for (Order order : orders) {
    if (processedIds.add(order.getId())) {  // add()가 false면 이미 존재
        process(order);
    }
}
```

## 6. equals/hashCode 계약 준수

- `HashSet`/`HashMap`은 `hashCode()`로 버킷을 찾고 `equals()`로 동일성을 판단합니다. 이 계약을 지키지 않으면 컬렉션이 오작동합니다.
- 커스텀 객체를 `Set`이나 `Map`의 키로 쓰려면, 이 계약(같은 값이면 같은 해시코드, `equals`가 true면 `hashCode`도 같음)을 반드시 지켜야 합니다.

### 6-1. 계약을 어긴 코드 ❌

```java
// ❌ equals/hashCode 없음 — 참조가 달라서 찾지 못함
class OrderId {
    private final long id;
    public OrderId(long id) { this.id = id; }
}

Set<OrderId> seen = new HashSet<>();
seen.add(new OrderId(1L));
seen.contains(new OrderId(1L));  // false!
```

- `equals()`/`hashCode()`를 오버라이드하지 않으면 `Object` 기본 구현(참조 동등성)을 씁니다. 같은 값이어도 참조가 다르면 다른 객체로 취급합니다.

### 6-2. 계약을 지킨 코드 ✔️

```java
// ✅ record — equals/hashCode 자동 생성
record OrderId(long id) {}

Set<OrderId> seen = new HashSet<>();
seen.add(new OrderId(1L));
seen.contains(new OrderId(1L));  // true
```

## 7. 확장 지점 응용하기 — 초기 용량 힌트

### 7-1. 클린하지 않은 코드 ❌

```java
// ❌ 기본 용량으로 시작 — 10만 건 넣으면 내부적으로 여러 번 리사이즈된다
Map<Long, Order> ordersById = new HashMap<>();
for (Order order : orders) {  // orders.size() == 100_000
    ordersById.put(order.getId(), order);
}
```

### 7-2. 초기 용량을 지정한 코드 ✔️

```java
// ✅ 예상 크기를 미리 반영 — 리사이즈 횟수를 줄인다
Map<Long, Order> ordersById = new HashMap<>(orders.size());
for (Order order : orders) {
    ordersById.put(order.getId(), order);
}
```

- 최종 크기를 대략이라도 예측할 수 있다면 생성 시점에 크기를 알려줘서 리사이즈 횟수를 줄일 수 있습니다.

## 8. 실무에서 찾아보는 List / Set / Map

### 8-1. Java 표준

- `List.of()`, `Set.of()`, `Map.of()` — 불변 컬렉션을 만드는 정적 팩토리 메서드 (Java 9+)
- `Collections.unmodifiableList()` — 기존 컬렉션을 감싸 수정 불가능한 뷰를 만드는 메서드

## 9. 관련된 개념과 비교

### 9-1. ArrayList VS LinkedList

**유사점**

- 둘 다 `List` 인터페이스를 구현하고, 순서 있는 데이터를 담습니다.

**차이점**

- 통념: "중간 삽입이 O(1)이라 `LinkedList`가 빠르다"
- 실제: 노드가 힙 여기저기 흩어져 있어 캐시 미스가 많이 발생합니다. 실제 벤치마크에서 대부분의 경우 `ArrayList`가 더 빠릅니다.
- 결론: 맨 앞에 빈번하게 삽입하는 게 아니라면 `ArrayList`를 씁니다.

## 10. 함정

**`ArrayList.contains()`를 루프 안에서 반복 호출한다**

- **증상**: 중복 여부 체크 로직이 데이터 증가에 따라 급격히 느려집니다.
- **원인**: `ArrayList.contains()`는 선형 탐색(O(n))입니다. 루프 안에서 부르면 O(n²)입니다.
- **해법**: 중복 체크가 목적이라면 `HashSet`을 씁니다. 기존 `List`를 체크용으로만 쓴다면 `new HashSet<>(list)`로 변환합니다.

**`HashMap`이 삽입 순서를 보장한다는 착각**

- **증상**: 작은 데이터에서는 우연히 순서가 맞아 보여도, 데이터가 늘거나 Java 버전이 바뀌면 달라집니다.
- **원인**: `HashMap`은 삽입 순서를 보장하지 않습니다.
- **해법**: 순서가 필요하면 `LinkedHashMap`을 명시적으로 씁니다.

## 11. 참고자료

- [Java Collections API (Oracle Java 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/Collection.html)
- `05-java/11-equals-hashcode.md` — `equals`·`hashCode` 계약과 컬렉션에서 객체가 사라지는 이유
- `05-java/08-concurrent-collections.md` — 멀티스레드 환경에서 컬렉션 쓰기
