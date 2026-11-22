# 멀쩡한 서버를 죽이는 헬스체크 — 인프라 계층의 숫자는 무엇을 기준으로 정하는가

## 1. 핵심 개념 — 헬스체크는 조회가 아니라 처분 트리거입니다

헬스체크는 "이 서버 살아있나요?"를 묻는 API가 아닙니다. 묻는 쪽이 대답에 따라 **서버를 처분하는 자동화**입니다. 로드밸런서는 트래픽을 끊고, Auto Scaling 그룹은 인스턴스를 종료하고, kubelet은 컨테이너를 재시작합니다.

> 그래서 헬스체크를 잘못 짜면 "장애를 못 잡는" 게 아니라 **멀쩡한 서버가 죽습니다.** DB가 3초 느려졌을 때 전체 서버가 동시에 unhealthy로 떨어지면, 원래 장애는 3초였는데 결과는 전체 재시작입니다. 헬스체크의 실패 모드는 두 방향인데, 실무에서 더 자주 터지는 쪽은 "놓치는 것"이 아니라 "과잉 처분"입니다.

엔드포인트에서 **무엇을 검사할지**는 `daily/day30-application-healthcheck.md`에서 다뤘습니다. 이 문서는 그다음 질문에 답합니다. **그 응답을 누가 읽고, 어떤 숫자로 몇 초 뒤에 무엇을 집행하는가.**

---

## 2. 누가 읽고 무엇을 집행하는가

같은 `/health` 응답 하나를 여러 주체가 읽습니다. 처분의 **되돌릴 수 있는 정도**가 전부 다릅니다.

| 소비자 | 실패 시 처분 | 되돌릴 수 있는가 |
|---|---|---|
| ALB / NLB 타깃 그룹 | 트래픽만 제외 | 예 — 다시 통과하면 복귀 |
| EC2 Auto Scaling (ELB 체크 켠 경우) | 인스턴스 **종료 후 교체** | 아니요 |
| kubelet `livenessProbe` | 컨테이너 **재시작** | 아니요 (상태·캐시 소실) |
| kubelet `readinessProbe` | Service 엔드포인트에서 제외 | 예 |
| Route 53 alias + evaluate target health | DNS 응답에서 제외 | 예 (단 TTL 지연) |

여기서 가장 중요한 분리가 나옵니다. **트래픽만 끊는 체크는 깊게 봐도 되고, 서버를 죽이는 체크는 얕게 봐야 합니다.** AWS Builders' Library의 헬스체크 편도 같은 결론을 제시합니다 — 로드밸런서에는 프로세스·로컬 수준 체크만 맡기고, 의존성 체크는 임계값과 속도 제한을 가진 외부 모니터링에 맡기라는 쪽입니다.

ASG 쪽에는 함정이 하나 더 있습니다. **Auto Scaling 그룹은 기본적으로 ELB 헬스체크 결과를 무시합니다.** 명시적으로 켜야 반영되고(`health_check_type = "ELB"`), 켜는 순간 로드밸런서의 unhealthy 판정이 **인스턴스 종료 권한**으로 승격됩니다. 반대로 EC2 상태 검사는 항상 켜져 있고 끌 수 없습니다. ([Auto Scaling 헬스체크 문서](https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-checks-overview.html))

---

## 3. 기본값이 정하는 시간

### 3-1. ALB 타깃 그룹 기본값

Application Load Balancer 타깃 그룹의 기본값입니다 (target type `instance` / `ip` 기준).

| 설정 | 기본값 | 범위 |
|---|---|---|
| `HealthCheckProtocol` | HTTP | HTTP, HTTPS |
| `HealthCheckPath` | `/` | — |
| `HealthCheckPort` | 트래픽 포트 | — |
| `HealthCheckIntervalSeconds` | 30초 | 5–300 |
| `HealthCheckTimeoutSeconds` | 5초 | 2–120 |
| `HealthyThresholdCount` | 5 | 2–10 |
| `UnhealthyThresholdCount` | 2 | 2–10 |
| `Matcher` | `200` | 200–499 |

출처: [ALB 타깃 그룹 헬스체크](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html)

경로 기본값이 `/`라는 점이 첫 번째 문제입니다. 루트는 보통 애플리케이션의 가장 무거운 핸들러이거나, 인증 필터·세션 조회·템플릿 렌더링을 전부 타는 경로입니다. 30초마다 LB 노드 수만큼 들어옵니다.

성공 코드 기본값이 `200` **하나뿐**인 것도 걸립니다. 헬스 엔드포인트를 204로 응답하게 짜두면 `Target.ResponseCodeMismatch`로 떨어집니다. 증상은 "분명 응답은 가는데 unhealthy"입니다.

### 3-2. 탐지와 복귀는 비대칭입니다

기본값을 그대로 쓰면 시간은 이렇게 나옵니다.

```
unhealthy 판정 = interval 30s × unhealthyThreshold 2  = 약 60초
healthy  복귀  = interval 30s × healthyThreshold  5  = 약 150초
```

고장을 알아채는 데 1분, 회복을 인정받는 데 2분 반입니다. 이 비대칭은 의도적입니다 — 끊는 건 빨라도 되고, 붙이는 건 신중해야 하니까요. 문제는 이 숫자가 **일시적 지연에도 똑같이 적용된다**는 점입니다. GC로 7초 멈춘 서버는 체크 2번을 놓치고 빠진 뒤, 멀쩡해진 다음에도 150초를 더 기다립니다.

단, 자주 혼동되는 지점이 있습니다. `HealthyThresholdCount`는 **unhealthy였던 타깃이 복귀할 때** 쓰입니다. 새로 등록된 타깃은 **첫 체크 한 번만 통과하면** 트래픽을 받습니다 — 임계값과 무관하게요. 그래서 "healthy threshold를 5로 뒀더니 배포가 느리다"는 진단은 틀립니다. 배포 지연의 원인은 보통 `deregistration_delay`(기본 300초)이고, 이쪽은 `daily/day18-graceful-shutdown.md`의 부등식 문제입니다.

### 3-3. NLB는 숫자가 다르고, 횟수도 다릅니다

| 설정 | NLB 기본값 |
|---|---|
| 프로토콜 | **TCP** |
| 타임아웃 | HTTP 6초 / TCP·HTTPS 10초 |
| 간격 | 30초 |
| healthy / unhealthy 임계값 | 5 / 2 |
| Matcher | `200-399` |

출처: [NLB 타깃 그룹 헬스체크](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/target-group-health-checks.html)

NLB는 기본이 TCP 체크입니다. TCP 핸드셰이크만 성공하면 healthy인데, 그건 **커널이 살아있다는 뜻**이지 애플리케이션이 요청을 처리할 수 있다는 뜻이 아닙니다. 스레드 풀이 꽉 찬 서버도 SYN에는 응답합니다.

그리고 NLB의 헬스체크는 분산 합의 방식으로 동작해서, **설정한 간격보다 많은 수의 체크가 타깃에 도착합니다.** 공식 문서가 직접 경고하는 내용이고, 그래서 HTTP 체크를 쓸 거면 정적 파일처럼 가벼운 대상을 쓰거나 TCP 체크를 쓰라고 권합니다.

---

## 4. 체크의 깊이 — 어디까지 보게 할 것인가

깊이는 세 단계로 나뉩니다. 중요한 건 깊이 자체가 아니라 **어떤 깊이를 어떤 소비자에게 연결하는가**입니다.

| 깊이 | 보는 것 | 실패가 한 대만의 문제인가 | 연결할 대상 |
|---|---|---|---|
| liveness | 프로세스가 떠 있고 포트를 듣는가 | 예 | LB, `livenessProbe` |
| local | 디스크, 스레드 풀 여유, 로컬 설정 | 예 | LB, `readinessProbe` |
| dependency | DB·Redis·외부 API 연결 | **아니요 — 전원이 동시에 실패** | 모니터링·알림 (처분 권한 없음) |

dependency 체크를 LB나 `livenessProbe`에 연결하면, 공유 의존성 하나가 **전체 함대를 동시에 탈락시키는 스위치**가 됩니다. 평소에 soft dependency였던 것이 그 순간 hard dependency로 승격됩니다.

---

## 5. 흐름 — 깊은 체크가 전체 장애로 번지는 경로

RDS 페일오버가 20초 걸렸다고 가정합니다. 서버 12대, ALB 기본값, 헬스체크는 DB에 `SELECT 1`을 던지는 구성입니다.

```
1. DB 페일오버 시작 — 커넥션 전부 끊김
2. 12대 전원의 헬스체크가 동시에 실패   ← 상관 장애
3. 60초 후(2 × 30s) 12대 전원 unhealthy
4. ASG가 ELB 체크를 켜둔 상태라면 교체 대상으로 분류
5. DB는 20초에 복구됐지만, 서버는 150초를 더 기다림
6. 그 사이 교체된 인스턴스는 캐시가 비어 있어 DB를 더 때림
7. 다시 느려짐 → 2번으로
```

6~7번이 downward spiral입니다. 원래 장애는 20초였는데, 자동화가 그걸 수 분짜리 장애로 증폭시켰습니다. 코드는 아무것도 안 틀렸고 설정 두 줄이 틀렸습니다.

### fail open — 구해주긴 하는데

ELB에는 안전장치가 있습니다. **타깃 그룹에 healthy 타깃이 하나도 없으면, 로드밸런서는 상태를 무시하고 전체 타깃에 트래픽을 보냅니다.** 이게 fail open이고, ALB·NLB 모두 문서에 명시돼 있습니다. NLB는 타깃 그룹이 비어 있을 때도 fail open합니다.

ASG에도 비슷한 제동이 있습니다. unhealthy 인스턴스는 한 번에 **desired capacity의 10%까지만** 교체하고, ELB가 전원을 unhealthy로 보고하는 경우에는 그보다도 더 적게 표시할 수 있습니다. 문서가 밝힌 의도는 "그룹 전체를 자동 종료하지 않고 사람이 고칠 시간을 주는 것"입니다. ([헬스체크 개요](https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-checks-overview.html))

그런데 이 둘에 기대는 설계는 위험합니다. fail open은 **전원이 동시에 죽었을 때만** 발동합니다. 실무에서 흔한 건 12대 중 9대만 떨어지는 부분 장애이고, 그때는 남은 3대가 4배 트래픽을 받아 같이 죽습니다. 그리고 전체가 죽어 fail open이 발동한 상태는 "트래픽이 흐르지만 전부 500"일 수 있어서, 안전장치가 작동했는지 아닌지 지표로 구분하기도 어렵습니다. Builders' Library가 fail open 의존에 신중한 태도를 권하는 이유입니다.

---

## 6. 설정으로 보는 구성

### 6-1. 흔한 설정 ❌

```hcl
resource "aws_lb_target_group" "order_api" {
  name     = "order-api-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  # 기본값 그대로 — path "/", interval 30, timeout 5, matcher "200"
  health_check {
    path    = "/health"   # DB·Redis까지 확인하는 종합 엔드포인트
    timeout = 10          # ❌ interval(30s)보다 짧지만, 느린 체크를 참아줌
  }
}

resource "aws_autoscaling_group" "order_api" {
  name             = "order-api-asg"
  desired_capacity = 12
  min_size         = 6
  max_size         = 24
  target_group_arns = [aws_lb_target_group.order_api.arn]

  health_check_type         = "ELB"   # ❌ DB 장애 = 인스턴스 전원 교체
  health_check_grace_period = 0       # ❌ CLI/Terraform 기본값. 부팅 중 바로 교체 대상
}
```

`health_check_grace_period`가 특히 악질입니다. **콘솔에서 만들면 300초가 기본인데, CLI·SDK로 만들면 0초가 기본입니다.** 0은 유예 없음을 뜻합니다. JVM 부팅에 60초 걸리는 앱이라면, 뜨자마자 unhealthy로 찍혀 종료되고 다시 뜨는 무한 루프가 됩니다. ([grace period 문서](https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-check-grace-period.html))

### 6-2. 고친 설정 ✔️

```hcl
resource "aws_lb_target_group" "order_api" {
  name     = "order-api-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  deregistration_delay = 30   # 기본 300초 — 종료 대기를 앱 타임아웃에 맞춤

  health_check {
    path     = "/actuator/health/readiness"  # 의존성 제외, 로컬 상태만
    interval = 10
    timeout  = 3                             # timeout < interval 필수
    healthy_threshold   = 2                  # 복귀 20초
    unhealthy_threshold = 3                  # 탐지 30초, 단발 지연은 흡수
    matcher = "200"
  }
}

resource "aws_autoscaling_group" "order_api" {
  name             = "order-api-asg"
  desired_capacity = 12
  min_size         = 6
  max_size         = 24
  target_group_arns = [aws_lb_target_group.order_api.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 180   # 부팅 60s + 워밍업 + LB 초기 체크
  default_instance_warmup   = 180
}
```

핵심은 두 가지입니다. 체크 대상을 **로컬 상태만 보는 엔드포인트로 바꿨고**, `unhealthy_threshold`를 올려 단발 지연을 흡수하면서 `interval`을 줄여 탐지 시간은 오히려 당겼습니다. 임계값을 높이는 것이 반드시 느려지는 걸 뜻하지는 않습니다.

### 6-3. 쿠버네티스 프로브

프로브 기본값은 이렇습니다 — `initialDelaySeconds` 0, `periodSeconds` 10, `timeoutSeconds` **1**, `successThreshold` 1, `failureThreshold` 3. ([프로브 문서](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/))

`timeoutSeconds`가 1초라는 게 핵심입니다. 부하가 걸린 JVM이 1초 안에 응답하지 못하는 건 흔한 일이고, 그게 3번 연속되면 `livenessProbe`는 컨테이너를 **재시작**합니다.

```yaml
# ❌ 부팅 느린 앱을 liveness로 때려잡는 설정
livenessProbe:
  httpGet:
    path: /actuator/health      # 의존성까지 보는 종합 엔드포인트
    port: 8080
  initialDelaySeconds: 30       # 부팅이 40초면 재시작 루프
  # timeoutSeconds 기본 1초, failureThreshold 기본 3
```

```yaml
# ✔️ 부팅은 startupProbe, 트래픽은 readinessProbe, 재시작은 최후수단
startupProbe:
  httpGet:
    path: /actuator/health/liveness
    port: 8080
  periodSeconds: 5
  failureThreshold: 30          # 최대 150초까지 부팅 허용

readinessProbe:
  httpGet:
    path: /actuator/health/readiness
    port: 8080
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3

livenessProbe:
  httpGet:
    path: /actuator/health/liveness   # 의존성 없음 — 프로세스 생존만
    port: 8080
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 6                 # 60초 응답 불가면 재시작
```

`startupProbe`가 성공하기 전까지 liveness·readiness는 **아예 실행되지 않습니다.** 그래서 "부팅이 느려서 재시작 루프" 문제는 `initialDelaySeconds`를 늘려 땜질할 게 아니라 `startupProbe`로 분리하는 문제입니다.

---

## 7. 숫자를 정하는 규칙

외워야 할 값은 없고, 지켜야 할 부등식이 넷입니다.

```
1. timeout < interval
   체크가 끝나기 전에 다음 체크가 시작되면 판정이 겹칩니다.

2. 탐지 시간(interval × unhealthyThreshold) > 앱의 최대 정상 멈춤 시간
   Full GC가 5초인 앱에 탐지 시간 6초를 주면, 정상 GC에 서버가 빠집니다.

3. grace period > 앱 부팅 완료 시간 + LB 초기 체크 1회
   또는 grace period를 0으로 두고 라이프사이클 훅으로 보장합니다.

4. deregistration delay ≥ 가장 긴 요청의 처리 시간
   헬스체크와 별개 축입니다. day18 참고.
```

2번이 가장 많이 틀립니다. 탐지를 빠르게 하려고 `interval 5초 × unhealthyThreshold 2` = 10초로 조이면, **부하가 몰려 응답이 조금 느려진 순간 서버가 빠집니다.** 그러면 남은 서버에 부하가 더 몰리고, 다음 차례가 빠집니다. 조인 설정은 장애를 빨리 잡는 대신 장애를 만듭니다.

---

## 8. fail open을 설정으로 바꾸기

"healthy 타깃이 1개면 정상"이라는 기본 판정은 함대가 클수록 말이 안 됩니다. 12대 중 1대만 살아있는 상태를 ALB는 정상으로 봅니다. 타깃 그룹 헬스 임계값으로 이 기준을 올릴 수 있습니다.

```bash
# healthy 타깃이 50% 미만이면 두 동작을 발동시킵니다
aws elbv2 modify-target-group-attributes \
  --target-group-arn "$TG_ARN" \
  --attributes \
    "Key=target_group_health.dns_failover.minimum_healthy_targets.percentage,Value=50" \
    "Key=target_group_health.unhealthy_state_routing.minimum_healthy_targets.percentage,Value=50"
```

두 동작의 역할이 다릅니다.

- **DNS failover** — 해당 AZ의 LB 노드 IP를 DNS에서 제거합니다. 새 연결이 건강한 AZ로 갑니다.
- **Routing failover** — 그 AZ로 들어온 트래픽은 unhealthy 타깃까지 포함해 전체에 분산합니다. 살아남은 소수에게 과부하가 쏠리는 걸 막습니다.

기본값은 count 기준 `1`, percentage 기준 `off`입니다. 제약이 하나 있습니다 — **DNS failover 임계값은 routing failover 임계값보다 크거나 같아야 합니다.** 그리고 DNS 레코드 TTL이 60초라, 클라이언트 캐시 때문에 즉시 반영되지는 않습니다. ([타깃 그룹 헬스](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html))

cross-zone 설정에 따라 계산 기준이 바뀌는 점도 주의할 부분입니다. 끄면 AZ별 타깃 수로, 켜면 전체 타깃 수로 퍼센트를 계산합니다.

---

## 9. 함정

**9-1. 부팅 중 인스턴스가 끝없이 교체됩니다**

- **증상**: ASG가 인스턴스를 띄우고 몇 분 뒤 종료하고 다시 띄우는 루프. `Terminating EC2 instance ... failed ELB health checks` 활동 기록이 반복됩니다.
- **원인**: `health_check_grace_period`가 0입니다. 콘솔 기본은 300초인데 CLI·Terraform 기본은 0입니다.
- **해법**: 앱 부팅 완료 시간 + 초기 체크 1회분으로 설정합니다. 또는 라이프사이클 훅으로 초기화 완료 후 `InService`로 올리고 0을 유지합니다.

**9-2. 응답은 200인데 unhealthy입니다**

- **증상**: 인스턴스에 직접 `curl`하면 200인데 타깃 그룹은 unhealthy. 이유 코드는 `Target.Timeout` 또는 `Target.ResponseCodeMismatch`.
- **원인**: 셋 중 하나입니다. (1) 보안 그룹이 **헬스체크 포트**를 LB에 열지 않음 — 트래픽 포트와 다른 포트를 쓸 때 자주 누락됩니다. (2) ALB 기본 matcher가 `200` 하나뿐인데 엔드포인트가 204·302를 반환. (3) 체크가 타임아웃 5초 안에 못 끝남.
- **해법**: `describe-target-health`의 이유 코드로 먼저 갈라냅니다. `Elb.`로 시작하면 LB 쪽, `Target.`으로 시작하면 타깃 쪽입니다. 헬스체크 로그를 S3로 내리면 응답 코드와 지연을 직접 볼 수 있습니다.

**9-3. DB 장애 한 번에 전체가 재시작됩니다**

- **증상**: RDS 페일오버·Redis 재시작 직후 모든 파드가 restart되고, 복구가 DB 복구보다 수 분 늦습니다.
- **원인**: `livenessProbe`가 의존성까지 확인하는 종합 엔드포인트를 가리킵니다. 공유 의존성 실패는 전원이 동시에 실패하는 상관 장애라, 롤링 복구가 아니라 동시 재시작이 됩니다.
- **해법**: liveness는 프로세스 생존만, readiness는 로컬 상태까지, 의존성 상태는 **처분 권한 없는 알림**으로 분리합니다. Spring Boot라면 `liveness`/`readiness` 그룹을 나눠 쓰면 됩니다.

**9-4. 트래픽이 늘어날 때만 서버가 빠집니다**

- **증상**: 평소 멀쩡한데 피크 시간대에 타깃이 번갈아 unhealthy↔healthy를 반복(flapping)하고, 실제 에러율은 낮습니다.
- **원인**: 타임아웃이 짧습니다. 쿠버네티스 기본 `timeoutSeconds`는 1초이고, 헬스체크 경로가 인증 필터·로깅 인터셉터·DB 커넥션 획득을 전부 타면 부하 상황에서 그 안에 못 끝납니다.
- **해법**: 타임아웃을 p99 응답 시간 기준으로 올리고, 헬스체크 경로를 애플리케이션 필터 체인에서 빼거나 관리 포트로 분리합니다.

**9-5. 로드밸런서는 정상이라는데 500이 나갑니다**

- **증상**: 타깃 그룹의 `UnHealthyHostCount`가 0인데 클라이언트는 5xx를 받습니다.
- **원인**: fail open입니다. 전원 unhealthy가 되면 LB가 상태를 무시하고 전체에 보내므로, 지표상으로는 "장애 아님"처럼 보입니다.
- **해법**: `HealthyHostCount`를 **절대값으로** 알럿합니다. unhealthy 수가 아니라 healthy 수가 기준이어야 합니다. 여기에 타깃 그룹 헬스 임계값(§8)을 설정해 부분 장애에서도 동작하게 만듭니다.

**9-6. NLB로 바꿨더니 죽은 서버에 계속 요청이 갑니다**

- **증상**: 애플리케이션은 응답을 못 하는데 NLB는 healthy로 판정합니다.
- **원인**: NLB 기본 프로토콜이 TCP입니다. 핸드셰이크 성공은 커널이 살아있다는 뜻일 뿐입니다.
- **해법**: HTTP 체크로 바꿉니다. 단 NLB는 합의 방식 때문에 설정 간격보다 많은 체크를 보내므로, 가벼운 경로를 지정합니다.

---

## 10. 정리

헬스체크 설정은 "장애를 얼마나 빨리 잡을까"의 문제가 아니라 **"자동화에 어느 정도의 처분 권한을 줄까"**의 문제입니다.

- 체크의 **깊이**와 소비자의 **처분 수준**을 맞춥니다. 깊은 체크에 재시작·종료 권한을 주지 않습니다.
- 공유 의존성을 보는 체크는 상관 장애를 만듭니다. soft dependency를 hard dependency로 승격시키지 않습니다.
- 임계값을 조이면 탐지는 빨라지지만 **정상 변동에 서버가 빠집니다.** 탐지 시간은 앱의 최대 정상 멈춤 시간보다 길어야 합니다.
- 기본값은 조직의 상황을 모릅니다. `health_check_grace_period` 0, 쿠버네티스 `timeoutSeconds` 1, ALB 경로 `/`, matcher `200` — 넷은 거의 항상 바꿔야 합니다.
- fail open과 ASG의 10% 제동은 최후의 보험입니다. 설계의 전제로 삼지 않습니다.

---

## 11. 참고자료

- [ALB 타깃 그룹 헬스체크](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html) — 기본값, 상태, 이유 코드
- [NLB 타깃 그룹 헬스체크](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/target-group-health-checks.html)
- [타깃 그룹 헬스 임계값](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html) — DNS/routing failover
- [EC2 Auto Scaling 헬스체크 개요](https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-checks-overview.html)
- [Auto Scaling 헬스체크 유예 기간](https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-check-grace-period.html)
- [쿠버네티스 Liveness·Readiness·Startup 프로브](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- [AWS Builders' Library — Implementing health checks](https://builder.aws.com/content/3Ev53O39izHCtWLzp4XU6t8PC1O/implementing-health-checks)
- 관련 챕터: `daily/day30-application-healthcheck.md` · `daily/day18-graceful-shutdown.md` · `daily/day76-alb-vs-nlb.md`
