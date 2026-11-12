# L7과 L4 — ALB와 NLB는 무엇을 기준으로 고르는가

## 1. 핵심 개념 — 차이는 "요청을 읽는가"입니다

둘 다 트래픽을 여러 대에 나눠주지만, 보는 단위가 다릅니다.

| | ALB (Application Load Balancer) | NLB (Network Load Balancer) |
|---|---|---|
| 동작 계층 | L7 | L4 |
| 리스너 프로토콜 | HTTP, HTTPS, gRPC | TCP, UDP, TLS, QUIC |
| 분산 단위 | HTTP 요청 1건 | 커넥션(플로우) 1개 |
| 연결 구조 | 클라이언트↔LB, LB↔타깃 두 개의 연결 | 한 플로우를 그대로 전달(목적지 IP만 재작성) |

출처: [ELB 제품 비교](https://aws.amazon.com/elasticloadbalancing/features/), [ALB 연결 구조](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html), [NLB 개요](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/introduction.html)

> 이 차이를 모르고 기능표만 보면 "ALB가 상위 버전"이라고 읽게 됩니다. 그러면 두 가지 사고가 납니다. 하나는 `request.getRemoteAddr()`로 만든 IP 제한이 ALB 뒤에서 전부 무용지물이 되는 것이고, 다른 하나는 gRPC 서비스를 NLB에 붙였더니 서버 10대 중 2대만 CPU 100%가 되는 것입니다. 둘 다 코드 버그가 아니라 **분산 단위를 잘못 고른 것**입니다.

이 문서는 "HTTP 서비스 앞에 무엇을 둘지"를 결정하는 축만 다룹니다.

---

## 2. 결정을 바꾸는 다섯 개의 축

### 2-1. 프로토콜 — 여기서 대부분 끝납니다

리스너가 받을 수 있는 프로토콜이 다릅니다. HTTP가 아닌 트래픽(MQTT, 게임 UDP, 직접 만든 TCP 프로토콜, DB 프록시)은 ALB로 아예 받을 수 없습니다. 반대로 경로 기반 분기가 필요하면 NLB로는 불가능합니다.

TLS는 양쪽 다 종료할 수 있습니다. 다만 NLB는 TCP 리스너로 **종료하지 않고 그대로 흘려보내는** 선택지가 있습니다. 인증서를 애플리케이션이 직접 들고 있어야 하는 요구사항(상호 TLS를 앱에서 검증 등)이 있으면 이 경로가 유일합니다.

### 2-2. 라우팅 단위 — 요청을 쪼갤 수 있는가

ALB는 요청을 파싱하므로 호스트·경로·헤더·HTTP 메서드·쿼리스트링·소스 IP로 리스너 규칙을 만들 수 있습니다. 하나의 ALB 뒤에 `/api/orders`와 `/api/members`를 다른 타깃 그룹으로 보내는 구성이 가능합니다.

NLB는 포트만 봅니다. 서비스를 나누려면 리스너 포트를 나누거나 NLB를 더 만들어야 합니다.

### 2-3. 분산 단위 — keep-alive가 NLB의 분산을 망가뜨립니다

가장 많이 놓치는 축입니다.

NLB는 TCP 트래픽에서 **프로토콜·소스 IP·소스 포트·목적지 IP·목적지 포트·TCP 시퀀스 번호**로 플로우 해시를 계산해 타깃을 고릅니다. 한번 정해지면 그 커넥션은 수명이 끝날 때까지 같은 타깃으로 갑니다. 그리고 NLB는 **커넥션 멀티플렉싱을 하지 않습니다** — ALB와 CLB는 합니다 ([NLB 트러블슈팅](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-troubleshooting.html)).

이게 왜 문제인지는 HTTP/2와 gRPC를 떠올리면 바로 보입니다. 클라이언트 한 대가 커넥션 하나를 열고 그 위에 수천 개 요청을 멀티플렉싱하면, NLB 입장에서는 **플로우 하나**입니다. 요청 수천 건이 전부 한 타깃으로 갑니다. 타깃을 나중에 늘려도 기존 커넥션은 이동하지 않으므로 신규 커넥션이 생길 때까지 불균형이 유지됩니다.

ALB는 요청 단위로 분산하고, 기본 알고리즘은 라운드 로빈이며 `least_outstanding_requests`(처리 중 요청이 가장 적은 타깃)도 고를 수 있습니다.

### 2-4. 클라이언트 IP — 누가 보존하고, 어떻게 꺼내는가

ALB는 프록시이므로 타깃이 보는 소스 IP는 **ALB 노드의 사설 IP**입니다. 실제 클라이언트 IP는 `X-Forwarded-For` 헤더로 전달됩니다. 기본 모드가 `append`라서 ALB가 마지막 홉의 IP를 덧붙입니다.

NLB는 패킷의 소스 IP를 그대로 둘 수 있습니다. 기본값이 타깃 그룹 종류에 따라 다릅니다.

| 타깃 그룹 | `preserve_client_ip.enabled` 기본값 |
|---|---|
| instance 타입 (TCP/TLS) | 켜짐 |
| ip 타입 (TCP/TLS) | 꺼짐 |
| UDP, TCP_UDP, QUIC, TCP_QUIC | 켜짐 (끌 수 없음) |

출처: [NLB 타깃 그룹 속성](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-target-groups.html)

보존을 끈 상태에서 클라이언트 IP가 필요하면 Proxy Protocol v2를 켭니다. 이때 타깃 애플리케이션이 커넥션 앞머리에 붙는 헤더를 해석할 수 있어야 합니다 — 톰캣이라면 커넥터 설정이 필요하고, 모르는 상태로 켜면 애플리케이션이 첫 바이트부터 깨진 요청을 받습니다.

### 2-5. IP 주소와 장애 경계

- **ALB**: 서로 다른 AZ의 서브넷을 **최소 두 개** 지정해야 합니다. 노드 IP는 AWS가 관리하며 고정할 수 없습니다. 교차 영역 부하 분산(cross-zone)은 로드 밸런서 레벨에서 **항상 켜져 있고 끌 수 없습니다**(타깃 그룹 레벨에서만 끌 수 있습니다).
- **NLB**: AZ당 IP가 하나씩 고정으로 붙고, 서브넷당 Elastic IP 하나를 지정할 수 있습니다. cross-zone은 **기본값이 꺼짐**입니다.

### 2-6. 타임아웃 — 기본값이 다르고, 조정 가능 범위도 다릅니다

| | ALB | NLB |
|---|---|---|
| 유휴 타임아웃 | 60초 (`idle_timeout.timeout_seconds`) | TCP 350초(60~6000초로 변경 가능) |
| | | TLS 리스너 350초 (변경 불가) |
| | | UDP 플로우 120초 (변경 불가) |
| 클라이언트 keep-alive | 3600초 (`client_keep_alive.seconds`) | 해당 없음 |

출처: [ALB 속성](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html), [NLB 유휴 타임아웃](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/network-load-balancers.html)

NLB는 유휴 타임아웃이 지나면 추적을 끊고, 그 뒤에 들어온 패킷에 TCP RST를 보냅니다. 애플리케이션 로그에는 "커넥션이 상대방에 의해 초기화됨"만 남아서 원인을 찾기 어렵습니다. 커넥션 풀이 오래 쉬는 커넥션을 들고 있다면 TCP keepalive나 풀의 유효성 검사 주기를 유휴 타임아웃보다 짧게 잡아야 합니다.

ALB 서브넷에는 확장용 여유 IP가 필요합니다. AWS는 AZ별 서브넷에 `/27` 이상, 여유 IP 8개 이상을 요구하며, 확장하려는 순간 IP가 없으면 ALB가 용량 부족 상태로 돌아가면서 5xx나 타임아웃이 날 수 있다고 명시합니다 ([ALB 서브넷 요건](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html)). 서브넷을 `/28`로 잘게 쪼개 놓은 VPC에서 트래픽이 튈 때 터지는 지점입니다. 서브넷 설계는 day04-vpc-subnet.md를 참고하세요.

---

## 3. 흐름 — 같은 요청이 둘을 지나는 방식

ALB (요청 단위, 두 개의 연결):

```
클라이언트 --TCP#1--> ALB 노드 : TLS 종료 → HTTP 파싱 → 규칙 평가
                        ALB --TCP#2--> 타깃 A   (요청 1)
                        ALB --TCP#2--> 타깃 A   (요청 2, 커넥션 재사용)
                        ALB --TCP#3--> 타깃 B   (요청 3)
```

NLB (플로우 단위, 연결은 하나):

```
클라이언트 --TCP#1--> NLB : 플로우 해시 → 목적지 IP만 재작성 --TCP#1--> 타깃 A
                                                 (이 커넥션의 모든 요청은 끝까지 타깃 A)
```

여기서 파생되는 결과가 거의 전부입니다. ALB는 요청마다 타깃을 다시 고를 수 있으니 세션 고정(sticky session)이 **별도 기능**으로 필요하고, NLB는 커넥션이 이미 고정이라 기본 동작만으로 "끈적"합니다. 반대로 ALB는 타깃의 커넥션 수를 줄여주지만, NLB는 클라이언트 커넥션 수가 그대로 타깃에 도달합니다.

---

## 4. 코드로 보는 차이 — 클라이언트 IP

Spring Boot 3.2 기준입니다.

### 4-1. 클린하지 않은 코드 ❌

```java
@Component
public class IpRateLimitFilter extends OncePerRequestFilter {

    private final RateLimiter rateLimiter;

    public IpRateLimitFilter(RateLimiter rateLimiter) {
        this.rateLimiter = rateLimiter;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        // ALB 뒤에서는 ALB 노드의 사설 IP가 들어옵니다.
        // 전체 트래픽이 IP 몇 개로 보이므로 제한이 즉시 오동작합니다.
        String clientIp = request.getRemoteAddr();

        if (!rateLimiter.tryAcquire(clientIp)) {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            return;
        }
        chain.doFilter(request, response);
    }
}
```

로컬과 개발 환경에서는 잘 돌아갑니다. ALB를 붙인 순간 모든 사용자가 같은 키를 공유하게 되므로, 평소에는 과도하게 막히고 로그에는 전부 같은 IP가 찍힙니다.

### 4-2. 개선한 코드 ✔️

```yaml
# application.yml — 신뢰하는 프록시 뒤에 있을 때만 켭니다
server:
  forward-headers-strategy: framework   # X-Forwarded-* 를 요청에 반영
```

```java
@Component
public class IpRateLimitFilter extends OncePerRequestFilter {

    private final RateLimiter rateLimiter;

    public IpRateLimitFilter(RateLimiter rateLimiter) {
        this.rateLimiter = rateLimiter;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws IOException, ServletException {
        // forward-headers-strategy=framework 를 켜면
        // ForwardedHeaderFilter 가 X-Forwarded-For 를 반영해 remoteAddr 를 교정합니다.
        String clientIp = request.getRemoteAddr();

        if (!rateLimiter.tryAcquire(clientIp)) {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            return;
        }
        chain.doFilter(request, response);
    }
}
```

주의할 점이 있습니다. `X-Forwarded-For`는 클라이언트가 위조해서 보낼 수 있는 헤더입니다. ALB의 기본 모드(`append`)는 기존 값을 지우지 않고 **뒤에 덧붙이므로**, 맨 앞 값을 그대로 신뢰하면 위조된 IP를 믿게 됩니다. 신뢰 경계를 직접 정하거나(ALB가 덧붙인 마지막 값을 쓰거나), `routing.http.xff_header_processing.mode`를 `remove`로 두고 ALB가 새로 쓰게 만들어야 합니다.

NLB(instance 타깃, 클라이언트 IP 보존 켜짐)라면 이 설정이 필요 없습니다. `getRemoteAddr()`가 이미 진짜 클라이언트 IP입니다.

---

## 5. 비용 — 세는 축이 다릅니다

둘 다 "시간당 고정 요금 + 용량 단위(LCU/NLCU)" 구조지만 측정 차원이 다릅니다. 각 차원을 시간당 평균으로 계산한 뒤 **가장 높은 하나만** 과금합니다.

| 차원 | ALB (LCU 1개당) | NLB (NLCU 1개당) |
|---|---|---|
| 신규 연결 | 25/초 | TCP 800/초, UDP 400/초, **TLS 50/초** |
| 활성 연결 | 3,000/분 | TCP 100,000/분, UDP 50,000/분, TLS 3,000/분 |
| 처리 바이트 | 1GB/시간 (EC2·컨테이너·IP 타깃) | 1GB/시간 |
| 규칙 평가 | 1,000/초 (처음 10개 규칙은 무료) | 해당 없음 |

출처: [ELB 요금](https://aws.amazon.com/elasticloadbalancing/pricing/) <!-- TODO: 시간당 단가(ALB-시간/LCU-시간, NLB-시간/NLCU-시간)는 리전마다 다릅니다. 금액은 요금 페이지에서 리전을 직접 선택해 확인해야 합니다. -->

읽어야 할 점은 TLS 줄입니다. NLB에서 TLS를 종료하면 신규 연결 기준이 초당 50개로, TCP(800개)의 1/16입니다. "NLB가 더 싸다"는 말은 TCP 평문 트래픽에 대한 이야기이고, TLS 종료를 NLB에서 하면서 짧은 커넥션을 대량으로 받는 패턴은 계산이 완전히 달라집니다. 비용 추정의 일반 원칙은 day58-cloud-cost-basics.md에 있습니다.

여기에 cross-zone이 더해집니다. NLB는 기본이 꺼짐이므로 켜는 순간 AZ를 넘는 트래픽이 발생합니다.

---

## 6. 그래서 무엇을 고르는가

| 상황 | 선택 | 이유 |
|---|---|---|
| 일반 HTTP/REST API 서비스 | ALB | 경로 분기·요청 단위 분산·WAF 연동 |
| gRPC 서버 | ALB | NLB는 커넥션 하나에 요청이 몰려 분산이 깨집니다 |
| HTTP가 아닌 TCP/UDP 프로토콜 | NLB | ALB로는 리스너를 만들 수 없습니다 |
| 방화벽 화이트리스트용 고정 IP가 필요 | NLB | AZ당 고정 IP, EIP 지정 가능 |
| 애플리케이션이 TLS를 직접 종료해야 함 | NLB (TCP 리스너) | 패스스루 |
| 타깃이 소스 IP를 그대로 봐야 함 | NLB | 헤더 파싱 없이 패킷 레벨 보존 |
| 경로 분기는 필요한데 고정 IP도 필요 | NLB → ALB | NLB 타깃 그룹에 ALB를 등록할 수 있습니다 |

---

## 7. 함정

### 7-1. NLB 뒤의 서버가 자기 자신을 호출하면 타임아웃

- **증상**: 서버 A가 NLB 주소로 요청하면 어떤 요청은 성공하고 어떤 요청은 타임아웃으로 멈춥니다. 재현이 불규칙합니다.
- **원인**: 클라이언트 IP 보존이 켜져 있으면 NAT 루프백(헤어핀)이 지원되지 않습니다. 요청이 다른 타깃으로 라우팅되면 성공하지만, 자기 자신으로 돌아오면 소스와 목적지 IP가 같아져 커넥션이 성립하지 않습니다. **같은 EC2 노드 위의 EKS 파드끼리도** 동일하게 걸립니다(IP가 달라도).
- **해법**: 클라이언트 IP 보존을 끄고 Proxy Protocol v2로 IP를 받습니다. 또는 서로 호출하는 컨테이너를 다른 노드에 배치합니다. 애초에 내부 서비스 간 호출을 로드 밸런서로 되돌리지 않는 구조가 낫습니다. ([NLB 트러블슈팅](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-troubleshooting.html))

### 7-2. 타깃 보안 그룹을 LB 기준으로 열었는데 안 됩니다

- **증상**: NLB 생성 직후 타깃이 계속 `unhealthy`이거나, 헬스 체크는 통과하는데 실제 요청만 닿지 않습니다.
- **원인**: NLB + instance 타깃 + 클라이언트 IP 보존이면, 타깃에 도착하는 패킷의 소스 IP는 **클라이언트 IP**입니다. 보안 그룹을 "로드 밸런서에서 오는 트래픽 허용"으로만 열면 리스너 포트 트래픽이 막힙니다. AWS 문서는 instance 타깃이면 클라이언트 IP, ip 타깃이면 로드 밸런서 노드에서 오는 트래픽을 허용하라고 구분해 설명합니다.
- **해법**: 타깃 타입과 보존 설정을 먼저 확인하고 규칙을 정합니다. 보안 그룹과 NACL의 동작 차이는 day22-sg-vs-nacl.md를 참고하세요. 그리고 **NLB의 보안 그룹은 생성 시점에만 붙일 수 있습니다** — 없이 만든 NLB에는 나중에 추가할 수 없습니다.

### 7-3. ALB 502와 504는 원인이 다릅니다

- **증상**: 간헐적인 502 Bad Gateway, 또는 10초 뒤의 504.
- **원인**: 502의 흔한 원인은 **타깃의 keep-alive 시간이 ALB의 유휴 타임아웃보다 짧은 것**입니다. ALB가 재사용하려고 들고 있던 커넥션을 타깃이 먼저 끊으면 그 요청이 502가 됩니다. ALB의 기본 유휴 타임아웃은 60초입니다. 504는 타깃 연결 수립 실패(연결 타임아웃 10초) 또는 타깃이 유휴 타임아웃 안에 응답하지 못한 경우입니다.
- **해법**: 타깃(톰캣 `keepAliveTimeout`, nginx `keepalive_timeout`)을 ALB 유휴 타임아웃보다 **길게** 잡습니다. 504는 타임아웃 값을 늘리기 전에 느린 쿼리를 먼저 찾습니다. ([ALB 트러블슈팅](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html))

### 7-4. 세션 고정을 켰는데 적용되지 않습니다

- **증상**: `stickiness.enabled=true`인데 요청이 계속 다른 타깃으로 갑니다. 또는 API 자체가 실패합니다.
- **원인**: ALB의 세션 고정은 **교차 영역 부하 분산이 꺼져 있으면 지원되지 않습니다**. 꺼진 상태에서 켜려고 하면 실패합니다. 쿠키를 받지 않는 클라이언트(서버 간 호출, 모바일 HTTP 클라이언트)도 고정되지 않습니다. 추가로 ALB가 생성하는 쿠키 자체의 만료는 **7일 고정이며 변경할 수 없습니다** — 설정하는 "고정 기간"과 별개입니다.
- **해법**: 세션 고정은 마이그레이션 중의 임시 수단으로만 씁니다. 상태를 Redis 같은 외부 저장소로 빼면 타깃 교체·스케일 아웃·배포가 전부 단순해집니다.

### 7-5. NLB의 cross-zone 기본값이 꺼짐이라는 사실

- **증상**: AZ 두 곳에 각각 1대, 2대를 띄웠는데 1대뿐인 AZ의 서버만 CPU가 높습니다.
- **원인**: NLB는 기본적으로 각 노드가 **자기 AZ의 타깃에만** 트래픽을 보냅니다. 클라이언트가 DNS에서 받은 IP가 AZ를 결정하므로, AZ별 타깃 수가 다르면 대당 부하가 그대로 어긋납니다.
- **해법**: AZ별 타깃 수를 맞추거나 cross-zone을 켭니다. 켜면 AZ를 넘는 트래픽이 생기므로 비용과 지연을 함께 봅니다. 모든 AZ의 타깃이 전부 비정상이면 NLB는 **fail open**으로 전환해 비정상 타깃에도 요청을 보냅니다 — 그래서 "장애인데 요청이 계속 들어오는" 상태가 정상 동작일 수 있습니다.

### 7-6. 트래픽은 여유가 있는데 커넥션이 실패합니다

- **증상**: NLB의 `PortAllocationErrorCount` 지표가 올라가고, 클라이언트는 간헐적으로 커넥션 수립에 실패합니다. 타깃의 CPU와 메모리는 한가합니다.
- **원인**: 클라이언트 IP 보존이 꺼져 있거나 PrivateLink 트래픽이면 NLB가 소스 주소를 자기 것으로 바꿉니다. 이때 **(NLB IP, 타깃 IP, 타깃 포트) 조합 하나당 약 55,000 커넥션**이 한계입니다. 포트가 고갈되면 더 이상 새 플로우를 만들 수 없습니다.
- **해법**: 타깃 그룹에 타깃을 추가하는 것이 1차 해법입니다(조합이 늘어나 한계도 늘어납니다). 타깃을 늘릴 수 없으면 NLB 네트워크 인터페이스에 보조 IP를 최대 7개까지 추가할 수 있습니다. 단, **한 번 추가한 보조 IP는 제거할 수 없고** 로드 밸런서를 삭제해야만 해제됩니다. ([NLB 타깃 그룹](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-target-groups.html))

---

## 8. 관련 개념과 비교

- **NLB → ALB 타깃**: NLB 타깃 그룹에 ALB를 등록할 수 있습니다. 고정 IP와 경로 분기를 동시에 요구할 때 쓰는 조합입니다. 홉이 하나 늘고 로드 밸런서 요금도 두 번 냅니다.
- **헬스 체크**: ALB는 HTTP/HTTPS로 검사하고, NLB는 TCP·HTTP·HTTPS를 지원합니다. TCP 체크는 포트가 열렸는지만 보므로 "프로세스는 살았고 DB는 끊긴" 상태를 잡지 못합니다. 무엇을 검사해야 하는지는 day30-application-healthcheck.md에 있습니다.
- **배포와 등록 해제**: 등록 해제 지연 기본값은 300초입니다. 애플리케이션이 이 신호를 어떻게 받아야 하는지는 day18-graceful-shutdown.md를 참고하세요.

---

## 9. 참고자료

- [ELB 제품 비교](https://aws.amazon.com/elasticloadbalancing/features/)
- [Application Load Balancer 사용자 가이드](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/)
- [Network Load Balancer 사용자 가이드](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/)
- [NLB 타깃 그룹 속성 — 클라이언트 IP 보존, Proxy Protocol v2](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-target-groups.html)
- [ALB 타깃 그룹 속성 — 세션 고정, 라우팅 알고리즘](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html)
- [ELB 요금](https://aws.amazon.com/elasticloadbalancing/pricing/)
