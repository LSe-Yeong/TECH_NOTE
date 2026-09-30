# Redis 없이 캐싱하기 — 로컬 캐시는 무엇을 얻고 무엇을 포기하는가

> 이 문서가 답할 질문: **캐시를 애플리케이션 프로세스 안(힙)에 두는 선택은 원격 공유 캐시 대비 무엇을 얻고 무엇을 포기하는가, 그리고 어떤 데이터가 그 거래에 맞는가?**
>
> 분류: 선택형(A vs B). 여러 출처가 공통으로 드는 비교 기준은 셋입니다. 접근 비용, 인스턴스 간 일관성, 메모리가 누구 소유인가. 이 세 축으로 조사했습니다.
>
> 기준: Caffeine 3.2.4, Spring Boot 4.1 레퍼런스, Java 21 `ConcurrentHashMap` javadoc 기준입니다.
>
> 경계: `daily/day33-cache-strategy.md`는 읽기·쓰기 전략 선택을, `daily/day39-cache-invalidation.md`는 무효화 설계를 다뤘습니다. 이 문서는 그보다 앞에 오는 질문 — **캐시를 어디에 둘 것인가**입니다.

## 1. 핵심 개념 — 로컬 캐시는 "네트워크를 없앤 Redis"가 아닙니다

로컬 캐시(local cache, in-process cache)는 캐시 항목을 애플리케이션과 **같은 JVM 힙**에 두는 캐시입니다. 조회가 메서드 호출로 끝나고, TCP 왕복도 직렬화도 없습니다.

여기서 생각이 멈추면 "Redis보다 빠른 Redis"로 오해합니다. 실제로 바뀌는 건 속도만이 아닙니다.

> 인스턴스를 1대로 돌릴 때는 아무 문제가 없습니다. 오토스케일링이 붙어 2대가 되는 순간이 문제입니다. 상품 정책을 고치고 관리 API를 호출하면 그 요청을 받은 1대만 새 값을 갖습니다. 나머지 1대는 TTL이 지날 때까지 옛 정책으로 계산합니다. 새로고침하면 값이 바뀌고, 또 하면 돌아옵니다. **로컬 캐시의 기본 동작은 "인스턴스마다 다른 답"입니다.** 인스턴스가 늘어나는 순간 코드를 한 줄도 안 고쳤는데 정확성이 바뀝니다.

그래서 이 선택의 본질은 이렇습니다.

```
원격 공유 캐시 : 모두가 같은 사본 1개를 본다        → 일관성을 사고, 네트워크로 지불
로컬 캐시      : 인스턴스마다 사본 N개를 각자 만든다 → 속도를 사고, 일관성과 힙으로 지불
```

## 2. 무엇을 얻는가

### 2-1. 접근 경로가 사라집니다

Redis 조회 한 번에 드는 일은 명령 직렬화 → 소켓 쓰기 → 서버 처리 → 응답 파싱 → 역직렬화입니다. 로컬 캐시는 해시 테이블 조회 하나입니다. 절대 수치는 환경마다 다르니 쓰지 않겠습니다. 중요한 건 **단계 수 자체가 다르다**는 점입니다. 단계가 없으면 그 단계에서 생기는 지연 편차도 없습니다.

특히 **같은 요청 안에서 같은 키를 여러 번 읽는 코드**가 이득을 크게 봅니다. 루프 안에서 코드 테이블을 조회하는 로직은 Redis라면 왕복이 N번입니다.

### 2-2. 의존성이 하나 줄어듭니다

Redis가 죽으면 캐시를 쓰는 모든 경로가 영향을 받습니다. 타임아웃을 짧게 걸고 폴백을 넣어도 코드가 늘어납니다. 로컬 캐시는 프로세스와 생사를 공유하므로 "캐시만 따로 죽는" 상태가 없습니다. 운영할 서버도, 커넥션 풀도, 보안 그룹도 늘지 않습니다. 성능 논점이 아니라 **운영 복잡도** 논점이고, 인스턴스 2~3대 규모에서는 이쪽이 속도보다 중요할 때가 많습니다.

### 2-3. 직렬화 형식을 고민하지 않습니다

원격 캐시는 객체를 바이트로 바꿔야 하고, 그 순간 스키마 호환성이 문제가 됩니다. 배포 중 구버전과 신버전이 같은 Redis를 보면 필드가 하나 추가된 JSON을 구버전이 읽다가 실패합니다. 로컬 캐시는 객체 참조를 그대로 들고 있어 이 문제가 없습니다. 대신 **참조를 그대로 들고 있다는 것이 3-3의 위험**이 됩니다.

## 3. 무엇을 포기하는가

### 3-1. 인스턴스 간 일관성 — 가장 큰 대가

`@CacheEvict`는 **그 JVM의 캐시만** 비웁니다. 다른 인스턴스는 무효화가 일어난 사실을 모릅니다. 여기서 나오는 성질이 로컬 캐시 설계의 전부입니다.

**로컬 캐시의 최대 낡음(staleness)은 TTL로 정해집니다.** 명시적 무효화는 "빠르게 맞춰주는 수단"일 뿐이고, 정확성의 상한은 TTL입니다. 그러니 TTL 없는 로컬 캐시는 설계가 아니라 사고입니다.

같은 이유로 **TTL을 정할 수 없는 데이터는 로컬 캐시 대상이 아닙니다.** "이 값이 최악의 경우 30초 틀려도 되는가"에 답할 수 없으면 그 데이터는 원격 캐시나 DB로 보냅니다.

### 3-2. 캐시 메모리가 애플리케이션 힙입니다

Redis 메모리는 Redis 것이고, 로컬 캐시 메모리는 **요청을 처리하는 그 힙**입니다. 둘의 차이는 두 방향으로 나타납니다.

1. **캐시가 애플리케이션을 죽일 수 있습니다.** 상한 없는 로컬 캐시는 `OutOfMemoryError`로 끝납니다.
2. **캐시가 GC 대상입니다.** 캐시 항목은 오래 살아남아 구세대로 승격되고, 구세대에 상주하는 객체가 많아지면 회수해야 할 그래프가 커집니다. 힙 영역 구분은 `daily/day07-jvm-memory.md`를 참고하면 됩니다.

그래서 로컬 캐시 용량은 "힙에 남는 만큼"이 아니라 **"이만큼을 캐시에 영구 할당한다"**고 정하고 `-Xmx`를 그만큼 올리는 편이 정직합니다.

### 3-3. 가변 객체를 공유하게 됩니다

원격 캐시는 조회할 때마다 역직렬화하므로 매번 새 객체입니다. 로컬 캐시는 **모든 요청이 같은 인스턴스를 받습니다.** 한 요청이 그 객체의 세터를 호출하면 다른 요청이 보는 값이 바뀌고, 심지어 캐시에 그대로 남습니다.

로컬 캐시에 담는 값은 불변이어야 합니다(`daily/day43-immutability.md`). `record`나 방어적 복사본을 담고, 컬렉션은 `List.copyOf()`로 감싸 넣습니다.

### 3-4. 기동할 때 항상 비어 있습니다

배포할 때마다 모든 인스턴스의 캐시가 0에서 시작합니다. 스케일아웃으로 새로 뜬 인스턴스도 그렇습니다. **캐시 히트율에 의존해 겨우 버티던 DB는 배포 순간 정면으로 부하를 받습니다.** 원격 캐시는 배포와 무관하게 내용을 유지하므로 이 문제가 없습니다. 인스턴스가 많아질수록 대가도 커집니다. 같은 인기 키를 N대가 각자 미스하고 각자 DB를 때립니다.

## 4. 그래서 언제 로컬 캐시인가

세 축을 표로 정리하면 선택 기준이 나옵니다.

| 기준 | 로컬 캐시 | 원격 공유 캐시 |
|---|---|---|
| 조회 비용 | 힙 조회 | 네트워크 왕복 + 직렬화 |
| 인스턴스 간 일관성 | 없음(TTL만큼 어긋남) | 있음 |
| 용량 | 힙에 종속 | 독립적으로 증설 |
| 배포 후 상태 | 항상 콜드 | 유지 |
| 추가 운영 대상 | 없음 | 서버·커넥션·모니터링 |
| 담아도 되는 값 | 불변 객체 | 직렬화 가능한 값 |

로컬 캐시가 맞는 데이터의 조건은 이렇게 좁혀집니다.

- **읽기가 압도적으로 많고 쓰기가 드물다** — 코드 테이블, 정책, 설정, 권한 정의
- **잠깐 낡아도 사고가 나지 않는다** — TTL만큼의 오차를 숫자로 답할 수 있다
- **항목 수가 예측 가능하다** — 상한을 정할 수 있다
- **값이 불변으로 만들 수 있다**

반대로 이런 데이터는 로컬 캐시에 넣지 않습니다. **잔액·재고·쿠폰 사용 여부처럼 인스턴스 간 불일치가 곧 금전 손실인 값**, 그리고 사용자 수에 비례해 키가 늘어나는 세션 데이터입니다.

## 5. `ConcurrentHashMap`으로는 왜 부족한가

로컬 캐시가 필요하면 가장 먼저 이 코드를 씁니다.

```java
// ❌ 캐시가 아니라 메모리 누수입니다
private final Map<Long, ProductPolicy> cache = new ConcurrentHashMap<>();

public ProductPolicy findPolicy(long productId) {
    return cache.computeIfAbsent(productId, policyRepository::loadPolicy);
}
```

문제가 셋입니다.

**① 상한이 없습니다.** `productId`가 100만 개면 100만 개가 들어갑니다. 아무도 지우지 않으므로 힙이 차면 `OutOfMemoryError`입니다. `ConcurrentHashMap`은 캐시가 아니라 맵이고, **맵의 계약에는 "오래된 걸 버린다"가 없습니다.**

**② 만료가 없습니다.** 정책을 DB에서 고쳐도 재기동 전까지 옛 값입니다. 3-1에서 말한 TTL 백스톱이 아예 존재하지 않습니다.

**③ `computeIfAbsent` 안에서 DB를 읽고 있습니다.** javadoc이 직접 경고하는 지점입니다.

> "Some attempted update operations on this map by other threads may be blocked while computation is in progress, so the computation should be short and simple." — `ConcurrentHashMap#computeIfAbsent`

전체 호출이 원자적으로 수행되는 대가로, 계산 중에는 **다른 스레드의 갱신이 막힐 수 있습니다.** 그래서 javadoc은 계산이 짧고 단순해야 한다고 못 박습니다. 수십 ms 걸리는 쿼리를 여기 넣으면 그 시간 동안 같은 버킷을 건드리는 스레드들이 대기합니다.

같은 javadoc의 또 한 줄이 더 위험합니다.

> "The mapping function must not modify this map during computation."

즉 매핑 함수 안에서 같은 맵을 다시 건드리면 안 됩니다. `loadPolicy` 내부가 다른 서비스를 타고 돌아와 같은 캐시를 조회하는 구조라면 이 조건을 어기게 되고, 증상은 응답이 영원히 돌아오지 않는 형태로 나타납니다.

`ConcurrentHashMap`이 충분한 경우도 있습니다. **키 집합이 유한하고 값이 프로세스 생애 동안 안 바뀔 때** — enum별 설정을 기동 시 한 번 채우는 경우입니다. 그건 캐시가 아니라 조회 테이블이고, 그렇게 이름 붙이는 게 맞습니다.

## 6. Caffeine — 로컬 캐시 라이브러리가 대신 해주는 것

Caffeine은 Guava 캐시와 `ConcurrentLinkedHashMap` 설계 경험을 바탕으로 만들어진 로컬 캐시 라이브러리입니다. **Java 11 이상은 3.x, 그 이하는 2.x**를 쓰라고 README가 안내합니다.

```java
LoadingCache<Long, ProductPolicy> policyCache = Caffeine.newBuilder()
        .maximumSize(10_000)
        .expireAfterWrite(Duration.ofMinutes(5))
        .refreshAfterWrite(Duration.ofMinutes(1))
        .recordStats()
        .build(policyRepository::loadPolicy);

ProductPolicy policy = policyCache.get(productId);
```

### 6-1. 크기 제한 — 정확한 상한이 아닙니다

`maximumSize(long)`은 항목 수 상한이고, `maximumWeight(long)` + `weigher`는 가중치 상한입니다. 흔히 오해하는 부분을 javadoc이 명시합니다.

> "Note that the cache may evict an entry before this limit is exceeded or temporarily exceed the threshold while evicting." — `Caffeine#maximumSize`

**한도는 근사치입니다.** 정확히 N개를 보장해야 하는 용도(반드시 유지해야 하는 락 객체 등)에는 쓸 수 없습니다.

### 6-2. 축출 정책 — LRU가 아닙니다

Caffeine은 **W-TinyLFU**를 씁니다. Efficiency 위키가 드는 채택 이유는 이렇습니다. LRU는 널리 쓰이지만 전체 스캔 같은 상황에서 히트율이 나빠질 수 있습니다. 한 번씩만 읽고 지나가는 요청이 캐시를 통째로 밀어내기 때문입니다. 대안인 ARC는 축출된 항목을 추적하려고 캐시 크기의 두 배를 요구하고 특허가 걸려 있으며, LIRS는 구현이 복잡하고 세 배를 요구합니다. W-TinyLFU는 빈도 스케치로 그 추적을 대체해 **더 적은 메모리로 ARC·LIRS와 겨룰 만한 히트율**을 낸다는 설명입니다.

실무 관점의 결론은 하나입니다. **LRU라고 가정하고 용량을 계산하지 않습니다.** 자주 쓰이는 키는 오래 남고, 한 번 지나가는 키는 캐시를 밀어내지 못합니다.

### 6-3. 만료 — 백그라운드 스레드가 없습니다

- `expireAfterWrite` — 생성 또는 마지막 값 교체 시점 기준
- `expireAfterAccess` — 생성·교체·**마지막 조회** 기준
- `expireAfter(Expiry)` — 항목별로 다른 만료

`expireAfterAccess`만 걸면 계속 읽히는 항목은 영원히 만료되지 않습니다. **낡음의 상한을 만들려면 `expireAfterWrite`가 필요합니다.**

그리고 중요한 구현 사실이 있습니다. Eviction 위키는 유지 작업이 **쓰기 시점에 주기적으로, 읽기 시점에는 간헐적으로** 일어난다고 설명합니다. 전용 청소 스레드가 도는 게 아닙니다. 그래서 **트래픽이 없으면 만료된 항목이 힙에 계속 남습니다.** 만료 즉시 제거가 필요하면 `Caffeine.scheduler(Scheduler.systemScheduler())`를 지정하라고 문서가 안내합니다(Java 9 이상).

⚠️ `softValues()`로 힙 압박 때 알아서 지워지게 만들려는 시도는 javadoc이 직접 만류합니다.

> "Warning: in most circumstances it is better to set a per-cache maximum size instead of using soft references."

`weakKeys()`도 함정이 있습니다. 키 비교가 `equals()`가 아니라 **동일성(`==`)** 으로 바뀝니다. `Long` 키나 문자열 키로 이걸 켜면 히트가 거의 나지 않습니다.

### 6-4. 갱신 — `refreshAfterWrite`

만료는 "지워서 다음 조회를 기다리게" 만들고, 갱신은 "옛 값을 주면서 뒤에서 새로 불러오게" 만듭니다. Refresh 위키에 따르면 갱신은 **조회될 때만 시작되고, 갱신이 진행되는 동안에도 옛 값이 반환됩니다.** `CacheLoader`가 있는 `LoadingCache`가 필요합니다.

`expireAfterWrite`와 함께 쓰는 게 핵심입니다. 갱신만 걸면 로더가 계속 실패할 때 무한히 낡은 값을 줄 수 있으므로, 만료를 상한으로 같이 걸어둡니다. 위 예시의 1분 갱신 / 5분 만료 조합이 그 의도입니다.

### 6-5. 수동 채우기의 원자성

Caffeine의 Population 위키는 `cache.get(key, k -> value)`로 **원자적으로 계산해 넣기**를 권합니다. 같은 키에 대해 계산이 한 번만 일어납니다. 대신 매핑 함수가 `null`을 돌려주면 `get`도 `null`이고, 예외를 던지면 그 예외가 전파됩니다. `ConcurrentHashMap`으로 직접 만들었을 때 5절 ③처럼 손으로 해결해야 했던 문제를 라이브러리가 대신 처리합니다.

## 7. Spring Boot에 붙이기

```yaml
spring:
  cache:
    type: caffeine
    cache-names: productPolicy,exchangeRate
    caffeine:
      spec: maximumSize=10000,expireAfterWrite=5m,recordStats
```

레퍼런스가 밝히는 커스터마이징 우선순위는 **`spring.cache.caffeine.spec` → `CaffeineSpec` 빈 → `Caffeine` 빈** 순입니다.

`spec` 문자열이 지원하는 키는 `initialCapacity`, `maximumSize`, `maximumWeight`, `expireAfterAccess`, `expireAfterWrite`, `refreshAfterWrite`, `weakKeys`, `weakValues`, `softValues`, `recordStats`뿐입니다. javadoc은 **값이 아닌 파라미터를 받는 설정은 코드로 해야 한다**고 명시합니다. 즉 `weigher`, `removalListener`, `CacheLoader`, 사용자 `Expiry`는 못 넣습니다. 캐시별로 다른 TTL을 주는 것도 `spec` 하나로는 안 되므로 그때는 `CacheManager`를 직접 만듭니다.

```java
@Bean
CacheManager cacheManager() {
    CaffeineCacheManager manager = new CaffeineCacheManager();
    manager.setCaffeine(Caffeine.newBuilder()
            .maximumSize(10_000)
            .expireAfterWrite(Duration.ofMinutes(5))
            .recordStats());
    // 캐시별로 다른 설정이 필요하면 개별 등록합니다
    manager.registerCustomCache("exchangeRate", Caffeine.newBuilder()
            .maximumSize(200)
            .expireAfterWrite(Duration.ofSeconds(30))
            .recordStats()
            .build());
    return manager;
}
```

### 7-1. 같은 키에 동시에 몰리면 전부 계산합니다

Spring 레퍼런스는 기본 동작을 이렇게 설명합니다. 여러 스레드가 같은 인자로 동시에 호출하면 **캐시 추상화는 아무것도 잠그지 않고, 같은 값이 여러 번 계산됩니다.** 기동 직후에 특히 잘 일어납니다.

```java
@Cacheable(cacheNames = "productPolicy", sync = true)
public ProductPolicy findPolicy(long productId) { ... }
```

`sync = true`면 한 스레드만 계산하고 나머지는 대기합니다. 선택적 기능이라 캐시 라이브러리가 지원하지 않을 수 있지만, 프레임워크가 제공하는 `CacheManager` 구현은 모두 지원한다고 문서에 적혀 있습니다.

다만 이건 **한 인스턴스 안에서만** 막아줍니다. 인스턴스가 10대면 인기 키 하나에 최소 10번의 DB 조회가 발생합니다. 로컬 캐시에서는 캐시 스탬피드가 인스턴스 수만큼 배가된다는 점을 기억하면 됩니다.

### 7-2. 히트율을 안 보면 캐시를 운영하는 게 아닙니다

Spring Boot 메트릭 문서는 Caffeine을 계측 대상으로 명시하면서 두 조건을 붙입니다.

- **기동 시점에 구성된 캐시만 자동으로 레지스트리에 바인딩됩니다.** 런타임에 만들어진 캐시는 `CacheMetricsRegistrar`로 직접 등록해야 합니다.
- **캐시 라이브러리 쪽에서 통계가 켜져 있어야 합니다.** Caffeine에서는 `recordStats()`입니다.

`recordStats`를 빼면 `/actuator/metrics/cache.gets`가 조용히 비어 있거나 0만 나옵니다. 그래서 위 설정과 코드 양쪽에 `recordStats`가 들어가 있습니다.

## 8. 예제 — 환율 조회

### 8-1. 클린하지 않은 코드 ❌

```java
@Service
public class ExchangeRateService {

    private final Map<String, BigDecimal> rates = new HashMap<>();   // ❌ ①
    private final ExchangeRateClient client;

    public BigDecimal rate(String currency) {
        BigDecimal cached = rates.get(currency);
        if (cached == null) {                                        // ❌ ②
            cached = client.fetchRate(currency);
            rates.put(currency, cached);                             // ❌ ③
        }
        return cached;
    }
}
```

**①** `HashMap`은 스레드 안전하지 않습니다. 동시 `put`이 겹치면 값이 유실되거나, 리사이징 도중 구조가 깨져 조회가 돌아오지 않을 수 있습니다. **②** 검사-후-행동이 원자적이지 않아 같은 통화를 여러 스레드가 동시에 조회합니다. **③** 상한도 만료도 없습니다. 환율이 바뀌어도 이 프로세스는 영원히 옛 값을 씁니다.

### 8-2. 개선한 코드 ✔️

```java
@Service
public class ExchangeRateService {

    private final LoadingCache<String, BigDecimal> rates;

    public ExchangeRateService(ExchangeRateClient client) {
        this.rates = Caffeine.newBuilder()
                .maximumSize(200)                             // 통화 코드 수는 유한합니다
                .expireAfterWrite(Duration.ofMinutes(1))      // 낡음의 상한
                .refreshAfterWrite(Duration.ofSeconds(20))    // 조회되면 뒤에서 갱신
                .recordStats()
                .build(client::fetchRate);
    }

    public BigDecimal rate(String currency) {
        return rates.get(currency);
    }
}
```

바뀐 것은 셋입니다. 같은 키의 로딩이 **원자적**이 되었고, 상한과 만료로 **힙과 낡음이 둘 다 유계**가 되었고, `refreshAfterWrite` 덕에 만료 직후 요청이 로딩을 기다리지 않습니다.

여기서 유일하게 정직해야 할 부분은 **1분입니다.** 이 값은 "환율이 1분 낡아도 되는가"에 대한 비즈니스 답변이지 기술적 최적값이 아닙니다. 결제 금액을 확정하는 경로라면 이 캐시를 쓰면 안 됩니다.

## 9. 2계층 캐시는 언제 정당한가

로컬 + Redis를 겹쳐 쓰는 구성이 흔히 거론됩니다. 판단 기준은 단순합니다. **Redis 조회 자체가 병목으로 측정되었는가.**

정당해지는 조건은 좁습니다. 요청당 같은 키를 여러 번 읽거나, 특정 키에 트래픽이 몰려 Redis 한 노드가 포화되는 경우입니다. 그때도 대가는 남습니다. 무효화할 층이 둘로 늘고, 로컬 층은 3-1 때문에 즉시 일관이 되지 않습니다. Redis 6부터의 `CLIENT TRACKING`이 전파를 거들어 주지만 그 자체로 순서 경합과 커넥션 유실 처리 문제가 따라옵니다 — `daily/day39-cache-invalidation.md` 4절에서 다룬 내용입니다.

그래서 **한 층으로 시작하고, 로컬 층은 TTL을 짧게(수십 초) 두는** 편이 안전합니다. 짧은 TTL은 히트율을 조금 포기하는 대신 불일치 시간을 납득할 수 있는 크기로 묶어줍니다.

## 10. 함정

**함정 1 — Redis 의존성이 있어서 `spring.cache.caffeine.spec`이 무시됩니다**
- **증상**: `spec`에 `maximumSize`와 `expireAfterWrite`를 넣었는데 아무 효과가 없습니다. 항목이 만료되지 않고, Caffeine 메트릭도 안 보입니다. 오류 로그는 없습니다.
- **원인**: Spring Boot의 캐시 프로바이더 감지 순서는 Generic → JCache → Hazelcast → Infinispan → Couchbase → **Redis → Caffeine** → Cache2k → Simple입니다. 다른 기능 때문에 Redis 의존성이 이미 들어와 있으면 Redis가 먼저 선택되고 Caffeine 설정은 사용되지 않습니다.
- **해법**: `spring.cache.type`으로 명시합니다. 두 캐시를 함께 쓸 거라면 `CacheManager`를 각각 빈으로 만들고 `@Cacheable(cacheManager = "...")`로 지정합니다.

<!-- TODO: 확인 필요 — 레퍼런스가 명시한 것은 감지 "순서"까지입니다. "Caffeine 설정이 조용히 무시된다"는 그 순서에서 도출한 결론이고, 경고 로그 유무를 확인한 1차 자료는 찾지 못했습니다. -->

**함정 2 — 인스턴스를 늘린 뒤 값이 요청마다 다르게 보입니다**
- **증상**: 관리자가 정책을 수정하고 저장했는데, 목록을 새로고침하면 새 값과 옛 값이 번갈아 나옵니다. 재현이 로드밸런서 배분에 따라 달라집니다.
- **원인**: `@CacheEvict`가 요청을 받은 인스턴스의 힙만 비웁니다. 다른 인스턴스는 무효화 사실을 모르고 자기 TTL이 끝날 때까지 옛 값을 서빙합니다.
- **해법**: 로컬 캐시에 담는 데이터의 TTL을 "번갈아 보여도 되는 시간"으로 정합니다. 그걸 허용할 수 없는 화면이면 그 조회만 캐시를 건너뛰거나 공유 캐시로 옮깁니다. 관리 화면은 대체로 후자가 맞습니다.

**함정 3 — 아무도 안 쓰는 시간대에 힙이 안 줄어듭니다**
- **증상**: `expireAfterWrite=10m`인데 새벽에 힙 사용량이 내려가지 않습니다. 트래픽이 들어오면 그때 떨어집니다.
- **원인**: Caffeine의 유지 작업은 쓰기 시 주기적으로, 읽기 시 간헐적으로 일어납니다. 전용 청소 스레드가 없어서 접근이 없으면 만료된 항목도 참조가 유지됩니다.
- **해법**: 만료 시점의 즉시 제거가 필요하면 `Caffeine.scheduler(Scheduler.systemScheduler())`를 지정합니다. 이건 힙 회수 타이밍 문제이고, 조회 시 만료 여부 판정은 정상 동작하므로 **낡은 값이 반환되는 문제는 아닙니다.**

**함정 4 — 캐시에 담은 객체를 누군가 고칩니다**
- **증상**: 정책 객체의 필드 하나가 어느 순간부터 이상한 값입니다. DB를 보면 정상이고, 재기동하면 사라집니다.
- **원인**: 로컬 캐시는 같은 객체 참조를 모든 요청에 돌려줍니다. 어느 코드가 응답을 만들면서 그 객체의 세터를 호출했고, 그 변경이 캐시에 그대로 남았습니다. 원격 캐시에서는 매번 역직렬화하므로 이 버그가 드러나지 않습니다.
- **해법**: 캐시 값은 `record`나 불변 객체로 만듭니다(`daily/day43-immutability.md`). 컬렉션 필드는 `List.copyOf()`로 감싸 넣어 밖에서 수정하지 못하게 합니다.

**함정 5 — `recordStats` 없이 캐시를 "적용 완료"로 처리합니다**
- **증상**: 캐시를 넣었는데 DB 부하가 기대만큼 안 줄었습니다. `/actuator/metrics/cache.gets`는 비어 있습니다.
- **원인**: 통계 수집이 꺼져 있으면 Spring Boot가 가져갈 값이 없습니다. 기동 후 런타임에 생성된 캐시라면 자동 바인딩 대상도 아닙니다. 그래서 히트율이 5%인지 95%인지 아무도 모릅니다.
- **해법**: `recordStats`를 켜고 히트율과 축출 수를 대시보드에 올립니다. 히트율이 낮으면 캐시가 아니라 **키 설계나 TTL이 틀린 것**이므로, 지표 없이는 고칠 방향조차 잡히지 않습니다.

## 11. 참고자료

- [Caffeine — Eviction](https://github.com/ben-manes/caffeine/wiki/Eviction) — 크기·시간·참조 기반 축출, 유지 작업이 쓰기/읽기 시점에 분산 수행된다는 점, `Scheduler`로 즉시 제거하는 방법
- [Caffeine — Efficiency](https://github.com/ben-manes/caffeine/wiki/Efficiency) — W-TinyLFU 채택 근거, LRU의 전체 스캔 취약성, ARC·LIRS와의 비교(추가 메모리 요구·특허)
- [Caffeine — Population](https://github.com/ben-manes/caffeine/wiki/Population), [Refresh](https://github.com/ben-manes/caffeine/wiki/Refresh) — `cache.get(key, fn)`의 원자성, `refreshAfterWrite`가 조회 시에만 시작되고 갱신 중 옛 값을 반환한다는 점
- [Caffeine javadoc 3.2.4](https://javadoc.io/doc/com.github.ben-manes.caffeine/caffeine/3.2.4/com.github.benmanes.caffeine/com/github/benmanes/caffeine/cache/Caffeine.html) — `maximumSize`가 근사치라는 문장, `softValues`·`weakKeys` 경고. `CaffeineSpec` 항목에 spec이 지원하는 키 목록과 "값이 아닌 파라미터는 코드로만" 제약
- [Caffeine README](https://github.com/ben-manes/caffeine/blob/master/README.md) — 3.x는 Java 11 이상, 2.x는 그 이하. Guava 캐시 설계 경험에서 출발했다는 배경
- [Caching — Spring Boot 레퍼런스](https://docs.spring.io/spring-boot/reference/io/caching.html) — 프로바이더 감지 순서, `spring.cache.caffeine.spec` 우선순위, Simple 프로바이더가 `ConcurrentHashMap`이라는 점
- [Cache Abstraction — Spring Framework 레퍼런스](https://docs.spring.io/spring-framework/reference/integration/cache/annotations.html) — 기본적으로 아무것도 잠그지 않아 같은 값이 여러 번 계산된다는 설명과 `sync` 속성
- [Metrics — Spring Boot 레퍼런스](https://docs.spring.io/spring-boot/reference/actuator/metrics.html) — 계측 대상 캐시 라이브러리, 기동 시점 구성된 캐시만 자동 바인딩된다는 제약, 라이브러리 쪽 통계 활성화 요구
- [`ConcurrentHashMap` javadoc (Java 21)](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/ConcurrentHashMap.html) — `computeIfAbsent`의 원자성, 계산 중 갱신 차단, 매핑 함수가 맵을 수정해서는 안 된다는 제약
- 관련 문서: `daily/day33-cache-strategy.md`(읽기·쓰기 전략), `daily/day39-cache-invalidation.md`(무효화와 전파), `daily/day43-immutability.md`(캐시 값을 불변으로), `daily/day07-jvm-memory.md`(캐시가 쓰는 힙)
