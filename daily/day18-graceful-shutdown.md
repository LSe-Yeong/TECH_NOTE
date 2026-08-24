# 배포할 때 요청이 끊기지 않으려면

> 이 문서가 답할 질문: **배포로 프로세스를 내릴 때 처리 중이던 요청은 왜 끊기고, 어디까지 손봐야 안 끊기는가?**
>
> 기준: Spring Boot 3.4 이상(현재 GA 4.1.1, 2026년 8월 확인) / Kubernetes 1.33 / AWS ALB. 롤링 배포 전략 자체(maxSurge, 카나리, 블루-그린)는 다루지 않습니다. "인스턴스 한 대를 내리는 순간"에만 집중합니다.

## 1. 핵심 개념 — 문제는 종료가 아니라 인수인계입니다

배포하면 5xx가 몇 건씩 찍힙니다. 그런데 재현이 안 됩니다. 로그를 보면 애플리케이션은 정상 종료했고, 에러는 로드밸런서 쪽에만 남습니다. 502 또는 504, 건수는 배포당 수십 건, 트래픽이 많을수록 늘어납니다.

여기서 대부분 이렇게 진단합니다. "처리 중이던 요청이 잘려서 그렇다. 그러니 요청이 끝날 때까지 기다렸다 죽으면 된다."

절반만 맞습니다. **끊긴 요청의 상당수는 프로세스가 죽기 시작한 뒤에 도착한 요청입니다.** 이미 안에서 처리 중이던 요청이 아니라, 이 서버가 죽는 줄 모르는 라우터가 그 뒤로도 계속 보낸 새 요청입니다.

> 무중단 종료는 "처리 중인 일을 마저 끝내는 것"이 아니라, **"나에게 트래픽을 보내는 모든 주체가 나를 목록에서 지웠음을 확인한 뒤에 죽는 것"** 입니다. 앞의 것만 하면 애플리케이션은 우아하게 종료되는데 5xx는 그대로 남습니다.

이게 없으면 벌어지는 일은 단순합니다. 배포가 무서워집니다. 그래서 배포를 새벽에 하고, 배포 빈도가 줄고, 한 번에 나가는 변경이 커지고, 장애 확률이 더 올라갑니다.

## 2. 종료에 관여하는 세 주체

종료 시점에 이 서버의 운명을 아는 주체가 셋 있습니다. 셋은 서로를 모릅니다.

| 주체 | 하는 일 | 아는 시점 |
|---|---|---|
| **라우터** (ALB 타깃그룹 / kube-proxy) | 어느 인스턴스로 요청을 보낼지 결정 | 등록 해제 이벤트가 전파된 뒤 |
| **프로세스** (JVM) | SIGTERM을 받고 종료 절차 시작 | SIGTERM을 받은 즉시 |
| **클라이언트 커넥션** | keep-alive로 이미 열려 있는 TCP 연결 | 서버가 연결을 닫아줄 때까지 모름 |

문제는 **프로세스가 가장 먼저 안다는 것**입니다. 자기가 죽는다는 사실을 라우터보다 먼저 아는데, 라우터에게 알려줄 방법이 없습니다.

### 2-1. 어긋남의 근원 — 두 절차가 동시에 시작됩니다

Kubernetes 공식 문서는 파드 종료 흐름을 이렇게 설명합니다([Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)).

> kubelet이 파드의 graceful shutdown을 시작하는 **것과 동시에**, 컨트롤 플레인은 종료 중인 파드를 EndpointSlice 객체에서 제거할지 판단합니다.

"동시에"가 전부입니다. 순서가 보장되지 않습니다. kubelet은 엔드포인트 제거가 모든 노드의 kube-proxy까지 전파되기를 기다리지 않고 SIGTERM을 보냅니다. 전파는 컨트롤 플레인 → EndpointSlice → 각 노드의 kube-proxy(또는 Ingress 컨트롤러, 서비스 메시 사이드카)를 거치는 비동기 과정입니다.

<!-- TODO: 전파에 걸리는 실제 시간은 클러스터 규모·CNI·kube-proxy 모드에 따라 달라집니다. 공식 문서에 보장 수치가 없어 여기서는 수치를 쓰지 않습니다. -->

AWS ALB도 구조가 같습니다. 타깃 등록 해제 요청이 들어가면 상태가 `draining`이 되지만, 이미 진행 중인 요청은 계속 처리됩니다. 기본 대기 시간은 **300초**입니다([ALB 타깃 그룹 속성](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html)). 이 문서에는 이런 문장도 있습니다.

> 등록 해제 중인 타깃이 등록 해제 지연 시간이 지나기 전에 연결을 끊으면, 클라이언트는 500번대 오류 응답을 받습니다.

즉 **먼저 죽는 쪽이 에러를 만듭니다.** 라우터가 나를 지우기 전에 내가 소켓을 닫으면, 그 대가는 사용자가 치릅니다.

## 3. 흐름

### 3-1. 손대지 않았을 때의 타임라인

```
t=0.0  배포 컨트롤러가 인스턴스 종료 요청
       ├─ 라우터: 엔드포인트 제거 시작 ─────┐ (비동기, 전파 중)
       └─ kubelet: SIGTERM 전송            │
t=0.1  JVM: 종료 훅 실행, 커넥터 닫기       │  ← 여기서 소켓이 닫힘
t=0.3  라우터가 아직 모름 → 새 요청 전송     │
       → connection refused → 502          │
t=?.?  전파 완료, 트래픽 멈춤 ──────────────┘
```

에러가 발생하는 구간은 `t=0.1`부터 전파 완료까지입니다. 애플리케이션이 아무리 우아하게 종료해도 이 구간은 줄어들지 않습니다. 오히려 **애플리케이션이 빨리 종료될수록 이 구간이 길어집니다.**

### 3-2. 고친 타임라인

해법은 반직관적입니다. **일부러 늦게 죽습니다.**

```
t=0.0  종료 요청
       ├─ 라우터: 엔드포인트 제거 시작
       └─ kubelet: preStop 훅 실행 (sleep) ← SIGTERM은 아직 안 감
t=0.0~ 서버는 멀쩡히 살아서 남은 트래픽을 정상 처리
t=5.0  전파 완료. 새 요청이 더는 오지 않음
t=5.0  preStop 종료 → SIGTERM 전송
t=5.0  JVM: 새 요청 거부 + 처리 중인 요청 완료 대기
t=8.0  마지막 요청 완료 → 컨텍스트 종료 → 프로세스 종료
t=45   (여기까지 안 끝났으면 SIGKILL)
```

핵심은 `t=0`부터 `t=5`까지 **서버가 아무것도 하지 않고 그냥 살아 있다는 것**입니다. 이 구간이 라우터에게 주는 시간입니다.

### 3-3. 코드로 보는 구성

애플리케이션 쪽입니다.

```yaml
# application.yml
server:
  shutdown: graceful          # Spring Boot 3.4부터 기본값. 명시해 두면 의도가 드러납니다

spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s   # 기본 30s
  task:
    execution:
      shutdown:
        await-termination: true       # 기본 false
        await-termination-period: 20s
    scheduling:
      shutdown:
        await-termination: true       # 기본 false
        await-termination-period: 20s

management:
  endpoint:
    health:
      probes:
        enabled: true
```

Kubernetes 쪽입니다.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-api
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: order-api
          image: registry.example.com/order-api:1.4.0
          lifecycle:
            preStop:
              sleep:
                seconds: 5
          readinessProbe:
            httpGet:
              path: /actuator/health/readiness
              port: 8080
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /actuator/health/liveness
              port: 8080
            periodSeconds: 10
```

`preStop.sleep`은 Kubernetes 1.33 기준 `PodLifecycleSleepAction` 피처 게이트로 기본 활성화된 **베타 기능**입니다([Container Lifecycle Hooks](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/)). 클러스터 버전이 낮거나 게이트가 꺼져 있으면 `exec: command: ["sleep", "5"]`를 씁니다. 단 이 방식은 **컨테이너 이미지 안에 `sleep` 바이너리가 있어야 합니다.** distroless 이미지에는 없어서 훅이 조용히 실패합니다.

## 4. 각 계층에서 실제로 해야 하는 일

### 4-1. 애플리케이션 — Spring Boot가 해주는 것과 안 해주는 것

Spring Boot 3.4부터 임베디드 웹 서버의 graceful shutdown이 **기본으로 켜집니다**([Spring Boot 3.4 릴리스 노트](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.4-Release-Notes)). 3.3 이하에서 올라왔다면 이전에는 꺼져 있었다는 뜻입니다. 되돌리려면 `server.shutdown`을 `immediate`로 둡니다.

켜져 있을 때 벌어지는 일은 이렇습니다([Graceful Shutdown](https://docs.spring.io/spring-boot/reference/web/graceful-shutdown.html)).

- 종료는 **애플리케이션 컨텍스트를 닫는 과정의 일부**로, `SmartLifecycle` 빈을 멈추는 가장 이른 단계에서 수행됩니다.
- Jetty, Reactor Netty, Tomcat은 **네트워크 계층에서 새 요청 수신을 멈춥니다.**
- 처리 중인 요청은 `spring.lifecycle.timeout-per-shutdown-phase` 동안 완료를 기다립니다. 기본값은 **30초**입니다.
- 액추에이터의 Readiness 상태가 `REFUSING_TRAFFIC`으로 바뀝니다([Kubernetes Probes](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html)).

"가장 이른 단계"라는 표현이 중요합니다. **웹 서버가 가장 먼저 멈추고, 그다음 다른 라이프사이클 빈이, 마지막에 싱글톤 빈이 파괴됩니다.** 그래서 요청 처리 중에 DB 커넥션 풀이 먼저 닫혀 버리는 일은 생기지 않습니다.

반대로 Spring Boot가 **안 해주는 것**이 두 가지입니다.

첫째, 라우터에게 알리지 않습니다. Readiness가 `REFUSING_TRAFFIC`이 되어도 그 사실이 라우터에 반영되는 건 프로브 주기(`periodSeconds`) × `failureThreshold` 뒤입니다. 위 설정이라면 최소 5초, 실패 임계값이 3이면 15초입니다. 그동안 트래픽은 계속 들어옵니다. **readiness 프로브는 이 문제의 해법이 아니라 백업입니다.**

둘째, 스레드 풀은 별도입니다. `@Async`가 쓰는 `applicationTaskExecutor`와 `@Scheduled`가 쓰는 스케줄러는 `spring.task.execution.shutdown.await-termination`, `spring.task.scheduling.shutdown.await-termination`이 각각 **기본 `false`** 라서 완료를 기다리지 않습니다. 직접 만든 `ExecutorService` 빈이라면 아예 관리 대상 밖입니다.

### 4-2. 부등식으로 정리하기

숫자 네 개의 관계만 맞으면 됩니다.

```
terminationGracePeriodSeconds  >  preStop sleep  +  timeout-per-shutdown-phase
              45               >        5        +         30           ✔
```

```
preStop sleep  ≥  라우터 전파에 걸리는 시간
```

```
deregistration_delay  ≥  preStop sleep + 처리 중인 요청의 최대 소요 시간
```

첫 번째 부등식이 깨지면 SIGKILL이 날아옵니다. `terminationGracePeriodSeconds`는 preStop 실행 시간과 컨테이너 종료 시간의 **합**에 적용되고, 기본값은 30초입니다. preStop에 5초, 종료 타임아웃에 30초를 줘 놓고 grace period를 기본값 그대로 두면 총합 35초가 30초를 넘어 강제 종료됩니다.

### 4-3. EC2 + ALB 조합이라면

Kubernetes가 아니어도 구조는 같습니다. 다만 손잡이 이름이 다릅니다.

- **등록 해제 지연**: 기본 300초. 배포마다 5분씩 기다리게 되니 실제로는 30~60초로 낮춰 씁니다. **0으로 두면 안 됩니다.** 처리 중인 요청이 그대로 잘립니다.
- **Auto Scaling 수명 주기 훅**: 인스턴스가 `Terminating:Wait` 상태에 머무는 동안 등록 해제가 전파됩니다. preStop sleep에 해당하는 역할입니다.
- **애플리케이션 종료 순서**: 등록 해제가 전파되기 전에 프로세스를 내리면 앞서 인용한 "500번대 오류" 문장 그대로가 됩니다.

## 5. 예제 — 흔한 나쁜 설정과 고친 설정

### 5-1. 손대지 않은 설정 ❌

```yaml
# Deployment — 기본값에 의존
spec:
  template:
    spec:
      # terminationGracePeriodSeconds 없음 → 30초
      containers:
        - name: order-api
          image: registry.example.com/order-api:1.4.0
          # preStop 없음 → 라우터 전파를 기다리지 않음
          readinessProbe:
            httpGet:
              path: /actuator/health   # 종료 상태를 반영하지 않는 종합 헬스체크
              port: 8080
```

```dockerfile
# Dockerfile — 셸 폼 ENTRYPOINT
ENTRYPOINT java -jar /app/order-api.jar
```

이 Dockerfile이 조용한 쪽입니다. 셸 폼으로 쓰면 PID 1이 `/bin/sh`가 되고, **셸은 SIGTERM을 자식 프로세스에 전달하지 않습니다.** JVM은 SIGTERM을 아예 못 받고, grace period가 지난 뒤 SIGKILL로 죽습니다. 애플리케이션 로그에는 종료 로그가 한 줄도 남지 않습니다. graceful shutdown 설정을 아무리 만져도 소용없습니다.

### 5-2. 고친 설정 ✔️

```dockerfile
# exec 폼 — JVM이 PID 1이 되어 SIGTERM을 직접 받습니다
ENTRYPOINT ["java", "-jar", "/app/order-api.jar"]
```

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: order-api
          image: registry.example.com/order-api:1.4.0
          lifecycle:
            preStop:
              sleep:
                seconds: 5
          readinessProbe:
            httpGet:
              path: /actuator/health/readiness
              port: 8080
            periodSeconds: 5
```

확인 방법도 정해 둡니다. 로컬에서 `docker stop`으로 검증할 때는 기본 타임아웃이 **10초**라는 점을 기억해야 합니다([docker stop](https://docs.docker.com/reference/cli/docker/container/stop/)). 종료에 20초가 걸리는 앱을 그냥 `docker stop`으로 테스트하면 매번 SIGKILL로 죽는데, 이걸 애플리케이션 버그로 오해하기 쉽습니다. `docker stop -t 60`으로 늘려서 봅니다.

## 6. HTTP 요청만 있는 게 아닙니다

웹 요청은 프레임워크가 챙겨주는 편입니다. 정작 데이터가 깨지는 쪽은 다른 데입니다.

**메시지 컨슈머.** Kafka·SQS 컨슈머가 메시지를 가져와 처리하다가 커밋 전에 죽으면 재처리됩니다. 재처리 자체는 정상 동작이고, 그래서 **멱등성이 필요합니다.** 종료를 우아하게 만드는 것으로는 이 문제를 없앨 수 없고, 발생 빈도만 낮춥니다.

**스케줄러.** `@Scheduled` 작업이 배포 시점에 실행 중일 수 있습니다. 앞서 본 대로 기본 설정은 기다려주지 않습니다.

**비동기 작업.** 컨트롤러가 202를 반환하고 `@Async`로 넘긴 작업은, 응답이 이미 나갔기 때문에 **클라이언트는 성공으로 알고 있는데 실제로는 실행되지 않은 상태**가 됩니다. 종료 중 유실이 가장 티가 안 나는 형태입니다. 재시도 가능한 큐에 넣는 편이 낫습니다.

```java
// 종료 시점에 정리가 필요한 리소스는 명시적으로 훅을 겁니다
@Component
public class OrderEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(OrderEventPublisher.class);
    private final BlockingQueue<OrderEvent> pending = new LinkedBlockingQueue<>();

    @PreDestroy
    public void flushPending() {
        log.info("종료 전 미발행 이벤트 {}건 처리", pending.size());
        List<OrderEvent> drained = new ArrayList<>();
        pending.drainTo(drained);
        drained.forEach(this::publishSynchronously);
    }

    private void publishSynchronously(OrderEvent event) {
        // ... 생략
    }
}
```

`@PreDestroy`는 싱글톤 빈 파괴 단계라 웹 서버가 멈춘 뒤에 실행됩니다. 그리고 이 시간도 `terminationGracePeriodSeconds` 안에 들어갑니다. 부등식에 항이 하나 더 붙는 셈입니다.

## 7. 함정

**증상: 배포할 때만 502가 뜨고, graceful shutdown을 켰는데도 그대로입니다.**
원인: preStop이 없어서 라우터 전파 전에 소켓이 닫힙니다. graceful shutdown은 "이미 들어온 요청"만 지키고, "곧 들어올 요청"은 지키지 못합니다.
해법: preStop sleep을 넣습니다. 애플리케이션 설정을 더 만지는 것으로는 해결되지 않습니다.

**증상: 종료 로그가 아예 안 남고 항상 정확히 30초 뒤에 컨테이너가 사라집니다.**
원인: SIGTERM이 JVM에 도달하지 않습니다. 셸 폼 ENTRYPOINT, 또는 엔트리포인트 셸 스크립트가 `exec` 없이 java를 호출하는 경우입니다.
해법: exec 폼으로 바꾸거나, 스크립트 마지막 줄을 `exec java -jar ...`로 씁니다. "정확히 grace period만큼"이라는 시간이 진단의 단서입니다.

**증상: 종료 중 `ApplicationContext has been closed` / `BeanCreationNotAllowedException`이 찍힙니다.**
원인: 웹 요청은 잘 막았는데 컨슈머나 스케줄러가 컨텍스트 종료 후에도 빈을 참조합니다.
해법: 해당 컴포넌트의 종료를 라이프사이클에 편입시킵니다. 리스너 컨테이너를 명시적으로 멈추거나, `await-termination` 설정을 켭니다.

**증상: 롱폴링·SSE·대용량 업로드 요청이 배포마다 끊깁니다.**
원인: 이 요청들은 종료 타임아웃 안에 끝나지 않습니다. 30초를 기다려도 SSE 연결은 몇 시간짜리입니다.
해법: 타임아웃을 늘려 해결하려 하지 않습니다. 클라이언트에 재연결 로직을 넣고, 서버는 종료 시작 시 스트림을 정상 종료 이벤트로 닫아줍니다. **끊기지 않게 만드는 대신, 끊겨도 되게 만듭니다.**

**증상: 등록 해제 지연을 0으로 낮췄더니 배포는 빨라졌는데 5xx가 늘었습니다.**
원인: 처리 중이던 요청이 그대로 잘립니다.
해법: 0이 아니라 "가장 느린 요청의 소요 시간 + preStop"으로 잡습니다. 300초 기본값이 부담이라면 30~60초가 현실적인 출발점입니다.

**증상: preStop을 늘렸더니 배포 중 SIGKILL 로그가 보이기 시작했습니다.**
원인: `terminationGracePeriodSeconds`를 안 올렸습니다. grace period는 preStop과 종료 시간의 **합**에 적용됩니다.
해법: 4-2의 첫 번째 부등식을 다시 맞춥니다.

## 8. 관련 개념과의 경계

**readiness 프로브**는 "트래픽을 받을 준비가 됐는가"를 계속 묻는 장치입니다. 시작 시점에는 이것만으로 충분합니다. 종료 시점에는 반응 속도가 프로브 주기에 묶여 있어 부족합니다. preStop은 그 지연을 **기다림으로 메우는** 장치입니다. 둘은 대체 관계가 아닙니다.

**멱등성**(`08-system-design/07-idempotency`)은 여기서 끊긴 요청을 클라이언트가 재시도할 때 안전하게 만듭니다. graceful shutdown이 실패 확률을 낮춘다면, 멱등성은 실패했을 때의 피해를 없앱니다. 배포 안정성은 이 둘을 같이 갖춰야 완성됩니다.

**타임아웃 설정**은 부등식의 오른쪽 항을 정하는 값입니다. 요청 타임아웃이 없으면 "가장 느린 요청의 소요 시간"이 무한대라서, 종료 타임아웃을 얼마로 잡아도 근거가 없습니다.

## 9. 참고자료

- [Graceful Shutdown :: Spring Boot](https://docs.spring.io/spring-boot/reference/web/graceful-shutdown.html)
- [Kubernetes Probes :: Spring Boot Actuator](https://docs.spring.io/spring-boot/reference/actuator/endpoints.html)
- [Spring Boot 3.4 Release Notes](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.4-Release-Notes)
- [Pod Lifecycle :: Kubernetes](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
- [Container Lifecycle Hooks :: Kubernetes](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/)
- [Edit target group attributes :: AWS ALB](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html)
- [docker stop :: Docker Docs](https://docs.docker.com/reference/cli/docker/container/stop/)
- 함께 보면 좋은 문서: `day06-env-variable.md`(환경별 설정 주입), `day09-rest-api-design.md`(재시도 안전성과 멱등성)
