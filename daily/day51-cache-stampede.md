# 캐시가 만료되는 순간 DB가 죽는 이유 — 캐시 스탬피드

> 이 문서가 답할 질문: **키 하나가 만료된 그 순간에 왜 DB가 쓰러지고, 무엇으로 막아야 하는가?**
>
> 분류: 문제해결형(증상 → 원인 → 해법). 여러 출처가 공통으로 보고하는 증상이 명확합니다. "캐시 히트율은 멀쩡한데 DB CPU가 주기적으로 100%를 친다." 그 증상으로 가는 경로가 하나가 아니라는 점(만료·동시만료·캐시 소실·느린 재생성)을 축으로 조사했습니다.
>
> 기준: Redis 공식 명령 레퍼런스(`SET`), Spring Framework 캐시 레퍼런스, Spring Data Redis 레퍼런스, Caffeine 공식 위키, nginx `ngx_http_proxy_module` 문서를 교차 확인했습니다. 알고리즘은 Vattani·Chierichetti·Lowenstein의 PVLDB 8(8) 논문을 근거로 합니다.
>
> `daily/day33-cache-strategy.md`(읽기·쓰기 전략 선택), `daily/day39-cache-invalidation.md`(무효화 설계)와 경계가 있습니다. 이 문서는 **정상적으로 만료된 캐시를 다시 채우는 순간의 부하**만 다룹니다.

## 1. 핵심 개념 — 미스 1건이 N건이 되는 산수

캐시 스탬피드(cache stampede, thundering herd 또는 dog-piling)는 **인기 있는 캐시 항목이 사라진 순간 그 값을 동시에 재계산하려는 요청이 몰려 공유 자원을 고갈시키는 현상**입니다. Wikipedia의 Cache stampede 항목은 이를 "연쇄 장애(cascading failure)의 한 종류"로 분류합니다.

핵심은 아주 단순한 곱셈입니다. 같은 문서의 예를 그대로 옮기면, 렌더링에 3초가 걸리는 페이지에 초당 10건의 요청이 들어오는 경우 캐시가 만료된 뒤 약 30개의 프로세스가 **동시에** 같은 계산을 합니다.

```
동시 재계산 수 ≈ 재생성 시간(delta) × 요청 도착률
```

> 이게 왜 중요한가. 캐시를 붙인 이유는 보통 "그 쿼리가 3초 걸려서"입니다. 즉 **재생성이 비싼 키일수록 캐시를 붙이고, 재생성이 비쌀수록 스탬피드가 큽니다.** 캐시는 평소에 DB 부하를 99% 줄여주지만, 만료되는 순간 그 키에 대해서는 캐시가 없는 상태보다 **더 나쁩니다.** 캐시가 있었기 때문에 DB 커넥션 풀도, 인스턴스 수도 "캐시가 먹어주는 양"을 기준으로 잡혀 있기 때문입니다.
>
> 그리고 이 현상은 자기를 증폭합니다. 동시 쿼리 30개가 DB를 느리게 만들면 `delta`가 3초에서 8초로 늘고, 그러면 겹치는 요청이 80개가 됩니다. 커넥션 풀이 마르고, 커넥션을 기다리는 스레드가 쌓이고, 그 키와 무관한 API까지 타임아웃이 납니다. 캐시 한 칸이 빈 것에서 시작해 서비스 전체가 멈춥니다.

여기서 반드시 구분해야 할 것이 있습니다. 스탬피드는 **캐시가 느려진 문제가 아니라 미스가 직렬화되지 않은 문제**입니다. Redis를 더 키워도, 히트율을 1% 올려도 사라지지 않습니다. 고쳐야 하는 건 "미스가 났을 때 몇 명이 DB로 가는가"입니다.

## 2. 증상 — 이렇게 보입니다

실제로 마주쳤을 때의 모양은 꽤 특징적입니다.

1. **DB CPU·커넥션 사용량이 주기적으로 튑니다.** 주기가 TTL과 일치합니다. TTL이 10분이면 10분마다 뾰족한 산이 생깁니다.
2. **슬로우 쿼리 로그에 같은 쿼리가 수십 건씩 같은 타임스탬프로 찍힙니다.** 종류는 하나인데 개수가 많습니다.
3. **캐시 히트율 그래프는 거의 평평합니다.** 미스 몇 건이 전체 비율을 흔들지 못하므로 캐시 지표만 보면 아무 문제가 없어 보입니다.
4. **애플리케이션 쪽 증상은 커넥션 풀 타임아웃입니다.** 스택트레이스에는 캐시도 그 쿼리도 안 나오고, 커넥션을 못 받은 엉뚱한 API가 터집니다.
5. **부하 테스트에서 재현되지 않습니다.** 테스트는 보통 캐시를 미리 채운 뒤 돌리기 때문입니다.

4번과 5번이 디버깅을 어렵게 만듭니다. 원인 키는 하나인데 증상은 전혀 다른 곳에서 나오고, 재현 시나리오를 일부러 만들지 않으면 보이지 않습니다.

## 3. 방아쇠는 넷입니다 — 원인을 하나로 보면 해법을 잘못 고릅니다

### 3-1. 인기 키 한 개의 만료 (고전적인 경우)

메인 화면 랭킹처럼 **한 키에 트래픽이 집중된** 경우입니다. 1절의 곱셈이 그대로 적용됩니다.

### 3-2. 동시 만료 — 키 1만 개가 같은 초에 사라집니다

배포 직후, 또는 배치가 캐시를 한꺼번에 적재한 경우입니다. 모두 같은 코드 경로로 `TTL = 10분`을 받았으므로 **만료 시각까지 같아집니다.** 10분 뒤 1만 개가 동시에 미스가 됩니다. 이 경우는 키마다 부하가 작아도 총량으로 DB를 넘깁니다.

이 방아쇠의 해법은 다른 셋과 완전히 다릅니다. **TTL에 지터(jitter)를 섞어 만료 시각을 흩뜨리는 것**이고, 그게 거의 전부입니다. 가장 싸고 가장 자주 빠뜨리는 조치입니다.

### 3-3. 캐시가 통째로 비는 경우

Redis 재시작, `FLUSHALL`, 페일오버로 인한 승격, `maxmemory` 정책에 따른 대량 eviction, 또는 새 인스턴스 투입(스케일 아웃)으로 로컬 캐시가 빈 상태. 이때는 TTL이 무관합니다. **키가 만료된 게 아니라 존재하지 않습니다.**

이 구분이 중요한 이유는 뒤에서 다룰 해법 중 하나(확률적 조기 만료)가 **이 상황에서 아무 일도 하지 않기** 때문입니다. "만료 전에 미리 갱신한다"는 전략은 갱신할 대상이 남아 있어야 성립합니다.

### 3-4. 재생성이 느려서 겹치는 경우

`delta`가 곱셈의 한 변이므로, 재생성이 느려지면 트래픽이 그대로여도 스탬피드가 커집니다. 외부 API를 호출하는 캐시가 특히 위험합니다. 그 API가 평소 200ms에서 5초로 느려지면 동시 재계산 수가 25배가 됩니다.

## 4. 해법 A — 재계산을 한 명만 하게 만든다

### 4-1. 프로세스 안에서 합치기 (request coalescing)

같은 JVM 안의 스레드 30개가 같은 키를 재계산하는 건 막기 쉽습니다. Caffeine 공식 위키는 `Cache.get(key, mappingFunction)`을 권하며, 이것이 **값이 없으면 원자적으로 계산해 넣고, 있으면 기존 값을 돌려준다**고 설명합니다. 원자적이므로 같은 키의 계산은 한 번만 일어납니다.

Spring Cache에는 같은 목적의 스위치가 있습니다. `@Cacheable(sync = true)`입니다. Spring Framework 레퍼런스의 설명은 이렇습니다. 기본적으로 캐시 추상화는 **아무것도 잠그지 않아서** 같은 인자에 대해 메서드가 동시에 여러 번 실행될 수 있고(특히 기동 시점), `sync = true`를 주면 캐시 제공자에게 항목을 잠그도록 요청해 **한 스레드만 계산하고 나머지는 갱신될 때까지 블로킹**됩니다.

다만 문서가 붙여 둔 조건을 같이 읽어야 합니다.

- 선택 기능이라 **캐시 라이브러리가 지원하지 않을 수 있습니다.** `@Cacheable` Javadoc은 이것이 사실상 **힌트**이며 제공자가 실제로 동기화하지 않을 수도 있다고 명시합니다.
- 제약이 있습니다. `unless()`를 쓸 수 없고, 캐시를 하나만 지정할 수 있고, 다른 캐시 연산과 조합할 수 없습니다.

⚠️ 그리고 가장 중요한 한계는 문서에 쓰여 있지 않습니다. **이건 JVM 안의 잠금입니다.** 인스턴스가 20대면 DB 쿼리는 30개에서 20개로 줄 뿐입니다. 멀티 인스턴스 보호 장치로 착각하면 안 됩니다.

참고로 Redis에서 이 잠금의 단위도 확인해 둘 만합니다. Spring Data Redis 레퍼런스는 `RedisCacheManager`가 **락 없는(lock-free) 캐시 라이터를 기본값**으로 쓰고, `lockingRedisCacheWriter`로 바꿔도 **"잠금은 캐시 단위에 적용되며 캐시 항목 단위가 아니다"**라고 못 박습니다. `RedisCache.get(key, valueLoader)`가 인스턴스 전역 `ReentrantLock`을 쓴다는 이슈(#2890)는 3.4 M1(2024.1.0) 마일스톤으로 닫혔습니다.

<!-- TODO: 확인 필요 — 현재 버전의 RedisCache.get(key, Callable)이 키 단위 락으로 동작하는지는 레퍼런스·Javadoc에 설명이 없어 1차 자료로 확정하지 못했습니다. 버전별로 다르므로 쓰는 버전의 소스를 확인하는 편이 안전합니다. -->

### 4-2. 분산 락으로 넘기기

인스턴스 경계를 넘으려면 잠금이 Redis에 있어야 합니다. Redis `SET` 명령 레퍼런스가 직접 제시하는 패턴입니다. `SET resource-name <token> NX EX <max-lock-time>`이 성공한 클라이언트만 재계산하고, 나머지는 잠시 후 재시도합니다. 만료 시간이 있으므로 락을 잡은 프로세스가 죽어도 교착되지 않습니다.

문서가 같이 지시하는 두 가지를 지켜야 합니다. **값은 추측 불가능한 랜덤 토큰으로 두고, 해제는 `DEL`이 아니라 토큰이 일치할 때만 지우는 스크립트로 합니다.** 그러지 않으면 락이 만료된 뒤 뒤늦게 돌아온 클라이언트가 **다른 클라이언트의 락을 지웁니다.**

```java
private static final Duration LOCK_TTL = Duration.ofSeconds(10);
private static final RedisScript<Long> UNLOCK = RedisScript.of("""
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """, Long.class);

public String getRanking(String cacheKey) {
    String cached = redis.opsForValue().get(cacheKey);
    if (cached != null) {
        return cached;
    }

    String lockKey = "lock:" + cacheKey;
    String token = UUID.randomUUID().toString();
    boolean acquired = Boolean.TRUE.equals(
            redis.opsForValue().setIfAbsent(lockKey, token, LOCK_TTL));   // SET NX PX

    if (!acquired) {
        String stale = redis.opsForValue().get(cacheKey + ":stale");
        if (stale != null) {
            return stale;                         // 낡은 값으로 즉시 응답합니다
        }
        throw new RebuildInProgressException();    // 그것도 없으면 빠르게 실패합니다
    }

    try {
        long start = System.nanoTime();
        String value = rankingRepository.calculateTop100();
        rebuildTimer.record(System.nanoTime() - start, TimeUnit.NANOSECONDS);

        redis.opsForValue().set(cacheKey, value, Duration.ofMinutes(10));
        redis.opsForValue().set(cacheKey + ":stale", value, Duration.ofHours(1));
        return value;
    } finally {
        redis.execute(UNLOCK, List.of(lockKey), token);
    }
}
```

락을 못 잡은 요청의 선택지는 셋이고, 이게 설계 결정입니다.

| 대기자의 행동 | 사용자 경험 | 위험 |
|---|---|---|
| 재계산이 끝날 때까지 폴링 | 느리지만 정확 | **스레드·커넥션이 묶임** — 대기자가 많으면 이게 다음 장애 |
| 낡은 값 응답 | 빠름 | 낡음을 허용해야 함 |
| 즉시 실패(503) | 빠름 | 그 요청은 실패 |

⚠️ 첫 번째를 기본값으로 고르면 스탬피드를 DB에서 애플리케이션 스레드 풀로 **옮기는** 것에 그칠 수 있습니다. 폴링을 쓸 거면 반드시 대기 상한을 두고, 상한을 넘으면 실패시키거나 낡은 값으로 내려야 합니다.

그리고 Redis 레퍼런스는 이 `SET NX` 패턴에 대해 **더 강한 보장이 필요하면 Redlock 알고리즘을 쓰라고 권고**하면서 이 패턴 자체는 권장하지 않는다(discouraged)고 적어 두었습니다. 캐시 재생성에서는 락이 두 번 잡히면 DB 쿼리가 한 번 더 나가는 정도의 손해이므로 보통 이 단순한 형태로 충분합니다. 하지만 **"락이 깨지면 안 되는" 용도로 이 코드를 복사해 가면 안 됩니다**(`08-system-design/06-distributed-lock` 주제).

## 5. 해법 B — 만료되는 순간 자체를 없앤다 (확률적 조기 만료)

락은 "다 같이 미스가 난 뒤"를 정리합니다. 발상을 뒤집으면 **애초에 다 같이 미스가 나지 않게** 할 수 있습니다.

물리 TTL을 논리 만료 시각보다 길게 잡고, 각 요청이 **만료가 가까워질수록 커지는 확률로 자발적으로 미리 갱신**합니다. 모든 요청이 독립적으로 주사위를 던지므로 보통 한 요청만 먼저 갱신하고 나머지는 계속 캐시를 읽습니다. 미스가 0건이므로 대기도 0입니다.

Vattani·Chierichetti·Lowenstein이 PVLDB 8(8)에서 이 방식의 최적 알고리즘을 유도했고, XFetch로 알려져 있습니다. 판정식은 이렇습니다.

```
now - delta * beta * ln(rand(0,1)) >= expiry   →  지금 갱신한다
```

- `delta` — **지난번 재계산에 걸린 시간.** 값과 함께 저장합니다.
- `beta` — 조절 파라미터. 기본 1.0이고, 키우면 더 일찍 갱신합니다.
- `rand(0,1)` — 0과 1 사이 난수. `ln`이 음수이므로 좌변은 현재 시각을 미래로 밀어냅니다.

`delta`가 식에 들어가는 지점이 이 알고리즘의 핵심입니다. **재생성이 비싼 키일수록 더 일찍, 더 멀리 앞당겨 갱신합니다.** 3초 걸리는 키는 만료 몇 초 전부터 후보가 되고, 20ms 걸리는 키는 거의 만료 직전까지 아무 일도 하지 않습니다. TTL을 사람이 키마다 조정할 필요가 없어집니다.

```java
private static final double BETA = 1.0;
private static final Duration LOGICAL_TTL = Duration.ofMinutes(10);

public String getRanking(String cacheKey) {
    Map<String, String> entry = redis.<String, String>opsForHash().entries(cacheKey);
    if (entry.isEmpty()) {
        return recompute(cacheKey);                       // 진짜 미스
    }

    long delta = Long.parseLong(entry.get("delta"));
    long expiry = Long.parseLong(entry.get("expiry"));
    // nextDouble()은 [0,1)이므로 1.0 - x 로 (0,1] 을 만들어 ln(0) 을 피합니다
    double shift = delta * BETA * -Math.log(1.0 - ThreadLocalRandom.current().nextDouble());

    if (System.currentTimeMillis() + shift >= expiry) {
        return recompute(cacheKey);                       // 만료 전인데 자발적으로 갱신
    }
    return entry.get("value");
}

private String recompute(String cacheKey) {
    long start = System.currentTimeMillis();
    String value = rankingRepository.calculateTop100();
    long delta = System.currentTimeMillis() - start;

    redis.<String, String>opsForHash().putAll(cacheKey, Map.of(
            "value", value,
            "delta", String.valueOf(delta),
            "expiry", String.valueOf(System.currentTimeMillis() + LOGICAL_TTL.toMillis())));
    redis.expire(cacheKey, LOGICAL_TTL.multipliedBy(2));  // 물리 TTL은 논리보다 길게
    return value;
}
```

트레이드오프는 분명합니다. **확률이므로 보장이 아닙니다.** 동시성이 충분히 높으면 두 요청이 같은 순간에 갱신을 결정할 수 있습니다(그래도 30개가 아니라 1~2개입니다). 값이 논리 만료 직전 구간에서 조금 낡을 수 있고, `delta`를 저장하느라 값 구조가 복잡해집니다. 그리고 3-3을 다시 떠올려야 합니다. **캐시가 통째로 비면 이 알고리즘은 아무것도 하지 못합니다.**

## 6. 해법 C — 낡은 값을 돌려준다 (이미 검증된 설계)

이 선택지는 웹 서버가 수십 년째 쓰고 있습니다. nginx의 `ngx_http_proxy_module` 문서를 보면 스탬피드 대응이 네 개의 지시어로 정리돼 있습니다.

```nginx
proxy_cache_lock on;              # 새 캐시 항목은 한 번에 한 요청만 채웁니다 (기본 off)
proxy_cache_lock_timeout 5s;      # 대기 상한. 넘으면 업스트림으로 보내지만 응답은 캐시하지 않습니다
proxy_cache_lock_age 5s;          # 락 보유 요청이 이 시간 안에 못 끝내면 한 요청을 더 보냅니다
proxy_cache_use_stale updating;   # 갱신 중인 항목은 낡은 응답으로 내려줍니다
proxy_cache_background_update on; # 낡은 응답을 주면서 백그라운드로 갱신합니다
```

4절·5절에서 직접 구현한 것이 전부 들어 있습니다. `proxy_cache_lock`은 분산 락이고, `lock_timeout`은 대기 상한이며(1.7.8 이전에는 타임아웃된 응답도 캐시됐습니다), `lock_age`는 **락 보유자가 멈췄을 때 영원히 기다리지 않기 위한 탈출구**입니다. `use_stale updating`은 낡은 값 응답입니다.

애플리케이션 로컬 캐시에서 같은 모양을 쓰려면 Caffeine의 `refreshAfterWrite`가 있습니다. 공식 위키의 설명을 그대로 적으면 이렇습니다. 지정한 시간이 지나면 항목이 갱신 **대상이 되지만 타이머로 시작되지 않고 "항목이 조회될 때 비로소 갱신이 시작"**됩니다. 그리고 **"갱신되는 동안 이전 값이 계속 반환"**됩니다. 만료와 달리 항목을 제거하지 않으므로 `expireAfterWrite`와 함께 걸어 낡음의 상한을 둡니다. 위키는 갱신 대상이 된 뒤 아무도 조회하지 않으면 그대로 만료된다고 설명합니다.

```java
LoadingCache<Long, Ranking> cache = Caffeine.newBuilder()
        .refreshAfterWrite(Duration.ofMinutes(1))    // 1분 뒤부터 조회 시 백그라운드 갱신
        .expireAfterWrite(Duration.ofMinutes(10))    // 10분은 낡음의 절대 상한
        .maximumSize(10_000)
        .build(rankingRepository::findById);
```

`refreshAfterWrite`는 5절의 저렴한 사촌입니다. 확률 대신 고정 시점을 쓰고, 대기 대신 낡은 값을 씁니다. 대가는 하나입니다. **낡음을 허용할 수 없는 데이터에는 쓸 수 없습니다.**

## 7. 무엇을 고르는가

| 해법 | 미스 시 DB 쿼리 | 사용자 대기 | 낡음 | 인스턴스 경계 | 캐시가 빈 상태에 효과 |
|---|---|---|---|---|---|
| 없음 | `delta` × 요청률 | 재계산 시간 | 없음 | — | 최악 |
| TTL 지터 | 변화 없음 | 변화 없음 | 없음 | 넘음 | 없음(동시 만료만 해결) |
| 프로세스 내 coalescing | 인스턴스 수 | 재계산 시간 | 없음 | **못 넘음** | 인스턴스 수만큼 |
| 분산 락 + 대기 | 1 | 재계산 시간 | 없음 | 넘음 | 있음 |
| 분산 락 + 낡은 값 | 1 | 거의 없음 | 있음 | 넘음 | 낡은 값이 없으면 무효 |
| 확률적 조기 만료 | 1~2 | 없음 | 조금 | 넘음 | **없음** |

결정 순서는 이렇게 잡습니다.

1. **TTL 지터는 조건 없이 먼저 넣습니다.** 한 줄이고 3-2를 없앱니다.
2. 재생성이 수십 ms 수준이고 트래픽이 낮으면 **거기서 멈춥니다.** 스탬피드 대응은 전부 복잡도 비용을 청구합니다.
3. 인스턴스가 1대거나 재생성 비용이 중간이면 **프로세스 내 coalescing**으로 충분합니다.
4. 인기 키가 소수이고 재생성이 비싸면 **확률적 조기 만료**가 가장 값싼 보호입니다. 대기가 0이고 조정 파라미터가 사실상 없습니다.
5. 재시작·페일오버·스케일 아웃까지 버텨야 하면 **락이 필수**입니다. 확률적 조기 만료는 여기서 아무 일도 하지 않습니다.
6. 낡은 값을 쓸 수 있는가가 마지막 갈림길입니다. 쓸 수 있으면 대기를 없앨 수 있고, 못 쓰면 대기 상한을 설계해야 합니다.

## 8. 예제 — 메인 랭킹 캐시

### 8-1. 클린하지 않은 코드 ❌

```java
public String getRanking() {
    String cached = redis.opsForValue().get("ranking:top100");
    if (cached != null) {
        return cached;
    }
    String value = rankingRepository.calculateTop100();          // ❌ ① 전원이 여기로 옵니다
    redis.opsForValue().set("ranking:top100", value, Duration.ofMinutes(10));  // ❌ ② 고정 TTL
    return value;
}
```

**①** 미스가 난 모든 요청이 재계산합니다. 교과서에 나오는 Cache-Aside 그대로인데, 교과서가 생략한 것이 바로 이 줄의 동시성입니다. **②** TTL이 상수라 같은 배치로 채운 키들이 같은 초에 만료됩니다. 그리고 `calculateTop100()`이 빈 결과를 돌려주는 경우 `null`이나 빈 문자열을 캐시하지 않으므로 **영원히 미스가 반복됩니다.**

### 8-2. 개선한 코드 ✔️

```java
private final AsyncLoadingCache<String, String> local = Caffeine.newBuilder()
        .refreshAfterWrite(Duration.ofSeconds(30))
        .expireAfterWrite(Duration.ofMinutes(2))
        .buildAsync((key, executor) ->
                CompletableFuture.supplyAsync(() -> loadWithRedisLock(key), executor));

public CompletableFuture<String> getRanking() {
    return local.get("ranking:top100");     // 같은 JVM의 동시 요청은 여기서 하나로 합쳐집니다
}

private String loadWithRedisLock(String cacheKey) {
    // 4-2의 코드. TTL에는 지터를 섞습니다
    Duration ttl = Duration.ofMinutes(10)
            .plusSeconds(ThreadLocalRandom.current().nextInt(120));
    // ... 생략 (락 획득 → 재계산 → set(cacheKey, value, ttl) → 토큰 비교 해제)
    return value;
}
```

두 단으로 막습니다. **같은 JVM의 요청은 로컬 캐시가 합치고, 인스턴스 사이의 요청은 Redis 락이 합칩니다.** 그래서 인스턴스가 20대여도 DB 쿼리는 1건입니다. `refreshAfterWrite`가 갱신을 백그라운드로 보내므로 사용자는 락 대기를 거의 보지 않고, TTL 지터가 동시 만료를 흩뜨립니다.

## 9. 함정

**함정 1 — 락 TTL이 재계산 시간보다 짧습니다**
- **증상**: 락을 걸었는데도 느린 시간대에만 DB 쿼리가 여러 건 나갑니다. 평소에는 1건입니다.
- **원인**: 락 TTL 5초, 재계산 8초. 락이 먼저 만료되므로 다음 요청이 락을 새로 잡고 또 계산합니다. 더 나쁜 건 먼저 끝난 요청이 **남의 락을 지우는** 것입니다.
- **해법**: 락 TTL을 재계산 시간의 p99보다 넉넉하게 잡고, 재계산 소요 시간을 메트릭으로 남겨 추적합니다. 해제는 반드시 토큰 비교 Lua 스크립트로 합니다(Redis `SET` 문서가 지시하는 그대로).

**함정 2 — 스탬피드를 DB에서 스레드 풀로 옮겼습니다**
- **증상**: DB CPU 스파이크는 사라졌는데 같은 시각에 서비스 전체가 응답하지 않습니다. 스레드 덤프에 `sleep`이나 폴링 대기가 가득합니다.
- **원인**: 락을 못 잡은 요청을 전부 폴링으로 대기시켰습니다. 요청 스레드와 커넥션이 재계산 시간만큼 점유됩니다.
- **해법**: 대기에 상한을 둡니다. nginx가 `proxy_cache_lock_timeout`(기본 5초)과 `proxy_cache_lock_age`를 둔 이유와 같습니다. 상한을 넘으면 낡은 값이나 503으로 내려보냅니다.

**함정 3 — TTL이 모든 키에서 같은 상수입니다**
- **증상**: 배포 후 정확히 TTL만큼 지난 시점에 DB가 한 번 크게 튑니다. 그 뒤로는 점점 퍼지면서 잦아듭니다.
- **원인**: 캐시를 한꺼번에 채웠고 TTL이 상수라 만료 시각이 전부 같습니다.
- **해법**: `TTL + random(0, TTL × 0.2)` 형태로 지터를 섞습니다. 비용이 거의 0인 유일한 대책입니다.

**함정 4 — 빈 결과를 캐시하지 않아 미스가 영구화됩니다**
- **증상**: 특정 키에 대해 캐시 히트가 한 번도 안 생기고 DB 쿼리가 요청 수만큼 나갑니다. 존재하지 않는 ID로 오는 트래픽에서 두드러집니다.
- **원인**: 조회 결과가 없으면 캐시에 아무것도 넣지 않았습니다. 다음 요청도 미스이므로 캐시가 전혀 작동하지 않습니다.
- **해법**: "없음"도 짧은 TTL로 캐시합니다(negative caching). Spring Cache라면 `@Cacheable`의 `unless` 조건을 과하게 걸지 않았는지 확인합니다. 단, `sync = true`와 `unless`는 함께 쓸 수 없다는 제약을 레퍼런스가 명시합니다.

**함정 5 — `sync = true`를 멀티 인스턴스 보호로 믿습니다**
- **증상**: 스테이징(1대)에서는 완벽히 동작하다가 프로덕션(20대)에서 DB 쿼리가 20건 나갑니다.
- **원인**: `sync`는 캐시 제공자에게 보내는 **힌트**이고 동작 범위는 JVM입니다. Spring Data Redis 레퍼런스는 Redis 쪽 잠금조차 **캐시 단위이며 항목 단위가 아니라고** 명시합니다.
- **해법**: 인스턴스 경계를 넘는 보호가 필요하면 Redis 락이나 확률적 조기 만료를 씁니다. 프로세스 내 coalescing은 그 앞단에 두는 1차 방어로만 셉니다.

**함정 6 — 확률적 조기 만료를 넣고 재시작 시나리오를 잊습니다**
- **증상**: 평상시 DB 부하는 매끄러운데 Redis 페일오버나 전면 배포 직후에만 과거와 똑같은 스파이크가 재현됩니다.
- **원인**: 조기 만료는 "만료가 가까운 값이 캐시에 있을 때" 동작합니다. 캐시가 비면 모든 요청이 그냥 미스입니다(3-3).
- **해법**: 조기 만료와 락을 함께 씁니다. 평상시엔 조기 만료가 미스를 0으로 만들고, 진짜 미스에서는 락이 1건으로 줄입니다. 배포 전 캐시 워밍업 절차를 두는 것도 같은 문제에 대한 답입니다.

## 10. 참고자료

- [Cache stampede — Wikipedia](https://en.wikipedia.org/wiki/Cache_stampede) — 연쇄 장애로서의 정의, 3초 렌더링 × 초당 10요청 ≈ 30개 동시 재계산 예시, XFetch 판정식과 변수 정의
- [Optimal Probabilistic Cache Stampede Prevention — PVLDB 8(8):886–897 (2015)](https://doi.org/10.14778/2757807.2757813) — Vattani·Chierichetti·Lowenstein. 확률적 조기 만료의 최적 알고리즘 유도
- [SET — Redis 명령 레퍼런스](https://redis.io/docs/latest/commands/set/) — `NX`·`PX` 옵션, `SET key token NX EX` 락 패턴, 토큰 비교 Lua 해제 스크립트, Redlock 권고
- [Cache Annotations — Spring Framework 레퍼런스](https://docs.spring.io/spring-framework/reference/integration/cache/annotations.html) — 기본적으로 아무것도 잠그지 않는다는 점, `sync = true`의 동작과 제약
- [Redis Cache — Spring Data Redis 레퍼런스](https://docs.spring.io/spring-data/redis/reference/redis/redis-cache.html) — lock-free가 기본값이라는 점, 잠금이 캐시 단위이며 항목 단위가 아니라는 점
- [Refresh / Population — Caffeine 위키](https://github.com/ben-manes/caffeine/wiki/Refresh) — `refreshAfterWrite`가 조회 시점에 시작되고 갱신 중 이전 값을 반환한다는 점, `expireAfterWrite`와의 조합
- [ngx_http_proxy_module — nginx 문서](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache_lock) — `proxy_cache_lock`, `proxy_cache_lock_timeout`(기본 5s), `proxy_cache_lock_age`, `proxy_cache_use_stale updating`, `proxy_cache_background_update`
- 관련 문서: `daily/day33-cache-strategy.md`(읽기·쓰기 전략), `daily/day39-cache-invalidation.md`(무효화 설계), `daily/day45-local-cache.md`(로컬 캐시의 일관성 비용)
