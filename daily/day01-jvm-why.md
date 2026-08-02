# JVM 위에서 실행된다는 게 개발자에게 주는 것

> 이 문서가 답할 질문: **내 Java 코드가 OS가 아니라 JVM이라는 중간 계층 위에서 돌아간다는 사실이, 실무에서 무엇을 바꾸는가?**
>
> 기준 버전: JDK 17 / JDK 21 / JDK 25 (LTS). 실행 결과는 Temurin JDK 17.0.19, Linux x86-64에서 확인했습니다.

## 1. 핵심 개념

Java 소스는 기계어로 컴파일되지 않습니다. `javac`가 만드는 것은 `.class` 파일이고, 그 안에는 **바이트코드(bytecode)** 라는 가상 명령어가 들어 있습니다. 이 명령어를 실제 CPU 명령으로 바꿔 실행하는 프로그램이 자바 가상 머신(JVM, Java Virtual Machine)입니다.

여기서 놓치기 쉬운 점이 하나 있습니다. JVM은 제품 이름이 아니라 **명세(specification)** 입니다. [Java Virtual Machine Specification](https://docs.oracle.com/javase/specs/jvms/se25/html/index.html)이 "바이트코드가 어떻게 동작해야 하는가"를 정의하고, HotSpot·OpenJ9·GraalVM 같은 구현체가 그 명세를 각자 구현합니다. 우리가 실무에서 거의 항상 쓰는 것은 OpenJDK의 HotSpot입니다. 이 문서에서 "JVM"이라고 쓰면 HotSpot을 뜻합니다.

> 이 중간 계층이 없다면, 여러분은 프로덕션에서 죽은 프로세스의 메모리를 스스로 해제해야 하고, 어느 함수가 병목인지 알기 위해 별도 프로파일러를 붙여야 하고, 배포 대상 OS마다 다시 빌드해야 합니다. JVM은 이 셋을 런타임이 대신 해주는 대가로 **워밍업 시간과 메모리 오버헤드**를 청구합니다. 실무에서 마주치는 Java 성능 문제의 상당수는 이 거래 조건을 모르고 쓴 결과입니다.

## 2. 구조

JVM은 크게 네 부분으로 나뉩니다.

| 구성요소 | 역할 | 실무에서 여기가 문제일 때 |
|---|---|---|
| 클래스 로더 | `.class`를 읽어 검증·연결·초기화 | `NoClassDefFoundError`, `UnsupportedClassVersionError` |
| 런타임 데이터 영역 | 힙, 스택, 메타스페이스 등 메모리 구획 | `OutOfMemoryError`, `StackOverflowError` |
| 실행 엔진 | 인터프리터 + JIT 컴파일러 | 배포 직후 응답 지연(워밍업) |
| 가비지 컬렉터 | 도달 불가능한 객체 회수 | Stop-The-World 지연, 힙 부족 |

### 2-1. 확장 지점

JVM은 자기 자신을 들여다보고 조작할 수 있는 공개 인터페이스를 갖고 있습니다. 이게 다른 런타임과 비교했을 때 JVM의 가장 실용적인 차별점입니다.

- **`java.lang.instrument` 에이전트** — `-javaagent`로 클래스 로딩 시점에 바이트코드를 바꿉니다. APM(Application Performance Monitoring) 도구가 코드 한 줄 안 고치고 메서드 호출 시간을 측정하는 원리입니다.
- **JVMTI(JVM Tool Interface)** — 네이티브 레벨 디버깅·프로파일링 인터페이스입니다.
- **JFR(JDK Flight Recorder)** — JVM에 내장된 이벤트 기록기입니다. 별도 설치 없이 GC, 락 경합, 할당, 예외를 기록합니다.
- **`jcmd` 진단 명령** — 실행 중인 JVM에 붙어 스레드 덤프·힙 덤프·플래그 조회를 수행합니다.

7절에서 실제로 써봅니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

바이트코드가 추상적으로 느껴진다면 직접 열어보는 게 가장 빠릅니다.

```java
// OrderAmount.java
public class OrderAmount {
    private final long unitPrice;
    private final int quantity;

    public OrderAmount(long unitPrice, int quantity) {
        this.unitPrice = unitPrice;
        this.quantity = quantity;
    }

    public long total() {
        return unitPrice * quantity;
    }
}
```

```bash
javac OrderAmount.java
javap -c -p OrderAmount.class
```

`total()` 부분의 실제 출력입니다.

```text
  public long total();
    Code:
       0: aload_0
       1: getfield      #7                  // Field unitPrice:J
       4: aload_0
       5: getfield      #13                 // Field quantity:I
       8: i2l
       9: lmul
      10: lreturn
```

읽어볼 지점이 두 개 있습니다.

첫째, 레지스터가 없습니다. `getfield`로 값을 **스택에 밀어 넣고** `lmul`이 스택에서 두 개를 꺼내 곱합니다. JVM은 스택 기반 가상 머신이라 특정 CPU의 레지스터 구조에 묶이지 않습니다. 이게 플랫폼 독립성의 실체입니다.

둘째, `i2l`이 보입니다. `int`인 `quantity`를 `long`으로 넓히는 명령이 **컴파일 시점에 이미 박혀 있습니다.** 타입 변환은 런타임 추론이 아니라 컴파일러가 결정한 결과입니다.

### 3-2. 실행 흐름

소스 한 줄이 CPU까지 가는 경로입니다.

```text
OrderAmount.java
  → [javac]        컴파일: 문법 검사 + 바이트코드 생성
  → OrderAmount.class (major version 61 = Java 17)
  → [클래스 로더]   로딩 → 검증(Verification) → 준비 → 해석 → 초기화
  → [인터프리터]    바이트코드를 한 줄씩 해석 실행 (Tier 0)
  → [프로파일링]    호출 횟수·분기 확률·실제 타입 수집
  → [C1 JIT]       빠르게 컴파일, 계속 프로파일 (Tier 1~3)
  → [C2 JIT]       공격적으로 최적화 (Tier 4)
  → 네이티브 코드 실행
```

핵심은 **왼쪽에서 오른쪽으로 한 번 흐르고 끝나지 않는다**는 점입니다. C2가 만든 코드도 프로파일 가정이 깨지면 폐기되고 인터프리터로 되돌아갑니다(역최적화, deoptimization). "느리게 시작해서 점점 빨라지는" Java의 성능 곡선은 여기서 나옵니다.

말로만 보면 와닿지 않으니 실제로 확인해보겠습니다.

```bash
java -XX:+PrintCompilation Main
```

```text
24    1       3       java.lang.Object::<init> (1 bytes)
26    2       3       java.lang.String::hashCode (60 bytes)
27    3       3       java.lang.String::coder (15 bytes)
28    4     n 0       jdk.internal.misc.Unsafe::getReferenceVolatile (native)
28    5       3       java.lang.String::length (11 bytes)
```

세 번째 열이 티어입니다. `3`은 프로파일링을 유지하는 C1 컴파일이고, 여기까지가 워밍업 구간입니다. 뜨거워진 메서드만 `4`(C2)로 올라갑니다. `main` 하나 도는 짧은 프로그램에서는 `4`가 아예 안 나옵니다. **JVM은 뜨겁지 않은 코드에 최적화 비용을 쓰지 않습니다.**

계층 구조와 각 티어의 의미는 [Microsoft의 OpenJDK Tiered Compilation 해설](https://devblogs.microsoft.com/java/how-tiered-compilation-works-in-openjdk/)에 정리돼 있습니다.

## 4. 특징

### 4-1. JVM이 실제로 개발자에게 주는 것

**(1) 런타임 프로파일 기반 최적화 — AOT 컴파일러가 못 하는 일**

C나 Go의 컴파일러는 실행 전에 최적화를 끝냅니다. 실제 입력이 어떻게 들어올지 모른 채 결정해야 합니다. JVM은 반대입니다. 수천 번 돌려보고 나서 최적화합니다.

```java
public interface DiscountPolicy {
    long apply(long amount);
}
```

인터페이스 호출은 원칙적으로 가상 호출이라 구현체를 매번 찾아야 합니다. 그런데 실제 서비스에서 이 자리에 들어오는 구현체가 `RateDiscountPolicy` 하나뿐이라면, JIT는 프로파일을 보고 "여기는 사실상 단일 타입"이라고 판단해 **호출을 통째로 인라이닝**합니다. 대신 다른 타입이 들어오면 즉시 역최적화하는 안전장치를 겁니다.

인터페이스로 추상화해도 성능이 크게 안 깎이는 이유가 이겁니다. 그래서 Java에서는 DI(의존성 주입)와 인터페이스 분리 같은 설계를 성능 걱정 없이 쓸 수 있습니다.

**(2) 메모리 안전 — 해제를 안 해도 됩니다**

GC가 있어서 `free()`를 호출하지 않고, 그 결과 use-after-free와 이중 해제라는 버그 종류가 통째로 사라집니다. Java에서 메모리 문제는 "해제를 안 했다"가 아니라 "참조를 안 끊었다"(누수)로 형태가 바뀝니다. 진단 난이도가 훨씬 낮습니다.

**(3) 관측 가능성 — 프로세스가 살아있는 채로 안을 봅니다**

이게 실무에서 체감이 가장 큽니다. 프로덕션에서 응답이 느려졌을 때, 프로세스를 죽이지 않고 스레드가 어디서 멈춰 있는지 그 자리에서 볼 수 있습니다.

**(4) 플랫폼 독립 — 단, 조건이 있습니다**

같은 `.class`가 Linux·macOS·Windows에서 돕니다. 다만 6절에서 다루듯 무조건은 아닙니다.

### 4-2. 대신 지불하는 비용

| 비용 | 실무에서 나타나는 모습 |
|---|---|
| 워밍업 | 배포 직후 p99 응답시간이 평소의 몇 배. 몇 분 뒤 정상화 |
| 메모리 오버헤드 | 힙 외에 메타스페이스, 코드 캐시, 스레드 스택, GC 구조체가 따로 필요 |
| GC 일시정지 | 애플리케이션 스레드가 멈추는 구간이 존재 |
| 시작 시간 | 클래스 로딩·검증·링킹에 수백 ms~수 초 |

**공짜가 아닙니다.** 짧게 뜨고 죽는 워크로드(Lambda 같은 FaaS, CLI 도구)에서는 이 비용이 이득보다 커집니다. 9절에서 대안을 봅니다.

## 5. 예제 — 워밍업을 모르고 짠 배포

### 5-1. 워밍업을 무시한 설정 ❌

```yaml
# ❌ 배포 직후 인스턴스에 곧바로 100% 트래픽이 들어갑니다
management:
  endpoint:
    health:
      show-details: never

# ALB/K8s 헬스체크: 포트가 열리면 곧바로 정상 판정
readinessProbe:
  tcpSocket:
    port: 8080
  initialDelaySeconds: 5
```

무슨 일이 벌어지느냐면, 포트는 열렸지만 애플리케이션 코드는 아직 인터프리터로 돌고 있습니다. 로드밸런서는 이 인스턴스를 정상으로 보고 트래픽을 균등 분배합니다. 첫 수천 요청이 몰리면서 응답이 느려지고, 응답이 느려지니 헬스체크 타임아웃이 나고, 인스턴스가 빠지고, 남은 인스턴스에 트래픽이 몰립니다. **배포할 때마다 알 수 없는 스파이크가 생기는** 전형적인 패턴입니다.

### 5-2. 워밍업을 고려한 설정 ✔️

```java
// ✅ 트래픽을 받기 전에 핵심 경로를 미리 실행해 JIT를 데웁니다
@Component
public class WarmupRunner implements ApplicationRunner {

    private final OrderQueryService orderQueryService;

    public WarmupRunner(OrderQueryService orderQueryService) {
        this.orderQueryService = orderQueryService;
    }

    @Override
    public void run(ApplicationArguments args) {
        // 실제 조회 경로를 반복 호출해 인터프리터 → C1 → C2 승격을 유도합니다.
        for (int i = 0; i < 2_000; i++) {
            orderQueryService.findRecentSummary(1L);
        }
    }
}
```

```yaml
# ✅ 워밍업이 끝난 뒤에만 트래픽을 받도록 readiness를 분리합니다
management:
  endpoints:
    web:
      exposure:
        include: health
  endpoint:
    health:
      probes:
        enabled: true          # /actuator/health/readiness 활성화

readinessProbe:
  httpGet:
    path: /actuator/health/readiness
    port: 8080
  initialDelaySeconds: 20
  periodSeconds: 5
```

`ApplicationRunner`는 컨텍스트 초기화가 끝난 뒤 실행되고, Spring Boot는 그때까지 readiness를 `OUT_OF_SERVICE`로 유지합니다. 즉 **워밍업이 끝날 때까지 트래픽이 안 들어옵니다.** ([Spring Boot Kubernetes Probes 문서](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html#actuator.endpoints.kubernetes-probes))

주의할 점은 워밍업 루프가 만능이 아니라는 겁니다. 실제 트래픽과 다른 파라미터로 데우면 JIT가 잘못된 프로파일을 학습하고, 진짜 트래픽이 들어왔을 때 역최적화가 일어납니다. **워밍업은 실제 요청과 같은 코드 경로여야 의미가 있습니다.**

## 6. "한 번 작성하면 어디서나 실행"의 실제 계약

이 슬로건은 절반만 맞습니다. 정확한 계약은 **"낮은 버전으로 컴파일하면 높은 버전 JVM에서 실행된다"** 입니다. 역방향은 성립하지 않습니다.

`.class` 파일 헤더에는 클래스 파일 버전이 박힙니다.

```bash
javap -v OrderAmount.class | grep "major version"
# major version: 61
```

| Java 버전 | 클래스 파일 major version |
|---|---:|
| 8 | 52 |
| 11 | 55 |
| 17 | 61 |
| 21 | 65 |
| 25 | 69 |

([Java Version Almanac — Bytecode Versions](https://javaalmanac.io/bytecode/versions/))

### 6-1. 계약을 어긴 빌드 ❌

```dockerfile
# ❌ 빌드는 21, 실행은 17
FROM eclipse-temurin:21-jdk AS build
COPY . /src
WORKDIR /src
RUN ./gradlew bootJar

FROM eclipse-temurin:17-jre
COPY --from=build /src/build/libs/app.jar /app.jar
ENTRYPOINT ["java", "-jar", "/app.jar"]
```

CI는 초록불입니다. 컨테이너를 띄우는 순간 터집니다.

```text
java.lang.UnsupportedClassVersionError: com/example/order/OrderApplication
  has been compiled by a more recent version of the Java Runtime
  (class file version 65.0), this version of the Java Runtime only
  recognizes class file versions up to 61.0
```

에러 메시지가 친절합니다. `65.0`은 Java 21, `61.0`은 Java 17입니다. 이 숫자만 위 표에서 찾으면 원인 규명은 끝납니다.

### 6-2. 계약을 지킨 빌드 ✔️

```dockerfile
# ✅ 빌드와 런타임의 메이저 버전을 일치시킵니다
FROM eclipse-temurin:21-jdk AS build
COPY . /src
WORKDIR /src
RUN ./gradlew bootJar

FROM eclipse-temurin:21-jre
COPY --from=build /src/build/libs/app.jar /app.jar
ENTRYPOINT ["java", "-jar", "/app.jar"]
```

런타임 버전을 못 올리는 상황이라면 `--release`로 컴파일 타깃을 낮춥니다.

```bash
# ✅ JDK 21로 빌드하되 17에서 돌아가는 클래스 파일을 생성합니다
javac --release 17 -d out src/main/java/com/example/order/*.java
```

`--release`는 `-target`과 달리 **해당 버전의 표준 API 집합까지 함께 제한합니다.** `-source`/`-target`만 쓰면 Java 17에 없는 메서드를 호출하는 코드가 컴파일을 통과했다가 런타임에 `NoSuchMethodError`로 터집니다. `--release`를 쓰세요.

## 7. 확장 지점 활용 — 돌아가는 JVM 들여다보기

응답이 느려졌다는 신고가 들어왔습니다. 재시작하지 말고 먼저 봅니다.

```bash
# 1. 프로세스 확인
jcmd -l

# 2. 스레드가 어디서 멈춰 있는가
jcmd <pid> Thread.print | grep -A 15 "BLOCKED"

# 3. 힙에서 무엇이 메모리를 먹고 있는가 (상위 20개 클래스)
jcmd <pid> GC.class_histogram | head -25

# 4. 지금 이 JVM에 실제로 적용된 플래그는 무엇인가
jcmd <pid> VM.flags
```

특히 4번을 습관화할 가치가 있습니다. `-Xmx`를 안 줬다면 JVM이 알아서 정했는데, 그 값이 얼마인지 추측하지 말고 확인합니다.

원인 파악이 안 되면 JFR로 일정 시간 기록합니다.

```bash
# 60초간 기록 (프로덕션에서 상시 켜기에 부담이 낮은 프로파일)
jcmd <pid> JFR.start name=diag settings=profile duration=60s filename=/tmp/diag.jfr

# 완료 후 JDK Mission Control 또는 CLI로 분석
jfr summary /tmp/diag.jfr
jfr print --events jdk.GarbageCollection /tmp/diag.jfr | head -40
```

이게 4-1의 (3)에서 말한 관측 가능성의 실체입니다. 별도 에이전트 설치, 재배포, 코드 수정 없이 **살아있는 프로덕션 프로세스의 GC·락·할당 이벤트를 그대로 뽑습니다.** ([JDK Flight Recorder 문서](https://docs.oracle.com/en/java/javase/25/jfapi/flight-recorder-configurations.html))

## 8. 실무에서 만나는 JVM — 컨테이너

JVM이 "알아서 해준다"는 점이 컨테이너에서는 함정이 됩니다.

JVM은 시작할 때 하드웨어를 보고 힙 크기와 GC를 스스로 정합니다. [Oracle GC 튜닝 가이드 — Ergonomics](https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html) 기준으로,

- **최대 힙**: 물리 메모리의 1/4
- **초기 힙**: 물리 메모리의 1/64
- **GC**: 서버급 머신(CPU 2개 이상 **그리고** 물리 메모리 1792MB 이상)이면 G1, 아니면 Serial

직접 확인해보면 이렇습니다. 메모리 16GB(정확히는 15,989MB) 장비에서,

```bash
java -XX:+PrintFlagsFinal -version | grep -E "MaxHeapSize|MaxRAMPercentage|UseG1GC|UseContainerSupport"
```

```text
   size_t MaxHeapSize     = 4192206848    {product} {ergonomic}
   double MaxRAMPercentage = 25.000000    {product} {default}
     bool UseContainerSupport = true      {product} {default}
     bool UseG1GC           = true        {product} {ergonomic}
```

`MaxHeapSize`가 약 4.19GB, 정확히 25%입니다. `{ergonomic}`이라는 표시는 "사용자가 안 줘서 JVM이 정했다"는 뜻입니다.

컨테이너에서는 `UseContainerSupport`(JDK 10 이후 기본 활성, [`java` 커맨드 문서](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html))가 cgroup 제한을 읽어 이 "물리 메모리"를 컨테이너 한도로 대체합니다. 즉 **컨테이너에 1GB를 주면 힙은 약 256MB만 잡힙니다.** 나머지 750MB는 놀고 있는데 애플리케이션은 `OutOfMemoryError`를 냅니다.

```yaml
# ❌ 컨테이너 메모리는 늘렸는데 힙은 그대로 25%
resources:
  limits:
    memory: "2Gi"
```

```yaml
# ✅ 힙 비율을 명시합니다
resources:
  limits:
    memory: "2Gi"
env:
  - name: JAVA_TOOL_OPTIONS
    value: "-XX:MaxRAMPercentage=70.0"
```

70%로 두는 이유는 나머지 30%가 필요하기 때문입니다. **힙은 JVM 메모리의 전부가 아닙니다.** 메타스페이스, 코드 캐시, 스레드 스택, GC 내부 구조체, 네이티브 버퍼가 힙 밖에 따로 있습니다. 100%로 두면 힙은 안 넘쳤는데 컨테이너가 OOM Killer에 죽습니다. 로그에는 아무것도 안 남고 파드만 `OOMKilled`로 재시작됩니다.

한편 시작 시간 문제는 최근 개선되고 있습니다. Project Leyden의 [JEP 483(Ahead-of-Time Class Loading & Linking, JDK 24)](https://openjdk.org/jeps/483)은 클래스 로딩·링킹 결과를 캐시에 저장해 다음 실행에서 재사용하고, [JEP 515(Ahead-of-Time Method Profiling, JDK 25)](https://openjdk.org/jeps/515)는 여기에 **이전 실행에서 수집한 메서드 프로파일까지 담습니다.** JIT가 프로파일을 처음부터 모으지 않고 시작 시점에 읽어들이므로 워밍업 구간이 짧아집니다. 5절의 워밍업 문제를 런타임 차원에서 줄이려는 시도입니다.

<!-- TODO: JEP 483/515 본문에 명시된 구체적 개선 수치(Spring PetClinic 기준 등)를 인용하려 했으나 openjdk.org가 자동 조회를 차단(HTTP 403)해 1차 출처 확인에 실패했습니다. 수치는 원칙 3에 따라 생략했습니다. 수동으로 JEP 원문을 확인 후 보강이 필요합니다. -->

## 9. 관련 개념과 비교 — JVM vs Native Image

JVM의 비용이 감당 안 되는 워크로드가 있습니다. GraalVM Native Image는 Java 코드를 AOT 컴파일해 **JVM 없이 도는 네이티브 실행 파일**로 만듭니다.

| | JVM (HotSpot) | GraalVM Native Image |
|---|---|---|
| 시작 시간 | 상대적으로 느림 (클래스 로딩·링킹) | 빠름 (이미 링크된 바이너리) |
| 최고 성능 | 런타임 프로파일 기반 최적화로 유리 | 실행 전 정보만으로 최적화 |
| 메모리 | 힙 외 오버헤드 큼 | 작음 |
| 리플렉션·동적 프록시 | 제약 없음 | 빌드 시 설정으로 등록 필요 |
| 진단 도구 | `jcmd`, JFR, 힙 덤프 | 제한적 |
| 빌드 시간 | 짧음 | 김 (분 단위) |

판단 기준은 **프로세스가 얼마나 오래 사는가**입니다.

- 상시 떠 있는 API 서버 → JVM. 워밍업 비용은 한 번이고, 이후 런타임 최적화 이득을 계속 가져갑니다.
- 요청마다 뜨고 죽는 FaaS, 자주 스케일 인/아웃하는 배치, CLI → Native Image를 검토할 가치가 있습니다.

"Native Image가 더 빠르다"는 말은 부정확합니다. **시작이 빠르고 최고 성능은 대체로 JVM이 유리합니다.** 두 축을 구분해서 봐야 합니다. ([GraalVM Native Image 문서](https://www.graalvm.org/latest/reference-manual/native-image/))

## 10. 함정

### 함정 1 — 컨테이너 메모리를 늘렸는데 OOM이 그대로입니다

- **증상**: `resources.limits.memory`를 1Gi에서 2Gi로 올렸는데 `java.lang.OutOfMemoryError: Java heap space`가 계속 납니다.
- **원인**: 힙은 컨테이너 한도의 25%만 씁니다. 2Gi로 올려도 힙은 512MB입니다. 컨테이너 메모리와 힙 크기는 자동으로 비례하지만 비율은 그대로입니다.
- **해법**: `-XX:MaxRAMPercentage`를 명시합니다(60~75% 사이에서 시작해 실측으로 조정). `-Xmx`로 절대값을 박으면 파드 스펙을 바꿀 때마다 같이 고쳐야 하니 비율 지정이 낫습니다. 적용 후 `jcmd <pid> VM.flags`로 실제 반영을 확인합니다.

### 함정 2 — 배포 직후에만 응답이 느립니다

- **증상**: 배포 후 1~3분간 p99 지연이 평소의 5~10배. 아무것도 안 해도 저절로 정상화됩니다.
- **원인**: 워밍업입니다. 코드가 아직 인터프리터/C1에서 돌고 있습니다. 여기에 커넥션 풀·캐시가 비어 있는 것까지 겹칩니다.
- **해법**: readiness 프로브를 워밍업 완료와 연결합니다(5-2). 배포 전략을 롤링에서 카나리로 바꿔 트래픽을 점진 유입시키는 것도 방법입니다. 이 지연이 "느려진 것"이 아니라 "원래 그런 것"이라는 걸 팀이 알고 있어야 알림 기준도 제대로 잡힙니다.

### 함정 3 — `availableProcessors()`가 호스트 CPU를 반환합니다

- **증상**: 컨테이너에 CPU 0.5코어를 줬는데 스레드 풀이 수십 개로 잡히고 스레드 경합만 심해집니다.
- **원인**: `Runtime.getRuntime().availableProcessors()`는 CPU 개수를 보고 값을 정하는데, cgroup CPU 제한이 **정수 코어가 아닌 quota 형태**일 때 해석이 환경마다 달라질 수 있습니다. `ForkJoinPool.commonPool()`, 여러 라이브러리의 기본 스레드 수, GC 스레드 수가 모두 이 값에서 파생됩니다.
- **해법**: 추측하지 말고 JVM이 무엇을 인식했는지 직접 봅니다.
  ```bash
  java -XshowSettings:system -version
  ```
  ```text
  Operating System Metrics:
      Provider: cgroupv2
      Effective CPU Count: 4
      CPU Period: 100000us
      CPU Quota: -1
      Memory Limit: Unlimited
  ```
  `Effective CPU Count`가 JVM이 실제로 쓰는 값입니다. 여기가 의도와 다르면 `-XX:ActiveProcessorCount=<n>`으로 명시합니다(기본값 `-1`은 "자동 감지"라는 뜻이라 `PrintFlagsFinal`로는 실제 감지 결과를 알 수 없습니다). CPU limit은 정수 코어로 주는 편이 예측 가능성이 높습니다.

### 함정 4 — 로컬은 되는데 서버에서 `UnsupportedClassVersionError`

- **증상**: 로컬 실행은 정상, 배포 후 기동 즉시 실패합니다.
- **원인**: 빌드 JDK와 런타임 JDK 메이저 버전이 다릅니다. 멀티스테이지 Dockerfile에서 빌드 이미지만 올리고 런타임 이미지를 안 올린 경우가 가장 흔합니다.
- **해법**: 에러 메시지의 `class file version` 숫자를 6절 표에서 찾아 어느 버전으로 컴파일됐는지 확인합니다. 두 이미지 태그를 맞추거나, 런타임을 못 올리면 `--release`로 타깃을 낮춥니다(`-source`/`-target`만으로는 API 차이를 못 막습니다).

### 함정 5 — GC 튜닝부터 시작합니다

- **증상**: 성능 문제가 생기자 `-XX:+UseParallelGC`, `-XX:NewRatio` 같은 플래그를 검색해서 붙여봅니다. 나아지지 않거나 오히려 나빠집니다.
- **원인**: 병목이 GC가 아닌데 GC를 만졌습니다. 대부분의 지연은 GC가 아니라 느린 쿼리, 외부 API 대기, 락 경합에서 옵니다.
- **해법**: 순서를 지킵니다. **측정 → 원인 특정 → 조치**입니다. 먼저 GC 로그를 켜서 실제로 GC가 시간을 먹는지 봅니다.
  ```bash
  java -Xlog:gc*:file=/var/log/app/gc.log:time,uptime:filecount=5,filesize=20M -jar app.jar
  ```
  GC 일시정지 합계가 전체 시간의 미미한 비중이라면 GC는 범인이 아닙니다. 플래그를 지우고 7절 도구로 돌아가세요.

## 11. 참고자료

- [The Java Virtual Machine Specification, Java SE 25](https://docs.oracle.com/javase/specs/jvms/se25/html/index.html) — 바이트코드 명령어와 클래스 파일 포맷의 1차 출처
- [HotSpot Virtual Machine GC Tuning Guide — Ergonomics (JDK 25)](https://docs.oracle.com/en/java/javase/25/gctuning/ergonomics.html) — 기본 힙 크기와 GC 자동 선택 규칙
- [`java` Command 문서 (JDK 25)](https://docs.oracle.com/en/java/javase/25/docs/specs/man/java.html) — `UseContainerSupport`, `TieredCompilation` 등 플래그 기본값
- [How Tiered Compilation works in OpenJDK — Microsoft](https://devblogs.microsoft.com/java/how-tiered-compilation-works-in-openjdk/) — Tier 0~4의 의미
- [JEP 483: Ahead-of-Time Class Loading & Linking](https://openjdk.org/jeps/483) / [JEP 515: Ahead-of-Time Method Profiling](https://openjdk.org/jeps/515) — 시작 시간·워밍업 개선
- [Java Version Almanac — Bytecode Versions](https://javaalmanac.io/bytecode/versions/) — 클래스 파일 버전 대응표
- [Spring Boot — Kubernetes Probes](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html#actuator.endpoints.kubernetes-probes) — readiness와 워밍업 연결
- [GraalVM Native Image](https://www.graalvm.org/latest/reference-manual/native-image/) — AOT 대안
