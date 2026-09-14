# 캐시 전략은 어떻게 고르는가 — Cache-Aside, Write-Through, Write-Behind

> 이 문서가 답할 질문: **읽기와 쓰기 경로에서 캐시와 DB 중 무엇을 어떤 순서로 건드릴 것인가, 그 선택이 무엇을 보장하고 무엇을 포기하는가?**
>
> 분류: 선택형(A vs B). 여러 출처가 공통으로 드는 비교 기준 — 정합성이 깨지는 시간 창, 쓰기 지연, 캐시 메모리 낭비, 캐시 노드가 비었을 때의 행동 — 을 찾는 관점으로 조사했습니다.
>
> 기준: AWS ElastiCache 개발자 가이드, Azure Architecture Center의 Cache-Aside 패턴 문서, Spring Framework 7.0 레퍼런스(Spring Boot 4.1 동반)를 교차 확인했습니다. Redis/Valkey 같은 **원격 공유 캐시**를 전제로 합니다. 캐시 무효화 타이밍 자체를 깊게 다루는 것은 별도 주제라 여기서는 전략 선택까지만 다룹니다.

## 1. 핵심 개념 — 고르는 것은 하나가 아니라 "읽기 전략 × 쓰기 전략"

캐시 전략 이름이 헷갈리는 이유는 단순합니다. **같은 층위의 선택지가 아니기 때문입니다.**

Cache-Aside는 읽기 경로 이야기이고, Write-Through는 쓰기 경로 이야기입니다. "Cache-Aside를 쓸까 Write-Through를 쓸까"는 애초에 성립하지 않는 질문입니다. 둘은 같이 씁니다. 실제로 골라야 하는 것은 두 가지입니다.

1. **읽기** — 캐시에 값이 없을 때 DB를 부르는 주체는 누구인가
2. **쓰기** — DB에 쓸 때 캐시를 어떻게 처리하는가

> 이 두 번째를 정하지 않으면 이런 일이 벌어집니다. 캐시를 붙이면 읽기가 빨라지는 건 사실입니다. 그런데 관리자가 상품 가격을 고쳤는데 사용자 화면에는 옛 가격이 계속 뜹니다. TTL이 10분이면 최악의 경우 10분 내내 틀린 가격으로 주문이 들어옵니다. 더 나쁜 건 재현이 안 된다는 점입니다. 같은 요청이 어떤 서버에서는 맞고 어떤 서버에서는 틀립니다. "캐시를 지우면 되잖아요"까지는 누구나 압니다. **어디서, 언제, 지울 것인가 아니면 갱신할 것인가**가 이 문서의 내용입니다.

## 2. 다섯 가지 전략

### 2-1. 읽기 경로 — Cache-Aside와 Read-Through

**Cache-Aside(= lazy loading)**: 애플리케이션이 직접 캐시를 조회하고, 없으면 DB에서 읽어서 캐시에 넣습니다. 캐시 클라이언트는 그냥 키-값 저장소일 뿐이고 모든 판단이 애플리케이션 코드에 있습니다.

**Read-Through**: 애플리케이션은 캐시에만 요청합니다. 없으면 **캐시 계층이** 등록된 로더를 호출해 DB에서 읽고, 채워 넣고, 반환합니다. 애플리케이션 코드에는 DB 호출이 보이지 않습니다.

| | Cache-Aside | Read-Through |
|---|---|---|
| DB를 부르는 주체 | 애플리케이션 | 캐시 계층(로더) |
| 캐시가 죽으면 | DB로 직접 폴백 가능 | 캐시가 단일 장애점이 되기 쉬움 |
| 데이터 종류별 다른 정책 | 쉬움 | 로더 단위로만 |
| 필요 조건 | 없음 | 캐시 제품이 로더 훅을 지원해야 함 |

Azure 문서는 Cache-Aside를 "read-through 기능이 없는 캐시에서 read-through를 흉내 내는 방법"으로 설명합니다. 실제로 Redis는 로더 훅이 없어서, Redis를 쓰는 순간 읽기 경로는 사실상 Cache-Aside로 정해집니다.

AWS 문서가 정리한 lazy loading의 장단점은 이렇습니다.

- **장점**: 실제로 요청된 데이터만 캐시에 올라갑니다. 그리고 노드가 죽어 빈 노드로 교체돼도 애플리케이션은 계속 동작합니다. 지연이 늘어날 뿐입니다.
- **단점**: 미스 페널티가 있습니다. 미스 한 번에 왕복이 세 번(캐시 조회 → DB 조회 → 캐시 기록)입니다. 그리고 쓰기 때 캐시를 손대지 않으면 값이 낡습니다.

### 2-2. 쓰기 경로 — 셋 중 하나가 아니라 넷

| 전략 | 동작 | 쓰기 지연 | 유실 위험 |
|---|---|---|---|
| **Write-Invalidate** | DB에 쓰고 → 캐시 키를 **삭제** | DB 1회 + 삭제 1회 | 없음 |
| **Write-Through** | DB에 쓰고 → 캐시도 **같은 값으로 갱신** | DB 1회 + 캐시 쓰기 1회 | 없음(부분 실패는 남음) |
| **Write-Behind** | 캐시에 먼저 쓰고 → DB는 나중에 비동기 flush | 캐시 1회 | **있음** |
| **Write-Around** | DB에만 쓰고 캐시는 손대지 않음 | DB 1회 | 없음 |

실무 기본값은 표의 첫 줄인 **Write-Invalidate**입니다. Azure 문서가 설명하는 Cache-Aside의 쓰기 경로가 정확히 이것입니다. "데이터 저장소를 갱신한 다음 해당 캐시 항목을 무효화한다." 이름이 따로 유명하지 않아서 Cache-Aside라는 이름에 묻혀 있을 뿐입니다. 왜 갱신이 아니라 삭제인지는 6절에서 따로 다룹니다.

**Write-Through**의 대가는 AWS 문서가 분명하게 씁니다. 캐시 데이터가 절대 낡지 않는 대신, 쓰기마다 왕복이 두 번입니다. 그리고 두 가지 부작용이 있습니다. 새 노드를 띄우면 그 데이터가 다시 쓰이기 전까지 캐시에 없고(그래서 lazy loading과 **함께** 써야 합니다), 아무도 읽지 않을 데이터까지 캐시에 올라가 메모리를 먹습니다. AWS 문서는 후자를 "cache churn"이라 부르고 TTL로 완화하라고 권합니다.

**Write-Behind**는 쓰기 버스트를 흡수합니다. 대신 flush 전에 캐시가 죽으면 그 사이 쓰기는 사라집니다. 주문이나 결제에는 쓸 수 없고, 조회수 카운터나 분석 이벤트처럼 몇 건 날아가도 되는 데이터에만 맞습니다. 그리고 Redis 자체에는 이 기능이 없습니다. Hazelcast·Ignite 같은 제품의 기능이거나, 직접 큐를 놓고 구현해야 합니다.

**Write-Around**는 "쓰기가 잦은데 읽기는 드문 데이터"를 캐시가 먹지 않게 합니다. 대신 다음 읽기는 반드시 미스입니다.

### 2-3. TTL은 전략이 아니라 안전망

AWS 문서의 정리가 이 절 전체를 요약합니다. **lazy loading은 낡은 데이터를 허용하지만 빈 노드에 강하고, write-through는 항상 신선하지만 빈 노드에 약하고 불필요한 데이터로 캐시를 채웁니다. 모든 쓰기에 TTL을 붙이면 양쪽의 장점을 취할 수 있습니다.**

TTL이 정합성을 보장하지는 않습니다. **낡음의 한도를 정할 뿐입니다.** TTL 10분은 "10분 이상 틀리지는 않는다"는 뜻이지 "10분 동안 맞다"는 뜻이 아닙니다. 그래서 TTL은 무효화의 대체재가 아니라, 무효화가 실패했을 때의 백스톱입니다.

## 3. 흐름

### 3-1. 코드로 보는 구성 — Cache-Aside + 쓰기 시 무효화

Redis를 쓰는 조회 서비스입니다. `StringRedisTemplate`과 Jackson만 씁니다.

```java
@Service
public class ProductQueryService {

    private static final Duration TTL = Duration.ofMinutes(10);

    private final StringRedisTemplate redis;
    private final ProductRepository productRepository;
    private final ObjectMapper objectMapper;

    public ProductQueryService(StringRedisTemplate redis,
                               ProductRepository productRepository,
                               ObjectMapper objectMapper) {
        this.redis = redis;
        this.productRepository = productRepository;
        this.objectMapper = objectMapper;
    }

    public ProductView findById(long productId) {
        String key = cacheKey(productId);

        String cached = redis.opsForValue().get(key);
        if (cached != null) {
            return deserialize(cached);
        }

        ProductView view = productRepository.findViewById(productId)
                .orElseThrow(() -> new ProductNotFoundException(productId));

        redis.opsForValue().set(key, serialize(view), withJitter(TTL));
        return view;
    }

    static String cacheKey(long productId) {
        return "product:v1:" + productId;   // v1 — 직렬화 포맷이 바뀌면 v2로 올립니다
    }

    // 동시 만료를 막는 지터. 기본 TTL의 0~10%를 무작위로 더합니다
    private static Duration withJitter(Duration base) {
        long millis = base.toMillis();
        return Duration.ofMillis(millis + ThreadLocalRandom.current().nextLong(millis / 10));
    }

    private String serialize(ProductView view) {
        try {
            return objectMapper.writeValueAsString(view);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("직렬화 실패: " + view, e);
        }
    }

    private ProductView deserialize(String json) {
        try {
            return objectMapper.readValue(json, ProductView.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("역직렬화 실패", e);
        }
    }
}
```

쓰기 쪽입니다. **DB 커밋이 끝난 뒤에** 캐시를 지웁니다.

```java
@Service
public class ProductCommandService {

    private final StringRedisTemplate redis;
    private final ProductRepository productRepository;

    public ProductCommandService(StringRedisTemplate redis, ProductRepository productRepository) {
        this.redis = redis;
        this.productRepository = productRepository;
    }

    @Transactional
    public void changePrice(long productId, BigDecimal newPrice) {
        Product product = productRepository.findById(productId)
                .orElseThrow(() -> new ProductNotFoundException(productId));
        product.changePrice(newPrice);

        String key = ProductQueryService.cacheKey(productId);
        TransactionSynchronizationManager.registerSynchronization(
                new TransactionSynchronization() {
                    @Override
                    public void afterCommit() {
                        redis.delete(key);   // 커밋이 확정된 뒤에만 실행됩니다
                    }
                });
    }
}
```

### 3-2. 실행 흐름

**캐시 히트** — 왕복 1회
```
애플리케이션 → Redis GET → 값 있음 → 반환
```

**캐시 미스** — 왕복 3회 (AWS 문서가 말하는 미스 페널티)
```
애플리케이션 → Redis GET → null
           → DB SELECT → 행 반환
           → Redis SET (TTL 10분±) → 반환
```

**쓰기** — 순서가 전부입니다
```
애플리케이션 → DB UPDATE → COMMIT → Redis DEL
                                      ↑
                        커밋 뒤에 지워야 합니다 (이유는 5절)
```

## 4. 특징 — 무엇을 기준으로 고르는가

### 4-1. 비교

| | Write-Invalidate | Write-Through | Write-Behind | Write-Around |
|---|---|---|---|---|
| 쓰기 직후 읽기 | 미스 1회 발생 | 즉시 새 값 | 즉시 새 값 | 미스 1회 발생 |
| 쓰기 지연 | 낮음 | 중간(왕복 2회) | 가장 낮음 | 가장 낮음 |
| 캐시 메모리 | 읽힌 것만 | 쓰인 것 전부 | 쓰인 것 전부 | 읽힌 것만 |
| 캐시 유실 시 | 안전 | 안전 | **데이터 유실** | 안전 |
| 동시 쓰기 순서 뒤집힘 | 영향 없음 | 취약 | 취약 | 영향 없음 |

Azure 문서가 Cache-Aside와 Write-Through의 경계를 명확히 짚습니다. **Cache-Aside는 쓰기에서 캐시를 무효화하고 다음 읽기에서 다시 채웁니다. 그 사이에 읽는 쪽은 미스를 겪거나 잠깐 낡은 값을 봅니다.** 반면 Write-Through는 저장소와 캐시를 같은 쓰기 작업에서 갱신하므로 쓰기 성공 직후 읽기가 새 값을 봅니다. "읽기 직후 자기가 쓴 값이 반드시 보여야 하는가(read-after-write)"가 이 둘을 가르는 기준입니다.

### 4-2. 선택 기준

읽기 경로는 고민할 게 별로 없습니다. **Redis를 쓴다면 Cache-Aside입니다.** 로더 훅이 없으니 선택지가 없습니다.

쓰기 경로는 데이터 성격이 정합니다.

- **기본값은 Write-Invalidate.** 정합성 창이 짧고, 동시 쓰기에 강하고, 안 읽히는 데이터로 캐시를 채우지 않습니다. 고민이 없으면 이걸 씁니다.
- **read-after-write가 필요하면 Write-Through.** 잔액, 재고, 주문 상태처럼 "방금 바꿨는데 왜 그대로냐"가 클레임이 되는 데이터입니다. 단, 반드시 TTL과 lazy loading을 함께 켭니다.
- **쓰기가 폭주하고 몇 건 유실을 감수할 수 있으면 Write-Behind.** 조회수, 좋아요 카운터, 분석 이벤트. 결제·정산에는 쓰지 않습니다.
- **쓰기는 많은데 거의 안 읽히면 Write-Around.** 감사 로그처럼 쌓기만 하는 데이터입니다.

### 4-3. 공통으로 지불하는 비용

전략과 무관하게 캐시를 붙이는 순간 생기는 것들입니다.

- **키 설계가 코드가 됩니다.** 캐시 키에 버전 접두사가 없으면 직렬화 포맷을 바꾼 순간 역직렬화가 터집니다. 3-1의 `product:v1:`이 그 대비입니다.
- **디버깅 단계가 하나 늘어납니다.** "DB에는 맞는 값이 있는데 API가 틀린 값을 준다"는 상황이 생깁니다.
- **캐시가 새 장애점이 됩니다.** 8절 함정 3을 참고하세요.

## 5. 예제 — 쓰기 경로를 잘못 짠 코드

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional
public void changePrice(long productId, BigDecimal newPrice) {
    String key = ProductQueryService.cacheKey(productId);

    redis.delete(key);                       // ❌ ① DB보다 먼저 지웁니다

    Product product = productRepository.findById(productId).orElseThrow();
    product.changePrice(newPrice);

    redis.opsForValue().set(key, serialize(ProductView.from(product)));  // ❌ ② 캐시를 직접 갱신
}
```

두 군데가 잘못됐습니다.

**①** DB보다 먼저 지웠습니다. 지운 직후, 커밋 전에 다른 요청이 미스를 겪으면 **옛 값을 DB에서 읽어 캐시에 다시 채웁니다.** 그다음 이쪽이 커밋합니다. 결과는 DB에 새 값, 캐시에 옛 값. 이걸 고쳐줄 무효화는 이미 지나갔고 TTL이 만료될 때까지 틀린 값이 남습니다. Azure 문서가 이 순서를 콕 집어 경고합니다. 저장소를 **먼저** 갱신하고 그다음 캐시 항목을 제거하라고요.

**②** 트랜잭션 안에서 캐시를 갱신했습니다. `changePrice` 이후 같은 트랜잭션에서 예외가 나면 DB는 롤백되는데 **Redis는 롤백되지 않습니다.** 커밋도 안 된 값이 캐시에 남습니다.

### 5-2. 개선한 코드 ✔️

3-1의 쓰기 코드가 정답이지만, 여러 서비스에서 반복된다면 이벤트로 분리하는 편이 낫습니다.

```java
// 도메인 서비스 — 캐시를 모릅니다
@Service
public class ProductCommandService {

    private final ProductRepository productRepository;
    private final ApplicationEventPublisher events;

    public ProductCommandService(ProductRepository productRepository,
                                 ApplicationEventPublisher events) {
        this.productRepository = productRepository;
        this.events = events;
    }

    @Transactional
    public void changePrice(long productId, BigDecimal newPrice) {
        Product product = productRepository.findById(productId)
                .orElseThrow(() -> new ProductNotFoundException(productId));
        product.changePrice(newPrice);
        events.publishEvent(new ProductChanged(productId));
    }
}

public record ProductChanged(long productId) {}
```

```java
// 캐시 무효화 — 커밋 이후에만 실행됩니다
@Component
public class ProductCacheEvictor {

    private final StringRedisTemplate redis;

    public ProductCacheEvictor(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void evict(ProductChanged event) {
        redis.delete(ProductQueryService.cacheKey(event.productId()));
    }
}
```

`AFTER_COMMIT`이 핵심입니다. 롤백되면 리스너 자체가 실행되지 않으므로 5-1의 ② 문제가 구조적으로 사라집니다.

## 6. 왜 "갱신"이 아니라 "삭제"인가

Write-Through가 더 좋아 보입니다. 미스도 안 나고 값도 최신인데 왜 기본값이 삭제일까요. 세 가지 이유가 있습니다.

**첫째, 동시 쓰기의 순서가 뒤집힙니다.** 스레드 A가 가격을 1000으로, B가 1200으로 바꾼다고 합시다. DB는 락으로 순서가 보장되지만 캐시 쓰기는 별개의 네트워크 호출입니다. DB에는 B의 1200이 최종으로 남았는데 캐시 쓰기만 A가 늦게 도착하면 캐시에는 1000이 박힙니다. 삭제는 순서가 뒤집혀도 결과가 같습니다. **둘 다 "없음"이고, 다음 읽기가 DB에서 진실을 가져옵니다.**

**둘째, 쓴 값이 반드시 읽히지는 않습니다.** 배치가 상품 100만 건을 갱신하면 그 100만 건이 전부 캐시에 올라갑니다. 대부분은 아무도 안 읽습니다. AWS 문서가 cache churn이라고 부르는 낭비입니다.

**셋째, 캐시에 든 것이 DB 행이 아닌 경우가 많습니다.** 캐시 값이 여러 테이블을 조인해 만든 화면용 DTO라면, 쓰기 시점에 그 DTO를 다시 만들려면 조회 로직을 쓰기 경로에 복제해야 합니다. 삭제는 이 문제가 없습니다.

**그래도 삭제가 완벽하지는 않습니다.** 읽기와 쓰기가 겹치면 이런 순서가 가능합니다.

```
A(읽기)  캐시 미스 → DB에서 옛 값 1000 읽음 ──────────── (여기서 멈춤) ──→ 캐시에 1000 기록
B(쓰기)                        DB를 1200으로 커밋 → 캐시 DEL
```

B의 삭제가 A의 기록보다 **먼저** 끝나면, A가 나중에 낡은 1000을 써 넣고 TTL까지 남습니다. 창이 아주 좁아서 자주 나지는 않지만, 트래픽이 크면 드문 일도 매일 일어납니다. 현실적인 방어는 세 가지입니다. 데이터 성격에 맞는 **짧은 TTL**, 정합성이 돈으로 직결되면 **CDC 기반 무효화**, 그리고 애초에 이런 데이터는 **캐시하지 않는 것**입니다.

## 7. 실무에서 찾아보는 캐시 전략 — Spring Cache 추상화

Spring의 `@Cacheable`은 read-through처럼 보이지만, 레퍼런스가 설명하는 동작은 **프록시가 대신 해주는 Cache-Aside**입니다. 캐시 계층이 로더를 부르는 게 아니라, AOP 프록시가 캐시를 조회하고 미스일 때 원래 메서드를 호출합니다. 애플리케이션 코드에서 분기가 사라졌을 뿐 구조는 그대로입니다.

| 애노테이션 | 대응 전략 |
|---|---|
| `@Cacheable` | Cache-Aside (읽기) |
| `@CachePut` | Write-Through — 메서드를 **항상 실행**하고 결과를 캐시에 넣습니다 |
| `@CacheEvict` | Write-Invalidate |

레퍼런스가 명시하는 주의점이 셋 있습니다.

- **`@Cacheable`과 `@CachePut`을 같은 메서드에 함께 쓰는 것은 강하게 권장되지 않습니다.** 동작이 정반대이기 때문입니다. 전자는 캐시를 써서 메서드 실행을 건너뛰고, 후자는 캐시를 갱신하려고 실행을 강제합니다.
- **`@CacheEvict`의 기본값은 `beforeInvocation = false`** 입니다. 메서드가 정상 종료해야 제거합니다. `true`로 두면 메서드가 예외를 던져도 캐시가 지워집니다. 다만 이건 **메서드 종료** 기준이지 **트랜잭션 커밋** 기준이 아닙니다. 5-1의 ② 함정은 `@CacheEvict`를 써도 그대로 남습니다.
- **자기 호출(self-invocation)에는 걸리지 않습니다.** 기본 프록시 모드에서는 외부에서 프록시를 거쳐 들어온 호출만 가로챕니다. 같은 클래스 안에서 `this.findById()`를 부르면 `@Cacheable`이 붙어 있어도 캐시가 동작하지 않습니다. `@Transactional`과 완전히 같은 제약이고, 배경은 `daily/day32-bean-lifecycle.md`에 있습니다.

`@Cacheable(sync = true)`도 알아둘 만합니다. 같은 키에 여러 스레드가 동시에 미스를 겪을 때 한 스레드만 값을 계산하고 나머지는 대기합니다. 다만 이건 **JVM 하나 안에서의 보호**입니다. 인스턴스가 10대면 최대 10번의 DB 조회는 그대로 나갑니다.

## 8. 함정

**함정 1 — 트랜잭션 커밋 전에 캐시를 지웠는데 롤백됐습니다**
- **증상**: DB에는 옛 값이 그대로인데 캐시만 비었습니다. 다음 읽기가 옛 값을 다시 채우니 겉으로는 정상으로 보입니다. 하지만 "분명히 저장 실패했는데 왜 캐시가 지워졌지"라는 미스 폭증이 배치 롤백 때마다 관측됩니다.
- **원인**: `redis.delete()`는 트랜잭션에 참여하지 않습니다. `@CacheEvict`도 마찬가지로 **메서드 반환** 시점에 동작하지 커밋 시점에 동작하지 않습니다.
- **해법**: `@TransactionalEventListener(phase = AFTER_COMMIT)`이나 `TransactionSynchronization.afterCommit()`으로 미룹니다. 5-2가 그 형태입니다.

**함정 2 — 없는 데이터를 캐시하지 않아 DB가 뚫립니다**
- **증상**: 존재하지 않는 `productId`로 초당 수천 건이 들어오면 전부 미스입니다. 캐시 히트율은 멀쩡한데 DB CPU만 올라갑니다.
- **원인**: 3-1 코드처럼 조회 결과가 없으면 예외를 던지고 끝내면, **"없음"이라는 사실이 캐시되지 않습니다.** 같은 요청이 매번 DB까지 갑니다.
- **해법**: "없음"도 짧은 TTL(예: 30초~1분)로 캐시합니다. 다만 이건 메모리를 공격에 내주는 면이 있어서, 존재하지 않는 키가 대량으로 들어오는 상황이라면 캐시가 아니라 입력 검증이나 레이트 리밋으로 막는 편이 낫습니다.

**함정 3 — 캐시가 죽자 서비스가 같이 죽었습니다**
- **증상**: Redis 장애 알림과 동시에 API 전체가 타임아웃납니다. DB는 커넥션 풀 고갈로 뒤따라 죽습니다.
- **원인**: 두 가지가 겹칩니다. 첫째, `redis.opsForValue().get()`에서 던진 예외를 아무도 잡지 않아 캐시 장애가 곧 요청 실패가 됩니다. 둘째, 캐시가 막아주던 트래픽이 한꺼번에 DB로 갑니다. 히트율 95%였다면 DB 부하가 20배가 됩니다.
- **해법**: 캐시 조회 실패를 **미스로 간주하고 DB로 폴백**합니다(Cache-Aside의 장점이 여기서 나옵니다). 그리고 폴백 경로에 동시 실행 제한을 둡니다. DB 커넥션 풀이 상한 역할을 하긴 하지만, 그 상한에 닿는 순간 다른 API까지 같이 막힙니다.

**함정 4 — TTL을 다 같게 줘서 한꺼번에 만료됩니다**
- **증상**: 배포 직후나 캐시 워밍 후 정확히 TTL 간격으로 DB 부하가 주기적으로 치솟습니다.
- **원인**: 같은 시점에 채워진 키들이 같은 TTL을 받으면 같은 순간에 만료됩니다. 게다가 Redis는 TTL이 0이 되는 즉시 지우지 않고, 접근 시점과 백그라운드 샘플링으로 지웁니다. 실제 만료 시각은 TTL보다 조금 뒤로 밀립니다.
- **해법**: 3-1의 `withJitter()`처럼 TTL에 무작위 폭을 더합니다. 만료 시각이 흩어지면 첨두가 평평해집니다.

**함정 5 — 캐시에서 꺼낸 객체를 호출부가 고쳤습니다**
- **증상**: 어떤 요청이 상품 이름을 바꿔 보고, 그 뒤 다른 요청의 응답에 그 변경이 섞여 나옵니다. 재현이 거의 불가능합니다.
- **원인**: 로컬 캐시(Caffeine, `ConcurrentHashMap`)는 **참조를 그대로 돌려줍니다.** 호출부가 그 객체를 변경하면 캐시 안의 값이 바뀝니다. Redis처럼 직렬화를 거치는 원격 캐시에서는 안 생기고, 로컬 캐시로 바꾼 순간 나타납니다.
- **해법**: 캐시에 넣는 타입을 불변으로 만듭니다. `record`나 불변 DTO면 이 문제 자체가 성립하지 않습니다.

## 9. 참고자료

- [Caching strategies — Amazon ElastiCache 개발자 가이드](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Strategies.html) — lazy loading·write-through의 장단점, 미스 페널티 왕복 3회, cache churn, TTL로 양쪽을 조합하는 근거
- [Cache-Aside pattern — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside) — 쓰기 시 DB 먼저·캐시 무효화 나중이라는 순서, write-through와의 read-after-write 차이, 만료 정책 설정 기준
- [Cache Annotations — Spring Framework 레퍼런스](https://docs.spring.io/spring-framework/reference/integration/cache/annotations.html) — `@Cacheable`/`@CachePut`/`@CacheEvict` 동작, `sync` 속성, `beforeInvocation`, 프록시 모드의 자기 호출 제약
- [Cache consistency: strategies to keep data fresh — Redis](https://redis.io/blog/cache-consistency-strategies/) — 캐시가 어긋나는 세 가지 경로(TTL 창, 쓰기 순서 경합, 다중 인스턴스 채우기 경합), Redis의 능동/수동 만료 방식
- 관련 문서: `daily/day32-bean-lifecycle.md`(프록시 자기 호출 제약), `daily/day26-response-design.md`(캐시하기 좋은 응답 형태)
