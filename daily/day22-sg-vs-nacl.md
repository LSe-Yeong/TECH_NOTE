# Stateful과 Stateless의 차이가 만드는 실수 — 보안 그룹과 네트워크 ACL

> 이 문서가 답할 질문: **보안 그룹과 네트워크 ACL은 무엇이 다르고, 상태를 기억하느냐 아니냐가 실무에서 어떤 실수를 만드는가?**
>
> 기준: Amazon VPC 사용자 가이드 · Amazon EC2 사용자 가이드 (2026년 8월 확인). `day04-vpc-subnet.md`가 "왜 나누는가", `day10-route-table.md`가 "나눈 것의 실체", `day16-igw-natgw.md`가 "바깥과 어떻게 통신하는가"를 다뤘다면, 이 문서는 **그 길 위에서 무엇을 통과시킬지 결정하는 두 장치**를 다룹니다.

## 1. 핵심 개념

VPC에는 패킷을 걸러내는 장치가 두 개 있습니다.

- **보안 그룹(Security Group)** — 네트워크 인터페이스(ENI)에 붙습니다. 허용 규칙만 있고, **상태를 기억합니다.**
- **네트워크 ACL(NACL, Network Access Control List)** — 서브넷 경계에 붙습니다. 허용과 거부 규칙이 둘 다 있고, **상태를 기억하지 않습니다.**

> 이 차이를 모르고 넘어가면 정확히 이런 장애가 납니다. 보안을 강화하라는 요구가 내려와서 서브넷에 커스텀 NACL을 붙이고, 인바운드 443을 열었습니다. 규칙표를 보면 완벽합니다. 그런데 배포하는 순간 모든 API가 타임아웃납니다. 이유는 **응답 패킷이 나가지 못해서**입니다. 서버가 443으로 받은 요청에 응답할 때, 목적지 포트는 443이 아니라 클라이언트가 고른 임시 포트(예: 54321)입니다. 보안 그룹은 "아까 들어온 그 연결의 응답"이라는 걸 기억하므로 아웃바운드 규칙과 무관하게 내보내지만, NACL은 아무것도 기억하지 않습니다. NACL에게 그 패킷은 **처음 보는 아웃바운드 트래픽**이고, 명시적 허용이 없으면 마지막 `*` 규칙이 버립니다.

에러 로그도 안 남습니다. 그냥 조용히 사라집니다. 규칙표만 노려봐서는 절대 안 보입니다.

## 2. 구조

### 2-1. 보안 그룹 — 허용 목록의 합집합

보안 그룹 규칙 하나는 다음으로 구성됩니다.

- **프로토콜** — 6(TCP), 17(UDP), 1(ICMP) 등
- **포트 범위** — `8080` 또는 `7000-8000`
- **출발지(인바운드) / 목적지(아웃바운드)** — CIDR, **접두사 목록(prefix list) ID**, 또는 **다른 보안 그룹 ID**
- **설명** — 선택, 255자까지
- 규칙을 만들면 AWS가 **고유한 규칙 ID**를 부여합니다. CLI·API로 특정 규칙만 수정·삭제할 때 씁니다.

성질이 몇 가지 중요합니다.

- **거부 규칙이 없습니다.** 허용만 씁니다. "이 IP만 빼고"를 보안 그룹으로는 표현할 수 없습니다.
- **새로 만든 보안 그룹은 인바운드 규칙이 하나도 없고, 아웃바운드는 전체 허용입니다.** 아웃바운드 규칙을 지우면 나가는 트래픽이 전부 막힙니다.
- **기본 보안 그룹(`default`)은 다릅니다.** 인바운드에 자기 자신을 출발지로 하는 규칙이 하나 있어서, 같은 기본 보안 그룹을 단 리소스끼리는 모든 포트로 통신합니다. 삭제는 불가능하고 규칙 수정만 됩니다.
- **여러 개를 붙이면 규칙이 합쳐집니다.** ENI 하나에 보안 그룹 5개를 붙이면 규칙 전체의 합집합으로 판정합니다. 하나라도 허용하면 통과입니다.
- **모든 규칙을 평가한 뒤** 허용 여부를 결정합니다. 순서라는 개념이 없습니다.

### 2-2. 네트워크 ACL — 번호 순서대로 읽다가 멈추는 목록

NACL 규칙은 **1~32766 사이의 번호**를 가집니다. 평가 방식이 보안 그룹과 정반대입니다.

1. 가장 낮은 번호부터 순서대로 봅니다.
2. 트래픽과 일치하는 규칙을 만나면 **거기서 적용하고 멈춥니다.** 뒤에 모순되는 규칙이 있어도 보지 않습니다.
3. 아무것도 매치되지 않으면 번호가 `*`인 규칙이 거부합니다. 이 규칙은 삭제할 수 없습니다.

그래서 **넓은 범위를 허용하면서 일부만 막으려면, 거부 규칙의 번호를 허용 규칙보다 낮게** 줘야 합니다. 규칙은 10이나 100 단위로 띄워서 만드는 걸 AWS가 권장합니다. 나중에 사이에 끼워 넣어야 하기 때문입니다.

기본값이 헷갈리는 지점입니다.

| | 인바운드 | 아웃바운드 |
|---|---|---|
| **VPC 생성 시 딸려오는 기본 NACL** | 100: 전체 ALLOW / `*`: DENY | 100: 전체 ALLOW / `*`: DENY |
| **내가 직접 만든 NACL** | `*`: DENY 하나뿐 | `*`: DENY 하나뿐 |

기본 NACL은 사실상 아무것도 막지 않습니다. 그래서 "NACL은 원래 신경 안 써도 되는 것"이라는 오해가 생깁니다. 반대로 **직접 만든 NACL을 서브넷에 붙이는 순간 통신이 전부 끊깁니다.** 서브넷은 반드시 NACL 하나에 연결되고, 명시적으로 지정하지 않으면 기본 NACL에 붙습니다. NACL 하나를 여러 서브넷에 붙일 수는 있지만, 서브넷 하나는 NACL 하나만 가집니다.

### 2-3. 두 장치가 놓인 위치

패킷이 지나는 순서로 보면 역할이 분명해집니다.

```text
[인터넷] → IGW → 라우팅 테이블 → [NACL 인바운드: 서브넷 경계] → [SG 인바운드: ENI] → 애플리케이션
[애플리케이션] → [SG 아웃바운드: ENI] → [NACL 아웃바운드: 서브넷 경계] → 라우팅 테이블 → IGW → [인터넷]
```

핵심은 **NACL은 서브넷을 드나들 때만 평가된다**는 점입니다. 같은 서브넷 안에서 인스턴스끼리 주고받는 트래픽에는 NACL이 개입하지 않습니다. 반면 보안 그룹은 ENI에 붙으므로 같은 서브넷 안이든 밖이든 항상 걸립니다.

둘 다 **요금이 없습니다.** 비용을 이유로 하나를 고를 일은 없습니다.

## 3. 흐름

### 3-1. 요청 한 번을 따라가 봅니다

클라이언트 `203.0.113.25`가 퍼블릭 서브넷의 웹 서버 `10.20.1.10:443`을 호출합니다. 클라이언트 OS가 출발지 포트로 54321을 골랐다고 하겠습니다.

**요청 패킷** — 출발지 `203.0.113.25:54321` → 목적지 `10.20.1.10:443`

- NACL 인바운드: 목적지 443 허용 규칙에 매치 → 통과
- SG 인바운드: 443 허용 규칙에 매치 → 통과 → **이 연결을 추적 테이블에 기록**

**응답 패킷** — 출발지 `10.20.1.10:443` → 목적지 `203.0.113.25:54321`

- SG 아웃바운드: **평가하지 않습니다.** 추적 중인 연결의 응답이므로 아웃바운드 규칙과 무관하게 나갑니다.
- NACL 아웃바운드: 목적지 포트가 **54321**입니다. 443이 아닙니다. `1024-65535` 같은 범위를 허용해두지 않았다면 여기서 드롭됩니다.

이게 임시 포트(ephemeral port) 문제의 전부입니다. NACL을 쓰는 순간, 규칙을 **패킷 방향 두 개로** 써야 합니다.

### 3-2. 임시 포트 범위는 클라이언트가 정합니다

몇 번 포트가 열려야 하는지는 **요청을 시작한 쪽의 운영체제**가 결정합니다. AWS 문서가 명시한 범위입니다.

| 요청을 시작하는 주체 | 임시 포트 범위 |
|---|---|
| 다수의 Linux 커널 (Amazon Linux 포함) | 32768-61000 |
| Windows Server 2003 이하 | 1025-5000 |
| Windows Server 2008 이상 | 49152-65535 |
| Elastic Load Balancing | 1024-65535 |
| NAT 게이트웨이 | 1024-65535 |
| AWS Lambda | 1024-65535 |

출처: [Custom network ACLs for your VPC — Ephemeral ports](https://docs.aws.amazon.com/vpc/latest/userguide/custom-network-acl.html#nacl-ephemeral-ports)

인터넷에 열린 서비스라면 클라이언트 OS를 통제할 수 없습니다. 그래서 실무에서는 `1024-65535`를 통째로 여는 선택을 합니다. AWS 문서도 같은 방향을 안내합니다. 그런데 이 순간 **NACL의 포트 필터링은 사실상 의미를 잃습니다.** 6만 개가 넘는 포트가 열린 목록이니까요. 여기서 결론이 하나 나옵니다. **포트 단위 통제는 보안 그룹의 일입니다.**

### 3-3. 코드로 보는 구성

3계층 구조를 보안 그룹으로 짭니다. ALB → 앱 서버 → DB 순으로 흐르고, 각 계층은 **앞 계층의 보안 그룹 ID를 출발지로 참조**합니다. IP를 쓰지 않는 게 핵심입니다. 오토스케일링으로 인스턴스가 바뀌어도 규칙을 고칠 일이 없습니다.

```bash
VPC_ID=vpc-0a1b2c3d4e5f67890

ALB_SG=$(aws ec2 create-security-group --group-name alb-tier \
  --description "ALB from internet" --vpc-id "$VPC_ID" --query GroupId --output text)
APP_SG=$(aws ec2 create-security-group --group-name app-tier \
  --description "App servers behind ALB" --vpc-id "$VPC_ID" --query GroupId --output text)
DB_SG=$(aws ec2 create-security-group --group-name db-tier \
  --description "MySQL for app tier" --vpc-id "$VPC_ID" --query GroupId --output text)

# 인터넷 → ALB (여기만 CIDR을 씁니다)
aws ec2 authorize-security-group-ingress --group-id "$ALB_SG" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0

# ALB → 앱 (출발지가 보안 그룹 ID)
aws ec2 authorize-security-group-ingress --group-id "$APP_SG" \
  --protocol tcp --port 8080 --source-group "$ALB_SG"

# 앱 → DB
aws ec2 authorize-security-group-ingress --group-id "$DB_SG" \
  --protocol tcp --port 3306 --source-group "$APP_SG"
```

보안 그룹을 참조하면 **참조된 보안 그룹의 규칙이 복사되지는 않습니다.** "그 보안 그룹을 단 ENI들의 사설 IP"를 출발지로 삼는다는 뜻일 뿐입니다. 같은 VPC이거나, VPC 피어링·Transit Gateway로 연결된 VPC 사이에서만 참조할 수 있습니다.

NACL은 굵직한 가드레일로만 씁니다. 프라이빗 서브넷에 "인터넷에서 직접 들어오는 것은 없다"를 강제하는 정도입니다.

```bash
# 프라이빗 서브넷: VPC 내부 통신 + 아웃바운드 응답만 허용
aws ec2 create-network-acl-entry --network-acl-id "$NACL_ID" \
  --ingress --rule-number 100 --protocol -1 \
  --cidr-block 10.20.0.0/16 --rule-action allow

aws ec2 create-network-acl-entry --network-acl-id "$NACL_ID" \
  --ingress --rule-number 200 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block 0.0.0.0/0 --rule-action allow   # 아웃바운드 요청에 대한 응답 수신

aws ec2 create-network-acl-entry --network-acl-id "$NACL_ID" \
  --egress --rule-number 100 --protocol -1 \
  --cidr-block 0.0.0.0/0 --rule-action allow
```

## 4. 특징

### 4-1. 비교표

AWS 공식 비교표에 실무에서 걸리는 항목을 더했습니다.

| 항목 | 보안 그룹 | 네트워크 ACL |
|---|---|---|
| 적용 지점 | 인스턴스(ENI) 수준 | 서브넷 수준 |
| 적용 범위 | 그 보안 그룹을 단 리소스 전부 | 연결된 서브넷 안의 리소스 전부 |
| 규칙 종류 | 허용만 | 허용 + 거부 |
| 평가 방식 | 모든 규칙을 본 뒤 판정 | 번호 오름차순으로 보다가 매치되면 중단 |
| 응답 트래픽 | 자동 허용 (stateful) | 명시적으로 허용해야 함 (stateless) |
| 출발지로 쓸 수 있는 것 | CIDR, 접두사 목록, **다른 보안 그룹** | CIDR만 |
| 기본 규칙 수 쿼터 | 인/아웃 각각 60개 (조정 가능) | 인/아웃 각각 20개 (최대 40개까지) |
| 요금 | 없음 | 없음 |

쿼터 출처: [Amazon VPC quotas](https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html). 보안 그룹은 ENI당 기본 5개(최대 16개)까지 붙고, `규칙 수 × ENI당 보안 그룹 수`가 1,000을 넘을 수 없습니다. NACL 규칙은 인바운드 40개 + 아웃바운드 40개까지 올릴 수 있지만 AWS가 네트워크 성능 영향을 경고합니다.

### 4-2. 그래서 무엇을 쓰는가

AWS 문서의 권고가 명확합니다. **보안 그룹을 주 통제 수단으로 쓰고, NACL은 보조 수단으로 씁니다.** 상태 기반 필터링과 보안 그룹 참조가 가능하다는 점에서 보안 그룹이 훨씬 유연하기 때문입니다.

NACL이 실제로 필요한 경우는 좁습니다.

- **특정 IP·대역을 거부**해야 할 때. 보안 그룹에는 거부 규칙이 없으므로 이건 NACL만 할 수 있습니다.
- **서브넷 전체에 대한 가드레일**이 필요할 때. 보안 그룹을 잘못 붙인 인스턴스가 실수로 뜨는 상황을 서브넷 레벨에서 막습니다.
- **기존 연결을 즉시 끊어야** 할 때. 이유는 6절에 있습니다.

### 4-3. 트레이드오프

NACL을 촘촘하게 쓰기로 하면 대가가 따라옵니다. 규칙을 방향별로 두 벌 관리해야 하고, 임시 포트 때문에 어차피 넓은 범위를 열게 되고, 규칙 20개(최대 40개) 안에 다 넣어야 하고, 장애 원인 파악이 어려워집니다. 보안이 두 배가 되지 않는데 운영 복잡도는 두 배가 됩니다.

보안 그룹만 쓰는 쪽의 대가도 있습니다. 거부를 표현할 수 없고, 리소스에 보안 그룹을 붙이는 걸 깜빡하면 통제가 통째로 빠집니다. 그래서 "보안 그룹으로 촘촘하게 + NACL로 굵게"가 기본형이 됩니다.

## 5. 예제

### 5-1. 흔한 나쁜 구성 ❌

```hcl
# NACL로 세밀한 접근 제어를 하려는 시도
resource "aws_network_acl" "app" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = [aws_subnet.app_a.id, aws_subnet.app_b.id]

  ingress {
    rule_no    = 100
    protocol   = "tcp"
    from_port  = 8080
    to_port    = 8080
    cidr_block = "10.20.0.0/16"
    action     = "allow"
  }
  # 아웃바운드 규칙 없음 → * DENY만 남습니다
}
```

문제가 세 가지 겹칩니다.

1. **아웃바운드가 비어 있어 응답이 전부 드롭됩니다.** 헬스체크부터 실패합니다.
2. 포트 8080 통제는 애초에 보안 그룹의 일입니다. 서브넷에 8080 서비스가 하나 더 생기면 규칙을 또 고쳐야 합니다.
3. 출발지를 CIDR로 박아서, 앱 서버가 다른 서브넷으로 옮겨가면 조용히 막힙니다.

### 5-2. 개선한 구성 ✔️

```hcl
# 통제는 보안 그룹으로 — 보안 그룹 참조로 IP 의존을 없앱니다
resource "aws_security_group" "app" {
  name   = "app-tier"
  vpc_id = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_egress_rule" "app_to_internet" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# NACL은 가드레일 — 알려진 악성 대역만 거부하고 나머지는 통과
resource "aws_network_acl_rule" "deny_known_bad" {
  network_acl_id = aws_network_acl.app.id
  rule_number    = 50 # 허용 규칙(100)보다 낮아야 먼저 매치됩니다
  egress         = false
  protocol       = "-1"
  rule_action    = "deny"
  cidr_block     = "192.0.2.0/24"
}

resource "aws_network_acl_rule" "allow_rest_in" {
  network_acl_id = aws_network_acl.app.id
  rule_number    = 100
  egress         = false
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = "0.0.0.0/0"
}

resource "aws_network_acl_rule" "allow_rest_out" {
  network_acl_id = aws_network_acl.app.id
  rule_number    = 100
  egress         = true
  protocol       = "-1"
  rule_action    = "allow"
  cidr_block     = "0.0.0.0/0"
}
```

거부 규칙 번호를 50으로 준 것이 핵심입니다. 100번 허용 규칙보다 뒤에 두면 영원히 평가되지 않습니다.

## 6. 상태를 기억하는 대가 — 연결 추적

보안 그룹의 stateful은 공짜가 아닙니다. AWS는 **연결 추적(connection tracking)** 테이블로 이를 구현하고, 그 테이블에는 인스턴스 타입별 상한이 있습니다.

**모든 흐름이 추적되지는 않습니다.** TCP·UDP 흐름에 대해 인바운드와 아웃바운드가 **양쪽 모두 `0.0.0.0/0`(또는 `::/0`)로 전 포트를 허용**하고 있으면, 그 흐름은 추적하지 않습니다. 응답을 규칙만으로 판단할 수 있기 때문입니다. 결과가 이렇게 갈립니다.

- **추적되는 연결**: 규칙을 바꿔도 기존 연결은 즉시 끊기지 않습니다. 타임아웃될 때까지 계속 흐릅니다.
- **추적되지 않는 연결**: 규칙을 지우거나 좁히는 순간 **즉시 끊깁니다.**

같은 "규칙 삭제"인데 결과가 정반대입니다. 아웃바운드 전체 허용 + 인바운드 `0.0.0.0/0` SSH 규칙 상태에서 그 SSH 규칙을 지우면, 지금 붙어 있는 SSH 세션이 그 자리에서 떨어집니다. 반대로 출발지를 특정 IP로 좁혀 두었던 경우라면 추적 중이므로 기존 세션이 살아 있습니다.

유휴 연결 타임아웃도 알아둘 값입니다. Nitro 기반 인스턴스에서 ENI 단위로 설정할 수 있습니다.

| 항목 | 기본값 | 조정 범위 |
|---|---|---|
| TCP established | Nitro v6 세대: **350초** / 그 외: **432000초** | 60 ~ 432000초 |
| UDP | 30초 | 30 ~ 60초 |
| UDP stream | 180초 | 60 ~ 180초 |

출처: [Amazon EC2 security group connection tracking](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)

기본값이 세대에 따라 크게 다릅니다. DB 커넥션 풀이나 지속 HTTP 연결처럼 오래 살아 있는 연결을 쓴다면, Nitro v6 인스턴스로 옮길 때 **아무 코드 변경 없이 커넥션이 끊기기 시작할 수 있습니다.** AWS는 5분보다 짧은 간격의 TCP keepalive를 권고합니다.

NAT 게이트웨이, NLB, PrivateLink 인터페이스 엔드포인트, Lambda 등을 통과하는 연결은 규칙과 무관하게 **항상 추적됩니다.** 추적 한도를 넘기면 패킷이 그냥 버려지고, `conntrack_allowance_exceeded` 메트릭으로만 확인됩니다.

## 7. 함정

**막힌 지점이 SG인지 NACL인지 구분하기**

- **증상**: 연결이 안 되는데 어느 쪽 규칙이 문제인지 모릅니다.
- **원인**: 둘 다 조용히 드롭하므로 애플리케이션 로그에는 타임아웃만 남습니다.
- **해법**: VPC 흐름 로그의 레코드 개수로 구분합니다. AWS 문서의 ICMP 예시가 정확히 이 패턴입니다. NACL 인바운드는 허용인데 아웃바운드가 막힌 경우 **ACCEPT 레코드와 REJECT 레코드가 한 쌍**으로 남습니다. 요청은 들어왔고 응답이 거부된 겁니다. 반대로 보안 그룹 인바운드에서 막히면 **REJECT 레코드 하나만** 남습니다. 애초에 도달하지 못했으니까요. 정적 분석이 필요하면 Reachability Analyzer를 씁니다.

**NACL 규칙을 지우면서 동시에 추가하기**

- **증상**: 배포 후 서브넷 통신이 통째로 끊깁니다.
- **원인**: 한 번에 규칙을 삭제하고 추가할 때 **추가분이 쿼터를 넘으면, 삭제는 실행되고 추가는 되지 않습니다.** 기본 쿼터가 20개뿐이라 IP 차단 목록을 NACL로 관리하다 보면 쉽게 닿습니다.
- **해법**: 차단 목록은 NACL이 아니라 AWS WAF나 Network Firewall로 옮깁니다. NACL은 대역 단위 가드레일로만 유지합니다.

**로드밸런서·미들박스 뒤에서 보안 그룹 참조가 안 먹는 경우**

- **증상**: 보안 그룹 참조로 규칙을 짰는데 트래픽이 차단됩니다.
- **원인**: 두 인스턴스 사이 트래픽을 미들박스 어플라이언스로 우회시키는 라우팅이 있으면, **상대 보안 그룹을 출발지로 참조해도 통신이 열리지 않습니다.** AWS 문서가 명시한 제약입니다.
- **해법**: 이 경우에는 상대 인스턴스의 사설 IP나 서브넷 CIDR을 출발지로 씁니다.

**아웃바운드를 막으면 안전하다는 착각**

- **증상**: 아웃바운드를 전부 잠갔는데도 인스턴스가 외부와 통신합니다.
- **원인**: 보안 그룹과 NACL 모두 **Route 53 Resolver로 가는 DNS 요청과 인스턴스 메타데이터 서비스(IMDS) 트래픽을 필터링하지 못합니다.** DHCP, Amazon Time Sync, ECS 태스크 메타데이터 엔드포인트도 마찬가지입니다.
- **해법**: DNS 통제가 목적이면 Route 53 Resolver DNS Firewall을 켭니다. IMDS는 인스턴스 메타데이터 옵션(IMDSv2 강제, 홉 제한)으로 제어합니다.

**"보안 그룹을 고쳤는데 왜 아직 뚫려 있지"**

- **증상**: 침해 대응으로 규칙을 삭제했는데 세션이 살아 있습니다.
- **원인**: 추적 중인 연결이라 타임아웃 전까지 계속 허용됩니다. TCP established 기본값이 432000초인 인스턴스 타입이라면 5일입니다.
- **해법**: **즉시 끊어야 할 때는 NACL을 씁니다.** NACL은 무상태라 양방향 어느 쪽을 막아도 기존 연결이 그 자리에서 깨집니다. 상태를 기억하지 않는 게 여기서는 장점이 됩니다.

**ELB 헬스체크가 NACL 거부 규칙에 걸리는 경우**

- **증상**: 타깃이 계속 unhealthy로 떨어집니다.
- **원인**: 백엔드 서브넷 NACL에 출발지 `0.0.0.0/0` 또는 서브넷 CIDR에 대한 거부 규칙을 넣으면 **로드밸런서가 헬스체크를 수행하지 못합니다.**
- **해법**: 거부 규칙의 범위를 좁히고, 로드밸런서 노드가 위치한 서브넷 대역은 허용에서 빼지 않습니다.

## 8. 정리

- 포트·출발지 단위의 세밀한 통제는 **보안 그룹**입니다. 보안 그룹 참조로 계층 간 관계를 표현하면 IP가 바뀌어도 규칙이 살아 있습니다.
- **NACL**은 거부가 필요할 때, 서브넷 가드레일이 필요할 때, 연결을 즉시 끊어야 할 때만 씁니다.
- NACL을 건드리기로 했다면 **응답 방향의 임시 포트**를 항상 먼저 확인합니다. 장애의 대부분이 여기서 나옵니다.
- 상태를 기억한다는 성질은 편의이자 제약입니다. 규칙 변경이 언제 즉시 반영되고 언제 반영되지 않는지는 그 연결이 추적 중인지에 달려 있습니다.

## 9. 참고자료

- [Control traffic to your AWS resources using security groups](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html)
- [Security group rules](https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html)
- [Control subnet traffic with network access control lists](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html)
- [Custom network ACLs for your VPC](https://docs.aws.amazon.com/vpc/latest/userguide/custom-network-acl.html)
- [Compare security groups and network ACLs](https://docs.aws.amazon.com/vpc/latest/userguide/infrastructure-security.html#VPC_Security_Comparison)
- [Amazon EC2 security group connection tracking](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-connection-tracking.html)
- [Flow log record examples](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-records-examples.html)
- 관련 문서: `day04-vpc-subnet.md`, `day10-route-table.md`, `day16-igw-natgw.md`
