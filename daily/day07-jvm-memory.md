# 힙, 스택, 메타스페이스 — JVM 메모리는 왜 나뉘어 있는가

> 이 문서가 답할 질문: **JVM은 메모리를 왜 여러 영역으로 쪼개서 쓰고, 어느 영역이 부족하냐에 따라 무엇이 달라지는가?**
>
> 기준: Java 25 (LTS, 2025-09-16 GA) / HotSpot. 직접 재현한 값은 Temurin JDK 17.0.19, Linux x64 환경에서 측정한 것이며 본문에 조건을 밝힙니다.

## 1. 핵심 개념 — 데이터마다 수명이 다르다

JVM이 관리하는 메모리는 한 덩어리가 아닙니다. Java 가상 머신 명세(JVMS) §2.5는 런타임 데이터 영역을 여섯 가지로 나눕니다. 나눈 기준은 두 가지입니다. **누가 공유하는가(스레드별 vs 전체 공유)**, 그리고 **언제 사라지는가**입니다.

메서드 안의 지역 변수는 메서드가 끝나면 확실히 죽습니다. 죽는 시점이 정해져 있으니 추적할 필요가 없고, 스택 포인터만 되돌리면 끝입니다. 반면 `new`로 만든 객체는 누가 참조하는지 실행해봐야 압니다. 그래서 추적기(GC)가 필요합니다. 클래스 정의는 또 다릅니다. 한 번 로딩되면 애플리케이션이 사는 내내 남고, 사라질 때는 객체 단위가 아니라 클래스로더 단위로 통째로 사라집니다.

**수명 패턴이 다르면 회수 전략도 달라야 합니다.** 하나의 공간에 다 넣으면 가장 비싼 전략(전체 추적)을 전부에 적용하게 됩니다.

> `OutOfMemoryError`가 떴다고 `-Xmx`를 올렸는데 그대로 다시 터집니다. 로그를 다시 보니 `OutOfMemoryError: Metaspace`입니다. 메타스페이스는 힙 밖에 있으니 `-Xmx`와는 아무 상관이 없습니다. 반대로 컨테이너에서 `-Xmx`를 넉넉히 줬더니 애플리케이션은 멀쩡한데 파드가 `OOMKilled`로 죽습니다. **JVM 메모리 영역을 구분하지 못하면 에러 메시지를 읽고도 엉뚱한 곳을 고칩니다.** 이 챕터는 그 지도를 그립니다.

## 2. 구조

### 2-1. 명세가 정의한 여섯 영역

| 영역 | 공유 범위 | 무엇이 들어가나 |
|---|---|---|
| PC 레지스터 | 스레드별 | 현재 실행 중인 바이트코드 명령의 주소 |
| JVM 스택 | 스레드별 | 프레임(지역 변수, 피연산자 스택, 호출 복귀 정보) |
| 네이티브 메서드 스택 | 스레드별 | JNI 등 네이티브 코드 호출용 스택 |
| 힙 | 전체 공유 | **모든 객체 인스턴스와 배열** |
| 메서드 영역 | 전체 공유 | 클래스 구조, 필드·메서드 데이터, 메서드 바이트코드 |
| 런타임 상수 풀 | 전체 공유 | 클래스 파일 상수 풀의 런타임 표현 (메서드 영역 안에 위치) |

명세가 못 박는 건 딱 하나, **객체는 전부 힙에 있다**는 것입니다. 나머지는 구현에 상당히 열려 있습니다. 실제로 명세는 메서드 영역을 "논리적으로는 힙의 일부"라고만 규정하고, GC나 압축을 할지 말지는 구현에 맡깁니다 ([JVMS §2.5.4](https://docs.oracle.com/javase/specs/jvms/se8/html/jvms-2.html)). 그래서 **명세의 영역 이름과 HotSpot의 실제 메모리 배치는 1:1로 대응하지 않습니다.**

### 2-2. HotSpot이 실제로 구현한 모습

```
JVM 프로세스가 잡는 메모리
├─ 힙                       -Xms / -Xmx          ← GC가 관리하는 유일한 영역
│   ├─ Young (Eden, Survivor)
│   ├─ Old
│   └─ 문자열 상수 풀        ← JDK 7부터 여기로 이사
│
└─ 힙 밖 (네이티브 메모리)    -Xmx와 무관
    ├─ 메타스페이스          클래스 메타데이터
    │   └─ 압축 클래스 공간   -XX:CompressedClassSpaceSize
    ├─ 스레드 스택           -Xss × 스레드 수
    ├─ 코드 캐시             JIT가 만든 기계어
    ├─ GC 자체의 자료구조
    └─ 다이렉트 버퍼 / JNI / 네이티브 라이브러리
```

명세의 **메서드 영역을 HotSpot이 구현한 것이 메타스페이스(Metaspace)** 입니다. JDK 7까지는 힙 안의 Permanent Generation이었고, JDK 8부터 힙 밖 네이티브 메모리로 옮겨졌습니다. HotSpot은 이 공간을 `malloc`이 아니라 `mmap`으로 확보하고, 청크를 클래스로더 단위로 묶어 관리합니다 ([HotSpot GC Tuning Guide — Class Metadata](https://docs.oracle.com/en/java/javase/25/gctuning/other-considerations.html)).

문자열 상수 풀도 JDK 7에서 PermGen을 떠나 힙 본체(Young/Old)로 옮겨졌습니다 ([JVM Enhancements in JDK 7](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/enhancements-7.html)). 그래서 `String.intern()`을 남발해서 나는 OOM은 메타스페이스가 아니라 **힙** 문제입니다.

### 2-3. 압축 포인터 — 64비트인데 참조는 32비트

64비트 JVM은 기본적으로 객체 참조를 32비트 오프셋으로 압축해서 저장합니다(`-XX:+UseCompressedOops`, 기본 활성). 대신 이 방식이 커버하는 힙 범위가 **32GB**로 제한됩니다 ([java 명령 레퍼런스](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)).

여기서 실무적으로 아픈 지점이 나옵니다. 힙을 31GB에서 33GB로 올리면 압축이 꺼지면서 모든 참조가 8바이트가 됩니다. **힙을 키웠는데 실제로 담기는 객체 수는 오히려 줄어들 수 있습니다.** 32GB 근처는 넘지 말고, 넘겨야 한다면 확실히 크게(48GB 이상) 넘기거나 JVM을 여러 개로 쪼개는 편이 낫습니다.

클래스 메타데이터를 가리키는 포인터도 같은 방식으로 압축되며(`UseCompressedClassPointers`, 기본 `true`), 이때는 **압축 클래스 공간의 크기가 `CompressedClassSpaceSize`로 고정**됩니다. 이 공간이 먼저 차면 `OutOfMemoryError: Compressed class space`가 납니다 ([Troubleshooting Guide](https://docs.oracle.com/en/java/javase/25/troubleshoot/troubleshooting-memory-leaks.html)).

JDK 25에는 객체 헤더 자체를 줄이는 압축 객체 헤더(`-XX:+UseCompactObjectHeaders`)가 정식 기능으로 들어왔습니다. 객체당 평균 4바이트를 아낍니다. 다만 **JDK 25 기준으로는 기본 비활성**이고, 문서는 "향후 릴리스에서 기본 활성화될 것으로 예상된다"고만 적고 있습니다 ([java 명령 레퍼런스](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)).

## 3. 흐름

### 3-1. 코드 한 줄이 어디에 놓이는가

```java
public class OrderService {

    private static final int MAX_ITEMS = 100;   // 클래스 상수 → 런타임 상수 풀 (메타스페이스)

    public long totalPrice(List<OrderItem> items) {
        long total = 0;          // 지역 변수 → 이 스레드의 스택 프레임
        for (OrderItem item : items) {   // items가 가리키는 리스트 객체 자체 → 힙
            total += item.price();
        }
        return total;
    }
}
```

읽는 법은 이렇습니다.

1. `OrderService`라는 **클래스 정의**는 메타스페이스에 한 벌만 존재합니다.
2. `totalPrice`를 호출한 **스레드마다** 자기 스택에 프레임이 하나 쌓이고, `total`은 그 프레임 안에 있습니다.
3. `items` **변수**는 스택에 있지만, 그 변수가 가리키는 **리스트 객체**는 힙에 있습니다.

3번이 핵심입니다. 스레드 100개가 같은 리스트를 동시에 넘겨받아도 리스트는 힙에 하나뿐이고, `total` 변수만 100개 생깁니다. **동시성 문제가 힙에서만 생기고 지역 변수에서는 안 생기는 이유가 이 그림입니다.**

### 3-2. 컨테이너가 보는 메모리는 힙이 아니다

```
컨테이너 메모리 한도 (예: 2GB)
   ≥  JVM 프로세스의 RSS
      = 힙 사용량 + 메타스페이스 + (스레드 수 × 스택) + 코드 캐시 + GC 구조체 + 네이티브
```

`-Xmx1500m`을 주면 힙만 1.5GB입니다. 여기에 스레드 200개 × 1MB = 200MB, 메타스페이스 100MB, 코드 캐시가 붙으면 2GB를 넘깁니다. 그러면 **JVM은 `OutOfMemoryError`를 던지지 않고 커널이 프로세스를 죽입니다.** 스택트레이스도 힙 덤프도 안 남습니다. 컨테이너에서 `-Xmx`를 한도에 바짝 붙이면 안 되는 이유입니다.

### 3-3. 기본값은 외우지 말고 출력합니다

```bash
java -XX:+PrintFlagsFinal -version | grep -E "MaxHeapSize|MaxMetaspaceSize|ThreadStackSize|MaxRAMPercentage|CompressedClassSpaceSize|ReservedCodeCacheSize"
```

Temurin JDK 17.0.19 / Linux x64에서 직접 실행한 결과입니다.

| 플래그 | 출력값 | 의미 |
|---|---|---|
| `MaxRAMPercentage` | `25.0` | 최대 힙 = 가용 메모리의 **1/4** |
| `InitialRAMPercentage` | `1.5625` | 초기 힙 = 1/64 |
| `MaxMetaspaceSize` | `18446744073709551615` | `2^64 - 1` = **사실상 무제한** |
| `ThreadStackSize` | `1024` (KB) | 스레드당 1MB |
| `CompressedClassSpaceSize` | `1073741824` | 1GB 고정 |
| `ReservedCodeCacheSize` | `251658240` | 240MB |

힙 1/4·1/64 규칙은 Oracle 문서와 일치합니다 ([Ergonomics](https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html)). 스레드 스택 기본값은 플랫폼마다 다릅니다. 문서 기준 Linux/x64는 1024KB, **Linux/AArch64는 2048KB**입니다 — Graviton이나 Apple Silicon으로 옮기면 스레드당 메모리가 두 배가 됩니다.

메타스페이스가 기본 무제한이라는 게 가장 중요합니다. Oracle 문서도 "클래스 메타데이터에 쓰이는 네이티브 메모리 양은 기본적으로 무제한"이라고 명시합니다. **한도가 없다는 건 안전하다는 뜻이 아니라, 클래스가 새면 컨테이너 한도까지 조용히 먹고 커널에 의해 죽는다는 뜻입니다.**

혼동하기 쉬운 이름이 하나 더 있습니다. `-XX:MetaspaceSize`는 최대치가 아니라 **첫 GC를 유발하는 초기 임계치**입니다(플랫폼별 12MB~20MB 안팎). 상한은 `-XX:MaxMetaspaceSize` 쪽입니다.

## 4. 영역별로 다르게 터진다

에러 메시지 한 줄이 어느 영역인지 알려줍니다. Oracle 트러블슈팅 가이드가 정리한 대표 메시지입니다.

### 4-1. 힙

- **`OutOfMemoryError: Java heap space`** — 힙에 객체를 못 만들었습니다. 문서도 강조하듯 이게 곧 메모리 누수는 아닙니다. 그냥 힙이 작아서일 수도 있습니다.
- **`OutOfMemoryError: GC Overhead limit exceeded`** — 직전 5회 연속 GC에서 **시간의 약 98%를 GC에 쓰고 힙의 2% 미만을 회수**한 경우 던집니다. "살아 있는 데이터가 힙에 겨우 들어차서 새로 할당할 여유가 없다"는 신호입니다.

둘의 차이가 진단에 중요합니다. 앞은 순간적인 큰 할당일 수도 있지만, 뒤는 **정상 상태에서 이미 한계**라는 뜻이라 힙 증설로는 시간만 벌립니다.

### 4-2. 스택

스택 부족은 `OutOfMemoryError`가 아니라 **`StackOverflowError`** 입니다. 한 스레드의 프레임이 자기 스택 한도를 넘은 것이고, 프로세스 전체 메모리와는 무관합니다.

`-Xss`를 바꿔가며 재귀 깊이를 직접 측정했습니다(Temurin 17.0.19, Linux x64, JIT 영향을 없애려고 `-Xint`, 인자 3개짜리 재귀).

| `-Xss` | 도달한 재귀 깊이 |
|---|---:|
| 512k | 3,090 |
| 1m | 6,945 |
| 2m | 14,655 |

거의 정비례합니다. 프레임 크기는 메서드의 지역 변수 수에 좌우되므로 **이 숫자는 절대 기준이 아니라 "스택을 두 배로 주면 깊이도 두 배"라는 관계를 보여주는 값**입니다. 값이 필요하면 각자 코드로 측정해야 합니다.

스레드를 못 만들 때는 얘기가 다릅니다. 프로세스 한도를 300으로 낮추고 스레드를 계속 만들어봤습니다.

```
$ bash -c 'ulimit -u 300; java -Xss1m ThreadBomb'
[warning][os,thread] Failed to start thread "Unknown thread" - pthread_create failed (EAGAIN)
created=210 -> java.lang.OutOfMemoryError: unable to create native thread:
               possibly out of memory or process/resource limits reached
```

힙은 텅 비어 있는데 `OutOfMemoryError`가 납니다. 메시지가 스스로 밝히듯 원인은 **네이티브 메모리 부족이거나 프로세스·리소스 한도**입니다. 여기서 `-Xmx`를 올리면 오히려 네이티브에 남는 공간이 줄어 상황이 나빠집니다.

<!-- TODO: 확인 필요 — 이 메시지는 JDK 17에서 직접 재현한 문자열입니다. JDK 25 트러블슈팅 가이드의 OutOfMemoryError 메시지 목록에는 이 변형이 실려 있지 않아, 버전에 따라 문구가 다를 수 있습니다. -->

### 4-3. 메타스페이스

- **`OutOfMemoryError: Metaspace`** — `MaxMetaspaceSize`를 지정했고 그걸 넘었을 때 납니다. 지정하지 않았다면 이 에러 대신 컨테이너 OOMKill을 보게 됩니다.
- **`OutOfMemoryError: Compressed class space`** — 압축 클래스 포인터가 켜진 상태에서 고정 크기인 압축 클래스 공간이 먼저 찬 경우입니다.

메타스페이스는 **클래스 단위가 아니라 클래스로더 단위로 회수**됩니다. 클래스로더 하나가 살아 있으면 그 로더가 로딩한 클래스 전부가 남습니다. 그래서 클래스를 동적으로 만들거나 애플리케이션을 반복 재배포하는 환경에서 새기 쉽습니다.

## 5. 예제 — 힙이 새는 가장 흔한 모양

### 5-1. 클린하지 않은 코드 ❌

```java
@Service
public class OrderCacheService {

    // static + 무한 증가 = 애플리케이션이 죽을 때까지 회수 불가
    private static final Map<Long, Order> CACHE = new HashMap<>();

    public Order find(Long orderId) {
        return CACHE.computeIfAbsent(orderId, orderRepository::getById);
    }
}
```

로컬에서는 완벽합니다. 두 번째 조회부터 빨라집니다. 문제는 **주문이 계속 늘어난다는 것**입니다. `static` 필드는 클래스가 언로딩될 때까지 GC 루트에서 도달 가능하므로, 여기 들어간 `Order`는 영원히 살아남습니다.

증상도 특이합니다. 배포 직후에는 멀쩡하고 며칠 뒤부터 GC가 잦아지다가 `GC Overhead limit exceeded`로 끝납니다. **재시작하면 멀쩡해지니 원인을 찾기 전에 재시작으로 넘어가기 쉽습니다.**

### 5-2. 개선한 코드 ✔️

```java
@Service
public class OrderCacheService {

    private final Cache<Long, Order> cache = Caffeine.newBuilder()
            .maximumSize(10_000)                          // 상한이 있다
            .expireAfterWrite(Duration.ofMinutes(10))     // 수명이 있다
            .build();

    private final OrderRepository orderRepository;

    public OrderCacheService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order find(Long orderId) {
        return cache.get(orderId, orderRepository::getById);
    }
}
```

바뀐 건 라이브러리가 아니라 **경계**입니다. 캐시에는 반드시 두 가지가 있어야 합니다.

1. **크기 상한** — 최악의 경우 얼마나 먹을지 계산할 수 있어야 합니다.
2. **만료 정책** — 안 쓰는 항목이 빠져나갈 길이 있어야 합니다.

`static` 컬렉션에 계속 담는 코드는 캐시가 아니라 상한 없는 누수입니다.

## 6. 실무 — 힙은 정상인데 RSS가 커질 때

컨테이너가 `OOMKilled`인데 힙 사용률은 60%. 이럴 때 쓰는 도구가 네이티브 메모리 추적(NMT, Native Memory Tracking)입니다. 힙 덤프는 힙만 보여주므로 이 상황에서는 아무 답도 주지 못합니다.

```bash
# 1) 기동 시 켠다 (약간의 오버헤드가 있으므로 조사할 때만)
java -XX:NativeMemoryTracking=summary -jar order-api.jar

# 2) 실행 중에 조회
jcmd <pid> VM.native_memory summary
```

출력은 `Java Heap`, `Class`, `Thread`, `Code`, `GC`, `Internal` 같은 카테고리별로 예약(reserved)·커밋(committed) 크기를 보여줍니다. **`Thread` 항목이 비정상적으로 크면 스레드 폭증, `Class`가 크면 클래스로더 누수** 쪽으로 방향이 잡힙니다 ([java 명령 레퍼런스](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)).

같이 쓰는 명령들입니다.

```bash
jcmd <pid> GC.heap_info          # 힙 영역별 현재 사용량
jcmd <pid> GC.class_histogram    # 클래스별 인스턴스 수·바이트 (많은 순)
jcmd <pid> Thread.print          # 스레드 전체 스택 — 스레드 수와 출처 확인
jcmd <pid> GC.heap_dump /tmp/heap.hprof
```

Oracle 문서는 힙 덤프에 대해 `jmap -dump` 대신 **`jcmd`를 권장 도구로** 명시하고 있습니다 ([Diagnostic Tools](https://docs.oracle.com/en/java/javase/25/troubleshoot/diagnostic-tools.html)). 사후 분석을 위해 `-XX:+HeapDumpOnOutOfMemoryError`는 미리 켜두는 편이 좋습니다. 기본값은 비활성이고, 켜두지 않으면 OOM이 난 그 순간의 힙은 영원히 사라집니다.

## 7. 함정

**함정 1 — `-Xmx`를 컨테이너 한도에 맞춘다**

- **증상**: 파드가 `OOMKilled`로 재시작됩니다. 애플리케이션 로그에는 `OutOfMemoryError`가 없고, 힙 덤프도 안 남습니다.
- **원인**: `-Xmx`는 **힙만** 제한합니다. 스레드 스택·메타스페이스·코드 캐시·GC 구조체는 그 밖에 있습니다. 힙 한도 안에서 정상 동작하는 JVM의 RSS가 컨테이너 한도를 넘고, 커널이 프로세스를 죽입니다. JVM이 던진 에러가 아니니 아무 기록도 없습니다.
- **해법**: 힙 밖 몫을 반드시 남깁니다. `-Xmx`를 직접 주지 않고 `-XX:MaxRAMPercentage`로 비율 지정하는 방식이 컨테이너에서는 더 안전합니다. 컨테이너 자동 인식은 Linux에서 기본 활성(`-XX:+UseContainerSupport`)이라 별도 설정이 필요 없습니다. 얼마를 남길지는 NMT로 실측해서 정합니다.

**함정 2 — 메시지를 안 읽고 `-Xmx`부터 올린다**

- **증상**: `-Xmx`를 두 배로 올렸는데 같은 `OutOfMemoryError`가 같은 주기로 납니다.
- **원인**: `Metaspace`·`Compressed class space`·`unable to create native thread`는 전부 **힙 밖** 이야기입니다. 오히려 `-Xmx`를 키우면 같은 컨테이너 안에서 네이티브에 남는 공간이 줄어 더 빨리 터집니다.
- **해법**: 에러 메시지의 뒷부분을 먼저 읽고 영역을 특정합니다. 4절의 분류가 그 지도입니다. `Java heap space`일 때만 힙 증설이 후보가 됩니다.

**함정 3 — 스레드 풀 크기를 스택 계산 없이 정한다**

- **증상**: 커넥션 풀도 스레드 풀도 여유 있게 잡았는데, 부하가 오르면 `unable to create native thread`가 뜨거나 컨테이너가 죽습니다.
- **원인**: 스레드 하나가 스택을 통째로 예약합니다. Linux/x64 기본 1MB면 스레드 500개는 그 자체로 500MB입니다. AArch64에서는 기본 2048KB라 같은 설정이 1GB가 됩니다. 여기에 OS의 프로세스·스레드 한도(`ulimit -u`)까지 걸립니다.
- **해법**: `스레드 수 × -Xss`를 메모리 예산에 명시적으로 포함시킵니다. 스택을 무작정 줄이면 `StackOverflowError`가 나므로, 깊은 재귀나 프록시 체인이 있는 코드는 4-2절처럼 실제 깊이를 측정하고 줄입니다. 블로킹 I/O 대기 스레드가 많은 구조라면 가상 스레드(Java 21+)가 근본 해법입니다. 가상 스레드의 스택은 힙에 있어 OS 스레드를 소모하지 않습니다.

**함정 4 — 재배포를 반복하면 메타스페이스가 샌다**

- **증상**: WAS에 애플리케이션을 여러 번 핫 리로드하거나 재배포하면 `OutOfMemoryError: Metaspace`가 납니다. 완전 재시작하면 사라집니다.
- **원인**: 메타스페이스는 클래스로더 단위로 회수됩니다. 이전 배포의 클래스로더를 누군가 한 명이라도 붙잡고 있으면(스레드 로컬, 종료되지 않은 스레드, JDBC 드라이버 등록, 로깅 프레임워크 캐시) 그 로더가 로딩한 클래스 전체가 안 죽습니다.
- **해법**: 상한을 지정합니다(`-XX:MaxMetaspaceSize`). 무제한으로 두면 조용히 커널에 죽지만, 상한이 있으면 `OutOfMemoryError: Metaspace`라는 **읽을 수 있는 신호**로 바뀝니다. 누구를 붙잡고 있는지는 힙 덤프에서 클래스로더의 참조 경로를 따라가 찾습니다. 운영 배포는 핫 리로드 대신 프로세스 교체로 하는 게 정공법입니다.

**함정 5 — 힙을 32GB 근처로 올린다**

- **증상**: `-Xmx31g`에서 `-Xmx33g`로 올렸는데 GC 빈도가 줄지 않거나 오히려 늘어납니다.
- **원인**: 압축 포인터가 커버하는 범위가 32GB입니다. 이를 넘으면 압축이 꺼지고 모든 참조가 4바이트에서 8바이트로 늘어납니다. 늘어난 2GB보다 참조 확장으로 낭비되는 양이 더 클 수 있습니다.
- **해법**: 32GB 경계에 걸치지 않습니다. 그 이하로 유지하거나, 넘겨야 한다면 손해를 상쇄할 만큼 확실히 크게 올립니다. 인스턴스 하나에 JVM을 여러 개 띄워 각각 32GB 아래로 두는 것도 흔한 선택입니다.

## 8. 정리

- 영역을 나눈 기준은 **공유 범위와 수명**입니다. 수명이 정해진 것은 스택에, 안 정해진 것은 힙에, 클래스로더와 함께 사는 것은 메타스페이스에 둡니다.
- **`-Xmx`는 힙만 제한합니다.** 스택·메타스페이스·코드 캐시·네이티브는 그 밖에 있고, 컨테이너 한도는 그 전부를 봅니다.
- `OutOfMemoryError`는 한 종류가 아닙니다. **메시지 뒷부분이 어느 영역인지 알려줍니다.** 그걸 읽기 전에 설정을 바꾸면 시간만 씁니다.
- 스택 부족은 `StackOverflowError`, 스레드 생성 실패는 `OutOfMemoryError`입니다. 이름은 비슷하지만 원인 영역이 정반대입니다.
- 기본값은 외우지 말고 `-XX:+PrintFlagsFinal`로 출력합니다. 플랫폼과 버전마다 다릅니다.
- 힙이 정상인데 RSS가 크면 힙 덤프가 아니라 **NMT**를 봅니다.

## 9. 참고자료

- [JVMS §2.5 — Run-Time Data Areas](https://docs.oracle.com/javase/specs/jvms/se8/html/jvms-2.html)
- [HotSpot Virtual Machine Garbage Collection Tuning Guide — Ergonomics](https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html)
- [HotSpot GC Tuning Guide — Other Considerations (Class Metadata)](https://docs.oracle.com/en/java/javase/25/gctuning/other-considerations.html)
- [Troubleshooting Guide — Understand the OutOfMemoryError Exception](https://docs.oracle.com/en/java/javase/25/troubleshoot/troubleshooting-memory-leaks.html)
- [Troubleshooting Guide — Diagnostic Tools](https://docs.oracle.com/en/java/javase/25/troubleshoot/diagnostic-tools.html)
- [java 명령 레퍼런스 (JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html)
- [Java Virtual Machine Enhancements in JDK 7](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/enhancements-7.html)
- JVM 위에서 돈다는 것 자체가 무엇을 주고받는 거래인지는 `daily/day01-jvm-why.md`에서 다룹니다.
