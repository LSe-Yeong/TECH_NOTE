# 헬스체크 엔드포인트 제대로 만들기 — 무엇을 검사하고, 무엇을 검사하면 안 되는가

## 1. 핵심 개념

헬스체크 엔드포인트는 애플리케이션이 자기 상태를 외부에 보고하는 HTTP 엔드포인트입니다. 응답 코드 하나가 전부입니다. 200이면 정상, 그 외면 비정상.

문제는 이 엔드포인트를 읽는 쪽이 그 결과로 **실제 행동을 한다**는 겁니다. 쿠버네티스는 컨테이너를 재시작하고, 로드밸런서는 라우팅 대상에서 뺍니다. 헬스체크는 관측용 지표가 아니라 **자동화된 조치를 발동시키는 트리거**입니다.

> `/health`에 DB 커넥션 검사를 넣어두고 잊고 있다가, DB가 30초 흔들린 순간 전체 인스턴스가 동시에 재시작되는 사고가 여기서 나옵니다. DB는 30초 뒤 돌아왔지만 서비스는 5분간 죽어 있습니다. 헬스체크가 없었다면 30초만 느렸을 장애입니다.

그래서 이 문서가 답할 질문은 하나입니다. **어떤 검사를 어느 엔드포인트에 넣어야 헬스체크가 장애를 키우지 않는가.**

기준 버전은 Spring Boot 3.5 / 4.1, Kubernetes 공식 문서 기준입니다.

---

## 2. 구조 — 세 가지 질문은 세 가지 엔드포인트다

헬스체크를 하나로 만들려는 순간부터 꼬입니다. 물어보는 질문이 셋이고, 답에 따른 조치가 전부 다르기 때문입니다.

| 질문 | 프로브 | 실패했을 때 벌어지는 일 |
|---|---|---|
| 프로세스가 살아 있고 진행 가능한가 | liveness | kubelet이 컨테이너를 **재시작**합니다 |
| 지금 트래픽을 받아도 되는가 | readiness | Pod IP가 Service의 EndpointSlice에서 **제거**됩니다. 재시작은 안 합니다 |
| 기동이 끝났는가 | startup | 컨테이너를 죽이고 restartPolicy를 따릅니다. 성공 전까지 liveness/readiness는 **실행되지 않습니다** |

출처: [Kubernetes — Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)

여기서 검사 내용을 결정하는 규칙이 그대로 나옵니다.

- **재시작해서 고쳐지는 문제만 liveness에 넣습니다.** 데드락, 힙 고갈 직전, 이벤트 루프 정지처럼 프로세스 자신이 망가진 경우입니다.
- **트래픽을 빼면 고쳐지거나, 트래픽을 빼는 게 이득인 문제만 readiness에 넣습니다.** 캐시 워밍업 중, 기동 직후, 종료 시작 직후입니다.
- **어느 쪽으로도 안 고쳐지는 문제는 헬스체크에 넣지 않습니다.** DB 장애가 대표적입니다. 재시작해도 DB는 안 살아나고, 트래픽을 빼도 갈 곳이 없습니다.

### 2-1. 왜 liveness에 외부 의존성을 넣으면 안 되는가

Spring 공식 문서가 이 부분을 직접 경고합니다. liveness 프로브가 외부 시스템 상태에 의존하면, DB나 외부 API가 죽었을 때 쿠버네티스가 **모든 인스턴스를 재시작**하고 연쇄 장애를 만든다는 내용입니다([Spring Boot Actuator — Kubernetes Probes](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html#actuator.endpoints.kubernetes-probes)).

메커니즘은 단순합니다.

```
DB 다운 → 전 인스턴스 liveness 실패 → 전 인스턴스 동시 재시작
       → 새 인스턴스도 DB에 못 붙음 → 또 실패 → 또 재시작 (CrashLoopBackOff)
       → DB가 돌아와도 재시작 백오프 때문에 복구가 더 늦어짐
```

DB가 죽은 시간보다 **서비스가 죽은 시간이 길어집니다.** 헬스체크가 장애를 증폭시킨 겁니다.

### 2-2. readiness에 넣는 것도 공짜가 아니다

"그럼 DB 검사는 readiness에 넣으면 되겠네"가 다음 결론인데, 절반만 맞습니다. 쿠버네티스 공식 문서는 필수 백엔드 의존성이 있는 경우 liveness는 자기 자신만, readiness는 의존성까지 검사하는 조합을 제시합니다. 하지만 **모든 인스턴스가 같은 DB를 본다면** readiness도 동시에 전부 실패합니다.

이때 소비자가 어떻게 반응하는지 알아둬야 합니다.

- **쿠버네티스**: Service의 엔드포인트가 0개가 되고, 들어오는 요청은 연결 자체가 실패합니다. 애플리케이션 로그에 아무것도 안 남습니다.
- **ALB**: 타깃 그룹의 모든 타깃이 unhealthy가 되면 로드밸런서는 **fail-open**으로 동작해서 상태와 무관하게 전 타깃으로 라우팅합니다([AWS — Health checks for ALB target groups](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html)).

정리하면 **전 인스턴스가 동시에 unready가 되는 검사는 넣어봐야 의미가 없거나, 상황을 나쁘게 만듭니다.** DB가 죽었을 때 클라이언트가 받을 응답이 "연결 거부"인 것보다 "503 + 에러 코드"인 편이 낫습니다. 후자는 재시도 정책을 태울 수 있고 로그도 남습니다.

의존성을 이렇게 나눠 판단합니다.

| 구분 | 예 | readiness에 넣는가 |
|---|---|---|
| 인스턴스별로 다르게 실패하는 것 | 로컬 캐시 워밍업, 이 인스턴스만 붙은 샤드, 리더 선출 상태 | 넣습니다. 트래픽이 건강한 인스턴스로 갑니다 |
| 전 인스턴스가 함께 실패하는 것 | 공용 RDS, 공용 Redis | 넣지 않습니다. 애플리케이션에서 503으로 처리합니다 |
| 없어도 일부 기능만 죽는 것 | 추천 API, 검색 엔진, 메일 발송 | 넣지 않습니다. 부분 장애로 전체를 내리는 셈입니다 |

---

## 3. 흐름

### 3-1. 코드로 보는 구성

Spring Boot Actuator는 liveness/readiness를 **헬스 그룹**으로 제공합니다. Spring Boot 3.x에서는 쿠버네티스 환경으로 감지될 때만 자동 활성화되고, 그 외 환경에서는 명시적으로 켜야 합니다. Spring Boot 4부터는 기본 활성화입니다.

```yaml
# application.yml — Spring Boot 3.5 기준
management:
  server:
    port: 8081                      # 애플리케이션 포트와 분리 (트레이드오프는 §5 참고)
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  endpoint:
    health:
      probes:
        enabled: true               # Spring Boot 4는 기본값이 true
      show-details: never           # 기본값. 의존성 구성을 외부에 노출하지 않습니다
      group:
        liveness:
          include: livenessState    # 외부 의존성 금지
        readiness:
          include: readinessState,orderCacheWarmup
  health:
    defaults:
      enabled: false                # 자동 등록되는 indicator를 전부 끄고 필요한 것만 켭니다
    db:
      enabled: true                 # /actuator/health 에서는 보고 싶으니 켜둡니다
```

`management.health.defaults.enabled: false`가 핵심입니다. 이걸 안 끄면 `db`, `diskspace`, `redis`, `ssl`, `mail` 등 클래스패스에 있는 만큼 전부 자동 등록되고, 그 집계 결과가 `/actuator/health`가 됩니다([자동 구성 HealthIndicator 목록](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html)).

인스턴스 고유 상태를 검사하는 커스텀 indicator는 이렇게 씁니다.

```java
package com.example.order.health;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

/**
 * 이 인스턴스의 로컬 캐시 적재가 끝났는지만 봅니다.
 * 인스턴스마다 결과가 다를 수 있는 검사여야 readiness에 넣을 값어치가 있습니다.
 */
@Component("orderCacheWarmup")
public class OrderCacheWarmupHealthIndicator implements HealthIndicator {

    private final OrderCategoryCache categoryCache;

    public OrderCacheWarmupHealthIndicator(OrderCategoryCache categoryCache) {
        this.categoryCache = categoryCache;
    }

    @Override
    public Health health() {
        if (!categoryCache.isLoaded()) {
            return Health.outOfService()
                    .withDetail("loadedCount", categoryCache.size())
                    .build();
        }
        return Health.up().build();
    }
}
```

빈 이름(`orderCacheWarmup`)이 곧 그룹 설정에서 쓰는 키입니다. `HealthIndicator` 접미사는 이름에서 잘려나갑니다.

### 3-2. 실행 흐름

기동부터 종료까지 상태가 이렇게 움직입니다.

```
1. 컨테이너 시작
   startup 프로브만 실행됨 → liveness/readiness는 아직 호출되지 않음
2. 애플리케이션 컨텍스트 리프레시 완료
   LivenessState = CORRECT       → /actuator/health/liveness 200
3. 서블릿 컨테이너가 포트 리스닝 시작 (ApplicationReadyEvent)
   ReadinessState = ACCEPTING_TRAFFIC → /actuator/health/readiness 200
   → startup 프로브 성공 → 이때부터 liveness/readiness 주기 실행
   → Service EndpointSlice에 Pod IP 등록 → 트래픽 유입
4. SIGTERM 수신
   ReadinessState = REFUSING_TRAFFIC → readiness 503
   → EndpointSlice에서 제거 → 신규 트래픽 차단
   → liveness는 계속 200 (아직 죽으면 안 되므로)
5. 진행 중이던 요청 처리 완료 후 종료
```

4번이 배포 시 요청이 끊기지 않게 하는 지점입니다. 자세한 내용은 `daily/day18-graceful-shutdown.md`에 있습니다. 여기서 중요한 건 **종료 중에 readiness는 실패하지만 liveness는 성공해야 한다**는 점입니다. 둘을 같은 엔드포인트로 두면 종료 시작과 동시에 SIGKILL을 맞습니다.

---

## 4. 상태와 HTTP 코드의 매핑

Actuator의 기본 매핑입니다.

| Health Status | HTTP 코드 |
|---|---|
| `UP` | 200 |
| `UNKNOWN` | **200** |
| `DOWN` | 503 |
| `OUT_OF_SERVICE` | 503 |

`UNKNOWN`이 200인 게 함정입니다. 커스텀 indicator에서 예외를 삼키고 `Health.unknown()`을 반환하면 소비자 입장에서는 **정상과 구분되지 않습니다.** 판정이 안 되면 `UNKNOWN`이 아니라 `DOWN`을 반환해야 합니다.

ALB의 성공 코드(Matcher) 기본값도 200 하나뿐입니다. 204나 3xx를 반환하도록 만들면 `Target.ResponseCodeMismatch`로 계속 unhealthy가 됩니다.

---

## 5. 소비자 쪽 설정 — 기본값을 그대로 쓰면 안 되는 것들

엔드포인트를 잘 만들어도 프로브 파라미터가 틀리면 결과는 같습니다.

**Kubernetes 프로브 기본값** ([공식 문서](https://kubernetes.io/docs/concepts/workloads/pods/probes/))

| 필드 | 기본값 | 실무에서 손대는 이유 |
|---|---:|---|
| `initialDelaySeconds` | 0 | startup 프로브를 쓰면 손댈 필요가 없습니다 |
| `periodSeconds` | 10 | liveness는 더 늘려도 됩니다 |
| `timeoutSeconds` | **1** | JVM은 GC 정지만으로 1초를 넘길 수 있습니다 |
| `failureThreshold` | 3 | 일시적 실패를 흡수하는 유일한 장치입니다 |
| `successThreshold` | 1 | readiness에서 플래핑이 심하면 올립니다 |

`timeoutSeconds: 1`이 특히 위험합니다. Stop-the-world GC 한 번에 liveness가 실패로 기록되고, 그게 3번 연속이면 정상 인스턴스가 재시작됩니다.

```yaml
livenessProbe:
  httpGet:
    path: /actuator/health/liveness
    port: 8081
  periodSeconds: 20
  timeoutSeconds: 5
  failureThreshold: 3       # 최악의 경우 감지까지 20*3 = 60초
readinessProbe:
  httpGet:
    path: /actuator/health/readiness
    port: 8081
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
startupProbe:               # 기동이 느린 애플리케이션에 필수
  httpGet:
    path: /actuator/health/liveness
    port: 8081
  periodSeconds: 5
  failureThreshold: 60      # 최대 300초까지 기동을 기다립니다
```

**ALB 타깃 그룹 기본값** ([AWS 문서](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html))

| 설정 | 기본값 |
|---|---:|
| `HealthCheckIntervalSeconds` | 30초 |
| `HealthCheckTimeoutSeconds` | 5초 |
| `UnhealthyThresholdCount` | 2 |
| `HealthyThresholdCount` | 5 |
| `Matcher` | 200 |

기본값 그대로면 인스턴스가 죽어도 **최대 60초(30초 × 2회)** 동안 트래픽이 계속 들어갑니다. 반대로 복구 판정에는 최대 150초가 걸립니다. 배포 시간이 길게 느껴진다면 여기부터 봅니다.

### 5-1. 관리 포트를 분리할 것인가

`management.server.port`로 Actuator를 별도 포트에 두면 헬스체크 엔드포인트가 외부에 노출되지 않고, 애플리케이션 트래픽과 섞이지 않습니다. 대신 대가가 있습니다.

- **분리하면**: 서블릿 스레드 풀이 고갈돼 실제 요청이 하나도 처리되지 않는 상태에서도 헬스체크는 200을 반환합니다. 로드밸런서는 이 좀비 인스턴스에 계속 트래픽을 보냅니다.
- **분리하지 않으면**: 스레드 고갈이 헬스체크 실패로 드러납니다. 대신 부하가 몰린 순간 전 인스턴스가 동시에 빠질 수 있고, Actuator 엔드포인트를 외부 노출에서 막는 책임이 생깁니다.

정답은 없습니다. 다만 관리 포트를 분리했다면 **스레드 풀 포화는 헬스체크가 아니라 메트릭과 알림으로 잡아야 한다**는 걸 인지하고 있어야 합니다. `management.endpoint.health.probes.add-additional-paths=true`를 쓰면 메인 포트에도 `/livez`, `/readyz`가 추가로 열려서 절충안이 됩니다.

---

## 6. 예제

### 6-1. 흔한 헬스체크 ❌

```java
@RestController
public class HealthController {

    private final JdbcTemplate jdbcTemplate;
    private final RestClient recommendationClient;

    @GetMapping("/health")
    public ResponseEntity<String> health() {
        try {
            jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            // 추천 서비스는 없어도 주문은 되는데 여기서 검사합니다
            recommendationClient.get().uri("/health").retrieve().toBodilessEntity();
            return ResponseEntity.ok("OK");
        } catch (Exception e) {
            return ResponseEntity.status(503).body("DOWN");
        }
    }
}
```

문제가 셋입니다.

1. liveness와 readiness를 구분하지 않습니다. 이 엔드포인트를 liveness에 물리면 DB 장애가 전 인스턴스 재시작이 됩니다.
2. 소프트 의존성인 추천 서비스가 전체 인스턴스를 내립니다.
3. 타임아웃이 없습니다. 추천 서비스가 응답하지 않으면 헬스체크 요청 자체가 매달립니다.

### 6-2. 개선한 코드 ✔️

```java
package com.example.order.health;

import java.time.Duration;
import java.time.Instant;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

/**
 * readiness 후보: 이 인스턴스가 담당 샤드에 붙었는지 확인합니다.
 * 인스턴스마다 결과가 갈리므로 트래픽을 빼면 실제로 이득이 있습니다.
 * 결과는 짧게 캐싱해서 프로브 주기보다 자주 실제 검사가 돌지 않게 합니다.
 */
@Component("shardConnection")
public class ShardConnectionHealthIndicator implements HealthIndicator {

    private static final Duration CACHE_TTL = Duration.ofSeconds(3);

    private final OrderShardRegistry shardRegistry;
    private volatile Health cached = Health.up().build();
    private volatile Instant checkedAt = Instant.EPOCH;

    public ShardConnectionHealthIndicator(OrderShardRegistry shardRegistry) {
        this.shardRegistry = shardRegistry;
    }

    @Override
    public Health health() {
        if (Duration.between(checkedAt, Instant.now()).compareTo(CACHE_TTL) < 0) {
            return cached;
        }
        Health result;
        try {
            String shardId = shardRegistry.assignedShardId();
            result = (shardId == null)
                    ? Health.outOfService().withDetail("reason", "shard not assigned").build()
                    : Health.up().withDetail("shardId", shardId).build();
        } catch (Exception e) {
            // 판정 불가를 UNKNOWN(200)으로 흘리지 않습니다
            result = Health.down(e).build();
        }
        cached = result;
        checkedAt = Instant.now();
        return result;
    }
}
```

DB는 이 그룹에서 빠졌습니다. 대신 DB 장애는 `@ControllerAdvice`에서 503과 에러 코드로 응답하고(`daily/day03-api-error-format.md`), 알림은 메트릭으로 받습니다. **헬스체크로 처리할 문제와 에러 응답으로 처리할 문제를 나눈 것**이 이 개선의 핵심입니다.

---

## 7. 함정

**함정 1 — 헬스체크가 커넥션 풀에서 커넥션을 빌려간다**

- **증상**: 부하가 몰려 커넥션 풀이 고갈되면 헬스체크까지 타임아웃으로 실패하고, 전 인스턴스가 동시에 로드밸런서에서 빠집니다. 트래픽이 남은 인스턴스에 몰려 상황이 더 나빠집니다.
- **원인**: `DataSourceHealthIndicator`는 `DataSource`에서 커넥션을 얻어 검증합니다. 검증 쿼리를 지정하지 않으면 `Connection.isValid(int)`를 씁니다([javadoc](https://docs.spring.io/spring-boot/api/java/org/springframework/boot/actuate/jdbc/DataSourceHealthIndicator.html)). 풀에 여유 커넥션이 없으면 헬스체크도 다른 요청과 똑같이 대기합니다.
- **해법**: liveness/readiness 그룹에서 `db`를 뺍니다. `/actuator/health`에는 남겨도 되지만 그 경로를 프로브에 물리지 않습니다. 굳이 넣어야 한다면 결과를 몇 초 캐싱해서 실제 검사 횟수를 프로브 주기와 분리합니다.

<!-- TODO: 확인 필요 — 풀 고갈 시 헬스체크가 정확히 얼마나 대기하는지는 커넥션 풀 구현과 설정(HikariCP의 connection-timeout 등)에 달려 있습니다. 위 설명은 "풀에서 커넥션을 얻는다"는 문서화된 동작에서 따라오는 결과이고, 구체적 대기 시간은 확인하지 못했습니다. -->

**함정 2 — `/actuator/health`를 그대로 프로브 경로로 쓴다**

- **증상**: 코드를 바꾼 적이 없는데 어느 날 인스턴스가 전부 unhealthy가 됩니다. 로그에는 아무 예외도 없습니다.
- **원인**: 기본 `/actuator/health`는 클래스패스에 따라 자동 등록된 모든 indicator의 집계입니다. 그중 하나만 `DOWN`이면 전체가 `DOWN`(503)이 됩니다. `diskspace`가 임계치 아래로 떨어지거나 `ssl` indicator가 만료 임박 인증서를 잡아내는 경우가 대표적입니다.
- **해법**: 프로브는 반드시 그룹 경로(`/actuator/health/liveness`, `/actuator/health/readiness`)를 씁니다. 그리고 `management.health.defaults.enabled: false`로 자동 등록을 끄고 필요한 것만 켭니다.

**함정 3 — startup 프로브 없이 `initialDelaySeconds`로 버틴다**

- **증상**: 평소엔 잘 뜨는데, 트래픽이 몰리거나 마이그레이션이 붙은 배포에서만 Pod가 `CrashLoopBackOff`에 빠집니다.
- **원인**: `initialDelaySeconds`는 고정값입니다. 기동 시간이 그 값을 넘기면 아직 기동 중인 프로세스에 liveness가 걸리고 재시작됩니다. 재시작하면 더 느려지므로 빠져나오지 못합니다.
- **해법**: `startupProbe`를 둡니다. startup이 성공할 때까지 liveness/readiness는 실행되지 않으므로, `failureThreshold × periodSeconds`만큼 기동을 기다려주면서 정상 운영 중의 liveness는 짧게 유지할 수 있습니다.

**함정 4 — liveness와 readiness가 같은 것을 본다**

- **증상**: 무중단 배포를 설정했는데도 배포마다 5xx가 소량 발생합니다. 종료 로그가 중간에 잘려 있습니다.
- **원인**: 두 프로브를 같은 경로에 물리면 SIGTERM 직후 `REFUSING_TRAFFIC`으로 바뀌는 순간 liveness도 함께 실패합니다. kubelet이 진행 중인 요청을 기다리지 않고 컨테이너를 죽입니다.
- **해법**: 경로를 분리합니다. 종료 중에 readiness는 503, liveness는 200이어야 합니다. Actuator의 기본 그룹 구성이 이미 이렇게 되어 있으니 `livenessState`에 다른 indicator를 섞지만 않으면 됩니다.

**함정 5 — 헬스체크 응답에 내부 정보가 그대로 나온다**

- **증상**: `/actuator/health` 응답에 DB 종류, 버전, Redis 주소, 인증서 만료일이 노출됩니다.
- **원인**: `show-details`를 `always`로 바꿔놓고 잊은 경우입니다. 기본값은 `never`입니다.
- **해법**: 기본값을 유지하거나 `when-authorized`를 씁니다. 상세 정보가 필요하면 관리 포트를 분리하고 그 포트를 보안 그룹에서 내부 대역으로만 엽니다(`daily/day22-sg-vs-nacl.md`).

---

## 8. 정리

헬스체크 설계는 검사 항목을 고르는 일이 아니라 **조치를 고르는 일**입니다. 하나만 기억한다면 이 질문입니다.

> 이 검사가 실패했을 때, 재시작하거나 트래픽을 빼는 것이 상황을 낫게 만드는가?

- 아니라면 헬스체크가 아니라 **에러 응답과 알림**으로 처리합니다.
- 재시작이 답이면 liveness, 트래픽 차단이 답이면 readiness입니다.
- 전 인스턴스가 동시에 실패하는 검사는 어느 쪽에도 넣지 않습니다.

---

## 9. 참고자료

- [Kubernetes — Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)
- [Spring Boot Actuator — Endpoints (Health, Health Groups, Kubernetes Probes)](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html)
- [Spring Boot 3.5 Actuator — Kubernetes Probes](https://docs.spring.io/spring-boot/3.5/reference/actuator/endpoints.html)
- [AWS — Health checks for Application Load Balancer target groups](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html)
- [DataSourceHealthIndicator javadoc](https://docs.spring.io/spring-boot/api/java/org/springframework/boot/actuate/jdbc/DataSourceHealthIndicator.html)
- 관련 문서: `daily/day18-graceful-shutdown.md`, `daily/day03-api-error-format.md`, `daily/day22-sg-vs-nacl.md`
