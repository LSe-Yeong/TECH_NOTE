# Redis 자료구조를 알면 설계가 바뀝니다

> 이 문서가 답할 질문: **Redis를 "JSON을 넣어두는 String 저장소"로만 쓰면 무엇을 잃고, 자료구조를 골랐을 때 애플리케이션 설계의 무엇이 바뀌는가?**
>
> 분류: 기술이해형(왜 존재하고 언제 쓰는가). 자료구조 목록을 외우는 건 레퍼런스의 일이고, 이 문서는 "타입 선택이 애플리케이션 코드에서 무엇을 지워주는가"를 축으로 조사했습니다.
>
> 기준: Redis Open Source 8.10 공식 문서(data types, memory optimization, 각 명령 레퍼런스)를 교차 확인했습니다. 복잡도와 설정 기본값은 모두 공식 명령 페이지·설정 문서에서 가져왔습니다.
>
> `daily/day33-cache-strategy.md`(읽기·쓰기 전략), `daily/day45-local-cache.md`(로컬 캐시와의 경계)와 다릅니다. 이 문서는 **Redis 안에 값을 어떤 모양으로 담을지**만 다룹니다.

## 1. 핵심 개념 — Redis는 캐시가 아니라 자료구조 서버입니다

공식 문서의 첫 문장은 "Redis is a data structure server"입니다. 키-값 저장소가 아니라, **값 자체가 자료구조이고 그 자료구조를 조작하는 명령이 서버에 있다**는 뜻입니다.

Redis Open Source 8.10이 제공하는 타입은 이 정도입니다.

- 기본형: String(+Bitmap, Bitfield), Hash, List, Set, Sorted Set, Stream, Array
- 구조형: JSON, Geospatial index
- 확률형: HyperLogLog, Bloom filter, Cuckoo filter, Count-min sketch, t-digest, Top-K
- 특수형: Time series, Vector set

JSON·Time series·확률형·Vector set은 예전에 Redis Stack 모듈로만 쓸 수 있었지만, 2025년 5월 1일 GA된 Redis 8부터 Redis Open Source에 내장되었습니다.

> 이걸 모르면 무슨 일이 벌어지는가. 대부분의 프로젝트에서 Redis 사용법은 이 한 줄로 끝납니다. **"객체를 JSON으로 직렬화해서 `SET`, 읽을 때 `GET` 후 역직렬화."** 돌아갑니다. 그리고 다음 네 가지를 전부 애플리케이션 코드로 떠안습니다.
>
> 1. **값을 고치려면 읽고-고치고-쓰기(read-modify-write)** 를 해야 하므로, 동시 요청이 서로의 수정을 덮어씁니다(lost update). 이걸 막으려고 분산 락을 도입합니다.
> 2. **일부만 필요해도 전체를 전송합니다.** 상품 캐시가 20KB면 재고 숫자 하나 때문에 20KB를 받고 20KB를 올려보냅니다.
> 3. **정렬·교집합·카운팅을 애플리케이션 메모리에서 합니다.** 전부 꺼내서 JVM에서 `sort()`를 돌립니다.
> 4. **큐가 필요하면 폴링합니다.** 1초마다 비어 있는지 물어보는 코드가 생깁니다.
>
> 네 가지 모두 "Redis가 느려서" 생긴 문제가 아닙니다. **타입을 잘못 골라서 서버가 할 수 있는 일을 애플리케이션으로 가져온 결과**입니다.

## 2. 타입을 고르면 코드에서 지워지는 것들

이 절이 이 문서의 본론입니다. 자료구조의 정의가 아니라, 각 선택이 **애플리케이션 설계에서 무엇을 없애는지**를 봅니다.

### 2-1. 원자성이 공짜로 생깁니다 → 분산 락이 사라집니다

Redis의 명령 하나는 그 자체로 원자적입니다. 그래서 `HINCRBY`, `INCR`, `ZINCRBY`, `SADD` 같은 **"값을 읽지 않고 변경만 지시하는 명령"** 을 쓰면 읽기-고치기-쓰기 구간이 아예 존재하지 않습니다.

이게 설계에 주는 변화가 큽니다. 조회수 카운터나 재고 차감 때문에 분산 락을 붙이는 경우가 많은데, 그 락의 절반은 **타입 선택 실수를 보정하려고 존재합니다.** JSON String 대신 Hash를 쓰고 필드를 `HINCRBY`로 올리면, 락도 재시도도 필요 없습니다.

단, 원자성이 **비즈니스 규칙까지 지켜주지는 않습니다.** `HINCRBY`로 재고를 -1씩 깎으면 음수까지 그대로 내려갑니다. "0 미만이면 실패"처럼 조건이 붙으면 Lua 스크립트로 조건과 변경을 한 덩어리로 묶어야 합니다.

### 2-2. 연산이 서버로 넘어갑니다 → 전부 꺼내오지 않습니다

Sorted Set은 멤버마다 점수(score)를 달아 정렬 상태를 유지합니다. 공식 문서 기준으로 대부분의 Sorted Set 연산은 O(log n)이고, `ZRANGE`는 O(log(n) + m)입니다(m은 반환 개수).

의미는 이렇습니다. **100만 명짜리 랭킹에서 상위 10명을 뽑는 비용이 100만에 거의 영향받지 않습니다.** 반면 String에 JSON 배열로 담아두면 100만 건을 전송해서 애플리케이션에서 정렬해야 합니다. 같은 기능인데 한쪽은 네트워크 수십 MB + JVM 힙 + GC 압박이고, 한쪽은 명령 한 번입니다.

Set의 교집합(`SINTER`), Sorted Set의 범위 조회(`ZRANGEBYSCORE`), 사전순 범위(`ZRANGEBYLEX`)도 같은 종류의 이득입니다. 데이터를 옮기지 않고 질문만 보냅니다.

### 2-3. 정확성을 포기하면 메모리가 상수가 됩니다

"오늘 방문한 순 사용자 수"를 Set으로 세면 사용자 수에 비례해 메모리가 늡니다. HyperLogLog는 다릅니다. 공식 문서 기준 **최대 12KB를 쓰고 표준오차는 0.81%** 입니다. 1천만 명을 세도 12KB입니다.

같은 교환이 Bitmap에도 있습니다. 공식 메모리 최적화 문서의 예시대로, 사용자를 연속된 정수 ID로 식별할 수 있다면 구독 여부 같은 1비트 정보를 **1억 명 기준 12MB** 로 담을 수 있습니다.

여기서 중요한 건 숫자가 아니라 **질문의 형태를 바꿀 수 있다는 판단**입니다. "정확히 몇 명"이 필요한지, "대략 몇 명"으로 충분한지. 후자라면 메모리가 데이터 양과 무관해집니다. 전자라면 확률형 자료구조는 쓰면 안 됩니다. 중복 체크를 Bloom filter로 하면 **없는데 있다고 답하는 경우(false positive)** 가 생깁니다.

### 2-4. 폴링이 사라집니다

List에는 `BLPOP`, `BRPOP`, `BLMOVE` 같은 블로킹 명령이 있습니다. 공식 문서는 `RPOP` 폴링의 문제를 두 가지로 정리합니다. 비어 있을 때의 호출이 전부 낭비라는 것과, 대기 간격이 그대로 처리 지연이 된다는 것입니다. 간격을 줄이면 낭비가 늘고, 늘리면 지연이 늡니다.

블로킹 명령은 이 교환 자체를 없앱니다. 워커는 "있으면 주고 없으면 기다려"라고 한 번 말하면 됩니다. 간단한 작업 큐에서 스케줄러·폴링 루프가 통째로 사라집니다.

여러 컨슈머가 같은 스트림을 나눠 읽거나, 처리 실패를 추적해야 한다면 List가 아니라 Stream입니다. Stream은 컨슈머 그룹과 at-least-once 전달을 내장하고 있습니다.

## 3. 선택 기준 — 표로 정리

공식 "Compare data types" 문서는 선택을 세 묶음으로 나눕니다. **문서(document)**, **컬렉션(collection)**, **시퀀스(sequence)** 입니다. 이 분류가 실무에서 꽤 잘 맞습니다.

| 하려는 일 | 타입 | 핵심 근거 |
|---|---|---|
| 필드 일부만 읽고 쓰는 객체 | Hash | 필드 단위 접근·증감, 필드별 TTL 가능 |
| 중첩 구조·배열이 있는 문서 | JSON | 경로 문법으로 부분 접근, Search 연동 |
| 통째로 쓰고 통째로 읽는 값 | String | 가장 적은 오버헤드 |
| 정수 인덱스에 붙은 플래그/카운터 | String(Bitmap, Bitfield) | 비트 단위 접근, 최소 메모리 |
| 중복 없는 집합, 교/합/차집합 | Set | 추가·삭제·포함 검사 O(1) |
| 순서·점수가 필요한 집합 | Sorted Set | 대부분 O(log n), 범위 조회 |
| 큐·스택 | List | 양 끝 연산 O(1), 블로킹 명령 |
| 다중 컨슈머 이벤트 로그 | Stream | 컨슈머 그룹, at-least-once |
| 순 방문자 수 추정 | HyperLogLog | 최대 12KB, 표준오차 0.81% |

복잡도는 선택의 근거가 되므로 자주 쓰는 것만 공식 명령 페이지 기준으로 옮겨둡니다.

| 명령 | 복잡도 | 주의 |
|---|---|---|
| `HSET` / `HGET` | O(1) | — |
| `HGETALL` / `HKEYS` / `HVALS` | O(N) | N = 해시 전체 크기 |
| `LPUSH` / `RPOP` | O(1) | 양 끝만 |
| `LINDEX` / `LINSERT` / `LSET` | O(n) | 중간 접근은 선형 |
| `LRANGE` | O(S+N) | S = 시작 오프셋 거리 |
| `ZADD` | O(log N) | — |
| `ZRANGE` | O(log(N)+m) | m = 반환 개수 |
| `SADD` / `SREM` / `SISMEMBER` | O(1) | — |
| `KEYS` | O(N) | 애플리케이션 코드에서 쓰지 않습니다 |
| `DEL` | O(N) | 큰 컬렉션은 `UNLINK` |

List의 최대 길이는 2^32 - 1(4,294,967,295)개입니다.

## 4. 예제 — 같은 기능, 다른 타입

### 4-1. 재고 차감 ❌ JSON String

```java
@Service
@RequiredArgsConstructor
public class ProductStockService {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    // ❌ 읽고 → 고치고 → 쓰는 사이에 다른 요청이 같은 값을 읽습니다
    public void decreaseStock(long productId, int quantity) throws JsonProcessingException {
        String key = "product:" + productId;

        String json = redisTemplate.opsForValue().get(key);
        ProductCache product = objectMapper.readValue(json, ProductCache.class);
        product.setStock(product.getStock() - quantity);

        redisTemplate.opsForValue().set(key, objectMapper.writeValueAsString(product));
    }
}
```

동시에 두 요청이 들어오면 재고가 1만 줄어듭니다. 그리고 재고 숫자 하나를 바꾸려고 상품 전체를 직렬화·역직렬화합니다.

### 4-2. 재고 차감 ✔️ Hash 필드 증감

```java
@Service
@RequiredArgsConstructor
public class ProductStockService {

    private final StringRedisTemplate redisTemplate;

    // ✔️ 읽지 않습니다. 변경만 지시하므로 끼어들 구간이 없습니다
    public long decreaseStock(long productId, long quantity) {
        return redisTemplate.opsForHash()
                .increment("product:" + productId, "stock", -quantity);
    }

    public int readStock(long productId) {
        Object stock = redisTemplate.opsForHash().get("product:" + productId, "stock");
        return stock == null ? 0 : Integer.parseInt(stock.toString());
    }
}
```

락이 없어졌고, 네트워크로 오가는 건 숫자 하나입니다. 반환값이 음수면 품절 처리로 보정할 수 있지만, **"음수가 되면 애초에 실패"** 가 필요하면 Lua 스크립트로 조건과 증감을 묶어야 합니다. 원자성과 비즈니스 규칙은 다른 문제입니다.

### 4-3. 실시간 랭킹 ✔️ Sorted Set

```java
@Service
@RequiredArgsConstructor
public class ProductRankingService {

    private final StringRedisTemplate redisTemplate;

    public void addScore(String rankingKey, long productId, double score) {
        redisTemplate.opsForZSet()
                .incrementScore(rankingKey, String.valueOf(productId), score);
    }

    // 100만 개가 들어 있어도 상위 10개만 서버에서 꺼냅니다
    public List<Long> topProductIds(String rankingKey, long size) {
        Set<String> members = redisTemplate.opsForZSet()
                .reverseRange(rankingKey, 0, size - 1);

        if (members == null) {
            return List.of();
        }
        return members.stream().map(Long::parseLong).toList();
    }
}
```

`reverseRange(key, 0, 9)`는 `ZREVRANGE key 0 9`가 되고 O(log(N)+m)입니다. 전체를 가져와 정렬하는 코드와 비교하면, 데이터가 늘어날 때 비용이 거의 늘지 않는다는 점이 다릅니다.

## 5. 메모리는 타입이 아니라 인코딩이 결정합니다

같은 Hash인데 메모리 사용량이 몇 배씩 차이 납니다. Redis는 작은 컬렉션을 `listpack`(또는 정수만 담긴 Set의 경우 `intset`)이라는 **선형 배열 형태로 압축해 저장**하고, 크기가 임계값을 넘으면 일반 해시테이블·스킵리스트로 자동 전환합니다. 공식 메모리 최적화 문서는 이 압축 인코딩이 **최대 10배, 평균 5배 적은 메모리**를 쓴다고 설명합니다.

임계값은 설정으로 조정합니다. Redis 7.2 이상 기본값입니다.

```
hash-max-listpack-entries 512
hash-max-listpack-value 64
zset-max-listpack-entries 128
zset-max-listpack-value 64
set-max-intset-entries 512
set-max-listpack-entries 128
set-max-listpack-value 64
```

실무에서 바로 쓰는 결론 두 개입니다.

1. **작은 객체는 키를 쪼개지 말고 Hash 하나로 묶습니다.** 공식 문서가 직접 권하는 방식입니다. `user:1:name`, `user:1:email`처럼 키를 늘리면 키마다 오버헤드가 붙습니다.
2. **필드 값 길이도 임계값입니다.** `hash-max-listpack-value 64`는 64바이트를 넘는 값이 하나라도 들어오면 인코딩이 전환된다는 뜻입니다. 필드 하나에 긴 JSON을 넣는 순간 압축 이득이 사라집니다.

내 키가 어떤 인코딩인지는 `OBJECT ENCODING <key>`로 확인합니다.

Redis 8.10은 여기에 **compact hash** 를 추가했습니다. 같은 필드 이름 구성(스키마)을 공유하는 해시 키들이 필드 이름을 한 번만 저장하는 인코딩입니다. 공식 블로그는 구조가 비슷한 해시가 많은 워크로드에서 메모리를 최대 50%까지 줄일 수 있다고 밝혔습니다. 엔티티 캐시처럼 **같은 필드 집합을 가진 해시를 수백만 개 쌓는** 패턴에 그대로 맞는 변화입니다.

## 6. 함정

### 6-1. 빅키 하나가 전체 지연을 만듭니다

- **증상**: 특정 API만 느린 게 아니라 **그 순간 모든 명령의 응답이 같이 느려집니다.** `SLOWLOG`에 `HGETALL`이나 `LRANGE`가 찍힙니다.
- **원인**: `HGETALL`·`SMEMBERS`·`LRANGE key 0 -1`은 O(N)입니다. 요소 10만 개짜리 키에 이 명령을 쓰면 그 명령이 끝날 때까지 뒤에 줄 선 명령들이 기다립니다. 캐시가 커질수록 느려지는 게 아니라, **커진 키 하나가 무관한 요청까지 끌고 내려갑니다.**
- **해법**: 전체 조회 명령을 쓰지 않습니다. 필요한 필드만 `HMGET`, 범위만 `LRANGE key 0 99`, 순회는 `HSCAN`/`SSCAN`/`ZSCAN`으로 나눠 받습니다. 애초에 한 키에 다 넣지 말고 날짜·사용자 등으로 키를 쪼갭니다. `KEYS`는 공식 문서가 "애플리케이션 코드에서 쓰지 말라"고 명시한 명령이고, 대안은 `SCAN`입니다.

### 6-2. 컬렉션은 통째로만 만료됩니다

- **증상**: Sorted Set으로 만든 슬라이딩 윈도우(최근 1시간 요청 기록)의 메모리가 계속 늡니다. TTL을 걸었는데도 줄지 않습니다.
- **원인**: TTL은 **키 단위**입니다. Sorted Set 안의 멤버는 개별적으로 만료되지 않습니다. 게다가 키에 TTL을 걸어두면 윈도우 전체가 어느 순간 통째로 사라져 기록이 끊깁니다.
- **해법**: 오래된 멤버를 직접 지웁니다. `ZREMRANGEBYSCORE key -inf <기준시각>`을 기록 추가와 같은 파이프라인·스크립트에서 함께 실행합니다. Hash라면 Redis 7.4부터 **필드별 TTL** 을 쓸 수 있습니다(`HEXPIRE`, `HPEXPIRE`, `HTTL`, `HPERSIST`, Redis 8.0의 `HGETEX`/`HSETEX`/`HGETDEL`). 단 이건 Hash 전용이고, List·Set·Sorted Set에는 없습니다.

<!-- TODO: 확인 필요 — Spring Data Redis에서 HEXPIRE 계열을 어느 버전부터 어떤 API로 노출하는지 1차 자료로 확정하지 못했습니다. 쓰려는 버전의 HashOperations Javadoc을 확인하거나 execute(RedisCallback)으로 직접 호출하는 편이 안전합니다. -->

### 6-3. 클러스터에서는 멀티 키 명령이 막힙니다

- **증상**: 단일 인스턴스에서 잘 돌던 코드가 클러스터로 옮기자 `CROSSSLOT Keys in request don't hash to the same slot` 에러를 냅니다.
- **원인**: `SINTER`, `ZUNIONSTORE`, `PFCOUNT`, `BITOP`, `MSETNX`, `RENAME` 등 **여러 키를 함께 다루는 명령은 클러스터에서 같은 슬롯에 있는 키만** 처리할 수 있습니다. `MULTI/EXEC` 트랜잭션과 Lua 스크립트가 참조하는 키도 같은 제약을 받습니다.
- **해법**: 함께 연산할 키를 해시 태그로 묶습니다. `{user:1}:follows`, `{user:1}:blocks`처럼 중괄호 부분이 같으면 같은 슬롯에 들어갑니다. 설계 단계에서 "이 키들을 서버에서 함께 연산할 일이 있나"를 먼저 판단해야 합니다. 나중에 키 이름을 바꾸는 건 마이그레이션입니다.

### 6-4. 읽기 명령인데 쓰기인 경우가 있습니다

- **증상**: 읽기 전용 레플리카로 보낸 `PFCOUNT`가 거부되거나, 읽기만 했는데 복제 트래픽이 생깁니다.
- **원인**: 공식 `PFCOUNT` 문서는 이 명령을 호출하면 HyperLogLog가 **수정될 수 있다**고 밝힙니다. 마지막 8바이트에 직전 계산 결과를 캐싱하기 때문입니다. 이름이 `COUNT`지만 쓰기 명령입니다.
- **해법**: 읽기/쓰기 분리 구성에서 `PFCOUNT`를 "읽기"로 분류하지 않습니다. 레플리카에서 세야 하면 결과를 별도 String 키에 주기적으로 적재해 그 값을 읽습니다.

### 6-5. 큰 키를 지우는 것도 O(N)입니다

- **증상**: 배치가 캐시를 정리하는 순간 지연이 튑니다. 지우는 쪽인데도 느립니다.
- **원인**: `DEL`은 O(N)이고 메모리 회수까지 **그 자리에서** 합니다. 요소 수백만 개짜리 키를 지우면 그동안 서버가 묶입니다.
- **해법**: `UNLINK`를 씁니다. 공식 문서 기준 `UNLINK`는 키 하나당 O(1)로 키스페이스에서 연결만 끊고, 실제 메모리 회수는 **다른 스레드에서** 수행합니다(Redis 4.0부터). 대량 삭제 스크립트의 `DEL`은 기본적으로 `UNLINK`로 바꿔도 좋습니다.

## 7. 정리 — 판단 순서

새로 Redis에 무언가를 담을 때는 이 순서로 묻습니다.

1. **일부만 읽고 쓰는가?** → 그렇다면 String + JSON은 탈락. Hash나 JSON.
2. **읽지 않고 변경만 지시할 수 있는가?** → `INCR` 계열로 바꾸면 분산 락이 사라집니다.
3. **정렬·교집합·범위를 서버에 맡길 수 있는가?** → Sorted Set, Set.
4. **정확한 수가 필요한가, 추정으로 충분한가?** → 후자면 HyperLogLog·Bloom filter로 메모리가 상수가 됩니다.
5. **이 키는 끝까지 얼마나 커지는가?** → O(N) 명령이 걸릴 크기면 키를 쪼갭니다.
6. **이 데이터는 어떻게 줄어드는가?** → TTL은 키 단위라는 걸 전제로 삭제 전략을 같이 설계합니다.

마지막 두 질문을 빼먹는 경우가 가장 많습니다. 자료구조 선택은 보통 **쓰기 편의**로 결정되는데, 터지는 건 **크기와 수명** 쪽입니다.

## 8. 참고자료

- [Redis data types](https://redis.io/docs/latest/develop/data-types/) — 전체 타입 목록
- [Compare data types](https://redis.io/docs/latest/develop/data-types/compare-data-types/) — 공식 선택 기준과 결정 트리
- [Memory optimization](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/memory-optimization/) — listpack/intset 인코딩, 설정 기본값, Bitmap 메모리 예시
- [Redis lists](https://redis.io/docs/latest/develop/data-types/lists/) · [Redis sorted sets](https://redis.io/docs/latest/develop/data-types/sorted-sets/) · [Redis hashes](https://redis.io/docs/latest/develop/data-types/hashes/) — 복잡도와 한계
- [HyperLogLog](https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs/) · [`PFCOUNT`](https://redis.io/docs/latest/commands/pfcount/) — 12KB·0.81%, 쓰기 부수효과
- [`KEYS`](https://redis.io/docs/latest/commands/keys/) · [`UNLINK`](https://redis.io/docs/latest/commands/unlink/) — 공식 경고와 대안
- [Multi-key operations](https://redis.io/docs/latest/develop/using-commands/multi-key-operations/) — 클러스터 CROSSSLOT 제약
- [What's new in Redis 8.10](https://redis.io/docs/latest/develop/whats-new/8-10/) · [Announcing Redis 8.10](https://redis.io/blog/announcing-redis-810-compact-hash-jsonpath-extensions-performance-improvements-and-more) — compact hash
- [Redis 8 GA](https://redis.io/blog/redis-8-ga/) — 모듈 타입의 Open Source 내장
