# 한 키에 트래픽이 몰릴 때 — 핫키는 왜 샤드를 늘려도 안 풀리는가

## 1. 핵심 개념

**핫키(hot key)** 는 전체 요청 중 불균형하게 큰 비율이 **키 하나**로 몰리는 상태입니다. 타임세일 상품 하나, 메인 화면에 박힌 공지 하나, 전역 설정 하나. 키 개수는 수천만 개인데 트래픽은 그중 한 개에 쏠립니다.

> 핫키가 있으면 샤드를 늘려도 지연이 안 내려갑니다. 노드를 2배로 늘리고 리샤딩까지 끝냈는데 특정 노드 하나만 CPU 100%, 나머지는 한가합니다. **키 하나의 처리 한도는 노드 하나의 한도**이고, 수평 확장은 그 한도를 건드리지 못합니다.

이 문서는 하나의 질문에 답합니다. **키 하나에 트래픽이 몰리면 무엇이 먼저 터지고, 무엇으로 푸는가.**

## 2. 왜 샤드를 늘려도 안 풀리는가

### 2-1. 키 이름이 같으면 노드가 같습니다

Redis Cluster는 키를 **해시 슬롯**에 배정합니다. 슬롯은 16384개이고, 키의 슬롯은 `CRC16(key) % 16384`입니다. 각 노드는 슬롯의 일부 구간을 소유합니다([Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)).

```
키 이름 → CRC16 → 슬롯 번호 → 그 슬롯을 가진 노드 1개
```

이 경로에 요청량은 들어가지 않습니다. 슬롯 배정은 **키 이름만** 보고 결정됩니다. 그래서 `product:9281`이 뜨거우면 그 키는 영원히 같은 슬롯, 같은 노드로 갑니다.

리샤딩은 슬롯을 노드 사이에서 옮기는 작업입니다. 핫 슬롯은 통째로 옮겨가므로, 리샤딩 후에 아픈 노드만 바뀌고 증상은 그대로입니다. 샤드를 늘려서 분산되는 것은 **키가 많을 때의 트래픽**이지, 키 하나의 트래픽이 아닙니다.

### 2-2. 그 노드는 코어 하나로 명령을 처리합니다

공식 문서는 이렇게 씁니다. Redis는 "명령 실행 관점에서 대체로 단일 스레드 서버이며, 여러 CPU 코어로부터 이득을 보도록 설계되지 않았다"([Redis benchmark](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/)). 최신 버전이 I/O에 스레드를 쓰더라도 명령 자체는 한 줄로 처리됩니다.

그래서 한 노드에 쏠린 요청은 **큐**가 됩니다. 평균 지연은 멀쩡해 보이는데 p99가 먼저 무너지는 이유입니다.

### 2-3. 천장이 CPU가 아닐 수도 있습니다

같은 문서는 "많은 실제 상황에서 Redis 처리량은 CPU보다 네트워크에서 먼저 한계에 걸린다"고 명시합니다. 핫키는 값이 클 때 특히 네트워크로 먼저 터집니다.

산수로 확인해봅니다. 값이 20KB인 상품 JSON을 초당 50,000번 읽으면 나가는 바이트는 `20KB × 50,000 = 1GB/s`, 즉 약 **8Gbps**입니다. 인스턴스 네트워크 대역폭을 넘기면 CPU가 한가해도 타임아웃이 납니다. 값 크기를 줄이는 것만으로도 같은 QPS를 버티는 경우가 여기서 나옵니다.

AWS도 같은 이야기를 합니다. 리스트·스트림·셋 같은 다차원 자료구조는 키 하나에 들어 있으므로 노드 하나에 올라가고, 큰 키 하나가 그 노드의 네트워크 용량과 메모리를 불균형하게 쓸 수 있다고 설명합니다([ElastiCache Well-Architected Lens, PE 2](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/PerformanceEfficiencyPillar.html)).

## 3. 핫키인지 확인하는 법

### 3-1. 증상으로 좁히기

| 보이는 것 | 핫키 의심 |
|---|---|
| 노드별 CPU·네트워크 편차가 큼 (한 노드만 높음) | 강함 |
| p99는 올라가는데 캐시 적중률은 정상 | 강함 |
| 적중률이 같이 떨어지고 DB 부하가 동시에 뜀 | 핫키보다 **스탬피드** (`daily/day51-cache-stampede.md`) |
| 메모리·`SLOWLOG`가 같이 튐 | 핫키보다 **빅키** (O(N) 명령) |

여기서 가장 자주 놓치는 것이 첫 줄입니다. 클러스터 **평균** CPU는 정상입니다. 노드별로 쪼개서 봐야 보입니다(`daily/day54-golden-signals.md`).

### 3-2. `--hotkeys`

`redis-cli --hotkeys`는 키 공간을 샘플링해 뜨거운 키를 보고합니다. 공식 옵션 설명은 한 줄입니다. "`maxmemory-policy`가 `*lfu`일 때만 동작합니다"([redis-cli](https://redis.io/docs/latest/develop/tools/cli/)). AWS도 LFU 정책이 걸려 있을 때 `valkey-cli --hotkeys`로 핫키를 찾을 수 있다고 안내합니다(PE 2).

읽는 값이 무엇인지 알고 봐야 합니다. LFU 카운터는 정확한 호출 횟수가 아니라 **Morris 카운터** 기반 확률적 근사이고, 범위는 0~255이며, 기본 설정은 "약 100만 요청에서 포화, 1분마다 감쇠"입니다(`lfu-log-factor 10`, `lfu-decay-time 1` — [Key eviction](https://redis.io/docs/latest/develop/reference/eviction/)).

그래서 `--hotkeys`는 **꾸준히 뜨거운 키**를 찾는 도구입니다. 30초짜리 트래픽 폭주는 포화와 감쇠에 묻혀 잘 안 보입니다.

### 3-3. `MONITOR`는 샘플링으로만

`MONITOR`는 모든 명령을 흘려주므로 키 분포를 직접 셀 수 있습니다. 대가가 명시돼 있습니다. 공식 문서의 벤치마크에서 `MONITOR` 클라이언트 하나를 붙였을 때 GET 처리량이 **104,275 → 45,330 req/s**로 떨어졌고, 문서는 "단일 `MONITOR` 클라이언트가 처리량을 50% 이상 떨어뜨릴 수 있다"고 적습니다([MONITOR](https://redis.io/docs/latest/commands/monitor/)).

이미 아픈 노드에 붙일 도구가 아닙니다. 붙여야 한다면 복제본에, 짧게, 한 개만.

### 3-4. 가장 믿을 만한 쪽은 애플리케이션

캐시를 조회하는 지점은 어차피 내 코드입니다. 거기서 세면 LFU 근사도, `MONITOR` 비용도 필요 없습니다.

```java
@Component
public class CacheKeySampler {

    private static final int SAMPLE_RATE = 100;  // 100건 중 1건만 집계
    private final ConcurrentHashMap<String, LongAdder> counters = new ConcurrentHashMap<>();
    private final AtomicLong seq = new AtomicLong();

    public void record(String cacheKey) {
        if (seq.incrementAndGet() % SAMPLE_RATE != 0) {
            return;
        }
        counters.computeIfAbsent(cacheKey, key -> new LongAdder()).increment();
    }

    @Scheduled(fixedRate = 60_000)
    public void reportTop10() {
        counters.entrySet().stream()
                .sorted(Map.Entry.comparingByValue(Comparator.comparingLong(LongAdder::sum).reversed()))
                .limit(10)
                .forEach(entry -> log.info("hotkey candidate key={} sampled={}",
                        entry.getKey(), entry.getValue().sum()));
        counters.clear();
    }
}
```

의심되는 키가 나왔으면 `CLUSTER KEYSLOT product:9281`로 슬롯을 구하고, 그 슬롯의 소유 노드가 아픈 노드와 같은지 맞춰봅니다. 같으면 확정입니다.

## 4. 읽기 핫키 — 네 가지 해법

읽기 핫키는 **요청이 노드에 도달하기 전에 줄이는 것**이 본질입니다. 비용이 싼 순서로 봅니다.

### 4-1. 로컬 캐시 — 가장 효과가 큰 수단

앱 인스턴스 안에 1초 TTL 캐시를 두면, 노드가 받는 요청은 `인스턴스 수 × 1 req/s`가 됩니다. 인스턴스 40대라면 초당 5만 요청이 **초당 40 요청**이 됩니다. 핫키일수록 효과가 큽니다. 같은 키를 다 같이 읽기 때문입니다.

대가는 **낡음**입니다. TTL 1초면 최대 1초 묵은 값을 보여주기로 합의한 겁니다. "이 데이터가 몇 초까지 낡아도 되는가"에 숫자로 답할 수 없으면 쓰면 안 됩니다. 구현과 트레이드오프는 `daily/day45-local-cache.md`에 있습니다.

### 4-2. 클라이언트 사이드 캐싱 — 서버가 무효화를 알려줍니다

TTL로 낡음을 감수하는 대신, Redis가 **tracking** 으로 해결해줍니다. 서버가 각 커넥션이 읽은 키를 기억하고, 그 키가 바뀌면 해당 커넥션들에 무효화 메시지를 보냅니다. 클라이언트는 그때 로컬 복사본을 버립니다([Client-side caching](https://redis.io/docs/latest/develop/clients/client-side-caching/)).

공식 문서가 그대로 경고하는 함정이 하나 있습니다. **자주 바뀌는 데이터에는 쓰지 말라**는 것입니다. 카운터나 점수판처럼 갱신이 잦으면 무효화 메시지 비용이 캐싱 이득보다 커지므로, 그런 데이터는 캐싱을 끈 **별도 커넥션**으로 다루라고 권합니다.

주의할 점은 지원 범위입니다. 공식 문서의 지원 클라이언트 표에는 `redis-py` 5.1.0, `Jedis` 5.2.0, `node-redis` 5.1.0, `go-redis` 9.22.0이 올라 있습니다. **Lettuce는 이 표에 없습니다.** 그리고 문서는 "일부 클라이언트가 `CLIENT TRACKING` 명령을 지원하는 것이 곧 클라이언트 사이드 캐싱 기능을 지원한다는 뜻은 아니다"라고 못을 박습니다. Spring Boot 기본 조합(Lettuce)에서 쓰려면 지원 여부를 먼저 확인해야 합니다.

<!-- TODO: Lettuce의 클라이언트 사이드 캐싱 지원 여부를 Lettuce 릴리스 노트로 재확인 필요. 위 표는 redis.io 기준이며 Lettuce 미등재. -->

### 4-3. 복제본으로 읽기 — 읽기 전용에 한정

Redis Cluster에서 복제본은 기본적으로 마스터로 리다이렉트합니다. 커넥션에서 `READONLY`를 보내면 그 커넥션은 "낡은 데이터를 읽을 의향이 있고 쓰기는 하지 않겠다"고 선언하고, 복제본이 직접 응답합니다([READONLY](https://redis.io/docs/latest/commands/readonly/)).

Spring Data Redis는 `readFrom`으로 전략을 지정합니다.

```java
@Configuration
class ReadFromReplicaConfig {

    @Bean
    LettuceConnectionFactory redisConnectionFactory() {
        LettuceClientConfiguration clientConfig = LettuceClientConfiguration.builder()
                .readFrom(ReadFrom.REPLICA_PREFERRED)
                .build();

        RedisStandaloneConfiguration serverConfig =
                new RedisStandaloneConfiguration("cache.internal.example.com", 6379);

        return new LettuceConnectionFactory(serverConfig, clientConfig);
    }
}
```

한계가 둘입니다. **쓰기 핫키에는 아무 효과가 없습니다.** 쓰기는 전부 마스터 한 대로 갑니다. 그리고 복제는 비동기이므로 방금 쓴 값이 안 읽힐 수 있습니다. 읽은 직후 그 값으로 분기하는 코드가 있으면 못 씁니다.

<!-- TODO: `LettuceClientConfiguration.readFrom`을 `RedisClusterConfiguration`과 함께 쓸 때의 동작은 Spring Data Redis 레퍼런스에 명시돼 있지 않음. 클러스터 환경에서 쓰기 전 Javadoc 확인 필요. -->

### 4-4. 키 분할 — 한 키를 N개로 복제

위 세 개로 안 되면(로컬 캐시를 못 쓰는 일관성 요구, 쓰기도 많은 키) 키 이름 자체를 쪼갭니다. 같은 값을 `product:9281#0` … `product:9281#7`로 저장하고, 읽을 때 무작위로 하나를 고릅니다. 키 이름이 다르면 슬롯이 다르고, 슬롯이 다르면 노드가 분산됩니다.

```java
@Service
public class HotProductCache {

    private static final int FANOUT = 8;
    private final StringRedisTemplate redis;

    public String read(long productId) {
        int shard = ThreadLocalRandom.current().nextInt(FANOUT);
        return redis.opsForValue().get(key(productId, shard));
    }

    public void write(long productId, String payload, Duration ttl) {
        for (int shard = 0; shard < FANOUT; shard++) {
            redis.opsForValue().set(key(productId, shard), payload, ttl);
        }
    }

    private String key(long productId, int shard) {
        return "product:" + productId + "#" + shard;
    }
}
```

AWS는 이 방식을 권하면서 조건을 같이 적습니다. 핫키를 여러 노드에 복제하는 것은 **클라이언트가 해야 하는 일**이고, 서버가 대신 해주지 않으며, 읽을 키 이름 목록을 애플리케이션이 관리해야 한다는 것입니다(PE 2).

대가가 분명합니다. 쓰기가 N배, 무효화도 N번, 그리고 N개 복사본이 일시적으로 서로 다를 수 있습니다. 쓰기 중간에 읽은 요청은 누군가는 새 값, 누군가는 옛 값을 봅니다.

## 5. 쓰기 핫키 — 카운터를 쪼갭니다

읽기 해법은 전부 쓰기 핫키에 무용합니다. 조회수·재고·좋아요처럼 `INCR` 하나에 몰리는 경우는 접근이 달라집니다. 키를 N개로 쪼개고 **읽을 때 합산**합니다.

```java
@Service
public class ViewCounter {

    private static final int BUCKETS = 16;
    private final StringRedisTemplate redis;

    public void increase(long articleId) {
        int bucket = ThreadLocalRandom.current().nextInt(BUCKETS);
        redis.opsForValue().increment("views:" + articleId + ":" + bucket);
    }

    public long total(long articleId) {
        List<String> keys = IntStream.range(0, BUCKETS)
                .mapToObj(bucket -> "views:" + articleId + ":" + bucket)
                .toList();

        return redis.opsForValue().multiGet(keys).stream()
                .filter(Objects::nonNull)
                .mapToLong(Long::parseLong)
                .sum();
    }
}
```

쓰기는 16개 슬롯으로 흩어지고, 읽기는 16번 조회를 합산합니다. 조회수처럼 **쓰기가 읽기보다 훨씬 많은** 지표에 맞는 교환입니다. 반대로 읽기가 많으면 읽기 쪽이 16배 비싸지므로 손해입니다.

클러스터에서는 `MGET` 키들이 서로 다른 슬롯에 있으면 단일 명령으로 못 보냅니다. 클라이언트가 노드별로 쪼개 보내므로 왕복이 늘어납니다. 합산 결과 자체를 1초 TTL로 캐싱하는 편이 보통 낫습니다.

## 6. 무엇을 고를 것인가

| 상황 | 첫 수단 |
|---|---|
| 읽기 쏠림, 1초 낡음 허용 | 로컬 캐시 |
| 읽기 쏠림, 낡음 불허 | 클라이언트 사이드 캐싱 (지원 클라이언트 확인) |
| 읽기 쏠림, 복제본 여유 있음 | `READONLY` / `readFrom` |
| 읽기 쏠림, 위 셋 다 불가 | 키 분할 |
| 쓰기 쏠림 | 카운터 샤딩 |
| 값이 20KB 이상 | 먼저 값 크기를 줄입니다 |

마지막 줄이 실제로 가장 자주 먹히는 수단입니다. 네트워크가 천장이면 QPS를 줄이는 것과 바이트를 줄이는 것이 같은 효과입니다.

## 7. 함정

### 7-1. 키를 쪼갰는데 전부 같은 노드에 남습니다

- **증상**: `product:9281#0~#7`로 분할 배포했는데 노드 CPU 편차가 그대로입니다.
- **원인**: 키에 해시태그가 들어 있습니다. 중괄호가 있으면 Redis는 **중괄호 안만** 해시합니다. `{product:9281}#0`과 `{product:9281}#7`은 해시태그가 같으므로 **같은 슬롯**입니다([Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)). 멀티키 연산을 위해 붙여둔 해시태그가 분산을 무력화합니다.
- **해법**: 분할 접미사를 해시태그 **안**에 넣습니다 (`{product:9281#3}`). 배포 전 `CLUSTER KEYSLOT`으로 분할 키들의 슬롯이 실제로 갈라지는지 확인합니다.

### 7-2. 핫키를 찾으려고 축출 정책을 바꿉니다

- **증상**: `--hotkeys`를 쓰려고 프로덕션에서 `maxmemory-policy`를 `allkeys-lfu`로 바꿨더니, 며칠 뒤 캐시 적중률이 달라지고 예상 못 한 키가 사라집니다.
- **원인**: `maxmemory-policy`는 진단 스위치가 아니라 **축출 정책**입니다. LRU에서 LFU로 바꾸면 메모리가 찼을 때 버려지는 키가 달라집니다. 게다가 `volatile-*` 정책은 TTL 없는 키를 축출 대상에서 제외하므로, `volatile-lru` → `allkeys-lfu` 변경은 축출 대상 집합 자체를 바꿉니다([Key eviction](https://redis.io/docs/latest/develop/reference/eviction/)).
- **해법**: 먼저 애플리케이션 샘플링(3-4)으로 찾습니다. 그래도 필요하면 복제본이나 스테이징에서 정책을 바꿔 측정합니다. 운영 마스터의 정책 변경은 캐시 동작 변경으로 취급하고 되돌릴 계획을 같이 세웁니다.

### 7-3. 로컬 캐시로 가렸는데 배포할 때마다 터집니다

- **증상**: 로컬 캐시 적용 후 평시에는 조용한데, 롤링 배포 중에 핫키 노드가 다시 100%를 칩니다.
- **원인**: 로컬 캐시는 프로세스 메모리입니다. 새 인스턴스가 뜨면 비어 있고, 같은 핫키를 동시에 조회합니다. 핫키는 정의상 모든 인스턴스가 같은 키를 찾으므로, 배포 순간이 가장 위험합니다.
- **해법**: 로컬 캐시 미스 지점에도 재계산 제한(키별 단일 비행)을 둡니다. 롤링 배포 간격을 벌려 동시 기동 수를 줄입니다. 원리는 `daily/day51-cache-stampede.md`와 같습니다 — 방아쇠만 만료가 아니라 **기동**입니다.

### 7-4. 복제본 읽기로 해결했다고 판단합니다

- **증상**: `readFrom`을 적용하고 지연이 내려갔는데, 몇 주 뒤 같은 증상이 다시 납니다.
- **원인**: 복제본은 **읽기만** 흡수합니다. 쓰기 비중이 커지면 마스터 한 대가 다시 천장이 됩니다. 쓰기가 늘어나는 변화(집계 저장, 세션 갱신 추가)는 조용히 들어옵니다.
- **해법**: 노드별 지표를 **마스터와 복제본으로 나눠** 봅니다. 마스터 CPU만 오르면 읽기 해법은 더 쌓아도 소용없다는 뜻이고, 그때부터는 5절(쓰기 분할)이나 값 크기 쪽을 봅니다.

## 8. 참고자료

- [Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/) — 해시 슬롯, `CRC16 % 16384`, 해시태그
- [Redis benchmark](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/) — 명령 실행의 단일 스레드 성격, 네트워크가 먼저 한계가 되는 점
- [Key eviction](https://redis.io/docs/latest/develop/reference/eviction/) — LFU 근사 카운터와 `lfu-log-factor` / `lfu-decay-time`
- [redis-cli](https://redis.io/docs/latest/develop/tools/cli/) — `--hotkeys`, `--bigkeys`, `--stat`
- [MONITOR](https://redis.io/docs/latest/commands/monitor/) — 처리량 비용 벤치마크
- [Client-side caching introduction](https://redis.io/docs/latest/develop/clients/client-side-caching/) — tracking, 지원 클라이언트, 사용 권고
- [READONLY](https://redis.io/docs/latest/commands/readonly/) — 복제본 읽기 커넥션
- [Connection Modes (Spring Data Redis)](https://docs.spring.io/spring-data/redis/reference/redis/connection-modes.html) — `readFrom`
- [ElastiCache Well-Architected Lens — Performance Efficiency](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/PerformanceEfficiencyPillar.html) — 핫키 탐지와 복제 전략
- 관련 문서: `daily/day45-local-cache.md`, `daily/day51-cache-stampede.md`, `daily/day54-golden-signals.md`, `daily/day57-redis-structures.md`
