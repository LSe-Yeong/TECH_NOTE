# 캐시 무효화 — 무엇을, 언제, 어디서 지우는가

> 이 문서가 답할 질문: **데이터가 바뀌었을 때 낡은 캐시가 남지 않게 하려면 무엇을 대상으로, 어느 시점에, 어느 범위까지 지워야 하는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처가 공통으로 보고하는 증상은 하나입니다. "DB는 맞는데 화면이 틀리다." 그 증상으로 가는 경로가 대상 누락·타이밍 경합·전파 실패 셋으로 갈린다는 관점으로 조사했습니다.
>
> 기준: Redis 공식 문서(client-side caching reference, keyspace notifications, `KEYS`), Spring Framework 레퍼런스, Spring Data Redis 레퍼런스, AWS CloudFront 개발자 가이드를 교차 확인했습니다. 원격 공유 캐시(Redis)를 전제로 하고, 로컬 캐시는 4절에서 따로 다룹니다.
>
> `daily/day33-cache-strategy.md`와 경계가 있습니다. 거기서는 **읽기·쓰기 전략을 어떻게 고르는가**(갱신이 아니라 삭제인 이유까지)를 다뤘습니다. 이 문서는 그 뒤의 문제, **무효화 자체를 어떻게 설계하는가**입니다.

## 1. 핵심 개념 — 어려운 건 "지우는 것"이 아니라 "대상을 아는 것"

무효화는 캐시 항목을 더 이상 유효하지 않다고 표시하는 행위입니다. 수단은 넷뿐입니다. **삭제하거나, 덮어쓰거나, 키 이름을 바꾸거나, TTL로 만료시키거나.** `DEL` 한 줄이면 끝나는 일이라 어려울 게 없어 보입니다.

Redis 공식 문서도 client-side caching 레퍼런스에 `There are two hard problems in computer science...`라는 제목의 절을 따로 두고 있습니다. 캐시를 제공하는 쪽조차 "어떻게 무효화할 것인가"를 별도의 문제로 취급한다는 뜻입니다.

> 이게 빠지면 이런 일이 벌어집니다. 상품명을 고쳤습니다. 상세 페이지는 바로 바뀝니다. 그런데 목록에는 옛 이름이 그대로입니다. 검색 결과에도, 홈 배너에도 남아 있습니다. 코드를 보면 `redis.delete("product:42")`는 분명히 호출됩니다. **지우는 코드가 틀린 게 아니라 지울 대상을 하나만 알고 있었던 겁니다.** 여기에 "어느 인스턴스의 로컬 캐시까지 지워졌는가", "지운 직후 누가 옛 값으로 다시 채우지 않았는가"가 겹치면 재현이 안 되는 버그가 됩니다.

문제를 셋으로 쪼개면 각각 해법이 다릅니다.

1. **무엇을** — 이 변경이 영향을 주는 캐시 키가 무엇인가 (2절)
2. **언제** — 어느 시점에 지워야 경합이 없는가 (3절)
3. **어디서** — 어느 캐시 층·어느 인스턴스까지 전파되는가 (4절)

## 2. 무엇을 지우는가 — 역인덱스 문제

### 2-1. 키 하나를 지우는 일은 거의 없습니다

상품 42번의 이름이 바뀌었습니다. 영향받는 캐시 키를 세어봅니다.

```
product:v1:42                     상세
category:3:list:page:1..50        카테고리 목록 (페이지마다 별도 키)
search:keyword:{여러 개}           검색 결과
home:banner:recommended           추천 배너
```

쓰기 코드가 이 목록을 알아야 하는데, **이 관계를 아는 코드는 읽기 쪽에 있습니다.** 목록 캐시 키를 만든 곳은 조회 서비스이고, 지워야 하는 곳은 명령 서비스입니다. 그래서 무효화는 항상 "읽기 쪽에서 만든 키를 쓰기 쪽이 역추적하는" 모양이 되고, 읽기 쪽에 캐시를 하나 추가할 때마다 쓰기 쪽에 무효화를 하나 추가해야 합니다. 이 추가를 잊는 것이 가장 흔한 실패입니다.

접근법은 셋입니다.

| 방식 | 무효화 비용 | 누락 위험 | 남는 문제 |
|---|---|---|---|
| **패턴 삭제** (`product:*`) | 키 개수에 비례 | 낮음 | 스캔 비용, 과도 삭제 |
| **태그 인덱스** (Set에 키 목록 저장) | 태그에 달린 키 수 | 중간 | 인덱스 자체가 낡음 |
| **버전 키** (키 이름에 세대 번호) | O(1) | 없음 | 고아 키가 메모리에 남음 |

### 2-2. 패턴 삭제 — `KEYS`는 쓰지 않습니다

가장 먼저 떠오르는 방법이고, 가장 먼저 사고가 나는 방법입니다. Redis 공식 문서는 `KEYS`에 경고를 붙여 두었습니다. 시간 복잡도가 O(N)이고, **대규모 데이터베이스에 실행하면 성능을 망칠 수 있으니 애플리케이션 코드에서 쓰지 말라**고 명시합니다. 디버깅이나 키스페이스 레이아웃 변경 같은 특수 작업용이라는 것이고, 대안으로 `SCAN`이나 Set 자료구조를 권합니다.

Redis는 명령을 한 번에 하나씩 처리하기 때문에 `KEYS *`가 도는 동안 **다른 모든 요청이 뒤에서 기다립니다.** 캐시 지연 하나가 전체 API 지연이 됩니다.

`SCAN`은 커서로 조금씩 끊어 읽으므로 블로킹은 없습니다. 대신 왕복이 늘고, 스캔 도중 추가된 키는 보일 수도 안 보일 수도 있습니다. 즉 **`SCAN` 기반 패턴 삭제는 완전성을 보장하지 않습니다.** 게다가 둘 다 "이 프리픽스로 시작하는 키" 이상을 표현하지 못합니다. `search:keyword:*`를 통째로 날리면 상품 42와 무관한 검색 캐시까지 사라집니다.

### 2-3. 태그 — 역인덱스를 직접 만듭니다

캐시를 채울 때 "이 키는 상품 42에 의존한다"는 사실을 Set에 같이 기록합니다.

```java
// 읽기 경로에서 캐시를 채울 때, 의존 관계도 함께 기록합니다
public void putWithTags(String key, String value, Duration ttl, Set<Long> productIds) {
    redis.opsForValue().set(key, value, ttl);
    for (Long productId : productIds) {
        String tagKey = "tag:product:" + productId;
        redis.opsForSet().add(tagKey, key);
        redis.expire(tagKey, ttl.multipliedBy(2));   // 캐시보다 반드시 오래 살아야 합니다
    }
}

// 쓰기 경로에서 태그 하나로 딸린 키를 전부 지웁니다
public void evictByProduct(long productId) {
    String tagKey = "tag:product:" + productId;
    Set<String> keys = redis.opsForSet().members(tagKey);
    if (keys != null && !keys.isEmpty()) {
        redis.delete(keys);
    }
    redis.delete(tagKey);
}
```

정확한 대신 대가가 있습니다. 쓰기가 두 배로 늘고(값 + 태그), 태그 Set이 **삭제된 키 이름을 계속 들고 있어** 시간이 지나면 부풀어 오릅니다. 그리고 `members` → `delete` 사이는 원자적이지 않아서, 그 틈에 채워진 키는 태그에 등록되기 전이라 살아남습니다.

⚠️ 여기서 가장 자주 나는 사고는 **태그 Set의 TTL을 캐시 값보다 짧게 주는 것**입니다. 태그가 먼저 사라지면 무효화는 아무것도 못 지우고 성공으로 끝납니다. 위 코드가 `ttl.multipliedBy(2)`를 쓰는 이유입니다.

### 2-4. 버전 키 — 지우지 말고 이름을 바꿉니다

가장 단순하면서 가장 강력한 방법입니다. **키 이름에 세대 번호를 넣고, 변경 시 번호만 올립니다.**

```java
// 세대 번호는 Redis에 하나만 둡니다
private long generation(long categoryId) {
    String gen = redis.opsForValue().get("gen:category:" + categoryId);
    return gen == null ? 0L : Long.parseLong(gen);
}

public String listCacheKey(long categoryId, int page) {
    return "category:" + categoryId + ":g" + generation(categoryId) + ":page:" + page;
}

// 무효화 = INCR 한 번
public void invalidateCategory(long categoryId) {
    redis.opsForValue().increment("gen:category:" + categoryId);
}
```

`INCR` 한 번으로 그 카테고리의 목록 캐시 **전부**가 한꺼번에 도달 불가능해집니다. 페이지가 50개든 5000개든 명령은 하나입니다. 스캔도, 태그도, 누락도 없습니다.

대신 옛 세대의 키들이 그대로 남아 메모리를 먹습니다. 그래서 이 방식은 **모든 캐시 값에 TTL이 걸려 있고 `maxmemory` 정책이 설정돼 있다는 전제** 위에서만 성립합니다. 그리고 읽기마다 세대 번호를 한 번 더 조회하므로 왕복이 하나 늘어납니다(세대 번호 자체를 짧게 로컬 캐시하면 완화됩니다).

같은 발상이 CDN에도 있습니다. AWS는 CloudFront 문서에서 파일을 자주 바꾼다면 **무효화(invalidation)보다 버전이 붙은 파일 이름을 우선 쓰라**고 권합니다. 근거가 그대로 옮겨옵니다. 무효화는 엣지 캐시만 지울 뿐 **사용자 브라우저나 회사 프록시에 남은 사본은 어쩌지 못하고**, 버저닝은 롤백·롤포워드가 쉽고, 비용도 들지 않는다는 것입니다.

## 3. 언제 지우는가 — 무효화는 실패할 수 있습니다

### 3-1. 트리거 세 가지

| 트리거 | 반영 지연 | 누락 가능성 | 결합도 |
|---|---|---|---|
| **TTL 만료** | TTL만큼 | 없음(언젠가 반드시) | 없음 |
| **쓰기 경로에서 명시적 호출** | 즉시 | **있음** — 호출을 빠뜨리거나 실패하면 끝 | 쓰기 코드가 캐시를 앎 |
| **변경 로그 기반**(CDC·이벤트) | 수백 ms~수 초 | 중간 — 파이프라인 유실 | 낮음 |

세 번째가 매력적으로 보입니다. 쓰기 코드가 캐시를 몰라도 되니까요. 다만 Redis keyspace notification을 이 용도로 쓰려 한다면 공식 문서의 문장을 먼저 봐야 합니다. **Redis Pub/Sub은 fire and forget이라, 클라이언트가 끊겼다가 재접속하면 그 사이의 이벤트는 전부 유실됩니다.** 클러스터에서는 이벤트가 노드별로 발생하므로 모든 노드에 구독해야 한다는 제약도 있습니다. 즉 이건 "확실한 무효화 채널"이 아니라 "빠른 힌트"입니다.

### 3-2. 무효화 실패는 조용합니다 — 그래서 TTL은 항상 켭니다

명시적 무효화의 진짜 문제는 실패했을 때 아무 일도 안 일어난다는 점입니다. DB 커밋은 이미 끝났고, `redis.delete()`가 타임아웃으로 실패해도 트랜잭션은 되돌릴 수 없습니다. 재시도를 걸어도 프로세스가 그 사이 죽으면 그만입니다.

여기서 나오는 결론은 하나입니다. **TTL은 무효화의 대체재가 아니라 무효화가 실패했을 때의 백스톱입니다.** 무효화가 성공하는 한 TTL은 아무 일도 하지 않습니다. 실패한 순간에만 "최악의 경우 이만큼만 틀린다"는 상한이 됩니다. TTL 없이 명시적 무효화만 믿는 설계는, 한 번 어긋나면 **영구히** 어긋납니다.

그리고 무효화 실패는 반드시 로그와 메트릭으로 남겨야 합니다. 실패 카운터가 없으면 "언제부터 틀렸는지"를 아무도 모릅니다.

### 3-3. 지운 자리에 옛 값이 다시 채워지는 경합

`daily/day33-cache-strategy.md` 6절 마지막에서 짚은 순서입니다.

```
A(읽기)  미스 → DB에서 옛 값 읽음 ────────(지연)────────→ 캐시에 옛 값 기록
B(쓰기)              DB 커밋 → 캐시 DEL
```

B의 삭제가 A의 기록보다 먼저 끝나면 낡은 값이 TTL까지 남습니다. 이걸 줄이려고 흔히 쓰는 것이 **지연 이중 삭제(delayed double delete)** 입니다. 쓰기 직후 한 번 지우고, 수백 밀리초 뒤에 한 번 더 지웁니다. 두 번째 삭제가 A의 뒤늦은 기록을 걷어낸다는 발상입니다.

정직하게 쓰면 이렇습니다. **이건 확률을 낮출 뿐 보장하지 않습니다.** 지연 시간을 얼마로 잡아야 하는지에 대한 근거 있는 기준이 없고(A가 그보다 더 늦으면 그대로 실패합니다), 삭제가 두 배로 늘고, 두 번째 삭제를 실행할 스케줄러나 지연 큐가 필요합니다. 쓰기 직후 잠깐 미스가 늘어나는 대가도 있습니다.

<!-- TODO: 확인 필요 — 지연 이중 삭제의 대기 시간 산정 기준을 다룬 1차 자료(공식 문서·논문)를 찾지 못했습니다. 실무 블로그에서는 수백 ms를 흔히 쓰지만 근거 수치는 확인되지 않았습니다. -->

경합 자체를 없애고 싶다면 방향이 다릅니다. **2-4의 버전 키는 이 경합이 구조적으로 성립하지 않습니다.** A가 뒤늦게 기록하는 키는 이미 지난 세대의 키이고, 아무도 그 키를 읽지 않기 때문입니다. 그리고 "방금 내가 쓴 값을 반드시 봐야 하는" 화면이라면 그 요청만 캐시를 건너뛰고 DB를 읽는 편이 훨씬 싸게 끝납니다.

## 4. 어디서 지우는가 — 캐시 층은 하나가 아닙니다

```
브라우저 → CDN → API 게이트웨이 → 앱 인스턴스 로컬 캐시 → Redis → DB
```

각 층은 서로의 무효화를 모릅니다. Redis를 지웠다고 로컬 캐시가 지워지지 않고, 로컬 캐시를 지웠다고 CDN이 지워지지 않습니다. **"어디까지 지웠는가"를 모르면 원인 파악이 불가능해집니다.** 그래서 층을 늘리기 전에 그 층을 어떻게 무효화할지부터 정해야 합니다.

가장 까다로운 층은 앱 로컬 캐시(Caffeine, `ConcurrentHashMap`)입니다. 인스턴스가 10대면 무효화를 처리한 1대만 최신이고 나머지 9대는 옛 값을 그대로 서빙합니다. 로컬 캐시의 무효화는 **메모리 조작이 아니라 네트워크 문제**입니다.

Redis 6부터는 서버가 이 전파를 거들어 줍니다. `CLIENT TRACKING`입니다. 공식 문서가 설명하는 모드는 둘입니다.

- **기본 모드** — 서버가 각 클라이언트가 읽은 키를 무효화 테이블(invalidation table)에 기억해 두고, 그 키가 바뀌면 해당 클라이언트에만 알립니다. 필요한 클라이언트에만 가는 대신 **서버 메모리를 씁니다.** 테이블에 상한이 있어서, 가득 차면 서버가 바뀌지도 않은 키를 바뀐 척하고 무효화 메시지를 보내 자리를 회수합니다.
- **BCAST 모드** — 서버가 아무것도 기억하지 않고, 클라이언트가 `object:` 같은 **프리픽스를 구독**합니다. 서버 메모리는 0이지만 관심 없는 키의 알림까지 받습니다. 등록된 프리픽스가 많아지면 서버 CPU가 그만큼 듭니다.

무효화 메시지는 RESP3에서는 데이터와 같은 커넥션으로 push 메시지로 오고, RESP2에서는 `REDIRECT`로 지정한 별도 커넥션이 받습니다. 그리고 공식 문서가 직접 경고하는 함정이 하나 있습니다. **커넥션을 둘로 나누면 `GET` 응답보다 무효화 메시지가 먼저 도착할 수 있습니다.**

```
[데이터] 클라이언트 → 서버 : GET product:42
[무효화] 서버 → 클라이언트 : invalidate product:42   ← 누군가 그사이 바꿨습니다
[데이터] 서버 → 클라이언트 : "옛 값"                  ← 이걸 캐시에 넣으면 끝입니다
```

문서가 제시하는 해법은 **요청을 보내는 순간 로컬 캐시에 "채우는 중" 표식을 먼저 넣는 것**입니다. 무효화 메시지가 먼저 오면 그 표식이 지워지고, 나중에 도착한 응답은 표식이 없으므로 캐시에 넣지 않습니다. 커넥션이 하나면 순서가 보장되므로 이 문제 자체가 없습니다.

끊김 처리도 규칙으로 정해져 있습니다. **무효화 커넥션이 끊기면 로컬 캐시를 통째로 비웁니다.** 그 사이 놓친 무효화를 알 방법이 없기 때문입니다. 문서는 주기적으로 `PING`을 보내 살아 있는지 확인하고, 응답이 없으면 커넥션을 닫고 캐시를 버리라고 권합니다. 같은 이유로 **로컬 캐시에는 TTL이 없더라도 최대 TTL을 걸어두라**고 명시합니다.

정리하면 이렇습니다. 로컬 캐시의 무효화 전파는 **즉시 일관이 아니라 빠른 수렴**입니다. 그러니 로컬 캐시에 담을 것은 "잠깐 낡아도 되는 데이터"여야 합니다. 권한이나 잔액을 로컬 캐시에 담고 전파를 믿는 설계는 위험합니다.

## 5. 예제 — 목록 캐시를 가진 서비스

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional
public void rename(long productId, String newName) {
    Product product = productRepository.findById(productId).orElseThrow();
    product.rename(newName);

    redis.delete("product:v1:" + productId);                      // ❌ ① 상세만 지웁니다

    Set<String> listKeys = redis.keys("category:*");              // ❌ ② KEYS — 서버를 세웁니다
    redis.delete(listKeys);                                       // ❌ ③ 전 카테고리를 날립니다
}
```

**①** 목록·검색·배너 캐시는 그대로입니다. 상세 화면만 맞고 나머지는 틀립니다. **②** `keys()`는 `KEYS` 명령을 그대로 보냅니다. 공식 문서가 애플리케이션 코드에서 쓰지 말라고 한 그 명령이고, 도는 동안 모든 요청이 대기합니다. **③** 상품 하나 때문에 모든 카테고리 목록 캐시가 사라집니다. 직후 목록 요청이 전부 미스가 되어 DB로 몰립니다. 그리고 이 셋 모두 커밋 전에 실행됩니다(`daily/day33-cache-strategy.md` 5절).

### 5-2. 개선한 코드 ✔️

```java
@Transactional
public void rename(long productId, String newName) {
    Product product = productRepository.findById(productId).orElseThrow();
    product.rename(newName);
    events.publishEvent(new ProductRenamed(productId, product.getCategoryId()));
}
```

```java
@Component
public class ProductCacheInvalidator {

    private static final Logger log = LoggerFactory.getLogger(ProductCacheInvalidator.class);

    private final StringRedisTemplate redis;
    private final Counter invalidationFailures;

    public ProductCacheInvalidator(StringRedisTemplate redis, MeterRegistry meterRegistry) {
        this.redis = redis;
        this.invalidationFailures = meterRegistry.counter("cache.invalidation.failure");
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onRenamed(ProductRenamed event) {
        try {
            redis.delete("product:v1:" + event.productId());                  // 단건은 직접 삭제
            redis.opsForValue().increment("gen:category:" + event.categoryId());  // 목록은 세대 증가
        } catch (RuntimeException e) {
            // 실패해도 예외를 던지지 않습니다. TTL이 백스톱이고, 대신 반드시 셉니다
            log.warn("캐시 무효화 실패 productId={}", event.productId(), e);
            invalidationFailures.increment();
        }
    }
}
```

세 가지가 달라졌습니다. 무효화가 **커밋 이후로** 옮겨졌고, 목록은 스캔 없이 `INCR` 한 번으로 정리되며, 무효화 실패가 **요청을 깨뜨리지 않고 메트릭으로 남습니다.**

## 6. 실무에서 찾아보는 무효화 — Spring Cache의 `allEntries`

`@CacheEvict(allEntries = true)`는 편해 보입니다. Spring 레퍼런스도 항목을 하나씩 제거하는 것보다 **한 번의 연산으로 전부 제거하는 편이 훨씬 효율적**이라고 설명합니다. 그런데 이 "한 번의 연산"이 Redis에서 무엇이 되는지는 Spring Data Redis 쪽 문서를 봐야 합니다.

`allEntries = true`는 `RedisCache.clear()`를 부르고, 이는 와일드카드 패턴으로 캐시 라이터의 `clean()`을 호출합니다. 그리고 **Spring Data Redis의 기본 `BatchStrategy`는 `KEYS`입니다.** 레퍼런스가 "`KEYS`는 큰 키스페이스에서 성능 문제를 일으킬 수 있다"고 경고하며 `SCAN` 전략으로 바꾸는 법을 함께 안내합니다.

```java
@Bean
RedisCacheManager cacheManager(RedisConnectionFactory connectionFactory) {
    return RedisCacheManager
            .builder(RedisCacheWriter.nonLockingRedisCacheWriter(
                    connectionFactory, BatchStrategies.scan(1000)))
            .cacheDefaults(RedisCacheConfiguration.defaultCacheConfig()
                    .entryTtl(Duration.ofMinutes(10)))
            .build();
}
```

`SCAN` 전략은 Lettuce 드라이버에서 완전히 지원되고, Jedis는 클러스터가 아닌 모드에서만 지원한다는 제약이 문서에 명시돼 있습니다. 그리고 `nonLocking`이 기본이며, `lockingRedisCacheWriter`로 바꿔도 잠금은 **캐시 단위**이지 항목 단위가 아닙니다.

`@CacheEvict`의 타이밍 기본값도 다시 확인해 둘 만합니다. `beforeInvocation`은 `false`라 메서드가 정상 종료해야 제거됩니다. 다만 이건 **메서드 종료** 기준이지 **트랜잭션 커밋** 기준이 아닙니다. 커밋 기준이 필요하면 5-2처럼 `@TransactionalEventListener`로 내려야 합니다.

## 7. 함정

**함정 1 — 상세는 맞는데 목록이 틀립니다**
- **증상**: 상품명을 바꾸면 상세 페이지는 즉시 반영되는데 목록·검색 결과에는 옛 이름이 남습니다. TTL이 지나야 맞아집니다.
- **원인**: 무효화 대상을 단건 키로만 잡았습니다. 파생 캐시(목록, 집계, 배너)는 읽기 쪽에서 만들어진 키라 쓰기 쪽 코드에 목록이 없습니다.
- **해법**: 파생 캐시는 단건 삭제가 아니라 2-4의 세대 번호로 묶습니다. 새 캐시를 추가할 때 무효화 경로를 함께 추가하는 것을 리뷰 항목으로 둡니다.

**함정 2 — `allEntries = true`를 기본값처럼 씁니다**
- **증상**: 특정 API를 호출할 때마다 전체 응답 시간이 튀고, 직후 DB CPU가 치솟습니다.
- **원인**: 두 가지가 겹칩니다. Spring Data Redis 기본 전략인 `KEYS`가 서버를 블로킹하고, 캐시가 통째로 비워지면서 살아 있던 모든 키가 동시에 미스가 됩니다.
- **해법**: `BatchStrategies.scan(1000)`으로 바꾸고, 정말 전체를 날려야 하는 상황(배치 재적재 등)에만 씁니다. 평상시 무효화는 키 단위나 세대 번호로 처리합니다.

**함정 3 — 태그 인덱스가 먼저 만료돼 무효화가 빈손으로 끝납니다**
- **증상**: 무효화 코드가 예외 없이 실행되는데 낡은 값이 그대로 남습니다. 로그에는 아무 문제가 없습니다.
- **원인**: 태그 Set의 TTL이 캐시 값보다 짧습니다. `SMEMBERS`가 빈 집합을 돌려주고 `DEL`이 아무것도 못 지운 채 성공합니다.
- **해법**: 태그 Set의 TTL을 캐시 TTL보다 길게 잡습니다. 그리고 무효화가 **몇 개를 지웠는지**를 메트릭으로 남깁니다. 0건이 계속 나오면 그게 신호입니다.

**함정 4 — 무효화 이벤트가 유실됐는데 아무도 모릅니다**
- **증상**: 평소에는 잘 동작하다가 배포·네트워크 순단 직후에만 낡은 값이 남습니다. 재현이 안 됩니다.
- **원인**: keyspace notification이나 Pub/Sub 기반 전파를 주 채널로 썼습니다. Redis 공식 문서가 밝히듯 Pub/Sub은 fire and forget이라 구독자가 끊긴 동안의 이벤트는 사라집니다.
- **해법**: Pub/Sub 전파는 "빠르게 하는 수단"으로만 쓰고 정확성은 TTL에 맡깁니다. 로컬 캐시라면 무효화 커넥션이 끊겼을 때 캐시를 통째로 비웁니다. 정합성이 돈으로 직결되면 CDC처럼 재처리 가능한 채널을 씁니다.

**함정 5 — TTL을 빼고 무효화만 믿습니다**
- **증상**: 특정 키 몇 개가 며칠째 낡은 값을 서빙합니다. 다시 저장하면 고쳐집니다.
- **원인**: "무효화를 정확히 하니 TTL은 낭비"라고 판단했습니다. 무효화 호출이 한 번 실패한 순간(타임아웃, 프로세스 종료, 이벤트 유실) 그 키를 고칠 기회가 영원히 사라집니다.
- **해법**: 모든 캐시 항목에 TTL을 겁니다. 그 길이는 "이 데이터가 최악의 경우 얼마나 틀려도 되는가"로 정합니다. TTL을 정할 수 없다면 그 데이터는 캐시 대상이 아닙니다.

## 8. 참고자료

- [Client-side caching reference — Redis](https://redis.io/docs/latest/develop/reference/client-side-caching/) — 기본 모드와 BCAST 모드의 트레이드오프, 무효화 테이블 상한, RESP2 REDIRECT의 순서 경합과 placeholder 해법, 커넥션 유실 시 캐시 플러시 규칙
- [Redis keyspace notifications](https://redis.io/docs/latest/develop/pubsub/keyspace-notifications/) — Pub/Sub이 fire and forget이라는 점, `expired` 이벤트가 TTL 0 시점이 아니라 실제 삭제 시점에 발생한다는 점, 클러스터에서 노드별로 발생한다는 점
- [KEYS — Redis 명령 레퍼런스](https://redis.io/docs/latest/commands/keys/) — 애플리케이션 코드에서 쓰지 말라는 경고와 `SCAN`·Set 대안
- [Cache Annotations — Spring Framework 레퍼런스](https://docs.spring.io/spring-framework/reference/integration/cache/annotations.html) — `@CacheEvict`의 `allEntries`·`beforeInvocation` 동작, `@Caching`으로 여러 무효화 묶기
- [Redis Cache — Spring Data Redis 레퍼런스](https://docs.spring.io/spring-data/redis/reference/redis/redis-cache.html) — 기본 `BatchStrategy`가 `KEYS`라는 점, `BatchStrategies.scan(1000)` 설정, 드라이버별 지원 범위, locking/non-locking 캐시 라이터
- [Invalidate files to remove content — Amazon CloudFront 개발자 가이드](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Invalidation.html) — 자주 바뀌는 파일에는 무효화보다 버전 파일명을 권하는 이유(중간 캐시 미반영, 로그 분석, 롤백, 비용)
- 관련 문서: `daily/day33-cache-strategy.md`(읽기·쓰기 전략 선택과 삭제 vs 갱신), `daily/day36-log-design.md`(무효화 실패를 남기는 로그 설계)
